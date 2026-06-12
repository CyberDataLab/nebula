import logging
import math

import numpy as np
import torch
import torch.nn.functional as F
from art.estimators.classification import PyTorchClassifier
from art.metrics import clever_u, empirical_robustness, loss_sensitivity
from nebula.core.datasets.image_metadata import get_image_normalization
from torch import nn, optim

logger = logging.getLogger(__name__)

R_L2 = 2
ROBUSTNESS_EPSILON = 0.03
# ART CLEVER is an L2 lower-bound estimate; the attack radius maps to a full trust score.
CLEVER_REFERENCE = R_L2
# ART empirical robustness is a relative perturbation distance; this maps 0.2 to a full trust score.
EMPIRICAL_ROBUSTNESS_REFERENCE = 0.2
TABULAR_ATTACK_STEPS = 3
ADVERSARIAL_LOG_SAMPLES = 2
ADVERSARIAL_LOG_FEATURES = 12

def _build_art_classifier(model, input_shape, nb_classes, learning_rate):
    # Wrap the PyTorch model with the ART classifier interface used by ART metrics.
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), learning_rate)

    return PyTorchClassifier(
        model=model,
        loss=criterion,
        optimizer=optimizer,
        input_shape=tuple(input_shape),
        nb_classes=nb_classes,
    )


def _validate_test_sample_tensors(test_sample):
    # Shared guard for sample-based metrics that expect a non-empty (x, y) batch.
    if not (isinstance(test_sample, (tuple, list)) and len(test_sample) >= 2):
        raise ValueError("`test_sample` must contain samples and labels.")

    samples, labels = test_sample[0], test_sample[1]
    if not (torch.is_tensor(samples) and torch.is_tensor(labels) and samples.shape[0] > 0):
        raise ValueError("`test_sample` must contain non-empty tensors for samples and labels.")

    return samples, labels


def _coerce_max_samples(max_samples, default=8):
    # Keep metric calls bounded even if configuration values are missing or invalid.
    try:
        return max(1, int(max_samples))
    except Exception:
        return default


def _coerce_tabular_metadata(metadata):
    # Accept both serialized dataset metadata and the typed metadata object.
    if metadata is None:
        return None

    # Keep tabular-only imports lazy so image workflows do not depend on them.
    from nebula.core.datasets.tabular_metadata import TabularAdversarialMetadata

    if isinstance(metadata, TabularAdversarialMetadata):
        return metadata
    return TabularAdversarialMetadata.from_dict(metadata)


def _get_tabular_metadata_from_dataset(dataset):
    # Dataloaders can wrap datasets; walk through wrappers until metadata is found.
    if dataset is None:
        return None

    metadata = getattr(dataset, "tabular_metadata", None)
    if metadata is not None:
        return _coerce_tabular_metadata(metadata)

    return _get_tabular_metadata_from_dataset(getattr(dataset, "dataset", None))


def _get_tabular_metadata_from_loader(data_loader):
    # Return None for image datasets, which keeps the adversarial path on FGSM.
    return _get_tabular_metadata_from_dataset(getattr(data_loader, "dataset", None))


def _get_dataset_name_from_dataset(dataset):
    # Dataset wrappers keep the real dataset in `.dataset`; walk through them.
    if dataset is None:
        return None

    dataset_name = getattr(dataset, "dataset_name", None)
    if dataset_name is not None:
        return dataset_name

    config = getattr(dataset, "config", None)
    participant = getattr(config, "participant", None)
    if isinstance(config, dict):
        participant = config.get("participant", participant)
    if isinstance(participant, dict):
        dataset_name = participant.get("data_args", {}).get("dataset")
        if dataset_name is not None:
            return dataset_name

    return _get_dataset_name_from_dataset(getattr(dataset, "dataset", None))


def _get_image_normalization_from_loader(data_loader):
    # Resolve image mean/std from shared dataset metadata instead of inferring by channels.
    dataset_name = _get_dataset_name_from_dataset(getattr(data_loader, "dataset", None))
    normalization = get_image_normalization(dataset_name)
    if normalization is not None:
        logger.info("[Robustness] Image normalization loaded | dataset=%s | mean/std=%s", dataset_name, normalization)
    return normalization


def _build_fixed_epsilon_tabular_generator(epsilon, tabular_metadata):
    # Reuse the tabular adversarial-training generator, but make evaluation deterministic.
    from nebula.addons.defenses.adversarial_training.config import AdversarialTrainingConfig
    from nebula.addons.defenses.adversarial_training.tabular import TabularConstrainedPGDGenerator

    class FixedEpsilonTabularConstrainedPGDGenerator(TabularConstrainedPGDGenerator):
        def _sample_epsilon(self, device):
            # Training samples epsilon; factsheet metrics should use the requested epsilon exactly.
            self.last_epsilon = float(self.config.epsilon)
            return self.last_epsilon

    config = AdversarialTrainingConfig(
        domain="tabular",
        attack="constrained_pgd",
        epsilon=float(epsilon),
        steps=TABULAR_ATTACK_STEPS,
        candidate_selection="none",
    )
    return FixedEpsilonTabularConstrainedPGDGenerator(config, tabular_metadata)


def _build_tabular_generator(epsilon, tabular_metadata):
    # A missing generator intentionally means "use the image/default FGSM path".
    tabular_metadata = _coerce_tabular_metadata(tabular_metadata)
    if tabular_metadata is None:
        return None

    return _build_fixed_epsilon_tabular_generator(epsilon, tabular_metadata)


def _attack_name(tabular_generator):
    # Keep log messages explicit about which adversarial path is active.
    return "tabular_constrained_pgd" if tabular_generator is not None else "fgsm"


def _tensor_range(tensor):
    # Compact numeric summary for batch-level logging.
    if tensor.numel() == 0:
        return "empty"

    tensor = tensor.detach().float().cpu()
    return "min={:.6f}, max={:.6f}, mean={:.6f}".format(
        tensor.min().item(),
        tensor.max().item(),
        tensor.mean().item(),
    )


def _format_preview_vector(vector, feature_names=None, max_features=ADVERSARIAL_LOG_FEATURES):
    # Log only a small prefix of the flattened vector to keep factsheet logs readable.
    values = vector.detach().flatten().float().cpu().tolist()
    preview_values = values[:max_features]

    if feature_names:
        names = list(feature_names)[:max_features]
        items = [
            "{}={:.6f}".format(name, float(value))
            for name, value in zip(names, preview_values, strict=False)
        ]
    else:
        items = ["{:.6f}".format(float(value)) for value in preview_values]

    suffix = ", ..." if len(values) > max_features else ""
    return "[" + ", ".join(items) + suffix + "]"


def _log_adversarial_generation(metric_name, samples, labels, x_adv, epsilon, tabular_generator, batch_idx):
    # Log one representative batch per metric invocation to inspect generated samples.
    if batch_idx != 0:
        return

    attack = _attack_name(tabular_generator)
    clean = samples.detach().cpu()
    adv = x_adv.detach().cpu()
    delta = adv - clean
    flat_delta = delta.reshape(delta.shape[0], -1).float()
    feature_names = getattr(getattr(tabular_generator, "metadata", None), "feature_names", None)

    logger.info(
        "[Robustness] %s adversarial generation | attack=%s | epsilon=%.6f | "
        "clean_shape=%s | adv_shape=%s | clean=%s | adv=%s | "
        "delta_linf=%.6f | delta_l2_mean=%.6f",
        metric_name,
        attack,
        float(epsilon),
        tuple(clean.shape),
        tuple(adv.shape),
        _tensor_range(clean),
        _tensor_range(adv),
        flat_delta.abs().max().item() if flat_delta.numel() else 0.0,
        flat_delta.norm(p=2, dim=1).mean().item() if flat_delta.numel() else 0.0,
    )

    n_preview = min(int(clean.shape[0]), ADVERSARIAL_LOG_SAMPLES)
    labels_cpu = labels.detach().cpu() if torch.is_tensor(labels) else labels
    for sample_idx in range(n_preview):
        label = labels_cpu[sample_idx].item() if torch.is_tensor(labels_cpu) else None
        logger.info(
            "[Robustness] %s adversarial sample %s | attack=%s | label=%s | "
            "clean=%s | adversarial=%s | delta=%s",
            metric_name,
            sample_idx,
            attack,
            label,
            _format_preview_vector(clean[sample_idx], feature_names),
            _format_preview_vector(adv[sample_idx], feature_names),
            _format_preview_vector(delta[sample_idx]),
        )


def _generate_adversarial_samples(
    model,
    samples,
    labels,
    epsilon=ROBUSTNESS_EPSILON,
    tabular_generator=None,
    image_normalization=None,
):
    # Central switch: FGSM for images, constrained PGD for tabular datasets.
    if tabular_generator is None:
        return fgsm_attack(
            model,
            samples,
            labels,
            epsilon=epsilon,
            image_normalization=image_normalization,
        )

    return tabular_generator.generate(model, samples, labels, nn.CrossEntropyLoss())


def get_clever_score(model, test_sample, nb_classes, learning_rate, max_samples=8):
    # Calculates and scales ART CLEVER into a trust score.

    samples, _ = _validate_test_sample_tensors(test_sample)

    input_shape = tuple(samples.shape[1:]) if samples.dim() >= 2 else tuple(samples.shape)

    max_samples = _coerce_max_samples(max_samples)
    n_samples = min(int(samples.shape[0]), max_samples)

    # Create the ART classifier once and reuse it for all selected samples.
    classifier = _build_art_classifier(model, input_shape, nb_classes, learning_rate)

    clever_scores = []
    for idx in range(n_samples):
        # ART CLEVER evaluates one input at a time without the batch dimension.
        background = samples[idx].detach().cpu()
        sample_np = background.numpy()

        try:
            score_untargeted = clever_u(
                classifier,
                sample_np,
                10,
                5,
                R_L2,
                norm=2,
                pool_factor=3,
                verbose=False,
            )
            if score_untargeted is not None and not math.isnan(float(score_untargeted)):
                clever_scores.append(float(score_untargeted))
        except Exception as exc:
            logger.warning("Could not compute CLEVER score for sample index %s", idx)
            logger.warning(exc)

    if not clever_scores:
        return 0.0

    raw_score = float(np.mean(clever_scores))
    score = min(max(raw_score / CLEVER_REFERENCE, 0.0), 1.0)
    logger.info(
        "[Robustness] CLEVER | raw_l2=%.6f | reference=%.6f | score=%.6f",
        raw_score,
        CLEVER_REFERENCE,
        score,
    )
    return score

def get_loss_sensitivity_score(model, test_sample, nb_classes, learning_rate, max_samples=8):
    # Calculates the loss sensitivity score as the mean score over multiple samples.

    samples, labels = _validate_test_sample_tensors(test_sample)

    max_samples = _coerce_max_samples(max_samples)
    n_samples = min(int(samples.shape[0]), max_samples)

    # Create the ART classifier once and reuse it for all selected samples.
    classifier = _build_art_classifier(model, samples.shape[1:], nb_classes, learning_rate)

    sensitivity_scores = []
    for idx in range(n_samples):
        # ART loss_sensitivity expects a batch and one-hot labels.
        sample = samples[idx].detach().cpu().unsqueeze(0)
        label = labels[idx].detach().cpu().unsqueeze(0)
        label = F.one_hot(label, num_classes=nb_classes).float()

        try:
            score = loss_sensitivity(
                classifier,
                sample.numpy(),
                label.numpy(),
            )
            if score is not None and not math.isnan(float(score)):
                sensitivity_scores.append(float(score))
        except Exception as exc:
            logger.warning("Could not compute loss sensitivity for sample index %s", idx)
            logger.warning(exc)

    if not sensitivity_scores:
        return 0.0

    return float(np.mean(sensitivity_scores))


def get_adversarial_accuracy(
    model,
    test_loader,
    nb_classes,
    learning_rate,
    epsilon=ROBUSTNESS_EPSILON
):
    # Computes adversarial accuracy on generated adversarial samples.

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.eval()
    model.to(device)
    # If metadata exists, adversarial examples preserve tabular feature constraints.
    tabular_generator = _build_tabular_generator(
        epsilon,
        _get_tabular_metadata_from_loader(test_loader),
    )
    image_normalization = None if tabular_generator is not None else _get_image_normalization_from_loader(test_loader)
    logger.info(
        "[Robustness] adversarial accuracy | attack=%s | epsilon=%.6f",
        _attack_name(tabular_generator),
        float(epsilon),
    )

    correct = 0
    total = 0

    for batch_idx, (samples, labels) in enumerate(test_loader):
        samples = samples.to(device)
        labels = labels.to(device)

        x_adv = _generate_adversarial_samples(
            model,
            samples,
            labels,
            epsilon=epsilon,
            tabular_generator=tabular_generator,
            image_normalization=image_normalization,
        )
        _log_adversarial_generation(
            "adversarial_accuracy",
            samples,
            labels,
            x_adv,
            epsilon,
            tabular_generator,
            batch_idx,
        )

        with torch.no_grad():
            outputs = model(x_adv)
            logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
            preds = logits.argmax(dim=1)

        correct += (preds == labels).sum().item()
        total += labels.size(0)

    return correct / total if total > 0 else 0.0


def get_empirical_robustness_score(
    model,
    test_sample,
    nb_classes,
    learning_rate,
    attack_name = "fgsm",
    attack_params = None,
    max_samples = 128,
):
    # Calculates and scales ART empirical robustness into a trust score.

    try:
        samples, _ = _validate_test_sample_tensors(test_sample)

        batch_size: int = int(samples.shape[0])
        n: int = int(min(max_samples, batch_size))
        x = samples[:n].detach().cpu().numpy()

        classifier = _build_art_classifier(model, samples.shape[1:], nb_classes, learning_rate)

        raw_score = empirical_robustness(
            classifier=classifier,
            x=x,
            attack_name=attack_name,
            attack_params=attack_params,
        )

        if isinstance(raw_score, np.ndarray):
            raw_score = float(np.mean(raw_score))

        if raw_score is None or (isinstance(raw_score, float) and math.isnan(raw_score)):
            return 0.0

        score = min(max(float(raw_score) / EMPIRICAL_ROBUSTNESS_REFERENCE, 0.0), 1.0)
        logger.info(
            "[Robustness] empirical robustness | raw_distance=%.6f | reference=%.6f | score=%.6f",
            float(raw_score),
            EMPIRICAL_ROBUSTNESS_REFERENCE,
            score,
        )
        return score

    except Exception as exc:
        logger.warning("Could not compute empirical robustness (ART). Returning 0.0")
        logger.warning(exc)
        return 0.0


def _get_image_normalization_for_samples(samples, image_normalization=None):
    # Image normalization must come from dataset metadata; do not infer it by channel count.
    if image_normalization is not None:
        return image_normalization

    if isinstance(samples, torch.Tensor) and samples.ndim >= 4:
        logger.warning(
            "[Robustness] Image normalization missing; FGSM will perturb without normalized-space clamping."
        )
    return None


def _channel_tensor(values, samples):
    # Broadcast channel statistics over the batch and spatial dimensions.
    shape = [1, len(values)] + [1] * max(samples.dim() - 2, 0)
    return torch.tensor(values, dtype=samples.dtype, device=samples.device).view(*shape)


def _fgsm_step_and_clamp(samples, grad, epsilon, image_normalization=None):
    # Clamp image attacks in normalized space; leave non-image tensors unclamped here.
    normalization = _get_image_normalization_for_samples(samples, image_normalization=image_normalization)
    if normalization is None:
        return samples + epsilon * grad.sign()

    mean, std = normalization
    mean = _channel_tensor(mean, samples)
    std = _channel_tensor(std, samples)

    normalized_epsilon = float(epsilon) / std
    lower = (0.0 - mean) / std
    upper = (1.0 - mean) / std

    x_adv = samples + normalized_epsilon * grad.sign()
    x_adv = torch.max(torch.min(x_adv, samples + normalized_epsilon), samples - normalized_epsilon)
    return torch.max(torch.min(x_adv, upper), lower)


def fgsm_attack(model, samples, labels, epsilon=ROBUSTNESS_EPSILON, image_normalization=None):
    # Performs an FGSM (Fast Gradient Sign Method) adversarial attack on a batch of samples.

    try:
        device = next(model.parameters()).device
    except Exception:
        device = samples.device

    samples = samples.clone().detach().to(device)
    labels = labels.to(device)
    # Gradients are needed only with respect to the input batch.
    samples.requires_grad = True

    outputs = model(samples)
    logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
    loss = nn.CrossEntropyLoss()(logits, labels)
    grad = torch.autograd.grad(loss, samples, only_inputs=True)[0]
    x_adv = _fgsm_step_and_clamp(samples, grad, epsilon, image_normalization=image_normalization)
    logger.debug(
        "[Robustness] FGSM batch generated | epsilon=%.6f | samples_shape=%s | grad=%s | adv=%s",
        float(epsilon),
        tuple(samples.shape),
        _tensor_range(grad),
        _tensor_range(x_adv),
    )

    return x_adv.detach()


def get_confidence_score(
    model,
    test_sample,
    max_samples = 128,
    use_true_label = True,
):
    # Calculates the confidence score.

    try:
        if not isinstance(model, torch.nn.Module):
            logger.warning("Model is not a torch.nn.Module")
            return 0.0

        x, y = test_sample

        if isinstance(x, torch.Tensor):
            x = x[:max_samples]
        if isinstance(y, torch.Tensor):
            y = y[:max_samples]

        try:
            device = next(model.parameters()).device
        except Exception:
            device = torch.device("cpu")

        model.eval()
        with torch.no_grad():
            x = x.to(device) if isinstance(x, torch.Tensor) else x
            out = model(x)

            logits = out[0] if isinstance(out, (tuple, list)) else out
            probs = torch.softmax(logits, dim=1)

            if use_true_label and isinstance(y, torch.Tensor):
                # True-label confidence is used when labels are available.
                if y.ndim > 1:
                    y_idx = torch.argmax(y, dim=1)
                else:
                    y_idx = y
                y_idx = y_idx.to(device)

                true_probs = probs.gather(1, y_idx.view(-1, 1)).squeeze(1)
                return float(true_probs.mean().detach().cpu().item())

            msp = probs.max(dim=1).values
            return float(msp.mean().detach().cpu().item())

    except Exception as e:
        logger.warning("Could not compute confidence score")
        logger.warning(e)
        return 0.0


def attack_success_rate(model, test_loader, epsilon=ROBUSTNESS_EPSILON):
    # Computes ASR over originally correct predictions only.
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.eval()
    model.to(device)
    # Tabular datasets use constrained PGD; image datasets fall back to FGSM.
    tabular_generator = _build_tabular_generator(
        epsilon,
        _get_tabular_metadata_from_loader(test_loader),
    )
    image_normalization = None if tabular_generator is not None else _get_image_normalization_from_loader(test_loader)
    logger.info(
        "[Robustness] attack success rate | attack=%s | epsilon=%.6f",
        _attack_name(tabular_generator),
        float(epsilon),
    )

    successful_attacks = 0
    num_correct = 0

    for batch_idx, (samples, labels) in enumerate(test_loader):
        samples = samples.to(device)
        labels = labels.to(device)

        with torch.no_grad():
            outputs = model(samples)
            logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
            preds = logits.argmax(dim=1)

        correct_mask = preds.eq(labels)
        batch_correct = correct_mask.sum().item()
        if batch_correct == 0:
            # ASR is defined over clean-correct samples, so this batch contributes nothing.
            continue

        x_adv = _generate_adversarial_samples(
            model,
            samples,
            labels,
            epsilon=epsilon,
            tabular_generator=tabular_generator,
            image_normalization=image_normalization,
        )
        _log_adversarial_generation(
            "attack_success_rate",
            samples,
            labels,
            x_adv,
            epsilon,
            tabular_generator,
            batch_idx,
        )

        with torch.no_grad():
            outputs_adv = model(x_adv)
            logits_adv = outputs_adv[0] if isinstance(outputs_adv, (tuple, list)) else outputs_adv
            preds_adv = logits_adv.argmax(dim=1)

        successful_attacks += (correct_mask & preds_adv.ne(labels)).sum().item()
        num_correct += batch_correct

    return successful_attacks / num_correct if num_correct > 0 else 0.0

import logging
import math

import numpy as np
import torch

# AIF360: AI Fairness 360 [Software]. https://github.com/Trusted-AI/AIF360
# Licensed under Apache License 2.0: https://github.com/Trusted-AI/AIF360/blob/main/LICENSE
# HolisticAI: open-source library to assess and improve AI trustworthiness.
# Licensed under Apache License 2.0: https://github.com/holistic-ai/holisticai/blob/main/LICENSE

logger = logging.getLogger(__name__)

def _extract_model_logits(model_output):
    # Normalize the output returned by a model forward pass into a logits tensor.
    return model_output[0] if isinstance(model_output, (tuple, list)) else model_output


def _prepare_class_targets(y):
    # Convert different target representations into a flat class-index tensor.
    if not torch.is_tensor(y):
        y = torch.as_tensor(y)

    if y.ndim > 1:
        if y.size(-1) > 1:
            y = y.argmax(dim=-1)
        else:
            y = y.view(-1)

    return y.long().view(-1)


def _logits_to_probabilities(logits):
    # Convert model outputs into a probability matrix of shape (N, C).
    if not torch.is_tensor(logits):
        logits = torch.as_tensor(logits)

    if logits.ndim == 0:
        logits = logits.view(1, 1)
    elif logits.ndim == 1:
        logits = logits.view(-1, 1)
    elif logits.ndim > 2:
        logits = logits.reshape(logits.shape[0], -1)

    if logits.size(1) == 1:
        pos_prob = torch.sigmoid(logits[:, 0])
        probs = torch.stack([1.0 - pos_prob, pos_prob], dim=1)
    else:
        row_sums = logits.sum(dim=1)
        looks_like_probs = (
            torch.all(logits >= 0)
            and torch.all(logits <= 1.0 + 1e-6)
            and torch.allclose(row_sums, torch.ones_like(row_sums), atol=1e-4, rtol=1e-4)
        )
        probs = logits if looks_like_probs else torch.softmax(logits, dim=1)

    probs = torch.clamp(probs, min=0.0, max=1.0)
    probs = probs / probs.sum(dim=1, keepdim=True).clamp_min(1e-12)
    return probs


def _collect_classification_statistics(model, dataloader):
    # Collect prediction statistics required by calibration and inequality metrics.
    if not isinstance(model, torch.nn.Module):
        logger.warning("Model is not a torch.nn.Module")
        empty = np.array([], dtype=float)
        return empty, empty, empty

    try:
        device = next(model.parameters()).device
    except Exception:
        device = torch.device("cpu")

    confidences = []
    correct = []
    true_probs = []

    model.eval()
    with torch.no_grad():
        for batch in dataloader:
            if not isinstance(batch, (tuple, list)) or len(batch) < 2:
                continue

            x, y = batch[0], batch[1]
            if not (torch.is_tensor(x) and torch.is_tensor(y)):
                continue

            x = x.to(device)
            y = _prepare_class_targets(y).to(device)

            # Metrics consume probabilities even when the model returns raw logits
            # or wraps the classification output in a tuple/list.
            probs = _logits_to_probabilities(_extract_model_logits(model(x)))

            if probs.ndim != 2 or probs.size(0) == 0:
                continue

            n = min(int(y.numel()), int(probs.size(0)))
            if n == 0:
                continue
            y = y[:n]
            probs = probs[:n]

            valid_mask = (y >= 0) & (y < probs.size(1))
            if not torch.any(valid_mask):
                continue

            y = y[valid_mask]
            probs = probs[valid_mask]

            # Confidence is the predicted-class probability. true_probs is the
            # probability assigned to the actual class, used as a continuous benefit.
            conf, preds = probs.max(dim=1)
            confidences.append(conf.cpu())
            correct.append(preds.eq(y).float().cpu())
            true_probs.append(probs.gather(1, y.view(-1, 1)).squeeze(1).cpu())

    if not confidences:
        empty = np.array([], dtype=float)
        return empty, empty, empty

    return (
        torch.cat(confidences).numpy(),
        torch.cat(correct).numpy(),
        torch.cat(true_probs).numpy(),
    )


def get_well_calibration_error(model, test_dataloader, n_bins=10):
    # Calculates a well-calibration error style metric using prediction confidence.
    if not isinstance(model, torch.nn.Module):
        logger.warning("Model is not a torch.nn.Module")
        return 1.0

    try:
        n_bins = max(2, int(n_bins))
    except Exception:
        n_bins = 10

    confidences, correct, _ = _collect_classification_statistics(model, test_dataloader)

    if len(confidences) == 0 or len(correct) == 0:
        return 1.0

    confidences = np.clip(np.asarray(confidences, dtype=float), 0.0, 1.0)
    correct = np.clip(np.asarray(correct, dtype=float), 0.0, 1.0)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    total = float(len(confidences))

    # ECE compares empirical accuracy and average confidence within each bin.
    for idx in range(n_bins):
        left = bin_edges[idx]
        right = bin_edges[idx + 1]
        if idx == n_bins - 1:
            mask = (confidences >= left) & (confidences <= right)
        else:
            mask = (confidences >= left) & (confidences < right)

        if not np.any(mask):
            continue

        bin_weight = float(mask.sum()) / total
        bin_accuracy = float(correct[mask].mean())
        bin_confidence = float(confidences[mask].mean())
        ece += bin_weight * abs(bin_accuracy - bin_confidence)

    return float(np.clip(ece, 0.0, 1.0))


def get_generalized_entropy_index(model, test_dataloader, alpha=2):
    # Calculates generalized entropy index from model predictions.
    try:
        _, _, true_class_probs = _collect_classification_statistics(model, test_dataloader)
        if len(true_class_probs) == 0:
            return 0.0

        eps = 1e-12
        b = np.clip(np.asarray(true_class_probs, dtype=float), eps, 1.0)
        mu = float(np.mean(b))
        if mu <= 0:
            return 0.0

        # GEI measures dispersion around the mean benefit. Lower values mean the
        # model gives more even true-class confidence across samples.
        ratio = np.clip(b / mu, eps, None)

        if alpha == 0:
            val = float(np.mean(-np.log(ratio)))
        elif alpha == 1:
            val = float(np.mean(ratio * np.log(ratio)))
        elif alpha == 2:
            val = float(np.mean((ratio - 1.0) ** 2) / 2.0)
        else:
            val = float(np.mean(ratio**alpha - 1.0) / (alpha * (alpha - 1.0)))

        if math.isnan(val) or math.isinf(val):
            return 0.0
        return max(0.0, val)
    except Exception as exc:
        logger.warning("Could not compute generalized entropy index")
        logger.warning(exc)
        return 0.0


def get_theil_index(model, test_dataloader):
    # Convenience wrapper for generalized entropy index with alpha=1.
    return get_generalized_entropy_index(model, test_dataloader, alpha=1)


def get_coefficient_of_variation(model, test_dataloader):
    # Calculates coefficient of variation from GEI(alpha=2).
    try:
        gei = get_generalized_entropy_index(model, test_dataloader, alpha=2)
        return float(np.sqrt(2 * gei))
    except Exception as exc:
        logger.warning("Could not compute coefficient of variation")
        logger.warning(exc)
        return 0.0

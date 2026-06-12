import logging

import torch

from nebula.addons.defenses.adversarial_training.config import AdversarialTrainingConfig
from nebula.config.config import TRAINING_LOGGER

logging_training = logging.getLogger(TRAINING_LOGGER)


class AdversarialTrainingSampleLogger:
    """Logs representative clean/adversarial samples without affecting training tensors."""

    LOGGED_SAMPLES_PER_ROUND = 3

    def __init__(self, config: AdversarialTrainingConfig, generator):
        # Keep logging state per defense instance and per federated round.
        self.config = config
        self.generator = generator
        self._logged_samples_by_round: dict[int, int] = {}

    def log(self, model, x_clean: torch.Tensor, x_adv: torch.Tensor, y: torch.Tensor) -> None:
        # Log only a few representative samples per round to avoid noisy training logs.
        if not self.config.log_adversarial_metrics:
            return

        current_round = int(getattr(model, "round", 0))
        already_logged = self._logged_samples_by_round.get(current_round, 0)
        remaining = self.LOGGED_SAMPLES_PER_ROUND - already_logged
        if remaining <= 0:
            return

        with torch.no_grad():
            # Predictions must use the same normalized tensors that the model saw during training.
            model_clean = x_clean.detach()
            model_adv = x_adv.detach()
            clean_predictions = torch.argmax(model(model_clean), dim=1)
            adversarial_predictions = torch.argmax(model(model_adv), dim=1)

            # Display values can be denormalized for images; tabular tensors are already in model space.
            clean_view = model_clean
            adv_view = model_adv
            if hasattr(self.generator, "denormalize"):
                clean_view = self.generator.denormalize(clean_view)
                adv_view = self.generator.denormalize(adv_view)

            delta = adv_view - clean_view
            samples_to_log = min(remaining, int(clean_view.size(0)))
            for sample_idx in range(samples_to_log):
                self._log_sample(
                    current_round=current_round,
                    sample_number=already_logged + sample_idx + 1,
                    clean=clean_view[sample_idx].detach().float().cpu(),
                    adversarial=adv_view[sample_idx].detach().float().cpu(),
                    delta=delta[sample_idx].detach().float().cpu(),
                    label=self._safe_scalar(y, sample_idx),
                    clean_prediction=self._safe_scalar(clean_predictions, sample_idx),
                    adversarial_prediction=self._safe_scalar(adversarial_predictions, sample_idx),
                )

            self._logged_samples_by_round[current_round] = already_logged + samples_to_log

    def _log_sample(
        self,
        current_round: int,
        sample_number: int,
        clean: torch.Tensor,
        adversarial: torch.Tensor,
        delta: torch.Tensor,
        label: int | None,
        clean_prediction: int | None,
        adversarial_prediction: int | None,
    ) -> None:
        # Write the shared summary line before adding image/tabular-specific details.
        logging_training.info(
            "[AdversarialTrainingDefense] Round %s | Sample %s/%s before/after distortion | "
            "dataset=%s | attack=%s | epsilon_effective=%.6f | label=%s | "
            "clean_pred=%s | adversarial_pred=%s | "
            "clean[min=%.6f max=%.6f mean=%.6f] | "
            "adv[min=%.6f max=%.6f mean=%.6f] | delta_linf=%.6f | delta_l2=%.6f",
            current_round,
            sample_number,
            self.LOGGED_SAMPLES_PER_ROUND,
            self.config.dataset_name,
            self.config.attack,
            float(getattr(self.generator, "last_epsilon", self.config.epsilon) or 0.0),
            label,
            clean_prediction,
            adversarial_prediction,
            clean.min().item(),
            clean.max().item(),
            clean.mean().item(),
            adversarial.min().item(),
            adversarial.max().item(),
            adversarial.mean().item(),
            delta.abs().max().item(),
            delta.reshape(-1).norm(p=2).item(),
        )
        if self.config.domain == "tabular":
            self._log_tabular_sample(current_round, sample_number, clean, adversarial, delta)
        else:
            # Image logs stay compact: a 4x4 patch is enough to see that perturbations exist.
            self._log_image_sample(current_round, sample_number, clean, adversarial, delta)

    def _log_tabular_sample(
        self,
        current_round: int,
        sample_number: int,
        clean: torch.Tensor,
        adversarial: torch.Tensor,
        delta: torch.Tensor,
    ) -> None:
        # For tabular data, log full vectors because each feature has semantic meaning.
        feature_names = getattr(getattr(self.generator, "metadata", None), "feature_names", None)
        logging_training.info(
            "[AdversarialTrainingDefense] Round %s | Clean tabular sample %s:\n%s",
            current_round,
            sample_number,
            self._format_tabular_vector(clean, feature_names),
        )
        logging_training.info(
            "[AdversarialTrainingDefense] Round %s | Final adversarial tabular sample %s:\n%s",
            current_round,
            sample_number,
            self._format_tabular_vector(adversarial, feature_names),
        )
        logging_training.info(
            "[AdversarialTrainingDefense] Round %s | Tabular perturbation delta sample %s:\n%s",
            current_round,
            sample_number,
            self._format_tabular_vector(delta, feature_names),
        )
        logging_training.info(
            "[AdversarialTrainingDefense] Round %s | Changed tabular features sample %s:\n%s",
            current_round,
            sample_number,
            self._format_tabular_changes(clean, adversarial, delta, feature_names),
        )

    def _log_image_sample(
        self,
        current_round: int,
        sample_number: int,
        clean: torch.Tensor,
        adversarial: torch.Tensor,
        delta: torch.Tensor,
    ) -> None:
        # For images, log a small patch instead of the full tensor.
        logging_training.info(
            "[AdversarialTrainingDefense] Round %s | Clean sample %s channel0 4x4:\n%s",
            current_round,
            sample_number,
            self._format_patch(clean),
        )
        logging_training.info(
            "[AdversarialTrainingDefense] Round %s | Adversarial sample %s channel0 4x4:\n%s",
            current_round,
            sample_number,
            self._format_patch(adversarial),
        )
        logging_training.info(
            "[AdversarialTrainingDefense] Round %s | Delta sample %s channel0 4x4:\n%s",
            current_round,
            sample_number,
            self._format_patch(delta),
        )

    @staticmethod
    def _safe_scalar(values: torch.Tensor, sample_idx: int) -> int | None:
        # Read one scalar defensively in case a short tensor is passed to the logger.
        if values.numel() <= sample_idx:
            return None
        return int(values[sample_idx].detach().cpu().item())

    @staticmethod
    def _format_patch(sample: torch.Tensor, patch_size: int = 4) -> str:
        # Format a small leading patch so image logs stay human-readable.
        if sample.dim() >= 3:
            patch = sample[0, :patch_size, :patch_size]
        elif sample.dim() == 2:
            patch = sample[:patch_size, :patch_size]
        else:
            patch = sample[:patch_size]
        values = patch.tolist()
        if sample.dim() < 2:
            return str([round(float(value), 6) for value in values])
        return str([[round(float(value), 6) for value in row] for row in values])

    @staticmethod
    def _format_tabular_vector(sample: torch.Tensor, feature_names: list[str] | None = None) -> str:
        # Format a tabular sample as a feature-name to value mapping.
        values = sample.reshape(-1).tolist()
        names = feature_names or [f"feature_{idx}" for idx in range(len(values))]
        return str({str(name): round(float(value), 6) for name, value in zip(names, values, strict=False)})

    @staticmethod
    def _format_tabular_changes(
        clean: torch.Tensor,
        adversarial: torch.Tensor,
        delta: torch.Tensor,
        feature_names: list[str] | None = None,
        tolerance: float = 1e-7,
    ) -> str:
        # Format only features whose perturbation is larger than numerical noise.
        clean_values = clean.reshape(-1).tolist()
        adversarial_values = adversarial.reshape(-1).tolist()
        delta_values = delta.reshape(-1).tolist()
        names = feature_names or [f"feature_{idx}" for idx in range(len(delta_values))]
        # Keep the changed-features log focused; full vectors are logged just above.
        changes = {
            str(name): {
                "clean": round(float(clean_value), 6),
                "adversarial": round(float(adversarial_value), 6),
                "delta": round(float(delta_value), 6),
            }
            for name, clean_value, adversarial_value, delta_value in zip(
                names,
                clean_values,
                adversarial_values,
                delta_values,
                strict=False,
            )
            if abs(float(delta_value)) > tolerance
        }
        return str(changes)

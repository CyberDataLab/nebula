import logging
from typing import Any

import torch

from nebula.addons.defenses.adversarial_training.base import AdversarialExampleGenerator
from nebula.addons.defenses.adversarial_training.config import (
    ERR_ALPHA,
    ERR_APPLY_PROBABILITY,
    ERR_CANDIDATE_SELECTION,
    ERR_EPSILON,
    ERR_IMAGE_ATTACK,
    ERR_LOSS_INCREASE,
    ERR_MARGIN_WINDOW,
    ERR_MODE,
    ERR_STEPS,
    ERR_TABULAR_ATTACK,
    ERR_TABULAR_METADATA,
    ERR_UNSUPPORTED_ATTACK,
    IMAGE_ADVERSARIAL_ATTACKS,
    IMAGE_DATASET_NORMALIZATION,
    TABULAR_ADVERSARIAL_ATTACKS,
    TABULAR_ADVERSARIAL_DATASETS,
    AdversarialTrainingConfig,
    config_from_participant,
    validate_config,
)
from nebula.core.datasets.image_metadata import get_image_normalization
from nebula.addons.defenses.adversarial_training.image import (
    ImageAdversarialExampleGenerator,
    ImageFGSMGenerator,
    ImagePGDGenerator,
)
from nebula.addons.defenses.adversarial_training.logging import AdversarialTrainingSampleLogger
from nebula.addons.defenses.adversarial_training.tabular import (
    TabularAdversarialExampleGenerator,
    TabularConstrainedPGDGenerator,
    TabularConstraintSet,
)
from nebula.core.datasets.tabular_metadata import CATEGORICAL, CONTINUOUS, INTEGER, TabularAdversarialMetadata


class AdversarialTrainingDefense:
    """Batch-level adversarial training defense for Nebula models."""

    LOGGED_SAMPLES_PER_ROUND = AdversarialTrainingSampleLogger.LOGGED_SAMPLES_PER_ROUND

    def __init__(self, config: AdversarialTrainingConfig, generator: AdversarialExampleGenerator):
        # Keep the selected generator and logger together for each participant model.
        self.config = config
        self.generator = generator
        self.sample_logger = AdversarialTrainingSampleLogger(config, generator)
        self._logged_adversarial_samples_by_round = self.sample_logger._logged_samples_by_round

    @classmethod
    def from_participant_config(
        cls,
        participant_config: dict[str, Any],
        partition=None,
    ) -> "AdversarialTrainingDefense | None":
        # This is the only entry point used by Nebula's node setup.
        config = config_from_participant(participant_config)
        if config is None:
            return None
        validate_config(config)

        if config.domain == "tabular":
            metadata = cls._get_tabular_metadata(partition)
            return cls(config=config, generator=TabularConstrainedPGDGenerator(config, metadata))

        if config.domain == "image":
            # Image attacks run in normalized model space, so each dataset must provide mean/std.
            normalization = get_image_normalization(config.dataset_name)
            if normalization is None:
                logging.warning(
                    "[AdversarialTrainingDefense] Skipping adversarial training: dataset '%s' has no image bounds",
                    config.dataset_name,
                )
                return None

            return cls(config=config, generator=cls._build_image_generator(config, normalization))

        logging.warning(
            "[AdversarialTrainingDefense] Skipping adversarial training: domain '%s' is not implemented yet",
            config.domain,
        )
        return None

    @staticmethod
    def _build_image_generator(config, normalization):
        # Choose the image attack implementation requested by the participant config.
        mean, std = normalization
        if config.attack == "fgsm":
            return ImageFGSMGenerator(config, mean, std)
        if config.attack == "pgd":
            return ImagePGDGenerator(config, mean, std)
        raise ValueError(ERR_UNSUPPORTED_ATTACK.format(attack=config.attack))

    @staticmethod
    def _get_tabular_metadata(partition) -> TabularAdversarialMetadata:
        # Load the tabular constraints from the local training partition.
        train_set = getattr(partition, "train_set", None) if partition is not None else None
        metadata = getattr(train_set, "tabular_metadata", None)
        if metadata is None:
            raise ValueError(ERR_TABULAR_METADATA)
        # Metadata can come from an in-memory dataset object or from a serialized config.
        if isinstance(metadata, TabularAdversarialMetadata):
            tabular_metadata = metadata
        else:
            tabular_metadata = TabularAdversarialMetadata.from_dict(metadata)

        _log_tabular_metadata(tabular_metadata)
        return tabular_metadata

    def should_apply(self, x: torch.Tensor) -> bool:
        # Allows adversarial training to be applied to only a fraction of batches.
        if self.config.apply_probability >= 1.0:
            return True
        if self.config.apply_probability <= 0.0:
            return False
        return bool(torch.rand((), device=x.device).item() < self.config.apply_probability)

    def compute_training_step(self, model, x, y, criterion):
        if not self.should_apply(x):
            logits = model(x)
            loss = criterion(logits, y)
            return loss, logits, {}

        # Generate x_adv once and reuse it for logging, adversarial loss and metrics.
        x_adv = self.generator.generate(model, x, y, criterion)
        self._log_adversarial_samples(model, x, x_adv, y)
        adv_logits = model(x_adv)
        adv_loss = criterion(adv_logits, y)

        # "adversarial" replaces the clean batch loss completely.
        if self.config.mode == "adversarial":
            return adv_loss, adv_logits, self._extra_metrics({
                "Adversarial Loss": adv_loss,
                "Adversarial Accuracy": self._accuracy(adv_logits, y),
            })

        clean_logits = model(x)
        clean_loss = criterion(clean_logits, y)
        # "mixed" uses a fixed 50/50 clean/adversarial objective.
        loss = self.config.clean_weight * clean_loss + self.config.adversarial_weight * adv_loss

        return loss, clean_logits, self._extra_metrics({
            "Clean Loss": clean_loss,
            "Adversarial Loss": adv_loss,
            "Adversarial Accuracy": self._accuracy(adv_logits, y),
        })

    def _log_adversarial_samples(self, model, x_clean: torch.Tensor, x_adv: torch.Tensor, y: torch.Tensor) -> None:
        # Delegate logging so the training step stays focused on loss computation.
        self.sample_logger.log(model, x_clean, x_adv, y)

    def _accuracy(self, logits, y):
        # Compute batch accuracy from model logits.
        predictions = torch.argmax(logits, dim=1)
        return torch.mean((predictions == y).float())

    def _extra_metrics(self, metrics):
        # Allow users to disable adversarial metrics without changing the training loss.
        if not self.config.log_adversarial_metrics:
            return {}
        return metrics


def _log_tabular_metadata(tabular_metadata: TabularAdversarialMetadata) -> None:
    # Log a compact metadata summary to make constrained PGD setup auditable.
    integer_features = _feature_names_by_type(tabular_metadata, {INTEGER})
    continuous_features = _feature_names_by_type(tabular_metadata, {CONTINUOUS})
    categorical_features = _feature_names_by_type(tabular_metadata, {CATEGORICAL})
    non_perturbable_features = _feature_names_excluding_types(
        tabular_metadata,
        {CONTINUOUS, INTEGER, CATEGORICAL},
    )
    logging.info(
        "[AdversarialTrainingDefense] Tabular feature mask loaded | integer=%s | continuous=%s | "
        "categorical=%s | categorical_groups=%s | non_perturbable=%s | integer_features=%s | "
        "continuous_features=%s | categorical_preview=%s | non_perturbable_preview=%s",
        len(integer_features),
        len(continuous_features),
        len(categorical_features),
        len(tabular_metadata.categorical_groups or []),
        len(non_perturbable_features),
        integer_features,
        continuous_features,
        categorical_features[:20],
        non_perturbable_features[:20],
    )


def _feature_names_by_type(tabular_metadata: TabularAdversarialMetadata, feature_types: set[str]) -> list[str]:
    # Return feature names whose metadata type is included in feature_types.
    return [
        name
        for name, feature_type in zip(tabular_metadata.feature_names, tabular_metadata.feature_types, strict=True)
        if feature_type in feature_types
    ]


def _feature_names_excluding_types(tabular_metadata: TabularAdversarialMetadata, feature_types: set[str]) -> list[str]:
    # Return feature names whose metadata type is not included in feature_types.
    return [
        name
        for name, feature_type in zip(tabular_metadata.feature_names, tabular_metadata.feature_types, strict=True)
        if feature_type not in feature_types
    ]


def apply_adversarial_training_if_enabled(model, participant_config: dict[str, Any], partition=None) -> None:
    # Attach the defense to the model only when the participant config enables it.
    defense = AdversarialTrainingDefense.from_participant_config(participant_config, partition=partition)
    if defense is not None:
        model.set_adversarial_training(defense)
        logging.info(
            "[AdversarialTrainingDefense] Enabled | dataset=%s | attack=%s | epsilon_max=%s | "
            "epsilon_range=[%.6f, %.6f] | epsilon_step=%.6f | steps=%s | mode=%s | "
            "clean_weight=%.2f | adversarial_weight=%.2f | apply_probability=%.2f | "
            "candidate_selection=%s | target_loss_increase=%s | max_loss_increase=%s | "
            "target_margin=%s | max_margin=%s | log_adversarial_metrics=%s",
            defense.config.dataset_name,
            defense.config.attack,
            defense.config.epsilon,
            defense.config.epsilon / 4.0,
            defense.config.epsilon,
            defense.config.epsilon / 8.0,
            defense.config.steps,
            defense.config.mode,
            defense.config.clean_weight,
            defense.config.adversarial_weight,
            defense.config.apply_probability,
            defense.config.candidate_selection,
            defense.config.target_loss_increase,
            defense.config.max_loss_increase,
            defense.config.target_margin,
            defense.config.max_margin,
            defense.config.log_adversarial_metrics,
        )


__all__ = [
    "ERR_ALPHA",
    "ERR_APPLY_PROBABILITY",
    "ERR_CANDIDATE_SELECTION",
    "ERR_EPSILON",
    "ERR_IMAGE_ATTACK",
    "ERR_LOSS_INCREASE",
    "ERR_MARGIN_WINDOW",
    "ERR_MODE",
    "ERR_STEPS",
    "ERR_TABULAR_ATTACK",
    "ERR_TABULAR_METADATA",
    "ERR_UNSUPPORTED_ATTACK",
    "IMAGE_ADVERSARIAL_ATTACKS",
    "IMAGE_DATASET_NORMALIZATION",
    "TABULAR_ADVERSARIAL_ATTACKS",
    "TABULAR_ADVERSARIAL_DATASETS",
    "AdversarialExampleGenerator",
    "AdversarialTrainingConfig",
    "AdversarialTrainingDefense",
    "ImageAdversarialExampleGenerator",
    "ImageFGSMGenerator",
    "ImagePGDGenerator",
    "TabularAdversarialExampleGenerator",
    "TabularConstrainedPGDGenerator",
    "TabularConstraintSet",
    "apply_adversarial_training_if_enabled",
]

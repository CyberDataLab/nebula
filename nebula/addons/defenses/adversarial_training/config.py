from dataclasses import dataclass
from typing import Any

from nebula.core.datasets.image_metadata import IMAGE_DATASET_NORMALIZATION

IMAGE_ADVERSARIAL_ATTACKS = {"fgsm", "pgd"}
TABULAR_ADVERSARIAL_ATTACKS = {"constrained_pgd"}
TABULAR_ADVERSARIAL_DATASETS = {"AdultCensus", "BreastCancer", "Covtype", "KDDCUP99"}

ERR_IMAGE_ATTACK = "image adversarial_training.attack must be one of: fgsm, pgd"
ERR_TABULAR_ATTACK = "tabular adversarial_training.attack must be one of: constrained_pgd"
ERR_MODE = "adversarial_training.mode must be one of: adversarial, mixed"
ERR_EPSILON = "adversarial_training.epsilon must be >= 0"
ERR_ALPHA = "adversarial_training.alpha must be >= 0"
ERR_STEPS = "adversarial_training.steps must be >= 1"
ERR_APPLY_PROBABILITY = "adversarial_training.apply_probability must be in [0, 1]"
ERR_CANDIDATE_SELECTION = (
    "tabular adversarial_training.candidate_selection must be one of: none, loss_window, margin_window"
)
ERR_LOSS_INCREASE = "adversarial_training loss increase thresholds must be >= 0 and target <= max"
ERR_MARGIN_WINDOW = "adversarial_training margin thresholds must satisfy target_margin <= max_margin"
ERR_TABULAR_METADATA = "Tabular adversarial training requires tabular_metadata"
ERR_UNSUPPORTED_ATTACK = "Unsupported adversarial training attack: {attack}"

@dataclass(frozen=True)
class AdversarialTrainingConfig:
    enabled: bool = False
    dataset_name: str | None = None
    domain: str = "image"
    attack: str = "fgsm"
    epsilon: float = 8.0 / 255.0
    alpha: float | None = None
    steps: int = 1
    mode: str = "mixed"
    clean_weight: float = 0.5
    adversarial_weight: float = 0.5
    apply_probability: float = 0.3
    log_adversarial_metrics: bool = True
    candidate_selection: str = "none"
    target_loss_increase: float | None = None
    max_loss_increase: float | None = None
    target_margin: float | None = 0.0
    max_margin: float | None = 0.5


def config_from_participant(participant_config: dict[str, Any]) -> AdversarialTrainingConfig | None:
    # Read the raw participant config and normalize it into a typed defense config.
    raw = participant_config.get("defense_args", {}).get("adversarial_training", {})
    if not raw or not raw.get("enabled", False):
        return None

    dataset_name = participant_config.get("data_args", {}).get("dataset")
    domain = str(raw.get("domain", "image")).lower()
    attack = str(raw.get("attack", "constrained_pgd" if domain == "tabular" else "fgsm")).lower()

    mode = str(raw.get("mode", "mixed")).lower()
    clean_weight, adversarial_weight = _loss_weights_for_mode(mode)

    return AdversarialTrainingConfig(
        enabled=True,
        dataset_name=dataset_name,
        domain=domain,
        attack=attack,
        epsilon=float(raw.get("epsilon", 8.0 / 255.0)),
        alpha=float(raw["alpha"]) if raw.get("alpha") is not None else None,
        steps=int(raw.get("steps", 1)),
        mode=mode,
        clean_weight=clean_weight,
        adversarial_weight=adversarial_weight,
        apply_probability=float(raw.get("apply_probability", 0.3)),
        log_adversarial_metrics=True,
        candidate_selection=str(raw.get("candidate_selection", "none")).lower(),
        target_loss_increase=float(raw["target_loss_increase"])
        if raw.get("target_loss_increase") is not None
        else None,
        max_loss_increase=float(raw["max_loss_increase"])
        if raw.get("max_loss_increase") is not None
        else None,
        target_margin=float(raw["target_margin"])
        if raw.get("target_margin") is not None
        else 0.0,
        max_margin=float(raw["max_margin"])
        if raw.get("max_margin") is not None
        else 0.5,
    )


def _loss_weights_for_mode(mode: str) -> tuple[float, float]:
    if mode == "adversarial":
        return 0.0, 1.0
    return 0.5, 0.5


def validate_config(config: AdversarialTrainingConfig) -> None:
    # Fail early when a frontend/backend config value cannot produce a valid attack.
    if config.mode not in {"adversarial", "mixed"}:
        raise ValueError(ERR_MODE)
    if config.domain == "image" and config.attack not in IMAGE_ADVERSARIAL_ATTACKS:
        raise ValueError(ERR_IMAGE_ATTACK)
    if config.domain == "tabular" and config.attack not in TABULAR_ADVERSARIAL_ATTACKS:
        raise ValueError(ERR_TABULAR_ATTACK)
    if config.domain == "tabular" and config.candidate_selection not in {"none", "loss_window", "margin_window"}:
        raise ValueError(ERR_CANDIDATE_SELECTION)
    if config.domain == "image" and config.candidate_selection != "none":
        raise ValueError(ERR_CANDIDATE_SELECTION)
    if config.epsilon < 0:
        raise ValueError(ERR_EPSILON)
    if config.alpha is not None and config.alpha < 0:
        raise ValueError(ERR_ALPHA)
    if config.steps < 1:
        raise ValueError(ERR_STEPS)
    if not 0.0 <= config.apply_probability <= 1.0:
        raise ValueError(ERR_APPLY_PROBABILITY)
    if config.target_loss_increase is not None and config.target_loss_increase < 0:
        raise ValueError(ERR_LOSS_INCREASE)
    if config.max_loss_increase is not None and config.max_loss_increase < 0:
        raise ValueError(ERR_LOSS_INCREASE)
    if (
        config.target_loss_increase is not None
        and config.max_loss_increase is not None
        and config.target_loss_increase > config.max_loss_increase
    ):
        raise ValueError(ERR_LOSS_INCREASE)
    if (
        config.target_margin is not None
        and config.max_margin is not None
        and config.target_margin > config.max_margin
    ):
        raise ValueError(ERR_MARGIN_WINDOW)

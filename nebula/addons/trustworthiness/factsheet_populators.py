"""Profile-specific factsheet metric population."""

import logging

from nebula.addons.trustworthiness.helpers.explainability import (
    get_explainability_metrics_summary,
)
from nebula.addons.trustworthiness.helpers.model_quality import (
    get_coefficient_of_variation,
    get_generalized_entropy_index,
    get_theil_index,
    get_well_calibration_error,
)
from nebula.addons.trustworthiness.helpers.privacy import (
    get_epsilon_star,
    get_mia_auc,
)
from nebula.addons.trustworthiness.helpers.robustness import (
    attack_success_rate,
    get_adversarial_accuracy,
    get_clever_score,
    get_confidence_score,
    get_empirical_robustness_score,
    get_loss_sensitivity_score,
)

logger = logging.getLogger(__name__)
from nebula.addons.trustworthiness.factsheet_common import (
    DATA_TYPE_IMAGES,
    DATA_TYPE_TABULAR,
    cap_score,
    get_normalized_model_data_type,
    inverse_bounded_score,
    inverse_score,
)

FEDERATION_CFL = "cfl"
FEDERATION_DFL = "dfl"


def get_federation_profile(federation):
    # Group SDFL with DFL because both use decentralized factsheet profiles.
    return FEDERATION_DFL if str(federation).upper() in {"DFL", "SDFL"} else FEDERATION_CFL


def populate_profile_metrics(
    factsheet,
    federation,
    model,
    train_loader,
    test_loader,
    test_accuracy,
):
    # Select the profile-specific populator, falling back to the shared metric set.
    federation_profile = get_federation_profile(federation)
    data_type = str(factsheet.get("data", {}).get("type", "")).strip().lower()
    if not data_type:
        data_type = get_normalized_model_data_type(model)
    populator = PROFILE_POPULATORS.get((federation_profile, data_type), populate_common_profile_metrics)

    populator(
        factsheet=factsheet,
        model=model,
        train_loader=train_loader,
        test_loader=test_loader,
        test_accuracy=test_accuracy,
    )


def populate_cfl_images_metrics(factsheet, model, train_loader, test_loader, test_accuracy):
    # Image factsheets include all image-compatible robustness metrics.
    populate_common_profile_metrics(factsheet, model, train_loader, test_loader, test_accuracy)
    populate_image_robustness_metrics(factsheet, model, test_loader)


def populate_cfl_tabular_metrics(factsheet, model, train_loader, test_loader, test_accuracy):
    # Tabular factsheets use only metrics shared by valid tabular and image workflows.
    populate_common_profile_metrics(factsheet, model, train_loader, test_loader, test_accuracy)
    remove_image_only_robustness_metrics(factsheet)


def populate_dfl_images_metrics(factsheet, model, train_loader, test_loader, test_accuracy):
    # Image factsheets include all image-compatible robustness metrics.
    populate_common_profile_metrics(factsheet, model, train_loader, test_loader, test_accuracy)
    populate_image_robustness_metrics(factsheet, model, test_loader)


def populate_dfl_tabular_metrics(factsheet, model, train_loader, test_loader, test_accuracy):
    # Tabular factsheets use only metrics shared by valid tabular and image workflows.
    populate_common_profile_metrics(factsheet, model, train_loader, test_loader, test_accuracy)
    remove_image_only_robustness_metrics(factsheet)


def populate_common_profile_metrics(factsheet, model, train_loader, test_loader, test_accuracy):
    # Current shared metric set used by every factsheet profile.
    # Reuse one test batch for sample-based metrics and compute summary explainability once.
    test_sample = next(iter(test_loader))
    explainability_metrics = get_explainability_metrics_summary(model, test_loader)

    populate_common_model_quality_metrics(
        factsheet,
        model,
        train_loader,
        test_loader,
        test_accuracy,
        test_sample,
    )
    populate_common_explainability_metrics(factsheet, explainability_metrics)
    populate_common_robustness_metrics(factsheet, model, test_loader)


def populate_common_model_quality_metrics(
    factsheet,
    model,
    train_loader,
    test_loader,
    test_accuracy,
    test_sample,
):
    # Populate model quality, privacy, and fairness metrics shared by all profiles.

    # Privacy metrics derived from train/test behavior.
    factsheet["privacy"]["epsilon_star"] = get_epsilon_star(model, train_loader, test_loader)
    factsheet["privacy"]["inverse_epsilon_star"] = inverse_score(factsheet["privacy"]["epsilon_star"])
    factsheet["privacy"]["mia_auc"] = get_mia_auc(model, train_loader, test_loader)
    factsheet["privacy"]["mia_auc_score"] = 1 - 2 * abs(factsheet["privacy"]["mia_auc"] - 0.5)

    # Fairness and calibration metrics expressed as inverse scores.
    overfitting_value = max(0.0, float(factsheet["performance"]["train_accuracy"]) - float(test_accuracy))
    factsheet["fairness"]["inverse_overfitting"] = inverse_bounded_score(overfitting_value)

    well_calibration_error_value = get_well_calibration_error(model, test_loader)
    factsheet["fairness"]["inverse_well_calibration_error"] = inverse_bounded_score(well_calibration_error_value)

    generalized_entropy_index_value = get_generalized_entropy_index(model, test_loader)
    factsheet["fairness"]["inverse_generalized_entropy_index"] = inverse_score(generalized_entropy_index_value)

    theil_index_value = get_theil_index(model, test_loader)
    factsheet["fairness"]["inverse_theil_index"] = inverse_score(theil_index_value)

    coefficient_of_variation_value = get_coefficient_of_variation(model, test_loader)
    factsheet["fairness"]["inverse_coefficient_of_variation"] = inverse_score(coefficient_of_variation_value)

    # Confidence is already a probability-like score in [0, 1].
    value_confidence_score = get_confidence_score(model, test_sample)
    factsheet["performance"]["test_confidence_score"] = value_confidence_score


def populate_common_explainability_metrics(factsheet, explainability_metrics):
    # Copy explainability summary metrics into the factsheet schema.
    factsheet["explainability"]["alpha_score"] = explainability_metrics["alpha_score"]
    factsheet["explainability"]["spread_ratio"] = explainability_metrics["spread_ratio"]
    factsheet["explainability"]["spread_divergence"] = explainability_metrics["spread_divergence"]

    feature_importance = explainability_metrics["feature_importance_cv"]
    factsheet["performance"]["clipped_test_feature_importance_cv"] = cap_score(feature_importance)


def populate_common_robustness_metrics(factsheet, model, test_loader):
    # Populate robustness metrics valid for both image and tabular datasets.
    lr = factsheet["configuration"]["learning_rate"]
    num_classes = model.get_num_classes()

    # Loader-based adversarial accuracy.
    value_adv_accuracy = get_adversarial_accuracy(model, test_loader, num_classes, lr)
    factsheet["performance"]["test_adv_accuracy"] = value_adv_accuracy

    # Attack success is inverted so higher remains better in the factsheet.
    value_attack_success_rate = attack_success_rate(
        model,
        test_loader,
    )
    factsheet["performance"]["inverse_test_attack_success_rate"] = 1 - value_attack_success_rate


def populate_image_robustness_metrics(factsheet, model, test_loader):
    # Populate image-only continuous-input robustness metrics.
    lr = factsheet["configuration"]["learning_rate"]
    num_classes = model.get_num_classes()
    test_sample = next(iter(test_loader))

    value_clever = get_clever_score(model, test_sample, num_classes, lr)
    factsheet["performance"]["test_clever_score"] = value_clever

    value_loss_sensitivity = get_loss_sensitivity_score(model, test_sample, num_classes, lr)
    factsheet["performance"]["inverse_test_loss_sensitivity"] = inverse_score(value_loss_sensitivity)

    value_empirical_robustness = get_empirical_robustness_score(
        model,
        test_sample,
        num_classes,
        lr,
    )
    factsheet["performance"]["test_empirical_robustness_score"] = value_empirical_robustness


def remove_image_only_robustness_metrics(factsheet):
    # Drop stale values when an existing factsheet was created before tabular metrics were split.
    performance = factsheet.get("performance", {})
    for field in (
        "test_clever_score",
        "inverse_test_loss_sensitivity",
        "test_empirical_robustness_score",
    ):
        performance.pop(field, None)


PROFILE_POPULATORS = {
    (FEDERATION_CFL, DATA_TYPE_IMAGES): populate_cfl_images_metrics,
    (FEDERATION_CFL, DATA_TYPE_TABULAR): populate_cfl_tabular_metrics,
    (FEDERATION_DFL, DATA_TYPE_IMAGES): populate_dfl_images_metrics,
    (FEDERATION_DFL, DATA_TYPE_TABULAR): populate_dfl_tabular_metrics,
}

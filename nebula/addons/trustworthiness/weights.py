import json
import os


COMMON_TRUST_WEIGHT_FIELDS = {
    "robustness": "robustness_pillar",
    "resilience_to_attacks": "resilience_to_attacks",
    "algorithm_robustness": "algorithm_robustness",
    "client_reliability": "client_reliability",
    "privacy": "privacy_pillar",
    "technique": "technique",
    "uncertainty": "uncertainty",
    "indistinguishability": "indistinguishability",
    "fairness": "fairness_pillar",
    "class_distribution": "class_distribution",
    "outcome_fairness": "outcome_fairness",
    "explainability": "explainability_pillar",
    "interpretability": "interpretability",
    "post_hoc_methods": "post_hoc_methods",
    "accountability": "accountability_pillar",
    "factsheet_completeness": "factsheet_completeness",
    "monitoring": "monitoring",
    "architectural_soundness": "architectural_soundness_pillar",
    "client_management": "client_management",
    "optimization": "optimization",
    "federation_management": "federation_management",
    "sustainability": "sustainability_pillar",
    "energy_source": "energy_source",
    "federation_complexity": "federation_complexity",
}

CFL_TRUST_WEIGHT_FIELDS = {
    **COMMON_TRUST_WEIGHT_FIELDS,
    "selection_fairness": "selection_fairness",
    "performance_fairness": "performance_fairness",
    "hardware_efficiency": "hardware_efficiency",
}

DFL_TRUST_WEIGHT_FIELDS = COMMON_TRUST_WEIGHT_FIELDS

TRUST_WEIGHT_FIELDS_BY_FEDERATION = {
    "CFL": CFL_TRUST_WEIGHT_FIELDS,
    "DFL": DFL_TRUST_WEIGHT_FIELDS,
    "SDFL": DFL_TRUST_WEIGHT_FIELDS,
}


def load_trust_weights(experiment_name: str, federation: str) -> dict[str, float]:
    config_dir = os.environ.get("NEBULA_CONFIG_DIR")
    if not config_dir:
        raise RuntimeError("NEBULA_CONFIG_DIR is not configured")

    federation_key = (federation or "CFL").upper()
    weight_fields = TRUST_WEIGHT_FIELDS_BY_FEDERATION.get(federation_key)
    if weight_fields is None:
        raise ValueError(f"Unsupported trustworthiness federation: {federation}")

    scenario_path = os.path.join(config_dir, experiment_name, "scenario.json")
    with open(scenario_path, "r") as data_file:
        data = json.load(data_file)

    weights = {}
    missing_fields = []
    for weight_name, scenario_field in weight_fields.items():
        if scenario_field not in data:
            missing_fields.append(scenario_field)
            continue
        weights[weight_name] = float(data[scenario_field])

    if missing_fields:
        raise KeyError(
            f"Missing {federation_key} trustworthiness weight fields in {scenario_path}: {', '.join(sorted(missing_fields))}"
        )

    return weights

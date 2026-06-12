import json
import os
import shutil


dirname = os.path.dirname(__file__)

# Shared helpers for trustworthiness factsheet generation.
DATA_TYPE_IMAGES = "images"
DATA_TYPE_TABULAR = "tabular"
DATASET_DATA_TYPES = {
    "mnist": DATA_TYPE_IMAGES,
    "fashionmnist": DATA_TYPE_IMAGES,
    "emnist": DATA_TYPE_IMAGES,
    "cifar10": DATA_TYPE_IMAGES,
    "cifar100": DATA_TYPE_IMAGES,
    "kddcup99": DATA_TYPE_TABULAR,
    "adultcensus": DATA_TYPE_TABULAR,
    "breastcancer": DATA_TYPE_TABULAR,
    "covtype": DATA_TYPE_TABULAR,
    "sentiment140": DATA_TYPE_TABULAR,
}


def get_dataset_data_type(dataset_name):
    # Infer the data type from Nebula's built-in dataset names.
    if dataset_name is None:
        return ""

    normalized_name = str(dataset_name).strip().lower().replace("_", "").replace("-", "")
    return DATASET_DATA_TYPES.get(normalized_name, "")


def get_model_data_type(model, dataset_name=None):
    # Return the model-declared data type, falling back to the dataset name.
    if not hasattr(model, "get_data_type"):
        return get_dataset_data_type(dataset_name)

    try:
        data_type = model.get_data_type()
    except AttributeError:
        return get_dataset_data_type(dataset_name)

    if data_type is None:
        return get_dataset_data_type(dataset_name)

    data_type = str(data_type).strip()
    return data_type or get_dataset_data_type(dataset_name)


def get_normalized_model_data_type(model, dataset_name=None):
    # Normalize the model data type before matching templates or profiles.
    return get_model_data_type(model, dataset_name=dataset_name).lower()


def get_factsheet_template_name(federation, model, default_template_name, dataset_name=None):
    # Select a data-type-specific template when one exists for the federation.
    federation_prefix = "dfl" if str(federation).upper() in {"DFL", "SDFL"} else "cfl"
    data_type = get_normalized_model_data_type(model, dataset_name=dataset_name)

    if data_type not in {DATA_TYPE_IMAGES, DATA_TYPE_TABULAR}:
        return default_template_name

    template_name = f"factsheet_template_{federation_prefix}_{data_type}.json"
    template_path = get_factsheet_template_path(template_name)

    return template_name if os.path.exists(template_path) else default_template_name


def get_trustworthiness_dir(scenario_name):
    # Return the trustworthiness output directory for a scenario.
    return os.path.join(os.environ.get("NEBULA_LOGS_DIR"), scenario_name, "trustworthiness")


def get_factsheet_path(scenario_name, factsheet_name):
    # Return the path to a factsheet inside the scenario trustworthiness directory.
    return os.path.join(get_trustworthiness_dir(scenario_name), factsheet_name)


def get_factsheet_template_path(template_name):
    # Return the path to a factsheet template bundled with the addon.
    return os.path.join(dirname, "configs", template_name)


def load_or_create_factsheet(scenario_name, factsheet_name, template_name):
    # Load a factsheet, creating it from the selected template if needed.
    trustworthiness_dir = get_trustworthiness_dir(scenario_name)
    os.makedirs(trustworthiness_dir, exist_ok=True)

    factsheet_path = os.path.join(trustworthiness_dir, factsheet_name)
    template_path = get_factsheet_template_path(template_name)

    if not os.path.exists(factsheet_path):
        shutil.copyfile(template_path, factsheet_path)

    with open(factsheet_path, encoding="utf-8") as factsheet_file:
        return factsheet_path, json.load(factsheet_file)


def write_factsheet(factsheet_path, factsheet):
    # Write a factsheet using readable standard JSON formatting.
    with open(factsheet_path, "w", encoding="utf-8") as factsheet_file:
        json.dump(factsheet, factsheet_file, indent=4)


def cap_score(value, maximum=1):
    # Cap a score to the maximum value expected by the factsheet.
    return maximum if value > maximum else value


def inverse_score(value):
    # Convert an error or risk value into a bounded inverse score.
    return 1 / (1 + value)


def inverse_bounded_score(value):
    # Invert an error already bounded in [0, 1] while keeping the full score range.
    return min(max(1 - float(value), 0.0), 1.0)


def get_enabled_defences(data):
    # Return the active training-time defences declared in the scenario.
    defences = []
    if data.get("reputation", {}).get("enabled", False):
        defences.append("reputation-based defence")
    if data.get("feature_squeezing", {}).get("enabled", False):
        defences.append("feature squeezing")
    if data.get("adversarial_training", {}).get("enabled", False):
        defences.append(_format_adversarial_training_defence(data["adversarial_training"]))
    return defences


def _format_adversarial_training_defence(adversarial_training):
    attack = str(adversarial_training.get("attack", "")).upper()
    domain = str(adversarial_training.get("domain", "")).lower()
    if attack:
        return f"adversarial training with {attack}"
    if domain:
        return f"adversarial training for {domain} data"
    return "adversarial training"


def build_project_background(data):
    # Build the natural-language scenario description used in factsheets.
    federation = data["federation"]
    n_nodes = int(data["n_nodes"])
    dataset = data["dataset"]
    algorithm = data["model"]
    aggregation_algorithm = data["agg_algorithm"]
    n_rounds = int(data["rounds"])
    attack = data["attack_params"]["attacks"]
    enabled_defences = get_enabled_defences(data)

    base = (
        "For the project setup, the most important aspects are the following: "
        f"The federation architecture is {federation}, involving {n_nodes} clients, "
        f"the dataset used is {dataset}, the learning algorithm is {algorithm}, "
        f"the aggregation algorithm is {aggregation_algorithm} and the number of rounds is {n_rounds}. "
    )

    if attack != "No Attack":
        attack_text = f"In addition, the type of attack used is {attack}. "
    else:
        attack_text = "No attacks are used. "

    if enabled_defences:
        defence_list = ", ".join(enabled_defences)
        defence_text = f"The active defence mechanisms are: {defence_list}. The trustworthiness of the project is desired."
    else:
        defence_text = "No defence mechanism is used, and the trustworthiness of the project is desired."

    return base + attack_text + defence_text


def populate_common_pre_train_sections(factsheet, data, model):
    # Populate project, data, participant and training configuration fields.
    with_reputation = data["reputation"]["enabled"]

    factsheet["project"]["overview"] = data["scenario_title"]
    factsheet["project"]["purpose"] = data["scenario_description"]
    factsheet["project"]["background"] = build_project_background(data)

    factsheet["data"]["provenance"] = data["dataset"]
    factsheet["data"]["type"] = get_model_data_type(model, dataset_name=data["dataset"])
    factsheet["data"]["preprocessing"] = data["topology"]

    factsheet["participants"]["client_num"] = data["n_nodes"] or ""
    factsheet["participants"]["sample_client_rate"] = 1
    factsheet["participants"]["client_selector"] = (
        "Reputation Based" if with_reputation else "Full Participation"
    )

    factsheet["configuration"]["aggregation_algorithm"] = data["agg_algorithm"] or ""
    factsheet["configuration"]["training_model"] = data["model"] or ""
    factsheet["configuration"]["personalization"] = False
    factsheet["configuration"]["reputation_enabled"] = bool(
        data.get("reputation", {}).get("enabled", False)
    )
    adversarial_training = data.get("adversarial_training", {}) or {}
    factsheet["configuration"]["adversarial_training"] = bool(
        adversarial_training.get("enabled", False)
    )
    factsheet["configuration"]["adversarial_training_domain"] = (
        adversarial_training.get("domain", "") if adversarial_training.get("enabled", False) else ""
    )
    factsheet["configuration"]["adversarial_training_attack"] = (
        adversarial_training.get("attack", "") if adversarial_training.get("enabled", False) else ""
    )
    factsheet["configuration"]["adversarial_training_mode"] = (
        adversarial_training.get("mode", "") if adversarial_training.get("enabled", False) else ""
    )
    factsheet["configuration"]["visualization"] = True
    factsheet["configuration"]["monitoring"] = True
    factsheet["configuration"]["total_round_num"] = int(data["rounds"])
    factsheet["configuration"]["learning_rate"] = model.get_learning_rate()
    factsheet["configuration"]["trainable_param_num"] = model.count_parameters()
    factsheet["configuration"]["local_update_steps"] = data["epochs"]


def set_dp_configuration(factsheet, dp_enabled, dp_epsilon):
    # Write differential privacy configuration using the factsheet schema.
    factsheet["configuration"]["differential_privacy"] = bool(dp_enabled)
    factsheet["configuration"]["dp_epsilon"] = dp_epsilon if dp_enabled else ""


def populate_reliability(factsheet, reliability_summary):
    # Write dropout and timeout rates, defaulting to a fully reliable run.
    factsheet["system"]["dropout_rate"] = (
        reliability_summary.get("dropout_rate", 0.0)
        if reliability_summary is not None
        else 0.0
    )
    factsheet["system"]["timeout_rate"] = (
        reliability_summary.get("timeout_rate", 0.0)
        if reliability_summary is not None
        else 0.0
    )


def populate_participation(factsheet, participation_summary):
    # Write participant selection dispersion, defaulting to full participation.
    factsheet["fairness"]["selection_cv"] = (
        participation_summary.get("selection_cv", 1)
        if participation_summary is not None
        else 1
    )


def populate_reputation(factsheet, reputation_summary, include_neighbor_num=False):
    # Write reputation information for centralized or decentralized factsheets.
    if reputation_summary is not None:
        factsheet["participants"]["avg_neighbor_reputation"] = reputation_summary.get(
            "avg_neighbor_reputation",
            "",
        )
        if include_neighbor_num:
            factsheet["participants"]["neighbor_num"] = reputation_summary.get(
                "neighbor_num",
                0,
            )
        return

    factsheet["participants"]["avg_neighbor_reputation"] = 0
    if include_neighbor_num:
        factsheet["participants"]["neighbor_num"] = 0

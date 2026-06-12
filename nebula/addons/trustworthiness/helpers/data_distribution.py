import json
import os
from collections import Counter

import numpy as np
from hashids import Hashids
from scipy.stats import entropy

hashids = Hashids()


def _logs_dir():
    # Return the base logs directory used to read and write trust artifacts.
    return os.environ.get("NEBULA_LOGS_DIR") or os.path.join("nebula", "app", "logs")


def _trustworthiness_dir(scenario_name: str) -> str:
    # Return the trustworthiness directory for a scenario.
    return os.path.join(_logs_dir(), scenario_name, "trustworthiness")


def _trustworthiness_path(scenario_name: str, filename: str) -> str:
    # Return the path of a trustworthiness artifact for a scenario.
    return os.path.join(_trustworthiness_dir(scenario_name), filename)


def _ensure_trustworthiness_dir(scenario_name: str) -> None:
    # Create the scenario trustworthiness directory if it does not exist.
    os.makedirs(_trustworthiness_dir(scenario_name), exist_ok=True)


def _encode_class_id(class_id) -> str:
    # Convert a numeric class ID into the hash used in persisted JSON files.
    return hashids.encode(int(class_id))


def _class_counts_from_counter(class_counter: Counter) -> dict:
    # Return hashed class counts from an in-memory Counter.
    return {
        _encode_class_id(class_id): int(count)
        for class_id, count in class_counter.items()
    }


def _write_json(scenario_name: str, filename: str, data: dict, indent=None) -> None:
    # Write a JSON trust artifact inside the scenario trustworthiness directory.
    _ensure_trustworthiness_dir(scenario_name)
    with open(_trustworthiness_path(scenario_name, filename), "w") as file:
        json.dump(data, file, indent=indent)


def _iter_participant_class_counts(experiment_name: str):
    # Yield each consecutive participant ID and its saved class-count dictionary.
    participant_id = 0
    while True:
        file_path = get_class_count_file(experiment_name, participant_id)
        if not os.path.exists(file_path):
            break

        yield participant_id, load_class_counts(experiment_name, participant_id)
        participant_id += 1


def get_class_count_file(scenario_name, participant_id):
    # Return the class-count JSON path for one participant.
    return _trustworthiness_path(scenario_name, f"{str(participant_id)}_class_count.json")


def load_class_counts(scenario_name, participant_id):
    # Load one participant's saved class-count dictionary.
    with open(get_class_count_file(scenario_name, participant_id), "r") as file:
        return json.load(file)


def get_class_imbalance_from_counts(class_counts):
    # Calculate class imbalance as the coefficient of variation of class counts.
    return get_cv(list=list(class_counts.values()))


def get_class_imbalance_score(class_imbalance):
    # Convert class imbalance into a score where 1 means balanced classes.
    return 1 / (1 + class_imbalance)


def get_class_imbalance_local(participant_id, experiment_name):
    # Return the raw class-imbalance value for one participant.
    return get_class_imbalance_from_counts(load_class_counts(experiment_name, participant_id))


def get_local_class_imbalance_score(scenario_name, participant_id):
    # Return the trust-oriented class-imbalance score for one participant.
    return get_class_imbalance_score(get_class_imbalance_local(participant_id, scenario_name))


def get_entropy_from_class_counts(class_counts, normalize=False):
    # Calculate entropy from a class-count dictionary, optionally normalized to [0, 1].
    counts = np.array(list(class_counts.values()), dtype=float)
    total = counts.sum()
    if total <= 0:
        return 0.0

    probabilities = counts / total
    entropy_value = entropy(probabilities, base=2)

    if not normalize:
        return round(float(entropy_value), 6)

    class_count = len(probabilities)
    if class_count <= 1:
        return 0.0

    normalized_entropy = float(entropy_value / np.log2(class_count))
    return float(np.clip(normalized_entropy, 0.0, 1.0))


def get_local_normalized_entropy(scenario_name, participant_id):
    # Return normalized entropy for one participant's saved class counts.
    return get_entropy_from_class_counts(
        load_class_counts(scenario_name, participant_id),
        normalize=True,
    )


def get_cv(list=None, std=None, mean=None):
    # Return the coefficient of variation from either values or precomputed std/mean.
    if std is not None and mean is not None:
        return 0 if mean == 0 else std / mean

    if list is None:
        return 0

    values = np.asarray(list, dtype=float)
    mean_value = float(np.mean(values)) if values.size else 0.0
    if mean_value == 0:
        return 0

    return float(np.std(values) / mean_value)


def get_participation_variation_score(participation_counts):
    # Convert participation-count dispersion into a score where 1 means equal participation.
    if not participation_counts:
        return 1.0

    counts = np.asarray(participation_counts, dtype=float)
    mean_count = float(np.mean(counts))
    if mean_count <= 0:
        return 0.0

    cv = get_cv(list=counts)
    if not np.isfinite(cv):
        return 0.0

    return float(1 / (1 + cv))


def save_class_count_per_participant(experiment_name, class_counter: Counter, idx):
    # Save one participant's class-count dictionary as <participant>_class_count.json.
    _write_json(
        experiment_name,
        f"{str(idx)}_class_count.json",
        _class_counts_from_counter(class_counter),
    )


def get_all_data_entropy(experiment_name):
    # Compute entropy for every participant class-count file and write entropy.json.
    entropy_per_participant = {
        str(participant_id): round(get_entropy_from_class_counts(class_count), 6)
        for participant_id, class_count in _iter_participant_class_counts(experiment_name)
    }

    _write_json(experiment_name, "entropy.json", entropy_per_participant, indent=2)


def get_local_entropy(id, experiment_name):
    # Return non-normalized entropy for one participant's saved class counts.
    return get_entropy_from_class_counts(load_class_counts(experiment_name, id))

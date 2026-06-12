import copy
import json
import os

SCORE_KEYS = {"trust_score", "score"}
NAMED_ENTRY_KEYS = {"score", "metrics", "notions", "pillars"}
NAMED_ENTRY_PATH_KEY = "__named_entry__"


def _logs_dir() -> str:
    # Return the configured logs directory required by trust report exchange.
    logs_dir = os.environ.get("NEBULA_LOGS_DIR")
    if not logs_dir:
        raise ValueError("The NEBULA_LOGS_DIR environment variable is not defined.")
    return logs_dir


def _trustworthiness_dir(scenario_name: str) -> str:
    # Return the scenario trustworthiness directory used by report JSON files.
    return os.path.join(_logs_dir(), scenario_name, "trustworthiness")


def _trust_report_path(scenario_name: str, participant_id: int | str) -> str:
    # Return the local trust report path for one participant.
    return os.path.join(_trustworthiness_dir(scenario_name), f"nebula_trust_results_{participant_id}.json")


def _read_json_file(file_path: str) -> dict:
    # Load a JSON object and raise clear errors for missing or invalid files.
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"The file does not exist: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(f"The file does not contain valid JSON: {file_path}") from error


def _write_json_file(file_path: str, data: dict) -> str:
    # Write a formatted JSON object, creating the parent directory if needed.
    directory = os.path.dirname(file_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

    return file_path


def _is_score_entry(key, value) -> bool:
    # Trust report scores are numeric values stored under score-like keys.
    return key in SCORE_KEYS and _is_numeric_score(value)


def load_trust_report_json_dumped(scenario_name: str, participant_id: int) -> str:
    # Load one participant report and return it serialized for network messages.
    return json.dumps(load_trust_report_json(scenario_name, participant_id))


def load_trust_report_json(scenario_name: str, participant_id: int | str) -> dict:
    # Load one participant trustworthiness report as a dictionary.
    return _read_json_file(_trust_report_path(scenario_name, participant_id))


def create_local_trust_report_copy(scenario_name: str, participant_id: int | str, suffix: str = "global") -> tuple[dict, str]:
    # Copy a participant report to a local aggregation output file.
    trust_report = load_trust_report_json(scenario_name, participant_id)
    file_path = os.path.join(
        _trustworthiness_dir(scenario_name),
        f"nebula_trust_results_{participant_id}_{suffix}.json",
    )

    return trust_report, _write_json_file(file_path, trust_report)


def save_trust_report_json(file_path: str, trust_report: dict) -> str:
    # Save a trust report and return the written file path.
    return _write_json_file(file_path, trust_report)


def accumulate_weighted_trustscores(report: dict, weight: float, score_accumulator: dict, weight_accumulator: dict):
    # Add all score values from a report into weighted accumulators.
    if weight <= 0:
        raise ValueError("The aggregation weight must be greater than 0.")

    _accumulate_weighted_trustscores_recursive(
        obj=report,
        weight=float(weight),
        path=(),
        score_accumulator=score_accumulator,
        weight_accumulator=weight_accumulator,
    )


def build_weighted_trustscores_report(template_report: dict, score_accumulator: dict, weight_accumulator: dict) -> dict:
    # Return a deep-copied report with every score replaced by its weighted mean.
    aggregated_report = copy.deepcopy(template_report)
    _apply_weighted_trustscores_recursive(
        obj=aggregated_report,
        path=(),
        score_accumulator=score_accumulator,
        weight_accumulator=weight_accumulator,
    )
    return aggregated_report


def _accumulate_weighted_trustscores_recursive(obj, weight: float, path: tuple, score_accumulator: dict, weight_accumulator: dict):
    # Walk a trust report and accumulate weighted sums for every score path.
    if isinstance(obj, dict):
        named_entry = _get_structural_named_entry(obj)
        if named_entry is not None:
            _, nested_value = named_entry
            _accumulate_weighted_trustscores_recursive(
                obj=nested_value,
                weight=weight,
                path=path + (NAMED_ENTRY_PATH_KEY,),
                score_accumulator=score_accumulator,
                weight_accumulator=weight_accumulator,
            )
            return

        for key, value in obj.items():
            score_path = path + (key,)
            if _is_score_entry(key, value):
                score_accumulator[score_path] = score_accumulator.get(score_path, 0.0) + (float(value) * weight)
                weight_accumulator[score_path] = weight_accumulator.get(score_path, 0.0) + weight
                continue

            _accumulate_weighted_trustscores_recursive(
                obj=value,
                weight=weight,
                path=score_path,
                score_accumulator=score_accumulator,
                weight_accumulator=weight_accumulator,
            )
        return

    if isinstance(obj, list):
        for index, item in enumerate(obj):
            _accumulate_weighted_trustscores_recursive(
                obj=item,
                weight=weight,
                path=path + (index,),
                score_accumulator=score_accumulator,
                weight_accumulator=weight_accumulator,
            )


def _apply_weighted_trustscores_recursive(obj, path: tuple, score_accumulator: dict, weight_accumulator: dict):
    # Walk a report copy and replace score values with weighted averages.
    if isinstance(obj, dict):
        named_entry = _get_structural_named_entry(obj)
        if named_entry is not None:
            entry_key, nested_value = named_entry
            obj[entry_key] = _apply_weighted_trustscores_recursive(
                obj=nested_value,
                path=path + (NAMED_ENTRY_PATH_KEY,),
                score_accumulator=score_accumulator,
                weight_accumulator=weight_accumulator,
            )
            return obj

        for key, value in obj.items():
            score_path = path + (key,)
            if _is_score_entry(key, value):
                total_weight = weight_accumulator.get(score_path)
                if total_weight:
                    obj[key] = round(score_accumulator[score_path] / total_weight, 6)
                continue

            obj[key] = _apply_weighted_trustscores_recursive(
                obj=value,
                path=score_path,
                score_accumulator=score_accumulator,
                weight_accumulator=weight_accumulator,
            )
        return obj

    if isinstance(obj, list):
        for index, item in enumerate(obj):
            obj[index] = _apply_weighted_trustscores_recursive(
                obj=item,
                path=path + (index,),
                score_accumulator=score_accumulator,
                weight_accumulator=weight_accumulator,
            )

    return obj


def _get_structural_named_entry(obj: dict):
    # Detect wrappers like {"Privacy": {"score": ..., "metrics": ...}}.
    if len(obj) != 1:
        return None

    entry_key, nested_value = next(iter(obj.items()))
    if not isinstance(nested_value, dict):
        return None

    if any(key in nested_value for key in NAMED_ENTRY_KEYS):
        return entry_key, nested_value

    return None


def _is_numeric_score(value):
    # Booleans are ints in Python, but they are not trust score values here.
    return isinstance(value, (int, float)) and not isinstance(value, bool)

import logging
import math

from nebula.addons.trustworthiness.helpers.privacy import (
    get_global_privacy_risk,
    get_global_privacy_risk_dfl,
)
from nebula.addons.trustworthiness.helpers.scenario_metrics import comm_efficiency
from nebula.addons.trustworthiness.helpers.scoring import (
    check_properties,
    get_value,
)

logger = logging.getLogger(__name__)

# Operations available from the eval_metrics JSON files.
OPERATIONS = {
    "check_properties": check_properties,
    "comm_efficiency": comm_efficiency,
    "get_global_privacy_risk": get_global_privacy_risk,
    "get_global_privacy_risk_dfl": get_global_privacy_risk_dfl,
    "get_value": get_value,
}


def check_field_filled(factsheet_dict, factsheet_path, value, empty=""):
    # Keep an existing factsheet value; otherwise return a clean fallback for empty or NaN values.
    current_value = factsheet_dict[factsheet_path[0]][factsheet_path[1]]
    if current_value:
        return current_value

    if _is_empty_value(value):
        return empty

    if _is_nan_number(value):
        return 0

    return value


def _is_empty_value(value):
    # Empty strings and the literal "nan" should not overwrite missing factsheet fields.
    return value == "" or value == "nan"


def _is_nan_number(value):
    # Only numeric values can be checked with math.isnan safely.
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isnan(value)


def get_input_value(input_docs, inputs, operation):
    # Collect metric inputs from their configured paths and apply the configured operation.
    args = []
    for input_config in inputs:
        source = input_config.get("source", "")
        field = input_config.get("field_path", "")
        input_doc = input_docs.get(source)
        if input_doc is None:
            logger.warning(f"{source} is null")
            continue

        args.append(get_value_from_path(input_doc, field))

    try:
        operation_fn = OPERATIONS[operation]
        return operation_fn(*args)
    except (KeyError, TypeError):
        logger.warning(f"{operation} is not valid")
        return None


def get_value_from_path(input_doc, path):
    # Walk a slash-separated path through a nested dict and return the leaf value.
    current_value = input_doc
    for nested_key in path.split("/"):
        if not isinstance(current_value, dict):
            return None

        current_value = current_value.get(nested_key)
        if current_value is None:
            return None

    return current_value

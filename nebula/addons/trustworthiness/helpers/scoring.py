import logging

import numpy as np

logger = logging.getLogger(__name__)


def _is_number(value):
    # Score calculations expect real numeric values; booleans are handled explicitly.
    return isinstance(value, (int, float, np.number)) and not isinstance(value, bool)


def _warn_not_number(value):
    # Keep the warning format consistent across all numeric scoring functions.
    logger.warning("Input value is not a number")
    logger.warning(f"{value}")


def get_mapped_score(score_key, score_map):
    # Normalize the configured score map and return the normalized value for the input key.
    if score_map is None:
        logger.warning("Score map is missing")
        return 0

    normalized_scores = get_normalized_scores(list(score_map.values()))
    normalized_score_map = dict(zip(score_map.keys(), normalized_scores, strict=False))
    return normalized_score_map.get(score_key, np.nan)


def get_normalized_scores(scores):
    # Convert a list of raw configured scores to the [0, 1] range.
    if scores is None or len(scores) == 0:
        return []

    min_score = np.min(scores)
    max_score = np.max(scores)
    if max_score == min_score:
        return [1.0 for _ in scores]

    return [(score - min_score) / (max_score - min_score) for score in scores]


def get_range_score(value, ranges, direction="asc"):
    # Place the value in one of the configured bins and normalize that bin index.
    if not _is_number(value):
        _warn_not_number(value)
        return 0

    if ranges is None:
        logger.warning("Score ranges are missing")
        return 0

    total_bins = len(ranges) + 1
    bin_index = np.digitize(value, ranges, right=True)
    score = bin_index / total_bins
    return 1 - score if direction == "desc" else score


def get_map_value_score(score_key, score_map):
    # Return the exact configured score for maps that already store normalized values.
    if score_map is None:
        logger.warning("Score map is missing")
        return 0

    return score_map[score_key]


def get_true_score(value, direction):
    # Booleans are direct scores; numeric values can be inverted for descending metrics.
    if value is True:
        return 1
    if value is False:
        return 0

    if not _is_number(value):
        _warn_not_number(value)
        return 0

    return 1 - value if direction == "desc" else value


def get_scaled_score(value, scale: list, direction: str):
    # Clamp a metric from its configured scale into the [0, 1] score range.
    if value is None or value == "":
        logger.warning("Score value is missing. Set value to zero")
        return 0

    if not _is_number(value):
        _warn_not_number(value)
        return 0

    value_min, value_max = _get_scale_bounds(scale)
    if value_max == value_min:
        score = 1
    elif value >= value_max:
        score = 1
    elif value <= value_min:
        score = 0
    else:
        score = (float(value) - value_min) / (value_max - value_min)

    return 1 - score if direction == "desc" else score


def _get_scale_bounds(scale):
    # Fall back to the default [0, 1] scale when the config is incomplete.
    try:
        return scale[0], scale[1]
    except (TypeError, IndexError):
        logger.warning("Score minimum or score maximum is missing. The minimum has been set to 0 and the maximum to 1")
        return 0, 1


def get_value(value):
    # Factsheet operations use this when a metric only needs the raw input value.
    return value


def check_properties(*args):
    # Return the fraction of required properties that are filled.
    if not args:
        return 0

    filled = [value is not None and value != "" for value in args]
    return np.mean(filled)

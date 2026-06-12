from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

CONTINUOUS = "continuous"
INTEGER = "integer"
CATEGORICAL = "categorical"
NON_PERTURBABLE = "non_perturbable"

ERR_FEATURE_TYPES_LENGTH = "feature_types length must match feature_names length"
ERR_FEATURE_MIN_LENGTH = "feature_min_norm length must match feature_names length"
ERR_FEATURE_MAX_LENGTH = "feature_max_norm length must match feature_names length"
ERR_UNSUPPORTED_FEATURE_TYPES = "Unsupported tabular feature types: {feature_types}"
ERR_FEATURE_BOUNDS = "feature_min_norm must be <= feature_max_norm for every feature"
ERR_INTEGER_STEP_INDEX = "integer_step_norm contains invalid feature indices: {indices}"
ERR_INTEGER_STEP_VALUE = "integer_step_norm values must be > 0"
ERR_INTEGER_STEP_TYPE = "integer_step_norm contains non-integer feature indices: {indices}"
ERR_CATEGORICAL_GROUP_SIZE = "categorical_groups entries must contain at least two feature indices"
ERR_CATEGORICAL_GROUP_INDEX = "categorical_groups contains invalid feature indices: {indices}"
ERR_CATEGORICAL_GROUP_TYPE = "categorical_groups contains non-categorical feature indices: {indices}"
ERR_CATEGORICAL_GROUP_OVERLAP = "categorical_groups contains duplicated feature indices: {indices}"
ERR_CATEGORICAL_GROUP_COVERAGE = "categorical feature indices missing from categorical_groups: {indices}"


@dataclass(frozen=True)
class TabularAdversarialMetadata:
    """Minimal metadata for tabular adversarial training."""

    # These fields describe the exact vector received by the model after preprocessing.
    # Bounds and steps must use the same normalized space as the training tensors.
    feature_names: list[str]
    feature_types: list[str]
    feature_min_norm: list[float]
    feature_max_norm: list[float]
    integer_step_norm: dict[int, float] | None = None
    categorical_groups: list[list[int]] | None = None

    def __post_init__(self):
        # Fail early if a dataset exposes incomplete metadata. The attack relies on
        # these arrays lining up feature-by-feature.
        n_features = len(self.feature_names)
        if len(self.feature_types) != n_features:
            raise ValueError(ERR_FEATURE_TYPES_LENGTH)
        if len(self.feature_min_norm) != n_features:
            raise ValueError(ERR_FEATURE_MIN_LENGTH)
        if len(self.feature_max_norm) != n_features:
            raise ValueError(ERR_FEATURE_MAX_LENGTH)

        # Every feature needs a valid normalized interval so projection can clamp safely.
        invalid_bounds = [
            idx
            for idx, (min_value, max_value) in enumerate(
                zip(self.feature_min_norm, self.feature_max_norm, strict=True)
            )
            if min_value > max_value
        ]
        if invalid_bounds:
            raise ValueError(ERR_FEATURE_BOUNDS)
        invalid_types = set(self.feature_types) - {CONTINUOUS, INTEGER, CATEGORICAL, NON_PERTURBABLE}
        if invalid_types:
            raise ValueError(ERR_UNSUPPORTED_FEATURE_TYPES.format(feature_types=sorted(invalid_types)))

        # Integer steps represent the normalized distance between consecutive integer values.
        # They only make sense for features marked as INTEGER.
        invalid_step_indices = [
            idx
            for idx in (self.integer_step_norm or {})
            if int(idx) < 0 or int(idx) >= n_features
        ]
        if invalid_step_indices:
            raise ValueError(ERR_INTEGER_STEP_INDEX.format(indices=invalid_step_indices))
        non_integer_step_indices = [
            idx
            for idx in (self.integer_step_norm or {})
            if self.feature_types[int(idx)] != INTEGER
        ]
        if non_integer_step_indices:
            raise ValueError(ERR_INTEGER_STEP_TYPE.format(indices=non_integer_step_indices))
        if any(step <= 0 for step in (self.integer_step_norm or {}).values()):
            raise ValueError(ERR_INTEGER_STEP_VALUE)

        # Categorical groups represent one original categorical column after one-hot encoding.
        # Each group must be disjoint so projection can activate exactly one value per group.
        grouped_counts: dict[int, int] = {}
        for group in self.categorical_groups or []:
            if len(group) < 2:
                raise ValueError(ERR_CATEGORICAL_GROUP_SIZE)
            invalid_indices = [idx for idx in group if idx < 0 or idx >= n_features]
            if invalid_indices:
                raise ValueError(ERR_CATEGORICAL_GROUP_INDEX.format(indices=invalid_indices))
            non_categorical_indices = [idx for idx in group if self.feature_types[idx] != CATEGORICAL]
            if non_categorical_indices:
                raise ValueError(ERR_CATEGORICAL_GROUP_TYPE.format(indices=non_categorical_indices))
            for idx in group:
                grouped_counts[idx] = grouped_counts.get(idx, 0) + 1

        duplicated_group_indices = sorted(idx for idx, count in grouped_counts.items() if count > 1)
        if duplicated_group_indices:
            raise ValueError(ERR_CATEGORICAL_GROUP_OVERLAP.format(indices=duplicated_group_indices))

        # A categorical feature without a group cannot be projected back to a valid one-hot state.
        grouped_categorical_indices = {
            idx
            for group in self.categorical_groups or []
            for idx in group
        }
        categorical_indices = {
            idx
            for idx, feature_type in enumerate(self.feature_types)
            if feature_type == CATEGORICAL
        }
        missing_categorical_indices = sorted(categorical_indices - grouped_categorical_indices)
        if missing_categorical_indices:
            raise ValueError(ERR_CATEGORICAL_GROUP_COVERAGE.format(indices=missing_categorical_indices))

    def to_dict(self) -> dict[str, Any]:
        # Partitions persist metadata as JSON-like dictionaries in HDF5 attributes.
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TabularAdversarialMetadata:
        # HDF5/JSON round-trips can turn integer keys into strings; normalize them here.
        return cls(
            feature_names=[str(value) for value in data["feature_names"]],
            feature_types=[str(value) for value in data["feature_types"]],
            feature_min_norm=[float(value) for value in data["feature_min_norm"]],
            feature_max_norm=[float(value) for value in data["feature_max_norm"]],
            integer_step_norm={int(k): float(v) for k, v in (data.get("integer_step_norm") or {}).items()},
            categorical_groups=[
                [int(idx) for idx in group]
                for group in data.get("categorical_groups") or []
            ],
        )


def build_tabular_adversarial_metadata(
    *,
    feature_names: list[str],
    x_train,
    continuous_columns: list[str] | tuple[str, ...] = (),
    integer_columns: list[str] | tuple[str, ...] = (),
    categorical_columns: list[str] | tuple[str, ...] = (),
    perturbable_continuous_columns: list[str] | tuple[str, ...] = (),
    perturbable_integer_columns: list[str] | tuple[str, ...] = (),
    perturbable_categorical_columns: list[str] | tuple[str, ...] = (),
    integer_step_by_column: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build tabular adversarial metadata from dataset-level perturbability lists."""
    # Datasets should only decide which raw columns are perturbable. This helper
    # maps that decision to the transformed feature vector consumed by the model.
    _validate_perturbable_columns(
        continuous_columns=continuous_columns,
        integer_columns=integer_columns,
        categorical_columns=categorical_columns,
        perturbable_continuous_columns=perturbable_continuous_columns,
        perturbable_integer_columns=perturbable_integer_columns,
        perturbable_categorical_columns=perturbable_categorical_columns,
    )

    perturbable_continuous = set(perturbable_continuous_columns)
    perturbable_integer = set(perturbable_integer_columns)
    perturbable_categorical = set(perturbable_categorical_columns)

    # Continuous/integer transformed features usually keep their raw column name
    # after an optional transformer prefix, for example "integer__age".
    continuous_features = [
        idx
        for idx, name in enumerate(feature_names)
        if _raw_feature_name(name) in perturbable_continuous
    ]
    integer_features = [
        idx
        for idx, name in enumerate(feature_names)
        if _raw_feature_name(name) in perturbable_integer
    ]
    # One raw categorical column becomes several one-hot features, for example
    # "categorical__sex_Female" and "categorical__sex_Male".
    categorical_features = [
        idx
        for idx, name in enumerate(feature_names)
        if _categorical_column_name(name, categorical_columns) in perturbable_categorical
    ]

    continuous_feature_set = set(continuous_features)
    integer_feature_set = set(integer_features)
    categorical_feature_set = set(categorical_features)
    perturbable_feature_set = continuous_feature_set | integer_feature_set | categorical_feature_set
    non_perturbable_features = [
        idx
        for idx in range(len(feature_names))
        if idx not in perturbable_feature_set
    ]

    categorical_groups = _categorical_groups(feature_names, perturbable_categorical)
    integer_step_norm = _integer_step_norm(feature_names, integer_features, integer_step_by_column or {})
    # The attack consumes only TabularAdversarialMetadata. The extra lists are
    # returned so dataset wrappers and logs can expose the same mask clearly.
    tabular_metadata = TabularAdversarialMetadata(
        feature_names=feature_names,
        feature_types=[
            CONTINUOUS if idx in continuous_feature_set
            else INTEGER if idx in integer_feature_set
            else CATEGORICAL if idx in categorical_feature_set
            else NON_PERTURBABLE
            for idx in range(len(feature_names))
        ],
        feature_min_norm=[float(value) for value in x_train.min(axis=0)],
        feature_max_norm=[float(value) for value in x_train.max(axis=0)],
        integer_step_norm=integer_step_norm,
        categorical_groups=categorical_groups,
    ).to_dict()

    return {
        "continuous_features": continuous_features,
        "integer_features": integer_features,
        "categorical_features": categorical_features,
        "non_perturbable_features": non_perturbable_features,
        "categorical_groups": categorical_groups,
        "integer_step_norm": integer_step_norm,
        "tabular_metadata": tabular_metadata,
    }


def _validate_perturbable_columns(
    *,
    continuous_columns,
    integer_columns,
    categorical_columns,
    perturbable_continuous_columns,
    perturbable_integer_columns,
    perturbable_categorical_columns,
) -> None:
    invalid_continuous = sorted(set(perturbable_continuous_columns) - set(continuous_columns))
    invalid_integer = sorted(set(perturbable_integer_columns) - set(integer_columns))
    invalid_categorical = sorted(set(perturbable_categorical_columns) - set(categorical_columns))
    if invalid_continuous or invalid_integer or invalid_categorical:
        raise ValueError(
            "Perturbable columns must exist in the dataset schema: "
            f"continuous={invalid_continuous}, integer={invalid_integer}, categorical={invalid_categorical}"
        )


def _raw_feature_name(feature_name: str) -> str:
    # Strip sklearn ColumnTransformer prefixes such as "integer__" or
    # "categorical__" while leaving plain feature names untouched.
    return feature_name.split("__", maxsplit=1)[1] if "__" in feature_name else feature_name


def _categorical_column_name(feature_name: str, categorical_columns) -> str | None:
    # Recover the raw categorical column name from a one-hot feature name.
    raw_name = _raw_feature_name(feature_name)
    for column in categorical_columns:
        if raw_name.startswith(f"{column}_"):
            return column
    return None


def _categorical_groups(feature_names: list[str], perturbable_categorical_columns: set[str]) -> list[list[int]]:
    # Constrained PGD projects each group back to exactly one active one-hot value.
    groups = []
    for column in perturbable_categorical_columns:
        prefix = f"categorical__{column}_"
        group = [idx for idx, name in enumerate(feature_names) if name.startswith(prefix)]
        if group:
            groups.append(group)
    return groups


def _integer_step_norm(
    feature_names: list[str],
    integer_features: list[int],
    integer_step_by_column: dict[str, float],
) -> dict[int, float]:
    # Integer columns may be scaled. The step tells constrained PGD what "+1 raw unit"
    # means in the normalized model-input space.
    return {
        idx: float(integer_step_by_column[_raw_feature_name(feature_names[idx])])
        for idx in integer_features
        if _raw_feature_name(feature_names[idx]) in integer_step_by_column
    }

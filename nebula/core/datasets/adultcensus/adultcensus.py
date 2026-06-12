# nebula/core/datasets/adultcensus/adultcensus.py
# Becker, B. & Kohavi, R. (1996). Adult [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5XW20.
# Licensed under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/

import logging
import os
from typing import Any, ClassVar

import numpy as np
import torch
from torch.utils.data import Dataset

from nebula.core.datasets.nebuladataset import NebulaDataset, NebulaPartitionHandler
from nebula.core.datasets.tabular_metadata import (
    build_tabular_adversarial_metadata,
)

logger = logging.getLogger(__name__)


class AdultCensusTorchDataset(Dataset):
    """
    Torch Dataset wrapper for Adult Census Income dataset (tabular, already numeric).
    x: float32 tensor (n_features,)
    y: long scalar {0,1} where 1 means >50K
    """
    def __init__(
        self,
        x: np.ndarray,
        y: np.ndarray,
        feature_names: list[str] | None = None,
        continuous_features: list[int] | None = None,
        integer_features: list[int] | None = None,
        categorical_features: list[int] | None = None,
        non_perturbable_features: list[int] | None = None,
        categorical_groups: list[list[int]] | None = None,
        tabular_metadata: dict | None = None,
    ):
        if not isinstance(x, np.ndarray) or not isinstance(y, np.ndarray):
            raise ValueError("x and y must be numpy arrays")

        if x.ndim != 2:
            raise ValueError(f"x must be 2D (n_samples, n_features). Got shape={x.shape}")

        y_arr: np.ndarray = np.asarray(y).reshape(-1)
        if x.shape[0] != y_arr.shape[0]:
            raise ValueError(f"x and y must have same number of samples. Got {x.shape[0]} != {y_arr.shape[0]}")

        self.x: np.ndarray = x.astype(np.float32, copy=False)
        self.y: np.ndarray = y_arr.astype(np.int64, copy=False)

        # Nebula dataset conventions used by partitioning, logging and model setup.
        self.data: np.ndarray = self.x
        self.targets: np.ndarray = self.y
        self.classes: list[str] = ["<=50K", ">50K"]
        self.feature_names = feature_names or [f"feature_{i}" for i in range(self.x.shape[1])]
        self.continuous_features = continuous_features or []
        self.integer_features = integer_features or []
        self.categorical_features = categorical_features or []
        self.non_perturbable_features = non_perturbable_features or []
        self.categorical_groups = categorical_groups or []
        self.tabular_metadata = tabular_metadata
        self.input_dim = int(self.x.shape[1])

    def __len__(self) -> int:
        return int(self.y.shape[0])

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        x_i: torch.Tensor = torch.from_numpy(self.x[idx])
        y_i: torch.Tensor = torch.tensor(int(self.y[idx]), dtype=torch.long)
        return x_i, y_i


class AdultCensusPartitionHandler(NebulaPartitionHandler):
    """
    Partition handler for tabular data.
    """
    def __init__(self, file_path: str, prefix: str, config: Any, empty: bool = False):
        super().__init__(file_path, prefix, config, empty)
        self.transform = None  # no torchvision transforms for tabular

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        data, target = super().__getitem__(idx)

        # Some Nebula handlers may wrap data in tuples
        if isinstance(data, tuple):
            data = data[0]

        if isinstance(data, torch.Tensor):
            x: torch.Tensor = data.to(dtype=torch.float32)
        else:
            x = torch.tensor(np.asarray(data), dtype=torch.float32)

        if isinstance(target, torch.Tensor):
            y: torch.Tensor = target.to(dtype=torch.long)
        else:
            y = torch.tensor(int(target), dtype=torch.long)

        if self.target_transform is not None:
            y = self.target_transform(y)

        return x, y


class AdultCensusDataset(NebulaDataset):
    """
    Adult Census Income dataset integration for Nebula.

    - 2 classes: <=50K vs >50K
    - mixed tabular data -> numeric model input via preprocessing
    - deterministic stratified train/test split
    """
    CONTINUOUS_COLUMNS: ClassVar[list[str]] = []
    INTEGER_COLUMNS: ClassVar[list[str]] = [
        "age",
        "fnlwgt",
        "education-num",
        "capital-gain",
        "capital-loss",
        "hours-per-week",
    ]
    CATEGORICAL_COLUMNS: ClassVar[list[str]] = [
        "workclass",
        "education",
        "marital-status",
        "occupation",
        "relationship",
        "race",
        "sex",
        "native-country",
    ]
    # Experimental wide attack surface for testing constrained PGD thoroughly.
    # This intentionally allows broad changes, including categorical flips.
    PERTURBABLE_INTEGER_COLUMNS: ClassVar[list[str]] = list(INTEGER_COLUMNS)
    PERTURBABLE_CATEGORICAL_COLUMNS: ClassVar[list[str]] = list(CATEGORICAL_COLUMNS)

    def __init__(
        self,
        num_classes: int = 2,
        partitions_number: int = 1,
        batch_size: int = 32,
        num_workers: int = 4,
        iid: bool = True,
        partition: str = "dirichlet",
        partition_parameter: float = 0.5,
        seed: int = 42,
        config_dir: str | None = None,
        test_size: float = 0.2,
    ):
        super().__init__(
            num_classes=num_classes,
            partitions_number=partitions_number,
            batch_size=batch_size,
            num_workers=num_workers,
            iid=iid,
            partition=partition,
            partition_parameter=partition_parameter,
            seed=seed,
            config_dir=config_dir,
        )
        self.test_size: float = float(test_size)

    def initialize_dataset(self) -> None:
        if self.train_set is None or self.test_set is None:
            self.train_set, self.test_set = self.load_adult_census_dataset()

        self.data_partitioning(plot=True)

    @staticmethod
    def _make_ohe_dense():
        """
        scikit-learn compatibility:
        - older: OneHotEncoder(..., sparse=False)
        - newer: OneHotEncoder(..., sparse_output=False)
        """
        from sklearn.preprocessing import OneHotEncoder

        try:
            return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        except TypeError:
            return OneHotEncoder(handle_unknown="ignore", sparse=False)

    @classmethod
    def _validate_manual_schema(cls, columns) -> None:
        continuous_columns = set(cls.CONTINUOUS_COLUMNS)
        integer_columns = set(cls.INTEGER_COLUMNS)
        categorical_columns = set(cls.CATEGORICAL_COLUMNS)
        overlapping_columns = sorted(
            (continuous_columns & integer_columns)
            | (continuous_columns & categorical_columns)
            | (integer_columns & categorical_columns)
        )
        if overlapping_columns:
            raise ValueError(f"AdultCensusDataset columns configured twice: {overlapping_columns}")

        configured_columns = continuous_columns | integer_columns | categorical_columns
        dataset_columns = set(columns)
        missing_columns = sorted(configured_columns - dataset_columns)
        if missing_columns:
            raise ValueError(f"AdultCensusDataset is missing configured columns: {missing_columns}")
        unconfigured_columns = sorted(dataset_columns - configured_columns)
        if unconfigured_columns:
            raise ValueError(f"AdultCensusDataset has unconfigured columns: {unconfigured_columns}")

    def load_adult_census_dataset(self) -> tuple[AdultCensusTorchDataset, AdultCensusTorchDataset]:
        """
        Loads Adult dataset from OpenML and preprocesses to all-numeric features.

        Steps:
          1) fetch_openml(data_id=1590, as_frame=True)
          2) y = (target == '>50K').astype(int)
          3) replace '?' with NA for missing values
          4) ColumnTransformer:
              - continuous: median impute + StandardScaler
              - integer: median impute + StandardScaler
              - categorical: most_frequent impute + OneHotEncoder(dense)
          5) train/test split (stratified), fit preprocessing only on train (avoid leakage)
        """
        data_dir: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)

        try:
            import pandas as pd
            from sklearn.compose import ColumnTransformer
            from sklearn.datasets import fetch_openml
            from sklearn.impute import SimpleImputer
            from sklearn.model_selection import train_test_split
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import StandardScaler
        except Exception as e:
            raise ImportError(
                "AdultCensusDataset requires pandas + scikit-learn. Install them (e.g., pip install pandas scikit-learn)."
            ) from e

        # Raw Adult Census uses mixed pandas columns; the model receives the
        # numeric matrix produced later by the ColumnTransformer.
        bunch = fetch_openml(data_id=1590, as_frame=True, data_home=data_dir)
        X_df = bunch.data.copy()
        y_raw = bunch.target

        # Normalize target labels to {0, 1}; 1 means income >50K.
        y_str = y_raw.astype(str).str.strip()
        y: np.ndarray = (y_str == ">50K").astype(np.int64).to_numpy()

        # Adult encodes missing values as '?'. Drop incomplete rows so the
        # adversarial metadata is based on real observed feature ranges.
        X_df = X_df.replace(r"^\s*\?\s*$", np.nan, regex=True)
        self._validate_manual_schema(X_df.columns)

        numeric_columns = self.CONTINUOUS_COLUMNS + self.INTEGER_COLUMNS
        for column in numeric_columns:
            X_df[column] = pd.to_numeric(X_df[column], errors="coerce")
        for column in self.CATEGORICAL_COLUMNS:
            X_df[column] = X_df[column].astype(object)

        configured_columns = numeric_columns + self.CATEGORICAL_COLUMNS
        valid_rows = ~X_df[configured_columns].isna().any(axis=1)
        removed_rows = int((~valid_rows).sum())
        if removed_rows:
            logger.info("[AdultCensus] Dropping %s rows with NA values", removed_rows)
        X_df = X_df.loc[valid_rows].copy()
        y = y[valid_rows.to_numpy()]

        # Numeric columns are standardized; categorical columns become one-hot
        # columns. Constrained PGD metadata is built after this, in model input space.
        numeric_transformer = Pipeline(
            steps=[
                ("impute", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler(with_mean=True, with_std=True)),
            ]
        )

        categorical_transformer = Pipeline(
            steps=[
                ("impute", SimpleImputer(strategy="most_frequent")),
                ("ohe", self._make_ohe_dense()),
            ]
        )

        transformers = []
        if self.CONTINUOUS_COLUMNS:
            transformers.append(("continuous", numeric_transformer, self.CONTINUOUS_COLUMNS))
        if self.INTEGER_COLUMNS:
            transformers.append(("integer", numeric_transformer, self.INTEGER_COLUMNS))
        if self.CATEGORICAL_COLUMNS:
            transformers.append(("categorical", categorical_transformer, self.CATEGORICAL_COLUMNS))

        preprocessor = ColumnTransformer(transformers=transformers, remainder="drop")

        # Fit preprocessing only on train to avoid leaking test statistics.
        X_train_df, X_test_df, y_train, y_test = train_test_split(
            X_df,
            y,
            test_size=self.test_size,
            random_state=self.seed,
            shuffle=True,
            stratify=y,
        )

        X_train = preprocessor.fit_transform(X_train_df)
        X_test = preprocessor.transform(X_test_df)
        feature_names = self._feature_names(preprocessor, X_train.shape[1])

        # In case some sklearn path returns sparse matrices, densify safely
        if hasattr(X_train, "toarray"):
            X_train = X_train.toarray()
        if hasattr(X_test, "toarray"):
            X_test = X_test.toarray()

        X_train_np = np.asarray(X_train, dtype=np.float32)
        X_test_np: np.ndarray = np.asarray(X_test, dtype=np.float32)
        metadata = self._build_adversarial_metadata(feature_names, X_train_np, preprocessor)
        logger.info("[AdultCensus] X_train shape = %s", X_train_np.shape)
        logger.info("[AdultCensus] INPUT_DIM (post-OHE) = %s", int(X_train_np.shape[1]))
        self._log_adversarial_metadata(metadata, feature_names)

        train_ds = self._make_dataset(X_train_np, y_train, feature_names, metadata)
        test_ds = self._make_dataset(X_test_np, y_test, feature_names, metadata)

        return train_ds, test_ds

    @staticmethod
    def _feature_names(preprocessor, n_features: int) -> list[str]:
        try:
            return [str(name) for name in preprocessor.get_feature_names_out()]
        except Exception:
            return [f"feature_{idx}" for idx in range(n_features)]

    @staticmethod
    def _make_dataset(x, y, feature_names, metadata) -> AdultCensusTorchDataset:
        return AdultCensusTorchDataset(
            x,
            np.asarray(y, dtype=np.int64),
            feature_names=feature_names,
            continuous_features=[],
            integer_features=metadata["integer_features"],
            categorical_features=metadata["categorical_features"],
            non_perturbable_features=metadata["non_perturbable_features"],
            categorical_groups=metadata["categorical_groups"],
            tabular_metadata=metadata["tabular_metadata"],
        )

    @classmethod
    def _build_adversarial_metadata(cls, feature_names, x_train, preprocessor) -> dict[str, Any]:
        # Dataset responsibility ends here: declare which raw columns are perturbable.
        # The shared metadata builder maps those declarations to transformed model features.
        integer_scaler = preprocessor.named_transformers_["integer"].named_steps["scaler"]
        integer_step_by_column = {
            column: float(1.0 / scale)
            for column, scale in zip(cls.INTEGER_COLUMNS, integer_scaler.scale_, strict=False)
        }
        return build_tabular_adversarial_metadata(
            feature_names=feature_names,
            x_train=x_train,
            continuous_columns=cls.CONTINUOUS_COLUMNS,
            integer_columns=cls.INTEGER_COLUMNS,
            categorical_columns=cls.CATEGORICAL_COLUMNS,
            perturbable_integer_columns=cls.PERTURBABLE_INTEGER_COLUMNS,
            perturbable_categorical_columns=cls.PERTURBABLE_CATEGORICAL_COLUMNS,
            integer_step_by_column=integer_step_by_column,
        )

    @staticmethod
    def _log_adversarial_metadata(metadata: dict[str, Any], feature_names: list[str]) -> None:
        integer_features = metadata["integer_features"]
        categorical_features = metadata["categorical_features"]
        non_perturbable_features = metadata["non_perturbable_features"]
        logger.info(
            "[AdultCensus] Tabular adversarial feature mask | integer=%s | categorical=%s | "
            "categorical_groups=%s | non_perturbable=%s | integer_features=%s | "
            "categorical_preview=%s | non_perturbable_preview=%s | integer_step_norm=%s",
            len(integer_features),
            len(categorical_features),
            len(metadata["categorical_groups"]),
            len(non_perturbable_features),
            [feature_names[idx] for idx in integer_features],
            [feature_names[idx] for idx in categorical_features[:20]],
            [feature_names[idx] for idx in non_perturbable_features[:20]],
            metadata["integer_step_norm"],
        )

    def generate_non_iid_map(self, dataset, partition: str = "dirichlet", partition_parameter: float = 0.5):
        if partition == "dirichlet":
            return self.dirichlet_partition(dataset, alpha=partition_parameter)
        if partition == "percent":
            return self.percentage_partition(dataset, percentage=partition_parameter)
        raise ValueError(f"Partition {partition} is not supported for Non-IID map")

    def generate_iid_map(self, dataset, partition: str = "balancediid", partition_parameter: float = 2):
        if partition == "balancediid":
            return self.balanced_iid_partition(dataset)
        if partition == "unbalancediid":
            return self.unbalanced_iid_partition(dataset, imbalance_factor=partition_parameter)
        raise ValueError(f"Partition {partition} is not supported for IID map")

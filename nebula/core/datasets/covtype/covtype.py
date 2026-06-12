# nebula/core/datasets/covtype/covtype.py
# Blackard, J. (1998). Covertype [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C50K5N.
# Licensed under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/

import logging
import os
from typing import Any

import numpy as np
import torch
from torch.utils.data import Dataset

from nebula.core.datasets.nebuladataset import NebulaDataset, NebulaPartitionHandler
from nebula.core.datasets.tabular_metadata import build_tabular_adversarial_metadata

logger = logging.getLogger(__name__)


class CovtypeTorchDataset(Dataset):
    """
    Torch Dataset wrapper for tabular Covtype data.

    Returns:
        x: torch.float32 tensor of shape (n_features,)
        y: torch.long scalar in [0, num_classes-1]
    """
    def __init__(
        self,
        x: np.ndarray,
        y: np.ndarray,
        feature_names: list[str] | None = None,
        continuous_features: list[int] | None = None,
        integer_features: list[int] | None = None,
        non_perturbable_features: list[int] | None = None,
        binary_features: list[int] | None = None,
        tabular_metadata: dict | None = None,
    ):
        if not isinstance(x, np.ndarray) or not isinstance(y, np.ndarray):
            raise ValueError("x and y must be numpy arrays")

        if x.ndim != 2:
            raise ValueError(f"x must be 2D (n_samples, n_features). Got shape={x.shape}")
        if y.ndim != 1:
            y = y.reshape(-1)

        if x.shape[0] != y.shape[0]:
            raise ValueError(f"x and y must have same number of samples. Got {x.shape[0]} != {y.shape[0]}")

        self.x = x.astype(np.float32, copy=False)
        self.y = y.astype(np.int64, copy=False)

        # Nebula dataset conventions used by partitioning, logging and model setup.
        self.data = self.x
        self.targets = self.y

        n_classes = int(np.max(self.targets)) + 1
        self.classes = [str(i) for i in range(n_classes)]
        self.feature_names = feature_names or [f"feature_{i}" for i in range(self.x.shape[1])]
        self.continuous_features = continuous_features or []
        self.integer_features = integer_features or []
        self.non_perturbable_features = non_perturbable_features or []
        self.binary_features = binary_features or []
        self.tabular_metadata = tabular_metadata
        self.input_dim = int(self.x.shape[1])

    def __len__(self) -> int:
        return int(self.y.shape[0])

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        x_i = torch.from_numpy(self.x[idx])
        y_i = torch.tensor(self.y[idx], dtype=torch.long)
        return x_i, y_i


class CovtypePartitionHandler(NebulaPartitionHandler):
    """
    Partition handler for tabular datasets.

    NebulaPartitionHandler provides (data, target) from the partition storage.
    For images, we usually convert to PIL and apply torchvision transforms.
    Here we convert features to float32 torch tensors and targets to long.
    """
    def __init__(self, file_path: str, prefix: str, config: Any, empty: bool = False):
        super().__init__(file_path, prefix, config, empty)

        # Tabular features are already preprocessed before partitioning, so no
        # torchvision-style transform is applied here.
        self.transform = None

    def __getitem__(self, idx: int):
        data, target = super().__getitem__(idx)

        # Partition storage can return lists, numpy arrays or tensors. The model
        # expects a 1D float32 tensor for each tabular sample.
        if isinstance(data, tuple):
            data = data[0]

        if isinstance(data, torch.Tensor):
            x = data.to(dtype=torch.float32)
        else:
            x = torch.tensor(np.asarray(data), dtype=torch.float32)

        # Targets are stored as class indices and consumed by CrossEntropyLoss.
        if isinstance(target, torch.Tensor):
            y = target.to(dtype=torch.long)
        else:
            y = torch.tensor(int(target), dtype=torch.long)

        if self.target_transform is not None:
            y = self.target_transform(y)

        return x, y


class CovtypeDataset(NebulaDataset):
    """
    Covtype (Forest CoverType) dataset integration for Nebula.

    Notes:
    - Covtype has 7 classes.
    - Features are tabular (54 features in the classic version).
    - Deterministic stratified train/test split.

    Requirements:
    - scikit-learn must be installed (for fetch_covtype + train_test_split).
    """
    CONTINUOUS_COLUMNS = [
        "Elevation",
        "Aspect",
        "Slope",
        "Horizontal_Distance_To_Hydrology",
        "Vertical_Distance_To_Hydrology",
        "Horizontal_Distance_To_Roadways",
        "Hillshade_9am",
        "Hillshade_Noon",
        "Hillshade_3pm",
        "Horizontal_Distance_To_Fire_Points",
    ]
    BINARY_COLUMNS = [
        "Wilderness_Area_0",
        "Wilderness_Area_1",
        "Wilderness_Area_2",
        "Wilderness_Area_3",
        "Soil_Type_0",
        "Soil_Type_1",
        "Soil_Type_2",
        "Soil_Type_3",
        "Soil_Type_4",
        "Soil_Type_5",
        "Soil_Type_6",
        "Soil_Type_7",
        "Soil_Type_8",
        "Soil_Type_9",
        "Soil_Type_10",
        "Soil_Type_11",
        "Soil_Type_12",
        "Soil_Type_13",
        "Soil_Type_14",
        "Soil_Type_15",
        "Soil_Type_16",
        "Soil_Type_17",
        "Soil_Type_18",
        "Soil_Type_19",
        "Soil_Type_20",
        "Soil_Type_21",
        "Soil_Type_22",
        "Soil_Type_23",
        "Soil_Type_24",
        "Soil_Type_25",
        "Soil_Type_26",
        "Soil_Type_27",
        "Soil_Type_28",
        "Soil_Type_29",
        "Soil_Type_30",
        "Soil_Type_31",
        "Soil_Type_32",
        "Soil_Type_33",
        "Soil_Type_34",
        "Soil_Type_35",
        "Soil_Type_36",
        "Soil_Type_37",
        "Soil_Type_38",
        "Soil_Type_39",
    ]
    # Covtype has two kinds of inputs:
    # - terrain measurements, which constrained PGD may perturb;
    # - binary wilderness/soil indicators, which are already one-hot-like.
    #
    # The binary groups are immutable in the current metadata. This avoids
    # invalid wilderness/soil combinations while still exercising constrained
    # PGD on the numeric part of the dataset.
    PERTURBABLE_CONTINUOUS_COLUMNS = list(CONTINUOUS_COLUMNS)
    PERTURBABLE_INTEGER_COLUMNS = []
    NON_PERTURBABLE_COLUMNS = list(BINARY_COLUMNS)

    def __init__(
        self,
        num_classes: int = 7,
        partitions_number: int = 1,
        batch_size: int = 32,
        num_workers: int = 4,
        iid: bool = True,
        partition: str = "dirichlet",
        partition_parameter: float = 0.5,
        seed: int = 42,
        config_dir: str | None = None,
        test_size: float = 0.2,
        train_limit: int | None = None,
        test_limit: int | None = None,
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
        self.test_size = float(test_size)
        self.train_limit = train_limit
        self.test_limit = test_limit

    def initialize_dataset(self):
        if self.train_set is None or self.test_set is None:
            self.train_set, self.test_set = self.load_covtype_dataset()

        self.data_partitioning(plot=True)

    @classmethod
    def _default_feature_names(cls, n_features: int) -> list[str]:
        configured_columns = cls.CONTINUOUS_COLUMNS + cls.BINARY_COLUMNS
        if n_features == len(configured_columns):
            return configured_columns
        return [f"feature_{i}" for i in range(n_features)]

    @classmethod
    def _validate_manual_schema(cls, columns) -> None:
        continuous_columns = set(cls.CONTINUOUS_COLUMNS)
        integer_columns = set(cls.PERTURBABLE_INTEGER_COLUMNS)
        non_perturbable_columns = set(cls.NON_PERTURBABLE_COLUMNS)
        overlapping_columns = sorted(
            (continuous_columns & integer_columns)
            | (continuous_columns & non_perturbable_columns)
            | (integer_columns & non_perturbable_columns)
        )
        if overlapping_columns:
            raise ValueError(f"CovtypeDataset columns configured twice: {overlapping_columns}")

        configured_columns = continuous_columns | integer_columns | non_perturbable_columns
        dataset_columns = set(columns)
        missing_columns = sorted(configured_columns - dataset_columns)
        if missing_columns:
            raise ValueError(f"CovtypeDataset is missing configured columns: {missing_columns}")
        unconfigured_columns = sorted(dataset_columns - configured_columns)
        if unconfigured_columns:
            raise ValueError(f"CovtypeDataset has unconfigured columns: {unconfigured_columns}")

    def load_covtype_dataset(self):
        """
        Loads Covtype via sklearn, performs a deterministic train/test split,
        and wraps into torch Datasets.
        """
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)

        try:
            from sklearn.datasets import fetch_covtype
            from sklearn.model_selection import train_test_split
            from sklearn.preprocessing import StandardScaler
        except Exception as e:
            raise ImportError(
                "CovtypeDataset requires scikit-learn. Install it (e.g., pip install scikit-learn)."
            ) from e

        cov = fetch_covtype(data_home=data_dir, download_if_missing=True)

        x = cov.data
        y = cov.target  # commonly 1..7 in sklearn
        feature_names = getattr(cov, "feature_names", None)
        if feature_names is None:
            feature_names = self._default_feature_names(x.shape[1])
        feature_names = [str(name) for name in feature_names]
        try:
            self._validate_manual_schema(feature_names)
        except ValueError:
            if x.shape[1] != len(self.CONTINUOUS_COLUMNS) + len(self.BINARY_COLUMNS):
                raise
            logger.info(
                "[Covtype] Replacing sklearn feature names with canonical Covtype names for adversarial metadata"
            )
            feature_names = self._default_feature_names(x.shape[1])
            self._validate_manual_schema(feature_names)

        # sklearn usually returns labels in 1..7. CrossEntropyLoss expects
        # zero-based class indices, so map them to 0..6 when needed.
        y = np.asarray(y).reshape(-1)
        if y.min() == 1:
            y = y - 1

        # Build a deterministic stratified train/test split.
        x_train, x_test, y_train, y_test = train_test_split(
            x, y,
            test_size=self.test_size,
            random_state=self.seed,
            shuffle=True,
            stratify=y,
        )

        # Optional stratified limits keep experiments manageable without
        # changing the class distribution unnecessarily.
        if self.train_limit is not None and len(y_train) > self.train_limit:
            x_train, _, y_train, _ = train_test_split(
                x_train, y_train,
                train_size=self.train_limit,
                random_state=self.seed,
                shuffle=True,
                stratify=y_train,
            )

        if self.test_limit is not None and len(y_test) > self.test_limit:
            x_test, _, y_test, _ = train_test_split(
                x_test, y_test,
                train_size=self.test_limit,
                random_state=self.seed,
                shuffle=True,
                stratify=y_test,
            )

        # Scale only the terrain measurements. The binary columns must remain
        # exact 0/1 values because they encode wilderness and soil indicators.
        scaler = StandardScaler()
        x_train = np.asarray(x_train, dtype=np.float32).copy()
        x_test = np.asarray(x_test, dtype=np.float32).copy()
        continuous_features = [
            idx for idx, name in enumerate(feature_names)
            if name in self.CONTINUOUS_COLUMNS
        ]
        x_train[:, continuous_features] = scaler.fit_transform(x_train[:, continuous_features])
        x_test[:, continuous_features] = scaler.transform(x_test[:, continuous_features])
        metadata = self._build_adversarial_metadata(feature_names, x_train)
        self._log_adversarial_metadata(metadata, feature_names)

        return (
            self._make_dataset(x_train, y_train, feature_names, metadata),
            self._make_dataset(x_test, y_test, feature_names, metadata),
        )

    @staticmethod
    def _make_dataset(
        x: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        metadata: dict[str, Any],
    ) -> CovtypeTorchDataset:
        return CovtypeTorchDataset(
            x,
            y,
            feature_names=feature_names,
            continuous_features=metadata["continuous_features"],
            integer_features=metadata["integer_features"],
            non_perturbable_features=metadata["non_perturbable_features"],
            binary_features=metadata["non_perturbable_features"],
            tabular_metadata=metadata["tabular_metadata"],
        )

    @classmethod
    def _build_adversarial_metadata(cls, feature_names, x_train):
        # Dataset responsibility: declare which variables are perturbable. The
        # shared builder marks every other feature, including binary indicators,
        # as non-perturbable and creates the masks consumed by constrained PGD.
        return build_tabular_adversarial_metadata(
            feature_names=feature_names,
            x_train=x_train,
            continuous_columns=cls.CONTINUOUS_COLUMNS,
            integer_columns=[],
            categorical_columns=[],
            perturbable_continuous_columns=cls.PERTURBABLE_CONTINUOUS_COLUMNS,
            perturbable_integer_columns=cls.PERTURBABLE_INTEGER_COLUMNS,
        )

    @staticmethod
    def _log_adversarial_metadata(metadata: dict[str, Any], feature_names: list[str]) -> None:
        continuous_features = metadata["continuous_features"]
        non_perturbable_features = metadata["non_perturbable_features"]
        logger.info(
            "[Covtype] Tabular adversarial feature mask | continuous=%s | binary_non_perturbable=%s | "
            "continuous_features=%s | non_perturbable_preview=%s",
            len(continuous_features),
            len(non_perturbable_features),
            [feature_names[idx] for idx in continuous_features],
            [feature_names[idx] for idx in non_perturbable_features[:20]],
        )

    def generate_non_iid_map(self, dataset, partition: str = "dirichlet", partition_parameter: float = 0.5):
        if partition == "dirichlet":
            partitions_map = self.dirichlet_partition(dataset, alpha=partition_parameter)
        elif partition == "percent":
            partitions_map = self.percentage_partition(dataset, percentage=partition_parameter)
        else:
            raise ValueError(f"Partition {partition} is not supported for Non-IID map")

        return partitions_map

    def generate_iid_map(self, dataset, partition: str = "balancediid", partition_parameter: float = 2):
        if partition == "balancediid":
            partitions_map = self.balanced_iid_partition(dataset)
        elif partition == "unbalancediid":
            partitions_map = self.unbalanced_iid_partition(dataset, imbalance_factor=partition_parameter)
        else:
            raise ValueError(f"Partition {partition} is not supported for IID map")

        return partitions_map

# Stolfo, S., Fan, W., Lee, W., Prodromidis, A., & Chan, P. (1999). KDD Cup 1999 Data [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C51C7N.
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


class KDDCUP99TorchDataset(Dataset):
    """
    Torch Dataset wrapper for tabular KDDCUP99 data.

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


class KDDCUP99PartitionHandler(NebulaPartitionHandler):
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


class KDDCUP99Dataset(NebulaDataset):
    """
    KDDCUP99 dataset integration for Nebula.

    Notes:
    - KDDCUP99 is a tabular intrusion-detection dataset.
    - sklearn fetch_kddcup99 exposes 41 features.
    - Targets are mapped to a binary task: normal vs attack.
    - Categorical string columns are one-hot encoded.
    - Targets may come as bytes/strings, so we decode before mapping labels.

    Requirements:
    - scikit-learn must be installed
    - pandas must be installed
    """
    RAW_FEATURE_COLUMNS = [
        "duration",
        "protocol_type",
        "service",
        "flag",
        "src_bytes",
        "dst_bytes",
        "land",
        "wrong_fragment",
        "urgent",
        "hot",
        "num_failed_logins",
        "logged_in",
        "num_compromised",
        "root_shell",
        "su_attempted",
        "num_root",
        "num_file_creations",
        "num_shells",
        "num_access_files",
        "num_outbound_cmds",
        "is_host_login",
        "is_guest_login",
        "count",
        "srv_count",
        "serror_rate",
        "srv_serror_rate",
        "rerror_rate",
        "srv_rerror_rate",
        "same_srv_rate",
        "diff_srv_rate",
        "srv_diff_host_rate",
        "dst_host_count",
        "dst_host_srv_count",
        "dst_host_same_srv_rate",
        "dst_host_diff_srv_rate",
        "dst_host_same_src_port_rate",
        "dst_host_srv_diff_host_rate",
        "dst_host_serror_rate",
        "dst_host_srv_serror_rate",
        "dst_host_rerror_rate",
        "dst_host_srv_rerror_rate",
    ]
    CONTINUOUS_COLUMNS = [
        "serror_rate",
        "srv_serror_rate",
        "rerror_rate",
        "srv_rerror_rate",
        "same_srv_rate",
        "diff_srv_rate",
        "srv_diff_host_rate",
        "dst_host_same_srv_rate",
        "dst_host_diff_srv_rate",
        "dst_host_same_src_port_rate",
        "dst_host_srv_diff_host_rate",
        "dst_host_serror_rate",
        "dst_host_srv_serror_rate",
        "dst_host_rerror_rate",
        "dst_host_srv_rerror_rate",
    ]
    INTEGER_COLUMNS = [
        "duration",
        "src_bytes",
        "dst_bytes",
        "wrong_fragment",
        "urgent",
        "hot",
        "num_failed_logins",
        "num_compromised",
        "num_root",
        "num_file_creations",
        "num_shells",
        "num_access_files",
        "num_outbound_cmds",
        "count",
        "srv_count",
        "dst_host_count",
        "dst_host_srv_count",
    ]
    CATEGORICAL_COLUMNS = [
        "protocol_type",
        "service",
        "flag",
    ]
    NON_PERTURBABLE_COLUMNS = [
        "land",
        "logged_in",
        "root_shell",
        "su_attempted",
        "is_host_login",
        "is_guest_login",
    ]
    # KDDCUP99 exposes mixed network-traffic features. For the first supported
    # adversarial-training version, constrained PGD may perturb numeric traffic
    # measurements and counters. Protocol/service/flag one-hot columns and
    # binary login/status flags stay immutable to avoid invalid records.
    PERTURBABLE_CONTINUOUS_COLUMNS = list(CONTINUOUS_COLUMNS)
    PERTURBABLE_INTEGER_COLUMNS = list(INTEGER_COLUMNS)

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
        train_limit: int | None = 20000,
        test_limit: int | None = 4000,
        subset: str | None = None,
        percent10: bool = True,
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
        self.subset = subset
        self.percent10 = percent10

    def initialize_dataset(self):
        if self.train_set is None or self.test_set is None:
            self.train_set, self.test_set = self.load_kddcup99_dataset()

        self.data_partitioning(plot=True)

    @classmethod
    def _ensure_raw_feature_names(cls, x):
        if list(x.columns) == list(range(len(cls.RAW_FEATURE_COLUMNS))):
            x = x.copy()
            x.columns = cls.RAW_FEATURE_COLUMNS
        return x

    @classmethod
    def _validate_manual_schema(cls, columns) -> None:
        continuous_columns = set(cls.CONTINUOUS_COLUMNS)
        integer_columns = set(cls.INTEGER_COLUMNS)
        categorical_columns = set(cls.CATEGORICAL_COLUMNS)
        non_perturbable_columns = set(cls.NON_PERTURBABLE_COLUMNS)
        overlapping_columns = sorted(
            (continuous_columns & integer_columns)
            | (continuous_columns & categorical_columns)
            | (continuous_columns & non_perturbable_columns)
            | (integer_columns & categorical_columns)
            | (integer_columns & non_perturbable_columns)
            | (categorical_columns & non_perturbable_columns)
        )
        if overlapping_columns:
            raise ValueError(f"KDDCUP99Dataset columns configured twice: {overlapping_columns}")

        configured_columns = continuous_columns | integer_columns | categorical_columns | non_perturbable_columns
        dataset_columns = set(columns)
        missing_columns = sorted(configured_columns - dataset_columns)
        if missing_columns:
            raise ValueError(f"KDDCUP99Dataset is missing configured columns: {missing_columns}")
        unconfigured_columns = sorted(dataset_columns - configured_columns)
        if unconfigured_columns:
            raise ValueError(f"KDDCUP99Dataset has unconfigured columns: {unconfigured_columns}")

    def load_kddcup99_dataset(self):
        """
        Loads KDDCUP99 via sklearn, performs deterministic preprocessing
        and train/test split, and wraps into torch Datasets.
        """
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)

        try:
            import pandas as pd
            from sklearn.datasets import fetch_kddcup99
            from sklearn.model_selection import train_test_split
            from sklearn.preprocessing import StandardScaler
        except Exception as e:
            raise ImportError(
                "KDDCUP99Dataset requires scikit-learn and pandas. "
            ) from e

        kdd = fetch_kddcup99(
            subset=self.subset,
            data_home=data_dir,
            shuffle=True,
            random_state=self.seed,
            percent10=self.percent10,
            download_if_missing=True,
            as_frame=True,
        )

        x = kdd.data
        y = kdd.target

        # fetch_kddcup99 can return numpy arrays depending on sklearn version.
        # The preprocessing below expects pandas columns.
        if not hasattr(x, "columns"):
            x = pd.DataFrame(x)
        if not hasattr(y, "astype"):
            y = pd.Series(y)
        x = self._ensure_raw_feature_names(x)
        self._validate_manual_schema(x.columns)

        def _decode_if_bytes(v):
            if isinstance(v, (bytes, bytearray)):
                return v.decode("utf-8", errors="ignore")
            return v

        # Decode bytes before one-hot encoding categorical columns and mapping labels.
        for col in x.columns:
            if x[col].dtype == object:
                x[col] = x[col].map(_decode_if_bytes)

        y = y.map(_decode_if_bytes)

        # One-hot encode protocol/service/flag and keep numeric columns as-is.
        x = pd.get_dummies(x, drop_first=False)
        feature_names = [str(col) for col in x.columns]
        logger.info("[KDDCUP99] Encoded feature dimension: %s", len(feature_names))

        # Map labels to a binary task: 0 = normal, 1 = attack.
        y = pd.Series(y).astype(str)
        y = y.str.strip()
        y = (y != "normal.").astype(np.int64).to_numpy(copy=False)
        self.num_classes = 2

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
            logger.info("[KDDCUP99] Limited train split to %s samples", len(y_train))

        if self.test_limit is not None and len(y_test) > self.test_limit:
            x_test, _, y_test, _ = train_test_split(
                x_test, y_test,
                train_size=self.test_limit,
                random_state=self.seed,
                shuffle=True,
                stratify=y_test,
            )
            logger.info("[KDDCUP99] Limited test split to %s samples", len(y_test))

        x_train_np = x_train.astype(np.float32).to_numpy(copy=True)
        x_test_np = x_test.astype(np.float32).to_numpy(copy=True)

        # Scale perturbable numeric columns after splitting. One-hot categorical
        # columns and binary flags remain exact 0/1 values.
        continuous_features = self._column_indices(x_train.columns, self.CONTINUOUS_COLUMNS)
        integer_features = self._column_indices(x_train.columns, self.INTEGER_COLUMNS)
        scaled_features = continuous_features + integer_features
        integer_step_by_column = {}
        if scaled_features:
            scaler = StandardScaler()
            x_train_np[:, scaled_features] = scaler.fit_transform(x_train_np[:, scaled_features])
            x_test_np[:, scaled_features] = scaler.transform(x_test_np[:, scaled_features])
            integer_scales = scaler.scale_[len(continuous_features):]
            integer_step_by_column = {
                column: float(1.0 / scale)
                for column, scale in zip(self.INTEGER_COLUMNS, integer_scales, strict=False)
            }

        metadata = self._build_adversarial_metadata(feature_names, x_train_np, integer_step_by_column)
        self._log_adversarial_metadata(metadata, feature_names)

        return (
            self._make_dataset(x_train_np, y_train, feature_names, metadata),
            self._make_dataset(x_test_np, y_test, feature_names, metadata),
        )

    @staticmethod
    def _column_indices(columns, names: list[str]) -> list[int]:
        return [columns.get_loc(name) for name in names if name in columns]

    @staticmethod
    def _make_dataset(
        x: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        metadata: dict[str, Any],
    ) -> KDDCUP99TorchDataset:
        dataset = KDDCUP99TorchDataset(
            x,
            y,
            feature_names=feature_names,
            continuous_features=metadata["continuous_features"],
            integer_features=metadata["integer_features"],
            non_perturbable_features=metadata["non_perturbable_features"],
            binary_features=metadata["non_perturbable_features"],
            tabular_metadata=metadata["tabular_metadata"],
        )
        dataset.classes = ["normal", "attack"]
        return dataset

    @classmethod
    def _build_adversarial_metadata(
        cls,
        feature_names: list[str],
        x_train: np.ndarray,
        integer_step_by_column: dict[str, float],
    ) -> dict[str, Any]:
        # Dataset responsibility: declare which raw variables are perturbable.
        # The shared builder maps that declaration to transformed feature masks,
        # bounds and integer steps in model-input space.
        return build_tabular_adversarial_metadata(
            feature_names=feature_names,
            x_train=x_train,
            continuous_columns=cls.CONTINUOUS_COLUMNS,
            integer_columns=cls.INTEGER_COLUMNS,
            categorical_columns=cls.CATEGORICAL_COLUMNS,
            perturbable_continuous_columns=cls.PERTURBABLE_CONTINUOUS_COLUMNS,
            perturbable_integer_columns=cls.PERTURBABLE_INTEGER_COLUMNS,
            integer_step_by_column=integer_step_by_column,
        )

    @staticmethod
    def _log_adversarial_metadata(metadata: dict[str, Any], feature_names: list[str]) -> None:
        continuous_features = metadata["continuous_features"]
        integer_features = metadata["integer_features"]
        non_perturbable_features = metadata["non_perturbable_features"]
        logger.info(
            "[KDDCUP99] Tabular adversarial feature mask | continuous=%s | integer=%s | "
            "non_perturbable=%s | continuous_features=%s | integer_features=%s | "
            "non_perturbable_preview=%s | integer_step_norm=%s",
            len(continuous_features),
            len(integer_features),
            len(non_perturbable_features),
            [feature_names[idx] for idx in continuous_features],
            [feature_names[idx] for idx in integer_features],
            [feature_names[idx] for idx in non_perturbable_features[:20]],
            metadata["integer_step_norm"],
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

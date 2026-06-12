# Wolberg, W., Mangasarian, O., Street, N., & Street, W. (1993). Breast Cancer Wisconsin (Diagnostic) [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5DW2B.
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


class BreastCancerTorchDataset(Dataset):
    """
    Torch Dataset wrapper for sklearn breast cancer dataset (tabular).
    x: float32 tensor (n_features,)
    y: long scalar {0,1}
    """
    def __init__(
        self,
        x: np.ndarray,
        y: np.ndarray,
        feature_names: list[str] | None = None,
        continuous_features: list[int] | None = None,
        integer_features: list[int] | None = None,
        non_perturbable_features: list[int] | None = None,
        tabular_metadata: dict | None = None,
    ):
        if not isinstance(x, np.ndarray) or not isinstance(y, np.ndarray):
            raise ValueError("x and y must be numpy arrays")

        if x.ndim != 2:
            raise ValueError(f"x must be 2D (n_samples, n_features). Got shape={x.shape}")

        y = np.asarray(y).reshape(-1)
        if x.shape[0] != y.shape[0]:
            raise ValueError(f"x and y must have same number of samples. Got {x.shape[0]} != {y.shape[0]}")

        self.x = x.astype(np.float32, copy=False)
        self.y = y.astype(np.int64, copy=False)

        # Nebula dataset conventions used by partitioning, logging and model setup.
        self.data = self.x
        self.targets = self.y
        self.classes = ["0", "1"]
        self.feature_names = feature_names or [f"feature_{i}" for i in range(self.x.shape[1])]
        self.continuous_features = list(range(self.x.shape[1])) if continuous_features is None else continuous_features
        self.integer_features = [] if integer_features is None else integer_features
        self.non_perturbable_features = [] if non_perturbable_features is None else non_perturbable_features
        self.binary_features = []
        self.tabular_metadata = tabular_metadata
        self.input_dim = int(self.x.shape[1])

    def __len__(self) -> int:
        return int(self.y.shape[0])

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        x_i = torch.from_numpy(self.x[idx])
        y_i = torch.tensor(self.y[idx], dtype=torch.long)
        return x_i, y_i


class BreastCancerPartitionHandler(NebulaPartitionHandler):
    """
    Partition handler for tabular data.
    """
    def __init__(self, file_path: str, prefix: str, config: Any, empty: bool = False):
        super().__init__(file_path, prefix, config, empty)
        self.transform = None  # no torchvision transforms for tabular

    def __getitem__(self, idx: int):
        data, target = super().__getitem__(idx)

        if isinstance(data, tuple):
            data = data[0]

        if isinstance(data, torch.Tensor):
            x = data.to(dtype=torch.float32)
        else:
            x = torch.tensor(np.asarray(data), dtype=torch.float32)

        if isinstance(target, torch.Tensor):
            y = target.to(dtype=torch.long)
        else:
            y = torch.tensor(int(target), dtype=torch.long)

        if self.target_transform is not None:
            y = self.target_transform(y)

        return x, y


class BreastCancerDataset(NebulaDataset):
    """
    Breast Cancer Wisconsin (Diagnostic) dataset integration for Nebula.

    - 2 classes
    - tabular features (30)
    - deterministic stratified train/test split
    """
    # Raw sklearn feature names. These names are also the schema used to decide
    # which variables adversarial training may perturb.
    FEATURE_COLUMNS = [
        "mean radius",
        "mean texture",
        "mean perimeter",
        "mean area",
        "mean smoothness",
        "mean compactness",
        "mean concavity",
        "mean concave points",
        "mean symmetry",
        "mean fractal dimension",
        "radius error",
        "texture error",
        "perimeter error",
        "area error",
        "smoothness error",
        "compactness error",
        "concavity error",
        "concave points error",
        "symmetry error",
        "fractal dimension error",
        "worst radius",
        "worst texture",
        "worst perimeter",
        "worst area",
        "worst smoothness",
        "worst compactness",
        "worst concavity",
        "worst concave points",
        "worst symmetry",
        "worst fractal dimension",
    ]
    # Breast Cancer has only continuous medical measurements. Keeping this as a
    # list makes perturbability a dataset-level decision: remove a column here
    # and the shared metadata builder will mark it as non-perturbable.
    PERTURBABLE_CONTINUOUS_COLUMNS = list(FEATURE_COLUMNS)
    PERTURBABLE_INTEGER_COLUMNS = []

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
        self.test_size = float(test_size)

    def initialize_dataset(self):
        if self.train_set is None or self.test_set is None:
            self.train_set, self.test_set = self.load_breast_cancer_dataset()

        self.data_partitioning(plot=True)

    def load_breast_cancer_dataset(self):
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)

        try:
            from sklearn.datasets import load_breast_cancer
            from sklearn.model_selection import train_test_split
            from sklearn.preprocessing import StandardScaler
        except Exception as e:
            raise ImportError(
                "BreastCancerDataset requires scikit-learn. Install it (e.g., pip install scikit-learn)."
            ) from e

        ds = load_breast_cancer()
        x = np.asarray(ds.data)
        y = np.asarray(ds.target).reshape(-1)  # already 0/1
        feature_names = [str(name) for name in ds.feature_names]
        self._validate_manual_schema(feature_names)

        x_train, x_test, y_train, y_test = train_test_split(
            x,
            y,
            test_size=self.test_size,
            random_state=self.seed,
            shuffle=True,
            stratify=y,
        )

        scaler = StandardScaler()
        x_train = scaler.fit_transform(x_train)
        x_test = scaler.transform(x_test)

        # Constrained PGD receives standardized tensors, so metadata bounds must also be
        # computed in this transformed model-input space.
        x_train_np = np.asarray(x_train, dtype=np.float32)
        x_test_np = np.asarray(x_test, dtype=np.float32)
        metadata = self._build_adversarial_metadata(feature_names, x_train_np)
        self._log_adversarial_metadata(metadata, feature_names)

        return (
            self._make_dataset(x_train_np, y_train, feature_names, metadata),
            self._make_dataset(x_test_np, y_test, feature_names, metadata),
        )

    @classmethod
    def _validate_manual_schema(cls, columns) -> None:
        dataset_columns = set(columns)
        expected_columns = set(cls.FEATURE_COLUMNS)
        missing_columns = sorted(expected_columns - dataset_columns)
        extra_columns = sorted(dataset_columns - expected_columns)
        if missing_columns or extra_columns:
            raise ValueError(
                "BreastCancerDataset schema mismatch: "
                f"missing={missing_columns}, extra={extra_columns}"
            )

    @classmethod
    def _build_adversarial_metadata(cls, feature_names, x_train):
        # The dataset only declares perturbable columns. The shared builder
        # turns that declaration into feature types, bounds and masks for constrained PGD.
        return build_tabular_adversarial_metadata(
            feature_names=feature_names,
            x_train=x_train,
            continuous_columns=cls.FEATURE_COLUMNS,
            integer_columns=[],
            categorical_columns=[],
            perturbable_continuous_columns=cls.PERTURBABLE_CONTINUOUS_COLUMNS,
            perturbable_integer_columns=cls.PERTURBABLE_INTEGER_COLUMNS,
        )

    @staticmethod
    def _make_dataset(x, y, feature_names, metadata) -> BreastCancerTorchDataset:
        # Store the same metadata on train and test. Training uses it to create
        # adversarial examples; evaluation can inspect it for robustness reports.
        return BreastCancerTorchDataset(
            x,
            y,
            feature_names=feature_names,
            continuous_features=metadata["continuous_features"],
            integer_features=metadata["integer_features"],
            non_perturbable_features=metadata["non_perturbable_features"],
            tabular_metadata=metadata["tabular_metadata"],
        )

    @staticmethod
    def _log_adversarial_metadata(metadata: dict[str, Any], feature_names: list[str]) -> None:
        continuous_features = metadata["continuous_features"]
        non_perturbable_features = metadata["non_perturbable_features"]
        logger.info(
            "[BreastCancer] Tabular adversarial feature mask | continuous=%s | "
            "non_perturbable=%s | continuous_features=%s | non_perturbable_preview=%s",
            len(continuous_features),
            len(non_perturbable_features),
            [feature_names[idx] for idx in continuous_features],
            [feature_names[idx] for idx in non_perturbable_features[:20]],
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

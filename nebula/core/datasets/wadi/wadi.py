import os
import sys
import urllib.request

import numpy as np
import torch
from torchvision.datasets import MNIST

from nebula.core.datasets.nebuladataset import NebulaDataset


class WADI(MNIST):
    def __init__(self, partition_id, partitions_number, root_dir, train=True):
        super(MNIST, self).__init__(root_dir, transform=None, target_transform=None)
        self.partition_id = partition_id
        self.partitions_number = partitions_number
        self.download_link = "XXXX"
        self.files = ["X_train.npy", "y_train.npy", "X_test.npy", "y_test.npy"]
        self.train = train
        self.root = root_dir

        if (
            not os.path.exists(f"{self.root}/WADI/X_train.npy")
            or not os.path.exists(f"{self.root}/WADI/y_train.npy")
            or not os.path.exists(f"{self.root}/WADI/X_test.npy")
            or not os.path.exists(f"{self.root}/WADI/y_test.npy")
        ):
            self.dataset_download()

        if self.train:
            data_file = self.training_file
            self.data, self.targets = (
                torch.from_numpy(np.load(f"{self.root}/WADI/X_train.npy")),
                torch.from_numpy(np.load(f"{self.root}/WADI/y_train.npy")),
            )
            self.data = self.data.to(torch.float32)
            self.targets = self.targets.to(torch.float32)
        else:
            data_file = self.test_file
            self.data, self.targets = (
                torch.from_numpy(np.load(f"{self.root}/WADI/X_test.npy")),
                torch.from_numpy(np.load(f"{self.root}/WADI/y_test.npy")),
            )
            self.data = self.data.to(torch.float32)
            self.targets = self.targets.to(torch.float32)

    def __getitem__(self, index):
        img, target = self.data[index], int(self.targets[index])
        return img, target

    def dataset_download(self):
        paths = [f"{self.root}/WADI/"]
        for path in paths:
            if not os.path.exists(path):
                os.makedirs(path)
        for file in self.files:
            urllib.request.urlretrieve(
                os.path.join(f"{self.download_link}", file),
                os.path.join(f"{self.root}/WADI/", file),
            )


class WADIDataModule(NebulaDataset):
    def __init__(
        self,
        num_classes=10,
        partition_id=0,
        partitions_number=1,
        batch_size=32,
        num_workers=4,
        iid=True,
        partition="dirichlet",
        partition_parameter=0.5,
        seed=42,
        config=None,
    ):
        super().__init__(
            num_classes=num_classes,
            partition_id=partition_id,
            partitions_number=partitions_number,
            batch_size=batch_size,
            num_workers=num_workers,
            iid=iid,
            partition=partition,
            partition_parameter=partition_parameter,
            seed=seed,
            config=config,
        )

    def initialize_dataset(self):
        # Load wadi train dataset
        if self.train_set is None:
            self.train_set = self.load_wadi_dataset(train=True)
        if self.test_set is None:
            self.test_set = self.load_wadi_dataset(train=False)

        # All nodes have the same test set (indices are the same for all nodes)
        self.test_indices_map = list(range(len(self.test_set)))

        # Depending on the iid flag, generate a non-iid or iid map of the train set
        if self.iid:
            self.train_indices_map = self.generate_iid_map(self.train_set, self.partition, self.partition_parameter)
            self.local_test_indices_map = self.generate_iid_map(self.test_set, self.partition, self.partition_parameter)
        else:
            self.train_indices_map = self.generate_non_iid_map(self.train_set, self.partition, self.partition_parameter)
            self.local_test_indices_map = self.generate_non_iid_map(
                self.test_set, self.partition, self.partition_parameter
            )

        print(f"Length of train indices map: {len(self.train_indices_map)}")
        print(f"Lenght of test indices map: {len(self.test_indices_map)}")
        print(f"Lenght of test indices map (global): {len(self.test_indices_map)}")
        print(f"Length of test indices map (local): {len(self.local_test_indices_map)}")

    def load_wadi_dataset(self, train=True):
        if train:
            return WADI(
                partition_id=self.partition_id,
                partitions_number=self.partitions_number,
                root_dir=f"{sys.path[0]}/data",
                train=True,
            )
        else:
            return WADI(
                partition_id=self.partition_id,
                partitions_number=self.partitions_number,
                root_dir=f"{sys.path[0]}/data",
                train=False,
            )

    def generate_non_iid_map(self, dataset, partition="dirichlet", partition_parameter=0.5):
        if partition == "dirichlet":
            partitions_map = self.dirichlet_partition(dataset, alpha=partition_parameter)
        elif partition == "percent":
            partitions_map = self.percentage_partition(dataset, percentage=partition_parameter)
        else:
            raise ValueError(f"Partition {partition} is not supported for Non-IID map")

        if self.partition_id == 0:
            self.plot_data_distribution(dataset, partitions_map)
            self.plot_all_data_distribution(dataset, partitions_map)

        return partitions_map[self.partition_id]

    def generate_iid_map(self, dataset, partition="balancediid", partition_parameter=2):
        if partition == "balancediid":
            partitions_map = self.balanced_iid_partition(dataset)
        elif partition == "unbalancediid":
            partitions_map = self.unbalanced_iid_partition(dataset, imbalance_factor=partition_parameter)
        else:
            raise ValueError(f"Partition {partition} is not supported for IID map")

        if self.partition_id == 0:
            self.plot_data_distribution(dataset, partitions_map)
            self.plot_all_data_distribution(dataset, partitions_map)

        return partitions_map[self.partition_id]

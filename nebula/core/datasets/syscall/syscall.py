import ast
import os
import sys
import zipfile

import pandas as pd
import torch
from sklearn.model_selection import train_test_split
from torchvision.datasets import MNIST, utils

from nebula.core.datasets.nebuladataset import NebulaDataset


class SYSCALL(MNIST):
    def __init__(
        self,
        partition_id,
        partitions_number,
        root_dir,
        train=True,
        transform=None,
        target_transform=None,
        download=False,
    ):
        super().__init__(root_dir, transform=None, target_transform=None)
        self.transform = transform
        self.target_transform = target_transform
        self.partition_id = partition_id
        self.partitions_number = partitions_number
        self.download = download
        self.download_link = "https://files.ifi.uzh.ch/CSG/research/fl/data/syscall.zip"
        self.train = train
        self.root = root_dir
        self.training_file = f"{self.root}/syscall/processed/syscall_train.pt"
        self.test_file = f"{self.root}/syscall/processed/syscall_test.pt"

        if not os.path.exists(f"{self.root}/syscall/processed/syscall_test.pt") or not os.path.exists(
            f"{self.root}/syscall/processed/syscall_train.pt"
        ):
            if self.download:
                self.dataset_download()
                self.process()
            else:
                raise RuntimeError("Dataset not found, set parameter download=True to download")
        else:
            print("SYSCALL dataset already downloaded and processed.")

        if self.train:
            data_file = self.training_file
        else:
            data_file = self.test_file
        data_and_targets = torch.load(data_file)
        self.data, self.targets = data_and_targets[0], data_and_targets[1]

    def __getitem__(self, index):
        img, target = self.data[index], int(self.targets[index])
        if self.transform is not None:
            img = img
        if self.target_transform is not None:
            target = target
        return img, target

    def dataset_download(self):
        paths = [f"{self.root}/syscall/raw/", f"{self.root}/syscall/processed/"]
        for path in paths:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
        print("Downloading SYSCALL dataset...")
        filename = self.download_link.split("/")[-1]
        utils.download_and_extract_archive(
            self.download_link,
            download_root=f"{self.root}/syscall/raw/",
            filename=filename,
        )

        with zipfile.ZipFile(f"{self.root}/syscall/raw/{filename}", "r") as zip_ref:
            zip_ref.extractall(f"{self.root}/syscall/raw/")

    def process(self):
        print("Processing SYSCALL dataset...")
        df = pd.DataFrame()
        files = os.listdir(f"{self.root}/syscall/raw/")
        feature_name = "system calls frequency_1gram-scaled"
        for f in files:
            if ".csv" in f:
                fi_path = f"{self.root}/syscall/raw/{f}"
                csv_df = pd.read_csv(fi_path, sep="\t")
                feature = [ast.literal_eval(i) for i in csv_df[feature_name]]
                csv_df[feature_name] = feature
                df = pd.concat([df, csv_df])
        df["maltype"] = df["maltype"].replace(to_replace="normalv2", value="normal")
        classes_to_targets = {}
        t = 0
        for i in set(df["maltype"]):
            classes_to_targets[i] = t
            t += 1
        classes = list(classes_to_targets.keys())

        for c in classes_to_targets:
            df["maltype"] = df["maltype"].replace(to_replace=c, value=classes_to_targets[c])

        all_targes = torch.tensor(df["maltype"].tolist())
        all_data = torch.tensor(df[feature_name].tolist())

        x_train, x_test, y_train, y_test = train_test_split(all_data, all_targes, test_size=0.15, random_state=42)
        train = [x_train, y_train, classes_to_targets, classes]
        test = [x_test, y_test, classes_to_targets, classes]
        train_file = f"{self.root}/syscall/processed/syscall_train.pt"
        test_file = f"{self.root}/syscall/processed/syscall_test.pt"
        if not os.path.exists(train_file):
            torch.save(train, train_file)
        if not os.path.exists(test_file):
            torch.save(test, test_file)


class SYSCALLDataset(NebulaDataset):
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
        # Load syscall train dataset
        if self.train_set is None:
            self.train_set = self.load_syscall_dataset(train=True)
        if self.test_set is None:
            self.test_set = self.load_syscall_dataset(train=False)

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

    def load_syscall_dataset(self, train=True):
        if train:
            return SYSCALL(
                partition_id=self.partition_id,
                partitions_number=self.partitions_number,
                root_dir=f"{sys.path[0]}/data",
                train=True,
            )
        else:
            return SYSCALL(
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

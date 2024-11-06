import os
import random
import sys
from string import punctuation

import pandas as pd
import torch
from datasets import load_dataset
from sklearn.model_selection import train_test_split
from torch.nn.functional import pad
from torchtext import vocab
from torchvision.datasets import MNIST

from nebula.core.datasets.nebuladataset import NebulaDataset


class SENTIMENT140(MNIST):
    def __init__(self, train=True):
        self.root = f"{sys.path[0]}/data"
        self.download = True
        self.train = train
        super(MNIST, self).__init__(self.root)
        self.training_file = f"{self.root}/sentiment140/processed/sentiment140_train.pt"
        self.test_file = f"{self.root}/sentiment140/processed/sentiment140_test.pt"

        if not os.path.exists(f"{self.root}/sentiment140/processed/sentiment140_test.pt") or not os.path.exists(
            f"{self.root}/sentiment140/processed/sentiment140_train.pt"
        ):
            if self.download:
                self.dataset_download()
            else:
                raise RuntimeError("Dataset not found, set parameter download=True to download")

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
        saved_path = f"{self.root}/sentiment140/processed/"
        if not os.path.exists(saved_path):
            os.makedirs(saved_path)
        dataset = load_dataset("sentiment140")
        indices = range(0, len(dataset["train"]))
        num_samp = 80000
        random_index = random.sample(indices, num_samp)
        dataset1 = dataset["train"][random_index]
        data_df = pd.DataFrame(dataset1)
        data_df["sentiment"] = data_df["sentiment"].replace(to_replace=4, value=1)
        vec = vocab.FastText()
        tokenlized_text_data = data_df["text"].apply(str.lower).apply(str.split)
        table = str.maketrans("", "", punctuation)
        tokenlized_text_data = tokenlized_text_data.apply(lambda x: [w.translate(table) for w in x])
        tokenlized_text_data = tokenlized_text_data.apply(vec.get_vecs_by_tokens).tolist()
        tokenlized_text_data = [pad(i, [0, 0, 0, 64 - i.shape[0]], "constant", 0) for i in tokenlized_text_data]
        tokenlized_text_data = torch.stack(tokenlized_text_data)
        text_label = torch.Tensor(data_df["sentiment"].tolist())
        X_train, X_test, y_train, y_test = train_test_split(
            tokenlized_text_data, text_label, test_size=0.15, random_state=False
        )
        train = [X_train, y_train]
        test = [X_test, y_test]
        train_file = f"{self.root}/sentiment140/processed/sentiment140_train.pt"
        test_file = f"{self.root}/sentiment140/processed/sentiment140_test.pt"
        if not os.path.exists(train_file):
            torch.save(train, train_file)
        if not os.path.exists(test_file):
            torch.save(test, test_file)


class Sentiment140Dataset(NebulaDataset):
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
        # Load sent14 train dataset
        if self.train_set is None:
            self.train_set = self.load_sent14_dataset(train=True)
        if self.test_set is None:
            self.test_set = self.load_sent14_dataset(train=False)

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
        print(f"Lenght of test indices map (global): {len(self.test_indices_map)}")
        print(f"Length of test indices map (local): {len(self.local_test_indices_map)}")

    def load_sent14_dataset(self, train=True):
        if train:
            return SENTIMENT140(train=True)
        return SENTIMENT140(train=False)

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

import glob
import json
import logging
import os

import numpy as np
import torch
from torch.utils.data import Dataset
from torchvision import transforms

from nebula.config.config import TRAINING_LOGGER
from nebula.core.datasets.nebuladataset import NebulaDataset

logging_training = logging.getLogger(TRAINING_LOGGER)


class RandomCrop:
    def __init__(self, size):
        if isinstance(size, int):
            self.size = (size, size)
        else:
            assert len(size) == 2
            self.size = size

    def __call__(self, sample):
        _input = sample

        if len(_input.shape) < 3:
            _input = np.expand_dims(_input, axis=2)

        h, w, _ = _input.shape
        oh, ow = self.size

        dh = h - oh
        dw = w - ow
        y = np.random.randint(0, dh) if dh > 0 else 0
        x = np.random.randint(0, dw) if dw > 0 else 0
        oh = oh if dh > 0 else h
        ow = ow if dw > 0 else w

        return _input[y : y + oh, x : x + ow, :]


class CenterCrop:
    def __init__(self, size):
        if isinstance(size, int):
            self.size = (size, size)
        else:
            assert len(size) == 2
            self.size = size

    def __call__(self, sample):
        _input = sample

        if len(_input.shape) < 3:
            _input = np.expand_dims(_input, axis=2)

        h, w, _ = _input.shape
        oh, ow = self.size
        y = (h - oh) // 2
        x = (w - ow) // 2

        return _input[y : y + oh, x : x + ow, :]


class MilitarySAR(Dataset):
    def __init__(self, name="soc", is_train=False, transform=None):
        self.is_train = is_train
        self.name = name

        self.data = []
        self.targets = []
        self.serial_numbers = []

        # Path to data is "data" folder in the same directory as this file
        self.path_to_data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

        self.transform = transform

        # self._load_data(self.path_to_data)

        mode = "train" if self.is_train else "test"
        self.image_list = glob.glob(os.path.join(self.path_to_data, f"{self.name}/{mode}/*/*.npy"))
        self.label_list = glob.glob(os.path.join(self.path_to_data, f"{self.name}/{mode}/*/*.json"))
        self.image_list = sorted(self.image_list, key=os.path.basename)
        self.label_list = sorted(self.label_list, key=os.path.basename)
        assert len(self.image_list) == len(self.label_list)

    def __len__(self):
        return len(self.targets)

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()

        _image = np.load(self.image_list[idx])
        with open(self.label_list[idx], encoding="utf-8") as f:
            label_info = json.load(f)
        _label = label_info["class_id"]
        # serial_number = label_info['serial_number']

        if self.transform:
            _image = self.transform(_image)

        return _image, _label

    def _load_metadata(self):
        self.targets = []
        self.serial_numbers = []
        for label_path in self.label_list:
            with open(label_path, encoding="utf-8") as f:
                label_info = json.load(f)
            self.targets.append(label_info["class_id"])
            self.serial_numbers.append(label_info["serial_number"])

    def get_targets(self):
        if not self.targets:
            logging_training.info(f"Loading Metadata for {self.__class__.__name__}")
            self._load_metadata()
        return self.targets

    # def _load_data(self, path):
    #     logging_training.info(f'Loading {self.__class__.__name__} dataset: {self.name} | is_train: {self.is_train} | from {self.path_to_data}')
    #     mode = 'train' if self.is_train else 'test'

    #     image_list = glob.glob(os.path.join(self.path_to_data, f'{self.name}/{mode}/*/*.npy'))
    #     label_list = glob.glob(os.path.join(self.path_to_data, f'{self.name}/{mode}/*/*.json'))
    #     image_list = sorted(image_list, key=os.path.basename)
    #     label_list = sorted(label_list, key=os.path.basename)

    #     for image_path, label_path in zip(image_list, label_list):
    #         self.data.append(np.load(image_path))

    #         with open(label_path, mode='r', encoding='utf-8') as f:
    #             _label = json.load(f)

    #         self.targets.append(_label['class_id'])
    #         self.serial_number.append(_label['serial_number'])

    #     self.data = np.array(self.data)
    #     self.targets = np.array(self.targets)


class MilitarySARDataset(NebulaDataset):
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
        if self.train_set is None:
            self.train_set = self.load_militarysar_dataset(train=True)
        if self.test_set is None:
            self.test_set = self.load_militarysar_dataset(train=False)

        train_targets = self.train_set.get_targets()
        test_targets = self.test_set.get_targets()

        self.test_indices_map = list(range(len(self.test_set)))

        # Depending on the iid flag, generate a non-iid or iid map of the train set
        if self.iid:
            logging_training.info("Generating IID partition - Train")
            self.train_indices_map = self.generate_iid_map(self.train_set, self.partition, self.partition_parameter)
            logging_training.info("Generating IID partition - Test")
            self.local_test_indices_map = self.generate_iid_map(self.test_set, self.partition, self.partition_parameter)
        else:
            logging_training.info("Generating Non-IID partition - Train")
            self.train_indices_map = self.generate_non_iid_map(self.train_set, self.partition, self.partition_parameter)
            logging_training.info("Generating Non-IID partition - Test")
            self.local_test_indices_map = self.generate_non_iid_map(
                self.test_set, self.partition, self.partition_parameter
            )

        print(f"Length of train indices map: {len(self.train_indices_map)}")
        print(f"Lenght of test indices map (global): {len(self.test_indices_map)}")
        print(f"Length of test indices map (local): {len(self.local_test_indices_map)}")

    def load_militarysar_dataset(self, train=True):
        apply_transforms = [CenterCrop(88), transforms.ToTensor()]
        if train:
            apply_transforms = [RandomCrop(88), transforms.ToTensor()]

        return MilitarySAR(name="soc", is_train=train, transform=transforms.Compose(apply_transforms))

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

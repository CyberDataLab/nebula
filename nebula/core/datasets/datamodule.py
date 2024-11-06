import logging

import torch
from lightning import LightningDataModule
from torch.utils.data import DataLoader, RandomSampler, random_split

from nebula.config.config import TRAINING_LOGGER
from nebula.core.datasets.changeablesubset import ChangeableSubset

logging_training = logging.getLogger(TRAINING_LOGGER)


class DataModule(LightningDataModule):
    def __init__(
        self,
        train_set,
        train_set_indices,
        test_set,
        test_set_indices,
        local_test_set_indices,
        partition_id=0,
        partitions_number=1,
        batch_size=32,
        num_workers=0,
        val_percent=0.1,
        label_flipping=False,
        data_poisoning=False,
        poisoned_percent=0,
        poisoned_ratio=0,
        targeted=False,
        target_label=0,
        target_changed_label=0,
        noise_type="salt",
        seed=42,
    ):
        super().__init__()
        self.train_set = train_set
        self.train_set_indices = train_set_indices
        self.test_set = test_set
        self.test_set_indices = test_set_indices
        self.local_test_set_indices = local_test_set_indices
        self.partition_id = partition_id
        self.partitions_number = partitions_number
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.val_percent = val_percent
        self.label_flipping = label_flipping
        self.data_poisoning = data_poisoning
        self.poisoned_percent = poisoned_percent
        self.poisoned_ratio = poisoned_ratio
        self.targeted = targeted
        self.target_label = target_label
        self.target_changed_label = target_changed_label
        self.noise_type = noise_type
        self.seed = seed

        self.model_weight = None

        self.val_indices = None
        # Split train and validation datasets
        self.data_train = None
        self.data_val = None
        self.global_te_subset = None
        self.local_te_subset = None

    def setup(self, stage=None):
        if stage in (None, "fit"):
            tr_subset = ChangeableSubset(
                self.train_set,
                self.train_set_indices,
                label_flipping=self.label_flipping,
                data_poisoning=self.data_poisoning,
                poisoned_percent=self.poisoned_percent,
                poisoned_ratio=self.poisoned_ratio,
                targeted=self.targeted,
                target_label=self.target_label,
                target_changed_label=self.target_changed_label,
                noise_type=self.noise_type,
            )

            if self.val_indices is None:
                generator = torch.Generator()
                generator.manual_seed(self.seed)

                train_size = round(len(tr_subset) * (1 - self.val_percent))
                val_size = len(tr_subset) - train_size

                self.data_train, self.data_val = random_split(tr_subset, [train_size, val_size], generator=generator)

                self.val_indices = self.data_val.indices

            else:
                train_indices = list(set(range(len(tr_subset))) - set(self.val_indices))
                val_indices = self.val_indices

                self.data_train = ChangeableSubset(tr_subset, train_indices)
                self.data_val = ChangeableSubset(tr_subset, val_indices)

            self.model_weight = len(self.data_train)

        if stage in (None, "test"):
            # Test sets
            self.global_te_subset = ChangeableSubset(self.test_set, self.test_set_indices)
            self.local_te_subset = ChangeableSubset(self.test_set, self.local_test_set_indices)

            if len(self.test_set) < self.partitions_number:
                raise ValueError("Too many partitions for the size of the test set.")

    def teardown(self, stage=None):
        # Teardown the datasets
        if stage in (None, "fit"):
            self.data_train = None
            self.data_val = None

        if stage in (None, "test"):
            self.global_te_subset = None
            self.local_te_subset = None

    def train_dataloader(self):
        if self.data_train is None:
            raise ValueError(
                "Train dataset not initialized. Please call setup('fit') before requesting train_dataloader."
            )
        logging_training.info(f"Train set size: {len(self.data_train)}")
        return DataLoader(
            self.data_train,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.num_workers,
            drop_last=True,
            pin_memory=False,
        )

    def val_dataloader(self):
        if self.data_val is None:
            raise ValueError(
                "Validation dataset not initialized. Please call setup('fit') before requesting val_dataloader."
            )
        logging_training.info(f"Validation set size: {len(self.data_val)}")
        return DataLoader(
            self.data_val,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
            drop_last=True,
            pin_memory=False,
        )

    def test_dataloader(self):
        if self.local_te_subset is None or self.global_te_subset is None:
            raise ValueError(
                "Test datasets not initialized. Please call setup('test') before requesting test_dataloader."
            )
        logging_training.info(f"Local test set size: {len(self.local_te_subset)}")
        logging_training.info(f"Global test set size: {len(self.global_te_subset)}")
        return [
            DataLoader(
                self.local_te_subset,
                batch_size=self.batch_size,
                shuffle=False,
                num_workers=self.num_workers,
                drop_last=True,
                pin_memory=False,
            ),
            DataLoader(
                self.global_te_subset,
                batch_size=self.batch_size,
                shuffle=False,
                num_workers=self.num_workers,
                drop_last=True,
                pin_memory=False,
            ),
        ]

    def bootstrap_dataloader(self):
        if self.data_val is None:
            raise ValueError(
                "Validation dataset not initialized. Please call setup('fit') before requesting bootstrap_dataloader."
            )
        random_sampler = RandomSampler(
            data_source=self.data_val,
            replacement=False,
            num_samples=max(int(len(self.data_val) / 3), 300),
        )
        logging_training.info(f"Bootstrap samples: {len(random_sampler)}")
        return DataLoader(
            self.data_train,
            batch_size=self.batch_size,
            shuffle=False,
            sampler=random_sampler,
            num_workers=self.num_workers,
            drop_last=True,
            pin_memory=False,
        )

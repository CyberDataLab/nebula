"""
This module provides classes for label flipping attacks in datasets, allowing for the simulation of label noise
as a form of data poisoning. It implements both targeted and non-targeted label flipping attacks.

Classes:
- LabelFlippingAttack: Main attack class that implements the DatasetAttack interface
- LabelFlippingStrategy: Abstract base class for label flipping strategies
- TargetedLabelFlippingStrategy: Implementation for targeted label flipping
- NonTargetedLabelFlippingStrategy: Implementation for non-targeted label flipping
"""

import copy
import logging
import random
from abc import ABC, abstractmethod
from typing import Dict, TYPE_CHECKING

import numpy as np

from nebula.addons.attacks.dataset.datasetattack import DatasetAttack

if TYPE_CHECKING:
    from torch.utils.data import Dataset


class LabelFlippingStrategy(ABC):
    """Abstract base class for label flipping strategies."""

    @abstractmethod
    def flip_labels(
        self,
        dataset,
        indices: list[int],
        poisoned_percent: float,
    ) -> "Dataset":
        """
        Abstract method to flip labels in the dataset.

        Args:
            dataset: The dataset to modify
            indices: List of indices to consider for flipping
            poisoned_percent: Percentage of labels to change (0-100)

        Returns:
            Modified dataset with flipped labels
        """
        pass


class TargetedLabelFlippingStrategy(LabelFlippingStrategy):
    """Implementation of targeted label flipping strategy."""

    def __init__(self, target_label: int, target_changed_label: int):
        """
        Initialize targeted label flipping strategy.

        Args:
            target_label: The label to change
            target_changed_label: The label to change to
        """
        self.target_label = target_label
        self.target_changed_label = target_changed_label

    def flip_labels(
        self,
        dataset,
        indices: list[int],
        poisoned_percent: float,
    ) -> "Dataset":
        """
        Flips labels from target_label to target_changed_label.

        Args:
            dataset: The dataset to modify
            indices: List of indices to consider for flipping
            poisoned_percent: Percentage of labels to change (0-100)

        Returns:
            Modified dataset with flipped labels
        """
        new_dataset = copy.deepcopy(dataset)
        if not isinstance(new_dataset.targets, np.ndarray):
            new_dataset.targets = np.array(new_dataset.targets)
        else:
            new_dataset.targets = new_dataset.targets.copy()

        for i in indices:
            if int(new_dataset.targets[i]) == self.target_label:
                new_dataset.targets[i] = self.target_changed_label

        if self.target_label in new_dataset.targets:
            logging.info(f"[{self.__class__.__name__}] Target label {self.target_label} still present after flipping.")
        else:
            logging.info(
                f"[{self.__class__.__name__}] Target label {self.target_label} successfully flipped to {self.target_changed_label}."
            )

        return new_dataset


class NonTargetedLabelFlippingStrategy(LabelFlippingStrategy):
    """Implementation of non-targeted label flipping strategy."""

    def flip_labels(
        self,
        dataset,
        indices: list[int],
        poisoned_percent: float,
    ) -> "Dataset":
        """
        Flips labels randomly to different classes.

        Args:
            dataset: The dataset to modify
            indices: List of indices to consider for flipping
            poisoned_percent: Percentage of labels to change (0-100)

        Returns:
            Modified dataset with flipped labels
        """
        new_dataset = copy.deepcopy(dataset)
        if not isinstance(new_dataset.targets, np.ndarray):
            new_dataset.targets = np.array(new_dataset.targets)
        else:
            new_dataset.targets = new_dataset.targets.copy()

        num_indices = len(indices)
        num_flipped = int(poisoned_percent * num_indices / 100.0)

        if num_indices == 0 or num_flipped > num_indices:
            return new_dataset

        flipped_indices = random.sample(indices, num_flipped)
        class_list = list(set(new_dataset.targets.tolist()))

        for i in flipped_indices:
            current_label = new_dataset.targets[i]
            new_label = random.choice(class_list)
            while new_label == current_label:
                new_label = random.choice(class_list)
            new_dataset.targets[i] = new_label

        return new_dataset


class LabelFlippingAttack(DatasetAttack):
    """
    Implements a label flipping attack that can be either targeted or non-targeted.
    """

    def __init__(self, engine, attack_params: Dict):
        """
        Initialize the label flipping attack.

        Args:
            engine: The engine managing the attack context
            attack_params: Dictionary containing attack parameters
        """
        try:
            round_start = int(attack_params["round_start_attack"])
            round_stop = int(attack_params["round_stop_attack"])
            attack_interval = int(attack_params["attack_interval"])
        except KeyError as e:
            raise ValueError(f"Missing required attack parameter: {e}")
        except ValueError:
            raise ValueError("Invalid value in attack_params. Ensure all values are integers.")

        super().__init__(engine, round_start, round_stop, attack_interval)
        self.datamodule = engine._trainer.datamodule
        self.poisoned_percent = float(attack_params["poisoned_sample_percent"])

        # Create the appropriate strategy based on whether the attack is targeted
        if attack_params.get("targeted", False):
            target_label = int(attack_params.get("target_label") or attack_params.get("targetLabel", 4))
            target_changed_label = int(
                attack_params.get("target_changed_label") or attack_params.get("targetChangedLabel", 7)
            )
            self.strategy = TargetedLabelFlippingStrategy(target_label, target_changed_label)
        else:
            self.strategy = NonTargetedLabelFlippingStrategy()

    def get_malicious_dataset(self):
        """
        Creates a malicious dataset by flipping the labels of selected data points.

        Returns:
            Dataset: The modified dataset with flipped labels
        """
        return self.strategy.flip_labels(
            self.datamodule.train_set,
            self.datamodule.train_set_indices,
            self.poisoned_percent,
        )

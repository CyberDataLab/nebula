"""
This module provides a function for label flipping in datasets, allowing for the simulation of label noise
as a form of data poisoning. The main function modifies the labels of specific samples in a dataset based
on a specified percentage and target conditions.

Function:
- labelFlipping: Flips the labels of a specified portion of a dataset to random values or to a specific target label.
"""

import copy
import logging
import random

import numpy as np

from nebula.addons.attacks.dataset.datasetattack import DatasetAttack


class LabelFlippingAttack(DatasetAttack):
    """
    Implements an attack that flips the labels of a portion of the training dataset.

    This attack alters the labels of certain data points in the training set to
    mislead the training process.
    """

    def __init__(self, engine, attack_params):
        """
        Initializes the LabelFlippingAttack with the engine and attack parameters.

        Args:
            engine: The engine managing the attack context.
            attack_params (dict): Parameters for the attack, including the percentage of
                                  poisoned data, targeting options, and label specifications.
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
        self.poisoned_percent = float(attack_params["poisoned_percent"])
        self.targeted = attack_params["targeted"]
        self.target_label = int(attack_params["target_label"])
        self.target_changed_label = int(attack_params["target_changed_label"])

    def labelFlipping(
        self,
        dataset,
        indices,
        poisoned_percent=0,
        targeted=False,
        target_label=4,
        target_changed_label=7,
    ):
        """
        Flips the labels of a specified portion of a dataset to random values or to a specific target label.

        This function modifies the labels of selected samples in the dataset based on the specified
        poisoning percentage. Labels can be flipped either randomly or targeted to change from a specific
        label to another specified label.

        Args:
            dataset (Dataset): The dataset containing training data, expected to be a PyTorch dataset
                               with a `.targets` attribute.
            indices (list of int): The list of indices in the dataset to consider for label flipping.
            poisoned_percent (float, optional): The ratio of labels to change, expressed as a fraction
                                                (0 <= poisoned_percent <= 1). Default is 0.
            targeted (bool, optional): If True, flips only labels matching `target_label` to `target_changed_label`.
                                       Default is False.
            target_label (int, optional): The label to change when `targeted` is True. Default is 4.
            target_changed_label (int, optional): The label to which `target_label` will be changed. Default is 7.

        Returns:
            Dataset: A deep copy of the original dataset with modified labels in `.targets`.

        Raises:
            ValueError: If `poisoned_percent` is not between 0 and 1, or if `flipping_percent` is invalid.

        Notes:
            - When not in targeted mode, labels are flipped for a random selection of indices based on the specified
              `poisoned_percent`. The new label is chosen randomly from the existing classes.
            - In targeted mode, labels that match `target_label` are directly changed to `target_changed_label`.
        """
        new_dataset = copy.deepcopy(dataset)
        if not isinstance(new_dataset.targets, np.ndarray):
            new_dataset.targets = np.array(new_dataset.targets)
        else:
            new_dataset.targets = new_dataset.targets.copy()

        # logging.info(f"[{self.__class__.__name__}] First 20 labels before flipping: {new_dataset.targets[:20]}")
        # logging.info(f"[{self.__class__.__name__}] First 20 indices before flipping: {indices[:20]}")

        if not targeted:
            num_indices = len(indices)
            num_flipped = int(poisoned_percent * num_indices)
            if num_indices == 0 or num_flipped > num_indices:
                return
            flipped_indices = random.sample(indices, num_flipped)
            class_list = list(set(new_dataset.targets.tolist()))
            for i in flipped_indices:
                current_label = new_dataset.targets[i]
                new_label = random.choice(class_list)
                while new_label == current_label:
                    new_label = random.choice(class_list)
                new_dataset.targets[i] = new_label
        else:
            for i in indices:
                if int(new_dataset.targets[i]) == target_label:
                    new_dataset.targets[i] = target_changed_label

            if target_label in new_dataset.targets:
                logging.info(f"[{self.__class__.__name__}] Target label {target_label} still present after flipping.")
            else:
                logging.info(
                    f"[{self.__class__.__name__}] Target label {target_label} successfully flipped to {target_changed_label}."
                )

        # logging.info(f"[{self.__class__.__name__}] First 20 labels after flipping: {new_dataset.targets[:20]}")

        return new_dataset

    def get_malicious_dataset(self):
        """
        Creates a malicious dataset by flipping the labels of selected data points.

        Returns:
            Dataset: The modified dataset with flipped labels.
        """
        return self.labelFlipping(
            self.datamodule.train_set,
            self.datamodule.train_set_indices,
            self.poisoned_percent,
            self.targeted,
            self.target_label,
            self.target_changed_label,
        )

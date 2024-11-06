"""
This module provides a function for label flipping in datasets, allowing for the simulation of label noise
as a form of data poisoning. The main function modifies the labels of specific samples in a dataset based
on a specified percentage and target conditions.

Function:
- labelFlipping: Flips the labels of a specified portion of a dataset to random values or to a specific target label.
"""

import copy
import random

import torch


def labelFlipping(
    dataset,
    indices,
    poisoned_persent=0,
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
    targets = new_dataset.targets.detach().clone()
    num_indices = len(indices)
    # classes = new_dataset.classes
    # class_to_idx = new_dataset.class_to_idx
    # class_list = [class_to_idx[i] for i in classes]
    class_list = set(targets.tolist())
    if not targeted:
        num_flipped = int(poisoned_persent * num_indices)
        if num_indices == 0:
            return new_dataset
        if num_flipped > num_indices:
            return new_dataset
        flipped_indice = random.sample(indices, num_flipped)

        for i in flipped_indice:
            t = targets[i]
            flipped = torch.tensor(random.sample(class_list, 1)[0])
            while t == flipped:
                flipped = torch.tensor(random.sample(class_list, 1)[0])
            targets[i] = flipped
    else:
        for i in indices:
            if int(targets[i]) == int(target_label):
                targets[i] = torch.tensor(target_changed_label)
    new_dataset.targets = targets
    return new_dataset

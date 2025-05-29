"""
This module contains functions for applying data poisoning techniques,
including the application of noise to tensors and modification of datasets
to simulate poisoning attacks.

Functions:
- apply_noise: Applies noise to a tensor based on the specified noise type and poisoning ratio.
- datapoison: Adds noise to a specified portion of a dataset for data poisoning purposes.
- add_x_to_image: Adds an 'X' mark to the top-left corner of an image.
- poison_to_nlp_rawdata: Poisons NLP data by setting word vectors to zero with a given probability.
"""

import copy
import logging
import random

import numpy as np
import torch
from skimage.util import random_noise

from nebula.addons.attacks.dataset.datasetattack import DatasetAttack


class SamplePoisoningAttack(DatasetAttack):
    """
    Implements a data poisoning attack on a training dataset.

    This attack introduces noise or modifies specific data points to influence
    the behavior of a machine learning model.

    Args:
        engine (object): The training engine object, including the associated
                         datamodule.
        attack_params (dict): Attack parameters including:
            - poisoned_sample_percent (float): The percentage of data points to be poisoned (0-100).
            - poisoned_noise_percent (float): The percentage of noise to be added to poisoned data (0-100).
            - targeted (bool): Whether the attack is targeted at a specific label.
            - target_label/targetLabel (int): The target label for the attack (used if targeted is True).
            - noise_type/noiseType (str): The type of noise to introduce during the attack.
    """

    def __init__(self, engine, attack_params):
        """
        Initializes the SamplePoisoningAttack with the specified engine and parameters.

        Args:
            engine (object): The training engine object.
            attack_params (dict): Dictionary of attack parameters.
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
        self.poisoned_noise_percent = float(attack_params["poisoned_noise_percent"])
        self.targeted = attack_params["targeted"]
        
        # Handle both camelCase and snake_case parameter names
        self.target_label = int(attack_params.get("target_label") or attack_params.get("targetLabel", 4))
        self.noise_type = (attack_params.get("noise_type") or attack_params.get("noiseType", "Gaussian")).lower()

    def apply_noise(self, t, noise_type, poisoned_noise_percent):
        """
        Applies noise to a tensor based on the specified noise type and poisoning percentage.

        Args:
            t (torch.Tensor): The input tensor to which noise will be applied.
            noise_type (str): The type of noise to apply. Supported types are:
                - "salt": Salt noise (binary salt-and-pepper noise with only 'salt').
                - "gaussian": Gaussian noise with mean 0 and specified variance.
                - "s&p": Salt-and-pepper noise.
                - "nlp_rawdata": Applies a custom NLP raw data poisoning function.
            poisoned_noise_percent (float): The percentage of noise to be applied (0-100).

        Returns:
            torch.Tensor: The tensor with noise applied. If the noise type is not supported,
                          returns the original tensor with an error message printed.

        Raises:
            ValueError: If the specified noise_type is not supported.

        Notes:
           - The "nlp_rawdata" noise type requires the custom `poison_to_nlp_rawdata` function.
           - Noise for types "salt", "gaussian", and "s&p" is generated using `random_noise` from
             the `skimage.util` package, and returned as a `torch.Tensor`.
        """
        arr = t.detach().cpu().numpy() if isinstance(t, torch.Tensor) else np.array(t)
        
        # Convert percentage to ratio for noise application
        poisoned_ratio = poisoned_noise_percent / 100.0

        if noise_type == "salt":
            return torch.tensor(random_noise(arr, mode=noise_type, amount=poisoned_ratio))
        elif noise_type == "gaussian":
            return torch.tensor(random_noise(arr, mode=noise_type, mean=0, var=poisoned_ratio, clip=True))
        elif noise_type == "s&p":
            return torch.tensor(random_noise(arr, mode=noise_type, amount=poisoned_ratio))
        elif noise_type == "nlp_rawdata":
            return self.poison_to_nlp_rawdata(arr, poisoned_ratio)
        else:
            logging.info(f"ERROR: noise_type '{noise_type}' not supported in data poison attack.")
            return t

    def datapoison(
        self,
        dataset,
        indices,
        poisoned_percent,
        poisoned_noise_percent,
        targeted=False,
        target_label=3,
        noise_type="salt",
    ):
        """
        Adds noise to a specified portion of a dataset for data poisoning purposes.

        This function applies noise to randomly selected samples within a dataset.
        Noise can be targeted or non-targeted. In non-targeted poisoning, random samples
        are chosen and altered using the specified noise type and percentage. In targeted poisoning,
        only samples with a specified label are altered by adding an 'X' pattern.

        Args:
            dataset (Dataset): The dataset to poison, expected to have `.data` and `.targets` attributes.
            indices (list of int): The list of indices in the dataset to consider for poisoning.
            poisoned_percent (float): The percentage of `indices` to poison (0-100).
            poisoned_noise_percent (float): The percentage of noise to apply to poisoned samples (0-100).
            targeted (bool, optional): If True, applies targeted poisoning by adding an 'X' only to samples with `target_label`.
                                       Default is False.
            target_label (int, optional): The label to target when `targeted` is True. Default is 3.
            noise_type (str, optional): The type of noise to apply in non-targeted poisoning. Supported types are:
                                        - "salt": Applies salt noise.
                                        - "gaussian": Applies Gaussian noise.
                                        - "s&p": Applies salt-and-pepper noise.
                                        Default is "salt".

        Returns:
            Dataset: A deep copy of the original dataset with poisoned data in `.data`.

        Raises:
            ValueError: If `poisoned_percent` or `poisoned_noise_percent` is not between 0 and 100, or if `noise_type` is unsupported.

        Notes:
            - Non-targeted poisoning randomly selects samples from `indices` based on `poisoned_percent`.
            - Targeted poisoning modifies only samples with `target_label` by adding an 'X' pattern, regardless of `poisoned_noise_percent`.
        """
        new_dataset = copy.deepcopy(dataset)
        if not isinstance(new_dataset.targets, np.ndarray):
            new_dataset.targets = np.array(new_dataset.targets)
        else:
            new_dataset.targets = new_dataset.targets.copy()

        num_indices = len(indices)
        if not isinstance(noise_type, str):
            noise_type = noise_type[0]

        if not targeted:
            num_poisoned = int(poisoned_percent * num_indices / 100.0)  # Convert percentage to count
            if num_indices == 0:
                return new_dataset
            if num_poisoned > num_indices:
                return new_dataset
            poisoned_indice = random.sample(indices, num_poisoned)
            logging.info(f"Number of poisoned samples: {num_poisoned}")

            for i in poisoned_indice:
                t = new_dataset.data[i]
                if isinstance(t, tuple):
                    t = t[0]
                poisoned = self.apply_noise(t, noise_type, poisoned_noise_percent)
                if isinstance(t, tuple):
                    poisoned = (poisoned, t[1])
                if isinstance(poisoned, torch.Tensor):
                    poisoned = poisoned.detach().clone()
                if len(poisoned.shape) == 0:
                    poisoned = poisoned.view(-1)
                new_dataset.data[i] = poisoned
        else:
            for i in indices:
                if int(new_dataset.targets[i]) == int(target_label):
                    t = new_dataset.data[i]
                    if isinstance(t, tuple):
                        t = t[0]
                    if isinstance(t, torch.Tensor):
                        t = t.detach().clone()
                    if len(t.shape) == 0:
                        t = t.view(-1)
                    poisoned = self.add_x_to_image(t)
                    if isinstance(t, tuple):
                        poisoned = (poisoned, t[1])
                    new_dataset.data[i] = poisoned
        return new_dataset

    def add_x_to_image(self, img):
        """
        Adds a 10x10 pixel 'X' mark to the top-left corner of an image.

        This function modifies the input image by setting specific pixels in the
        top-left 10x10 region to a high intensity value, forming an 'X' shape.
        Pixels on or below the main diagonal and above the secondary diagonal
        are set to 255 (white).

        Args:
            img (array-like): A 2D array or image tensor representing pixel values.
                              It is expected to be in grayscale, where each pixel
                              has a single intensity value.

        Returns:
            torch.Tensor: A tensor representation of the modified image with the 'X' mark.
        """
        for i in range(0, 10):
            for j in range(0, 10):
                if i + j <= 9 or i == j:
                    img[i][j] = 255
        return torch.tensor(img)

    def poison_to_nlp_rawdata(self, text_data, poisoned_ratio):
        """
        Poisons NLP data by setting word vectors to zero with a given probability.

        This function randomly selects a portion of non-zero word vectors in the
        input text data and sets them to zero vectors based on the specified
        poisoning ratio. This simulates a form of data corruption by partially
        nullifying the information in the input data.

        Args:
            text_data (list of torch.Tensor): A list where each entry is a tensor
                representing a word vector. Non-zero vectors are assumed to represent valid words.
            poisoned_ratio (float): The fraction of non-zero word vectors to set to zero,
                where 0 <= poisoned_ratio <= 1.

        Returns:
            list of torch.Tensor: The modified text data with some word vectors set to zero.

        Raises:
            ValueError: If `poisoned_ratio` is greater than 1 or less than 0.

        Notes:
            - `poisoned_ratio` controls the percentage of non-zero vectors to poison.
            - If `num_poisoned_token` is zero or exceeds the number of non-zero vectors,
              the function returns the original `text_data` without modification.
        """
        non_zero_vector_indice = [i for i in range(0, len(text_data)) if text_data[i][0] != 0]
        non_zero_vector_len = len(non_zero_vector_indice)

        num_poisoned_token = int(poisoned_ratio * non_zero_vector_len)
        if num_poisoned_token == 0:
            return text_data
        if num_poisoned_token > non_zero_vector_len:
            return text_data

        poisoned_token_indice = random.sample(non_zero_vector_indice, num_poisoned_token)
        zero_vector = torch.Tensor(np.zeros(len(text_data[0][0])))
        for i in poisoned_token_indice:
            text_data[i] = zero_vector
        return text_data

    def get_malicious_dataset(self):
        """
        Generates a poisoned dataset based on the specified parameters.

        Returns:
            Dataset: A modified version of the training dataset with poisoned data.
        """
        return self.datapoison(
            self.datamodule.train_set,
            self.datamodule.train_set_indices,
            self.poisoned_percent,
            self.poisoned_noise_percent,
            self.targeted,
            self.target_label,
            self.noise_type,
        )

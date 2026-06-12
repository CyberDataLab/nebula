"""
This module provides classes for data poisoning attacks in datasets, allowing for the simulation of
data poisoning by adding noise or modifying specific data points.

Classes:
- SamplePoisoningAttack: Main attack class that implements the DatasetAttack interface
- DataPoisoningStrategy: Abstract base class for poisoning strategies
- TargetedSamplePoisoningStrategy: Implementation for targeted poisoning (X pattern)
- NonTargetedSamplePoisoningStrategy: Implementation for non-targeted poisoning (noise-based)
"""

import copy
import logging
import random
from abc import ABC, abstractmethod
from typing import Dict, TYPE_CHECKING

import numpy as np
import torch
from PIL import Image
from skimage.util import random_noise

from nebula.addons.attacks.dataset.datasetattack import DatasetAttack

if TYPE_CHECKING:
    from torch.utils.data import Dataset


class DataPoisoningStrategy(ABC):
    """Abstract base class for poisoning strategies."""

    @abstractmethod
    def poison_data(
        self,
        dataset,
        indices: list[int],
        poisoned_percent: float,
        poisoned_noise_percent: float,
    ) -> "Dataset":
        """
        Abstract method to poison data in the dataset.

        Args:
            dataset: The dataset to modify
            indices: List of indices to consider for poisoning
            poisoned_percent: Percentage of data to poison (0-100)
            poisoned_noise_percent: Percentage of noise to apply (0-100)

        Returns:
            Modified dataset with poisoned data
        """
        pass

    def _convert_to_tensor(self, data: torch.Tensor | Image.Image | tuple) -> torch.Tensor:
        """
        Convert input data to tensor format.

        Args:
            data: Input data that can be a tensor, PIL Image, or tuple

        Returns:
            Tensor representation of the input data
        """
        if isinstance(data, tuple):
            data = data[0]

        if isinstance(data, Image.Image):
            return torch.tensor(np.array(data))
        elif isinstance(data, torch.Tensor):
            return data
        else:
            return torch.tensor(data)

    def _restore_data_format(self, data, original):
        if isinstance(data, torch.Tensor):
            array_data = data.detach().cpu().numpy()
        else:
            array_data = np.asarray(data)

        original_shape = None
        if isinstance(original, torch.Tensor):
            original_shape = tuple(original.shape)
        elif isinstance(original, Image.Image):
            original_shape = np.array(original).shape
        elif hasattr(original, "shape"):
            original_shape = tuple(original.shape)

        if original_shape is not None and array_data.shape != original_shape and array_data.size == np.prod(original_shape):
            array_data = array_data.reshape(original_shape)

        if isinstance(original, torch.Tensor):
            restored = torch.as_tensor(array_data, device=original.device)
            if original.dtype.is_floating_point:
                original_max = original.detach().max() if original.numel() > 0 else torch.tensor(1.0, device=original.device)
                if restored.numel() > 0 and original_max > 1 and restored.min() >= 0 and restored.max() <= 1:
                    restored = restored * original_max
                return restored.to(dtype=original.dtype)

            if restored.numel() > 0 and restored.min() >= 0 and restored.max() <= 1:
                restored = restored * torch.iinfo(original.dtype).max
            return restored.clamp(torch.iinfo(original.dtype).min, torch.iinfo(original.dtype).max).to(dtype=original.dtype)

        if isinstance(original, Image.Image):
            original_array = np.array(original)
            restored = self._restore_array_dtype(array_data, original_array.dtype, original_array)
            return Image.fromarray(restored, mode=original.mode)

        if isinstance(original, np.ndarray):
            return self._restore_array_dtype(array_data, original.dtype, original)

        return data

    def _restore_array_dtype(self, data: np.ndarray, dtype: np.dtype, original: np.ndarray | None = None) -> np.ndarray:
        dtype = np.dtype(dtype)
        if np.issubdtype(dtype, np.integer):
            if data.size > 0 and data.min() >= 0 and data.max() <= 1:
                data = data * np.iinfo(dtype).max
            return np.rint(np.clip(data, np.iinfo(dtype).min, np.iinfo(dtype).max)).astype(dtype)

        if original is not None and data.size > 0 and original.size > 0:
            original_max = np.max(original)
            if original_max > 1 and data.min() >= 0 and data.max() <= 1:
                data = data * original_max

        return data.astype(dtype)

    def _handle_single_point(self, tensor: torch.Tensor) -> tuple[torch.Tensor, bool]:
        """
        Handle single point tensors by reshaping them.

        Args:
            tensor: Input tensor

        Returns:
            Tuple of (reshaped tensor, is_single_point flag)
        """
        is_single_point = False
        if len(tensor.shape) == 0:
            tensor = tensor.view(-1)
            is_single_point = True
        return tensor, is_single_point


class NonTargetedSamplePoisoningStrategy(DataPoisoningStrategy):
    """Implementation of non-targeted poisoning strategy using noise."""

    def __init__(self, noise_type: str):
        """
        Initialize non-targeted poisoning strategy.

        Args:
            noise_type: Type of noise to apply (salt, gaussian, s&p, nlp_rawdata)
        """
        self.noise_type = noise_type.lower()

    def apply_noise(self, t: torch.Tensor | Image.Image, poisoned_noise_percent: float):
        """
        Applies noise to a tensor based on the specified noise type and poisoning percentage.

        Args:
            t: The input tensor or PIL Image to which noise will be applied
            poisoned_noise_percent: The percentage of noise to be applied (0-100)

        Returns:
            The poisoned data in the same format as the input
        """
        original = t[0] if isinstance(t, tuple) else t
        t = self._convert_to_tensor(original)
        t, is_single_point = self._handle_single_point(t)

        arr = t.detach().cpu().numpy()
        poisoned_ratio = poisoned_noise_percent / 100.0

        logging.info(
            f"[{self.__class__.__name__}] Applying noise to data with noise type: {self.noise_type} and amount: {poisoned_ratio} (float)"
        )

        if self.noise_type == "salt":
            poisoned = random_noise(arr, mode=self.noise_type, amount=poisoned_ratio)
        elif self.noise_type == "gaussian":
            poisoned = random_noise(arr, mode=self.noise_type, mean=0, var=poisoned_ratio, clip=True)
        elif self.noise_type == "s&p":
            poisoned = random_noise(arr, mode=self.noise_type, amount=poisoned_ratio)
        elif self.noise_type == "nlp_rawdata":
            poisoned = self.poison_to_nlp_rawdata(arr, poisoned_ratio)
        else:
            logging.info(f"ERROR: noise_type '{self.noise_type}' not supported in data poison attack.")
            return original

        if is_single_point:
            poisoned = poisoned[0]

        return self._restore_data_format(poisoned, original)

    def poison_to_nlp_rawdata(self, text_data: list, poisoned_ratio: float) -> list:
        """
        Poisons NLP data by setting word vectors to zero with a given probability.

        Args:
            text_data: List of word vectors
            poisoned_ratio: Fraction of non-zero vectors to set to zero

        Returns:
            Modified text data with some word vectors set to zero
        """
        non_zero_vector_indice = [i for i in range(0, len(text_data)) if text_data[i][0] != 0]
        non_zero_vector_len = len(non_zero_vector_indice)

        num_poisoned_token = int(poisoned_ratio * non_zero_vector_len)
        if num_poisoned_token == 0 or num_poisoned_token > non_zero_vector_len:
            return text_data

        poisoned_token_indice = random.sample(non_zero_vector_indice, num_poisoned_token)
        zero_vector = torch.Tensor(np.zeros(len(text_data[0][0])))
        for i in poisoned_token_indice:
            text_data[i] = zero_vector
        return text_data

    def poison_data(
        self,
        dataset,
        indices: list[int],
        poisoned_percent: float,
        poisoned_noise_percent: float,
    ) -> "Dataset":
        """
        Applies noise-based poisoning to the dataset.

        Args:
            dataset: The dataset to modify
            indices: List of indices to consider for poisoning
            poisoned_percent: Percentage of data to poison (0-100)
            poisoned_noise_percent: Percentage of noise to apply (0-100)

        Returns:
            Modified dataset with poisoned data
        """
        logging.info(f"[{self.__class__.__name__}] Poisoning data with noise type: {self.noise_type}")
        new_dataset = copy.deepcopy(dataset)
        if not isinstance(new_dataset.targets, np.ndarray):
            new_dataset.targets = np.array(new_dataset.targets)
        else:
            new_dataset.targets = new_dataset.targets.copy()

        num_indices = len(indices)
        num_poisoned = int(poisoned_percent * num_indices / 100.0)

        if num_indices == 0 or num_poisoned > num_indices:
            return new_dataset

        poisoned_indices = random.sample(indices, num_poisoned)
        logging.info(f"Number of poisoned samples: {num_poisoned}")

        for i in poisoned_indices:
            t = new_dataset.data[i]
            poisoned = self.apply_noise(t, poisoned_noise_percent)

            if isinstance(t, tuple):
                poisoned = (poisoned, t[1])

            new_dataset.data[i] = poisoned

        return new_dataset


class TargetedSamplePoisoningStrategy(DataPoisoningStrategy):
    """Implementation of targeted poisoning strategy using X pattern."""

    def __init__(self, target_label: int):
        """
        Initialize targeted poisoning strategy.

        Args:
            target_label: The label to target for poisoning
        """
        self.target_label = target_label

    def add_x_to_image(self, img: torch.Tensor | Image.Image):
        """
        Adds a 10x10 pixel 'X' mark to the top-left corner of an image.

        Args:
            img: Input image tensor or PIL Image

        Returns:
            Modified image in the same format as the input
        """
        logging.info(f"[{self.__class__.__name__}] Adding X pattern to image")
        original = img[0] if isinstance(img, tuple) else img
        img = self._convert_to_tensor(original)
        img, is_single_point = self._handle_single_point(img)

        # Handle batch dimension if present
        if len(img.shape) > 3:
            batch_size = img.shape[0]
            img = img.view(-1, *img.shape[-3:])
        else:
            batch_size = 1

        # Ensure image is large enough
        if img.shape[-2] < 10 or img.shape[-1] < 10:
            logging.warning(f"Image too small for X pattern: {img.shape}")
            return img

        # Determine if image is normalized (0-1) or not (0-255)
        is_normalized = img.max() <= 1.0
        pattern_value = 1.0 if is_normalized else 255.0

        # Create X pattern
        for i in range(0, 10):
            for j in range(0, 10):
                if i + j == 9 or i == j:
                    if len(img.shape) == 3:  # RGB image
                        img[..., i, j] = pattern_value
                    else:  # Grayscale image
                        img[..., i, j] = pattern_value

        # Restore batch dimension if it was present
        if batch_size > 1:
            img = img.view(batch_size, *img.shape[1:])

        if is_single_point:
            img = img[0]

        return self._restore_data_format(img, original)

    def poison_data(
        self,
        dataset,
        indices: list[int],
        poisoned_percent: float,
        poisoned_noise_percent: float,
    ) -> "Dataset":
        """
        Applies X-pattern poisoning to targeted samples.

        Args:
            dataset: The dataset to modify
            indices: List of indices to consider for poisoning
            poisoned_percent: Not used in targeted poisoning
            poisoned_noise_percent: Not used in targeted poisoning

        Returns:
            Modified dataset with poisoned data
        """
        logging.info(f"[{self.__class__.__name__}] Poisoning data with X pattern for target label: {self.target_label}")
        new_dataset = copy.deepcopy(dataset)
        if not isinstance(new_dataset.targets, np.ndarray):
            new_dataset.targets = np.array(new_dataset.targets)
        else:
            new_dataset.targets = new_dataset.targets.copy()

        for i in indices:
            if int(new_dataset.targets[i]) == int(self.target_label):
                t = new_dataset.data[i]
                logging.info(f"[{self.__class__.__name__}] Adding X pattern to image")
                poisoned = self.add_x_to_image(t)

                if isinstance(t, tuple):
                    poisoned = (poisoned, t[1])

                new_dataset.data[i] = poisoned

        return new_dataset


class SamplePoisoningAttack(DatasetAttack):
    """
    Implements a data poisoning attack on a training dataset.
    """

    def __init__(self, engine, attack_params: Dict):
        """
        Initialize the sample poisoning attack.

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
        self.poisoned_noise_percent = float(attack_params["poisoned_noise_percent"])

        # Create the appropriate strategy based on whether the attack is targeted
        if attack_params.get("targeted", False):
            target_label = int(attack_params.get("target_label") or attack_params.get("targetLabel", 4))
            self.strategy = TargetedSamplePoisoningStrategy(target_label)
        else:
            noise_type = (attack_params.get("noise_type") or attack_params.get("noiseType", "Gaussian")).lower()
            self.strategy = NonTargetedSamplePoisoningStrategy(noise_type)

    def get_malicious_dataset(self):
        """
        Creates a malicious dataset by poisoning selected data points.

        Returns:
            Dataset: The modified dataset with poisoned data
        """
        return self.strategy.poison_data(
            self.datamodule.train_set,
            self.datamodule.train_set_indices,
            self.poisoned_percent,
            self.poisoned_noise_percent,
        )

"""
This module provides classes for model poisoning attacks, allowing for the simulation of
model poisoning by adding different types of noise to model parameters.

Classes:
- ModelPoisonAttack: Main attack class that implements the ModelAttack interface
- ModelPoisoningStrategy: Abstract base class for model poisoning strategies
- GaussianNoiseStrategy: Implementation for Gaussian noise poisoning
- SaltNoiseStrategy: Implementation for salt noise poisoning
- SaltAndPepperNoiseStrategy: Implementation for salt-and-pepper noise poisoning
"""

import logging
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Dict, TYPE_CHECKING

import torch
from skimage.util import random_noise

from nebula.addons.attacks.model.modelattack import ModelAttack

if TYPE_CHECKING:
    from torch.utils.data import Dataset


class ModelPoisoningStrategy(ABC):
    """Abstract base class for model poisoning strategies."""

    @abstractmethod
    def apply_noise(
        self,
        model: OrderedDict,
        poisoned_noise_percent: float,
    ) -> OrderedDict:
        """
        Abstract method to apply noise to model parameters.

        Args:
            model: The model's parameters organized as an OrderedDict
            poisoned_noise_percent: Percentage of noise to apply (0-100)

        Returns:
            Modified model parameters with noise applied
        """
        pass


class GaussianNoiseStrategy(ModelPoisoningStrategy):
    """Implementation of Gaussian noise poisoning strategy."""

    def apply_noise(
        self,
        model: OrderedDict,
        poisoned_noise_percent: float,
    ) -> OrderedDict:
        """
        Applies Gaussian-distributed additive noise to model parameters.

        Args:
            model: The model's parameters organized as an OrderedDict
            poisoned_noise_percent: Percentage of noise to apply (0-100)

        Returns:
            Modified model parameters with Gaussian noise
        """
        poisoned_model = OrderedDict()
        poisoned_ratio = poisoned_noise_percent / 100.0

        for layer in model:
            bt = model[layer]
            t = bt.detach().clone()
            single_point = False
            if len(t.shape) == 0:
                t = t.view(-1)
                single_point = True
                logging.info(f"Layer {layer} is a single point, reshaping to {t.shape}")

            logging.info(f"Applying gaussian noise to layer {layer}")
            poisoned = torch.tensor(random_noise(t, mode="gaussian", mean=0, var=poisoned_ratio, clip=True))

            if single_point:
                poisoned = poisoned[0]
                logging.info(f"Layer {layer} is a single point, reshaping to {poisoned.shape}")
            poisoned_model[layer] = poisoned

        return poisoned_model


class SaltNoiseStrategy(ModelPoisoningStrategy):
    """Implementation of salt noise poisoning strategy."""

    def apply_noise(
        self,
        model: OrderedDict,
        poisoned_noise_percent: float,
    ) -> OrderedDict:
        """
        Applies salt noise to model parameters.

        Args:
            model: The model's parameters organized as an OrderedDict
            poisoned_noise_percent: Percentage of noise to apply (0-100)

        Returns:
            Modified model parameters with salt noise
        """
        poisoned_model = OrderedDict()
        poisoned_ratio = poisoned_noise_percent / 100.0

        for layer in model:
            bt = model[layer]
            t = bt.detach().clone()
            single_point = False
            if len(t.shape) == 0:
                t = t.view(-1)
                single_point = True
                logging.info(f"Layer {layer} is a single point, reshaping to {t.shape}")

            logging.info(f"Applying salt noise to layer {layer}")
            poisoned = torch.tensor(random_noise(t, mode="salt", amount=poisoned_ratio))

            if single_point:
                poisoned = poisoned[0]
                logging.info(f"Layer {layer} is a single point, reshaping to {poisoned.shape}")
            poisoned_model[layer] = poisoned

        return poisoned_model


class SaltAndPepperNoiseStrategy(ModelPoisoningStrategy):
    """Implementation of salt-and-pepper noise poisoning strategy."""

    def apply_noise(
        self,
        model: OrderedDict,
        poisoned_noise_percent: float,
    ) -> OrderedDict:
        """
        Applies salt-and-pepper noise to model parameters.

        Args:
            model: The model's parameters organized as an OrderedDict
            poisoned_noise_percent: Percentage of noise to apply (0-100)

        Returns:
            Modified model parameters with salt-and-pepper noise
        """
        poisoned_model = OrderedDict()
        poisoned_ratio = poisoned_noise_percent / 100.0

        for layer in model:
            bt = model[layer]
            t = bt.detach().clone()
            single_point = False
            if len(t.shape) == 0:
                t = t.view(-1)
                single_point = True
                logging.info(f"Layer {layer} is a single point, reshaping to {t.shape}")

            logging.info(f"Applying salt-and-pepper noise to layer {layer}")
            poisoned = torch.tensor(random_noise(t, mode="s&p", amount=poisoned_ratio))

            if single_point:
                poisoned = poisoned[0]
                logging.info(f"Layer {layer} is a single point, reshaping to {poisoned.shape}")
            poisoned_model[layer] = poisoned

        return poisoned_model


class ModelPoisonAttack(ModelAttack):
    """
    Implements a model poisoning attack by modifying the received model weights
    during the aggregation process.
    """

    def __init__(self, engine, attack_params: Dict):
        """
        Initialize the model poisoning attack.

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
        self.poisoned_noise_percent = float(attack_params["poisoned_noise_percent"])
        noise_type = attack_params["noise_type"].lower()

        # Create the appropriate strategy based on noise type
        if noise_type == "gaussian":
            self.strategy = GaussianNoiseStrategy()
        elif noise_type == "salt":
            self.strategy = SaltNoiseStrategy()
        elif noise_type == "s&p":
            self.strategy = SaltAndPepperNoiseStrategy()
        else:
            raise ValueError(f"Unsupported noise type: {noise_type}")

    def model_attack(self, received_weights: OrderedDict) -> OrderedDict:
        """
        Applies the model poisoning attack by modifying the received model weights.

        Args:
            received_weights: The aggregated model weights to be poisoned

        Returns:
            The modified model weights after applying the poisoning attack
        """
        return self.strategy.apply_noise(received_weights, self.poisoned_noise_percent)

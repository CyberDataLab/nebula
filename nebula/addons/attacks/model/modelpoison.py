"""
This module provides a function for adding noise to a machine learning model's parameters, simulating
data poisoning attacks. The main function allows for the injection of various types of noise into
the model parameters, effectively altering them to test the model's robustness against malicious
manipulations.

Function:
- modelpoison: Modifies the parameters of a model by injecting noise according to a specified ratio
  and type of noise (e.g., Gaussian, salt, salt-and-pepper).
"""

import logging
from collections import OrderedDict

import torch
from skimage.util import random_noise

from nebula.addons.attacks.model.modelattack import ModelAttack


class ModelPoisonAttack(ModelAttack):
    """
    Implements a model poisoning attack by modifying the received model weights
    during the aggregation process.

    This attack introduces specific modifications to the model weights to
    influence the global model's behavior.

    Args:
        engine (object): The training engine object that manages the aggregator.
        attack_params (dict): Parameters for the attack, including:
            - poisoned_noise_percent (float): The percentage of noise to be added to model weights (0-100).
            - noise_type (str): The type of noise to introduce during the attack.
    """

    def __init__(self, engine, attack_params):
        """
        Initializes the ModelPoisonAttack with the specified engine and parameters.

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

        self.poisoned_noise_percent = float(attack_params["poisoned_noise_percent"])
        self.noise_type = attack_params["noise_type"].lower()

    def modelPoison(self, model: OrderedDict, poisoned_noise_percent, noise_type="gaussian"):
        """
        Adds random noise to the parameters of a model for the purpose of data poisoning.

        This function modifies the model's parameters by injecting noise according to the specified
        noise type and percentage. Various types of noise can be applied, including salt noise, Gaussian
        noise, and salt-and-pepper noise.

        Args:
            model (OrderedDict): The model's parameters organized as an `OrderedDict`. Each key corresponds
                                 to a layer, and each value is a tensor representing the parameters of that layer.
            poisoned_noise_percent (float): The percentage of noise to apply (0-100).
            noise_type (str, optional): The type of noise to apply to the model parameters. Supported types are:
                                        - "salt": Applies salt noise, replacing random elements with 1.
                                        - "gaussian": Applies Gaussian-distributed additive noise.
                                        - "s&p": Applies salt-and-pepper noise, replacing random elements with either 1 or low_val.
                                        Default is "gaussian".

        Returns:
            OrderedDict: A new `OrderedDict` containing the model parameters with noise added.

        Raises:
            ValueError: If `poisoned_noise_percent` is not between 0 and 100, or if `noise_type` is unsupported.

        Notes:
            - If a layer's tensor is a single point (0-dimensional), it will be reshaped for processing.
            - Unsupported noise types will result in an error message, and the original tensor will be retained.
        """
        poisoned_model = OrderedDict()
        if not isinstance(noise_type, str):
            logging.info(f"Noise type is not a string, converting to string: {noise_type}")
            noise_type = noise_type[0]

        # Convert percentage to ratio for noise application
        poisoned_ratio = poisoned_noise_percent / 100.0

        for layer in model:
            bt = model[layer]
            t = bt.detach().clone()
            single_point = False
            if len(t.shape) == 0:
                t = t.view(-1)
                single_point = True
                logging.info(f"Layer {layer} is a single point, reshaping to {t.shape}")

            if noise_type == "salt":
                logging.info(f"Applying salt noise to layer {layer}")
                # Replaces random pixels with 1.
                poisoned = torch.tensor(random_noise(t, mode=noise_type, amount=poisoned_ratio))
            elif noise_type == "gaussian":
                logging.info(f"Applying gaussian noise to layer {layer}")
                # Gaussian-distributed additive noise.
                poisoned = torch.tensor(random_noise(t, mode=noise_type, mean=0, var=poisoned_ratio, clip=True))
            elif noise_type == "s&p":
                logging.info(f"Applying salt-and-pepper noise to layer {layer}")
                # Replaces random pixels with either 1 or low_val, where low_val is 0 for unsigned images or -1 for signed images.
                poisoned = torch.tensor(random_noise(t, mode=noise_type, amount=poisoned_ratio))
            else:
                logging.info(f"ERROR: noise_type '{noise_type}' not supported in model poison attack.")
                poisoned = t
            if single_point:
                poisoned = poisoned[0]
                logging.info(f"Layer {layer} is a single point, reshaping to {poisoned.shape}")
            poisoned_model[layer] = poisoned

        return poisoned_model

    def model_attack(self, received_weights):
        """
        Applies the model poisoning attack by modifying the received model weights.

        Args:
            received_weights (any): The aggregated model weights to be poisoned.

        Returns:
            any: The modified model weights after applying the poisoning attack.
        """
        logging.info(f"[ModelPoisonAttack] Performing model poison attack with poisoned_noise_percent={self.poisoned_noise_percent} and noise_type={self.noise_type}")
        received_weights = self.modelPoison(received_weights, self.poisoned_noise_percent, self.noise_type)
        return received_weights

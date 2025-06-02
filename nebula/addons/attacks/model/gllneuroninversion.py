import logging

import torch

from nebula.addons.attacks.model.modelattack import ModelAttack


class GLLNeuronInversionAttack(ModelAttack):
    """
    Implements a neuron inversion attack on the received model weights.

    This attack aims to invert the values of neurons in specific layers
    by replacing their values with random noise, potentially disrupting the model's
    functionality during aggregation.

    Args:
        engine (object): The training engine object that manages the aggregator.
        _ (any): A placeholder argument (not used in this class).
    """

    def __init__(self, engine, attack_params):
        """
        Initializes the GLLNeuronInversionAttack with the specified engine.

        Args:
            engine (object): The training engine object.
            _ (any): A placeholder argument (not used in this class).
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

    def model_attack(self, received_weights):
        """
        Performs the neuron inversion attack by modifying the weights of a specific
        layer with random noise.

        This attack replaces the weights of a chosen layer with random values,
        which may disrupt the functionality of the model.

        Args:
            received_weights (dict): The aggregated model weights to be modified.

        Returns:
            dict: The modified model weights after applying the neuron inversion attack.
        """
        logging.info("[GLLNeuronInversionAttack] Performing neuron inversion attack")
        lkeys = list(received_weights.keys())
        logging.info(f"Layer inverted: {lkeys[-2]}")
        received_weights[lkeys[-2]].data = torch.rand(received_weights[lkeys[-2]].shape) * 10000
        return received_weights

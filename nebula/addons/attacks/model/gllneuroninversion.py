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
        Applies a neuron inversion attack by injecting high-magnitude random noise into a target layer.

        This attack targets a specific layer (typically the penultimate fully connected layer)
        and overwrites all its weights with large random values. The intent is to cause extreme
        activations or exploding gradients, which can degrade model performance or destabilize training.

        Args:
            received_weights (dict): Dictionary of model weights with parameter names as keys.

        Returns:
            dict: Modified model weights after injecting noise into the selected layer.
        """
        logging.info("[NeuronInversionAttack] Injecting random noise into neuron layer")

        # Get list of layer names
        layer_keys = list(received_weights.keys())
        target_key = layer_keys[-2]  # Target penultimate weight matrix
        target_weights = received_weights[target_key]

        # Use configurable scale or default to a high perturbation
        # noise_scale = getattr(self, 'noise_scale', 1e4)
        noise_scale = 10000
        logging.info(f"Target layer: {target_key}, Noise scale: {noise_scale}")

        # Inject random noise of the same shape and type
        received_weights[target_key] = torch.empty_like(target_weights).uniform_(0, noise_scale)

        return received_weights
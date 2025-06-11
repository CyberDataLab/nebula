import copy
import logging

import numpy as np
import torch
from torchmetrics.functional import pairwise_cosine_similarity

from nebula.addons.attacks.model.modelattack import ModelAttack


class SwappingWeightsAttack(ModelAttack):
    """
    Implements a swapping weights attack on the received model weights.

    This attack performs stochastic swapping of weights in a specified layer of the model,
    potentially disrupting its performance. The attack is not deterministic, and its performance
    can vary. The code may not work as expected for some layers due to reshaping, and its
    computational cost scales quadratically with the layer size. It should not be applied to
    the last layer, as it would make the attack detectable due to high loss on the malicious node.

    Args:
        engine (object): The training engine object that manages the aggregator.
        attack_params (dict): Parameters for the attack, including:
            - layer_idx (int): The index of the layer where the weights will be swapped.
    """

    def __init__(self, engine, attack_params):
        """
        Initializes the SwappingWeightsAttack with the specified engine and parameters.

        Args:
            engine (object): The training engine object.
            attack_params (dict): Dictionary of attack parameters, including the layer index.
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

        self.layer_idx = int(attack_params["layer_idx"])

    def model_attack(self, received_weights):
        """
        Performs a similarity-based weight swapping attack to subtly sabotage a federated model.

        This attack targets a specific layer of the neural network (typically a fully connected layer)
        and permutes its neurons (rows in the weight matrix) in a way that alters the model's behavior
        without changing its structure or dimensions.

        Steps:
        1. Computes a pairwise cosine similarity matrix between the rows (neurons) of the selected layer.
        2. Finds neuron pairs that are mutually dissimilar (i.e., each is the most dissimilar to the other).
        These pairs are good candidates for swapping as the operation is more disruptive.
        3. For the remaining neurons (not in such pairs), applies a random permutation ensuring no neuron
        stays in its original position.
        4. Applies the final permutation to:
        - The target layer (permutes rows).
        - The next layer (permutes corresponding rows).
        - The following layer (if any), where the permutation is applied to columns (to preserve consistency).

        This subtle attack degrades model performance while preserving architectural validity and
        avoiding obvious signs of tampering.

        Args:
            received_weights (dict): Dictionary of aggregated model weights with parameter names as keys.

        Returns:
            dict: Modified model weights with rows of selected layers permuted.
        """
        logging.info("[SwappingWeightsAttack] Performing swapping weights attack")
        # Extract weight matrix for the target layer
        layer_keys = list(received_weights.keys())
        w = received_weights[layer_keys[self.layer_idx]]

        # Compute cosine similarity matrix
        sim_matrix = torch.nn.functional.cosine_similarity(
            w.unsqueeze(1), w.unsqueeze(0), dim=2
        )

        # Greedy mutual minimum pairing
        perm = -torch.ones(sim_matrix.shape[0], dtype=torch.long)
        mutual_rows = []

        for i in range(sim_matrix.shape[0]):
            j = torch.argmin(sim_matrix[i])
            if torch.argmin(sim_matrix[j]) == i:
                perm[i] = j
                mutual_rows.append(i)

        # Fully permute the remaining rows
        remaining_rows = torch.tensor([i for i in range(sim_matrix.shape[0]) if i not in mutual_rows])
        shuffled = remaining_rows[torch.randperm(len(remaining_rows))]
        while torch.any(remaining_rows == shuffled):
            shuffled = remaining_rows[torch.randperm(len(remaining_rows))]

        perm[remaining_rows] = shuffled

        # Apply permutation to current and next layers
        received_weights[layer_keys[self.layer_idx]] = w[perm]
        received_weights[layer_keys[self.layer_idx + 1]] = received_weights[layer_keys[self.layer_idx + 1]][perm]

        # If there's a third layer and it matches output shape, permute columns accordingly
        if self.layer_idx + 2 < len(layer_keys):
            received_weights[layer_keys[self.layer_idx + 2]] = received_weights[layer_keys[self.layer_idx + 2]][:, perm]

        return received_weights
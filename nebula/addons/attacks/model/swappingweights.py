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
        Performs the swapping weights attack by computing a similarity matrix and
        swapping the weights of a specified layer based on their similarity.

        This method applies a greedy algorithm to swap weights in the selected layer
        in a way that could potentially disrupt the training process. The attack also
        ensures that some rows are fully permuted, and others are swapped based on
        similarity.

        Args:
            received_weights (dict): The aggregated model weights to be modified.

        Returns:
            dict: The modified model weights after performing the swapping attack.
        """
        logging.info("[SwappingWeightsAttack] Performing swapping weights attack")
        lkeys = list(received_weights.keys())
        wm = received_weights[lkeys[self.layer_idx]]

        # Compute similarity matrix
        sm = torch.zeros((wm.shape[0], wm.shape[0]))
        for j in range(wm.shape[0]):
            sm[j] = pairwise_cosine_similarity(wm[j].reshape(1, -1), wm.reshape(wm.shape[0], -1))

        # Check rows/cols where greedy approach is optimal
        nsort = np.full(sm.shape[0], -1)
        rows = []
        for j in range(sm.shape[0]):
            k = torch.argmin(sm[j])
            if torch.argmin(sm[:, k]) == j:
                nsort[j] = k
                rows.append(j)
        not_rows = np.array([i for i in range(sm.shape[0]) if i not in rows])

        # Ensure the rest of the rows are fully permuted (not optimal, but good enough)
        nrs = copy.deepcopy(not_rows)
        nrs = np.random.permutation(nrs)
        while np.any(nrs == not_rows):
            nrs = np.random.permutation(nrs)
        nsort[not_rows] = nrs
        nsort = torch.tensor(nsort)

        # Apply permutation to weights
        received_weights[lkeys[self.layer_idx]] = received_weights[lkeys[self.layer_idx]][nsort]
        received_weights[lkeys[self.layer_idx + 1]] = received_weights[lkeys[self.layer_idx + 1]][nsort]
        if self.layer_idx + 2 < len(lkeys):
            received_weights[lkeys[self.layer_idx + 2]] = received_weights[lkeys[self.layer_idx + 2]][:, nsort]

        return received_weights

from typing import Any
import torch
import numpy as np
from torchmetrics.functional import pairwise_cosine_similarity
from copy import deepcopy
import time
import logging


# To take into account:
# - Malicious nodes do not train on their own data
# - Malicious nodes aggregate the weights of the other nodes, but not their own
# - The received weights may be the node own weights (aggregated of neighbors), or
#   if the attack is performed specifically for one of the neighbors, it can take
#   its weights only (should be more effective if they are different).


def create_attack(attack_name):
    """
    Function to create an attack object from its name.
    """
    if attack_name == "GLLNeuronInversionAttack":
        return GLLNeuronInversionAttack()
    elif attack_name == "NoiseInjectionAttack":
        return NoiseInjectionAttack()
    elif attack_name == "SwappingWeightsAttack":
        return SwappingWeightsAttack()
    elif attack_name == "DelayerAttack":
        return DelayerAttack()
    else:
        raise ValueError(f"Attack {attack_name} not supported")


class Attack:

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        return self.attack(*args, **kwds)

    def attack(self, received_weights):
        """
        Function to perform the attack on the received weights. It should return the
        attacked weights.
        """
        raise NotImplementedError


class GLLNeuronInversionAttack(Attack):
    """
    Function to perform neuron inversion attack on the received weights.
    """

    def __init__(self, strength=5.0, perc=1.0):
        super().__init__()
        self.strength = strength
        self.perc = perc

    def attack(self, received_weights):
        logging.info("[GLLNeuronInversionAttack] Performing neuron inversion attack")
        lkeys = list(received_weights.keys())
        logging.info(f"Layer inverted: {lkeys[-2]}")
        received_weights[lkeys[-2]].data = torch.rand(received_weights[lkeys[-2]].shape) * 10000
        return received_weights


class NoiseInjectionAttack(Attack):
    """
    Function to perform noise injection attack on the received weights.
    """

    def __init__(self, strength=10000, perc=1.0):
        super().__init__()
        self.strength = strength
        self.perc = perc       

    def attack(self, received_weights):
        logging.info("[NoiseInjectionAttack] Performing noise injection attack")
        lkeys = list(received_weights.keys())
        for k in lkeys:
            logging.info(f"Layer noised: {k}")
            received_weights[k].data += torch.randn(received_weights[k].shape) * self.strength
        return received_weights


class SwappingWeightsAttack(Attack):
    """
    Function to perform swapping weights attack on the received weights. Note that this
    attack performance is not consistent due to its stochasticity.

    Warning: depending on the layer the code may not work (due to reshaping in between),
    or it may be slow (scales quadratically with the layer size).
    Do not apply to last layer, as it would make the attack detectable (high loss
    on malicious node).
    """

    def __init__(self, layer_idx=0):
        super().__init__()
        self.layer_idx = layer_idx

    def attack(self, received_weights):
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
        nrs = deepcopy(not_rows)
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


class DelayerAttack(Attack):
    """
    Function to perform delayer attack on the received weights. It delays the
    weights for an indefinite number of rounds.
    """

    def __init__(self):
        super().__init__()
        self.weights = None

    def attack(self, received_weights):
        logging.info("[DelayerAttack] Performing delayer attack")
        logging.info("Delaying time from 15 seconds")
        time.sleep(15)
        logging.info("Delaying time finished")
        if self.weights is None:
            self.weights = deepcopy(received_weights)
        return self.weights

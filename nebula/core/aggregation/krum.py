import numpy
import torch

from nebula.core.aggregation.aggregator import Aggregator


class Krum(Aggregator):
    """
    Aggregator: Krum
    Authors: Peva Blanchard et al.
    Year: 2017
    Note: https://papers.nips.cc/paper/2017/hash/f4b9ec30ad9f68f89b29639786cb62ef-Abstract.html
    """

    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)

    def run_aggregation(self, models):
        super().run_aggregation(models)

        models = list(models.values())

        accum = {layer: torch.zeros_like(param).float() for layer, param in models[-1][0].items()}
        total_models = len(models)
        distance_list = [0 for i in range(0, total_models)]
        min_index = 0
        min_distance_sum = float("inf")

        for i in range(0, total_models):
            m1, _ = models[i]
            for j in range(0, total_models):
                m2, _ = models[j]
                distance = 0
                if i == j:
                    distance = 0
                else:
                    for layer in m1:
                        l1 = m1[layer]

                        l2 = m2[layer]
                        distance += numpy.linalg.norm(l1 - l2)
                distance_list[i] += distance

            if min_distance_sum > distance_list[i]:
                min_distance_sum = distance_list[i]
                min_index = i
        m, _ = models[min_index]
        for layer in m:
            accum[layer] = accum[layer] + m[layer]

        return accum

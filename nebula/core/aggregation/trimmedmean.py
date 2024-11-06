import numpy as np
import torch

from nebula.core.aggregation.aggregator import Aggregator


class TrimmedMean(Aggregator):
    """
    Aggregator: TrimmedMean
    Authors: Dong Yin et al et al.
    Year: 2021
    Note: https://arxiv.org/pdf/1803.01498.pdf
    """

    def __init__(self, config=None, beta=0, **kwargs):
        super().__init__(config, **kwargs)
        self.beta = beta

    def get_trimmedmean(self, weights):
        # check if the weight tensor has enough space
        weight_len = len(weights)

        if weight_len <= 2 * self.beta:
            remaining_wrights = weights
            res = torch.mean(remaining_wrights, 0)

        else:
            # remove the largest and smallest β items
            arr_weights = np.asarray(weights)
            nobs = arr_weights.shape[0]
            start = self.beta
            end = nobs - self.beta
            atmp = np.partition(arr_weights, (start, end - 1), 0)
            sl = [slice(None)] * atmp.ndim
            sl[0] = slice(start, end)
            print(atmp[tuple(sl)])
            arr_median = np.mean(atmp[tuple(sl)], axis=0)
            res = torch.tensor(arr_median)

        # get the mean of the remaining weights

        return res

    def run_aggregation(self, models):
        super().run_aggregation(models)

        models = list(models.values())
        models_params = [m for m, _ in models]

        total_models = len(models)

        accum = {layer: torch.zeros_like(param).float() for layer, param in models[-1][0].items()}

        for layer in accum:
            weight_layer = accum[layer]
            # get the shape of layer tensor
            l_shape = list(weight_layer.shape)

            # get the number of elements of layer tensor
            number_layer_weights = torch.numel(weight_layer)
            # if its 0-d tensor
            if l_shape == []:
                weights = torch.tensor([models_params[j][layer] for j in range(0, total_models)])
                weights = weights.double()
                w = self.get_trimmedmean(weights)
                accum[layer] = w

            else:
                # flatten the tensor
                weight_layer_flatten = weight_layer.view(number_layer_weights)

                # flatten the tensor of each model
                models_layer_weight_flatten = torch.stack(
                    [models_params[j][layer].view(number_layer_weights) for j in range(0, total_models)],
                    0,
                )

                # get the weight list [w1j,w2j,··· ,wmj], where wij is the jth parameter of the ith local model
                trimmedmean = self.get_trimmedmean(models_layer_weight_flatten)
                accum[layer] = trimmedmean.view(l_shape)

        return accum

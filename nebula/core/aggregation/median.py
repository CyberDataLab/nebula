import numpy as np
import torch

from nebula.core.aggregation.aggregator import Aggregator


class Median(Aggregator):
    """
    Aggregator: Median
    Authors: Dong Yin et al et al.
    Year: 2021
    Note: https://arxiv.org/pdf/1803.01498.pdf
    """

    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)

    def get_median(self, weights):
        # check if the weight tensor has enough space
        weight_len = len(weights)

        median = 0
        if weight_len % 2 == 1:
            # odd number, return the median
            median, _ = torch.median(weights, 0)
        else:
            # even number, return the mean of median two numbers
            # sort the tensor
            arr_weights = np.asarray(weights)
            nobs = arr_weights.shape[0]
            start = int(nobs / 2) - 1
            end = int(nobs / 2) + 1
            atmp = np.partition(arr_weights, (start, end - 1), 0)
            sl = [slice(None)] * atmp.ndim
            sl[0] = slice(start, end)
            arr_median = np.mean(atmp[tuple(sl)], axis=0)
            median = torch.tensor(arr_median)
        return median

    def run_aggregation(self, models):
        super().run_aggregation(models)

        models = list(models.values())
        models_params = [m for m, _ in models]

        total_models = len(models)

        accum = {layer: torch.zeros_like(param).float() for layer, param in models[-1][0].items()}

        # Calculate the trimmedmean for each parameter
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
                w = self.get_median(weights)
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
                median = self.get_median(models_layer_weight_flatten)
                accum[layer] = median.view(l_shape)
        return accum

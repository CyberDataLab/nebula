import gc

import torch

from nebula.core.aggregation.aggregator import Aggregator


class FedAvg(Aggregator):
    """
    Aggregator: Federated Averaging (FedAvg)
    Authors: McMahan et al.
    Year: 2016
    """

    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)

    def run_aggregation(self, models):
        super().run_aggregation(models)

        models = list(models.values())

        total_samples = float(sum(weight for _, weight in models))

        if total_samples == 0:
            raise ValueError("Total number of samples must be greater than zero.")

        last_model_params = models[-1][0]
        accum = {layer: torch.zeros_like(param, dtype=torch.float32) for layer, param in last_model_params.items()}

        with torch.no_grad():
            for model_parameters, weight in models:
                normalized_weight = weight / total_samples
                for layer in accum:
                    accum[layer].add_(
                        model_parameters[layer].to(accum[layer].dtype),
                        alpha=normalized_weight,
                    )

        del models
        gc.collect()

        # self.print_model_size(accum)
        return accum

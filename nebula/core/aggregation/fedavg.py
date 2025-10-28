import gc
import logging
from collections import defaultdict

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

        accum: dict[str, torch.Tensor] = {}
        contribution_sums: defaultdict[str, float] = defaultdict(float)
        participation_counts: defaultdict[str, int] = defaultdict(int)

        with torch.no_grad():
            for model_parameters, weight in models:
                normalized_weight = weight / total_samples
                for layer, param in model_parameters.items():
                    if layer not in accum:
                        accum[layer] = torch.zeros_like(param, dtype=torch.float32)
                    accum[layer].add_(param.to(accum[layer].dtype), alpha=normalized_weight)
                    contribution_sums[layer] += normalized_weight
                    participation_counts[layer] += 1

        num_models = len(models)
        logging.info(f"[yolo] num_models {num_models}")
        for layer, tensor in list(accum.items()):
            logging.info(f"####### [yolo] layer {layer} tensor {tensor} #######")
            logging.info(f"####### [yolo] contribution_sums {contribution_sums} #######")
            logging.info(f"####### [yolo] participation_counts {participation_counts} #######")
            weight_sum = contribution_sums[layer]
            if weight_sum == 0:
                logging.debug("FedAvg | Removing layer %s due to zero contribution weight.", layer)
                del accum[layer]
                continue
            tensor.div_(weight_sum)

        if num_models:
            partial_layers = [layer for layer, count in participation_counts.items() if count < num_models]
            if partial_layers:
                logging.debug(
                    "FedAvg | Partial contributions detected for %d layers: %s",
                    len(partial_layers),
                    partial_layers[:10],
                )

        del models
        gc.collect()

        # self.print_model_size(accum)
        return accum

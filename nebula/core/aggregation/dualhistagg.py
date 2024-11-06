import logging

import numpy as np
import torch

from nebula.core.aggregation.aggregator import Aggregator
from nebula.core.utils.helper import cosine_metric


class DualHistAgg(Aggregator):
    """
    Aggregator: Dual History Aggregation (DualHistAgg)
    Authors: Enrique et al.
    Year: 2024
    """

    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)

    def softmax(self, x):
        # Safeguard against empty input array
        if x.size == 0:
            return np.array([])
        e_x = np.exp(x - np.max(x))
        return e_x / e_x.sum(axis=0)  # ensure division is done correctly

    def run_aggregation(self, models, reference_model=None):
        if len(models) == 0:
            logging.error("Trying to aggregate models when there are no models")
            return None, None

        models = list(models.values())
        num_models = len(models)
        logging.info(f"Number of models: {num_models}")

        if num_models == 1:
            logging.info("Only one model, returning it")
            return models[0][0], models[0][0]

        # Total Samples
        total_samples = float(sum(w for _, w in models))
        # Create a Zero Model
        accum = {
            layer: torch.zeros_like(param).float() for layer, param in models[0][0].items()
        }  # use first model for template
        accum_similarity = accum.copy()

        similarities = (
            [cosine_metric(model, reference_model) for model, _ in models] if reference_model else [1] * num_models
        )

        logging.info(f"Similarities: {similarities}")
        weights = self.softmax(np.array(similarities))
        logging.info(f"Weights: {weights}")

        # Aggregation process
        for (model, _), weight, sim_weight in zip(models, weights, similarities, strict=False):
            for layer in accum:
                accum[layer] += model[layer].float() * float(weight)
                accum_similarity[layer] += model[layer].float() * float(sim_weight)

        # Normalize aggregated models
        for layer in accum:
            accum[layer] /= total_samples
            accum_similarity[layer] /= total_samples

        return accum, accum_similarity

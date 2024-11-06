import numpy as np
from sklearn.svm import LinearSVC

from nebula.core.aggregation.aggregator import Aggregator


class FedAvgSVM(Aggregator):
    """
    Aggregator: Federated Averaging (FedAvg)
    Authors: McMahan et al.
    Year: 2016
    Note: This is a modified version of FedAvg for SVMs.
    """

    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)

    def run_aggregation(self, models):
        super().run_aggregation(models)

        models = list(models.values())

        total_samples = sum([y for _, y in models])

        coeff_accum = np.zeros_like(models[-1][0].coef_)
        intercept_accum = 0.0

        for model, w in models:
            if not isinstance(model, LinearSVC):
                return None
            coeff_accum += model.coef_ * w
            intercept_accum += model.intercept_ * w

        coeff_accum /= total_samples
        intercept_accum /= total_samples

        aggregated_svm = LinearSVC()
        aggregated_svm.coef_ = coeff_accum
        aggregated_svm.intercept_ = intercept_accum

        return aggregated_svm

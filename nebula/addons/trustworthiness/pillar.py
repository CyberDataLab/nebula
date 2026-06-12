import logging

from nebula.addons.trustworthiness.helpers.factsheet_values import get_input_value
from nebula.addons.trustworthiness.helpers.scoring import (
    get_map_value_score,
    get_mapped_score,
    get_range_score,
    get_scaled_score,
    get_true_score,
)

logger = logging.getLogger(__name__)


class TrustPillar:
    """
    Class to represent a trust pillar.

    Args:
        name (string): Name of the pillar.
        metrics (dict): Metric definitions for the pillar.
        input_docs (dict): Input documents.
        use_weights (bool): True to turn on the weights in the metric config file.

    """

    def __init__(self, name, metrics, input_docs, use_weights=False, user_weights=None):
        self.name = name
        self.input_docs = input_docs
        self.metrics = metrics
        self.result = []
        self.use_weights = use_weights
        self.user_weights = user_weights or {}

    def evaluate(self):
        """
        Evaluate the trust score for the pillar.

        Returns:
            float: Score of [0, 1].
        """
        score = 0
        avg_weight = 1 / len(self.metrics)
        for key, value in self.metrics.items():
            weight = self._get_notion_weight(key, value, avg_weight) if self.use_weights else avg_weight
            score += weight * self.get_notion_score(key, value.get("metrics"))
        score = round(score, 2)
        return score, {self.name: {"score": score, "notions": self.result}}

    def _get_notion_weight(self, notion_name, notion_config, avg_weight):
        """
        Resolve the weight for a notion.

        Scenario-defined notion weights are stored as percentages in scenario.json.
        When present, they must override the defaults from the metrics config.
        """
        if notion_name in self.user_weights:
            return float(self.user_weights[notion_name]) / 100
        return notion_config.get("weight", avg_weight)

    def get_notion_score(self, name, metrics):
        """
        Evaluate the trust score for the notion.

        Args:
            name (string): Name of the notion.
            metrics (list): Metrics definitions of the notion.

        Returns:
            float: Score of [0, 1].
        """

        notion_score = 0
        avg_weight = 1 / len(metrics)
        metrics_result = []
        for key, value in metrics.items():
            metric_score = self.get_metric_score(metrics_result, key, value)
            weight = value.get("weight", avg_weight) if self.use_weights else avg_weight
            notion_score += weight * float(metric_score)
        self.result.append({name: {"score": notion_score, "metrics": metrics_result}})
        return notion_score

    def get_metric_score(self, result, name, metric):
        """
        Evaluate the trust score for the metric.

        Args:
            result (object): The result object
            name (string): Name of the metric.
            metrics (dict): The metric definition.

        Returns:
            float: Score of [0, 1].
        """

        score = 0
        try:
            input_value = get_input_value(self.input_docs, metric.get("inputs"), metric.get("operation"))

            score_type = metric.get("type")
            if input_value is None:
                logger.warning(f"{name} input value is null")
            else:
                if score_type == "true_score":
                    score = get_true_score(input_value, metric.get("direction"))
                elif score_type == "score_mapping":
                    score = get_mapped_score(input_value, metric.get("score_map"))
                elif score_type == "ranges":
                    score = get_range_score(input_value, metric.get("ranges"), metric.get("direction"))
                elif score_type == "score_map_value":
                    score = get_map_value_score(input_value, metric.get("score_map"))
                elif score_type == "scaled_score":
                    score = get_scaled_score(input_value, metric.get("scale"), metric.get("direction"))
                elif score_type == "property_check":
                    score = 0 if input_value is None else input_value

                else:
                    logger.warning(f"The score type {score_type} is not yet implemented.")

        except KeyError:
            logger.warning(f"Null input for {name} metric")
        score = round(score, 2)
        result.append({name: {"score": score}})
        return score

import json
import logging
import os

from nebula.addons.trustworthiness.graphics import Graphics
from nebula.addons.trustworthiness.pillar import TrustPillar
from nebula.addons.trustworthiness.utils import write_results_json

dirname = os.path.dirname(__file__)

logger = logging.getLogger(__name__)


class TrustMetricManager:
    """
    Manager class to help store the output directory and handle calls from the FL framework.
    """

    def __init__(self, scenario_start_time):
        self.factsheet_file_nm = "factsheet.json"
        self.eval_metrics_file_nm = "eval_metrics.json"
        self.nebula_trust_results_nm = "nebula_trust_results.json"
        self.scenario_start_time = scenario_start_time

    def evaluate(self, experiment_name, weights, use_weights=False):
        """
        Evaluates the trustworthiness score.

        Args:
            scenario (object): The scenario in whith the trustworthiness will be calculated.
            weights (dict): The desired weghts of the pillars.
            use_weights (bool): True to turn on the weights in the metric config file, default to False.
        """
        # Get scenario name
        scenario_name = experiment_name
        factsheet_file = os.path.join(os.environ.get('NEBULA_LOGS_DIR'), scenario_name, "trustworthiness", self.factsheet_file_nm)
        metrics_cfg_file = os.path.join(dirname, "configs", self.eval_metrics_file_nm)
        results_file = os.path.join(os.environ.get('NEBULA_LOGS_DIR'), scenario_name, "trustworthiness", self.nebula_trust_results_nm)

        if not os.path.exists(factsheet_file):
            logger.error(f"{factsheet_file} is missing! Please check documentation.")
            return

        if not os.path.exists(metrics_cfg_file):
            logger.error(f"{metrics_cfg_file} is missing! Please check documentation.")
            return

        with open(factsheet_file, "r") as f, open(metrics_cfg_file, "r") as m:
            factsheet = json.load(f)
            metrics_cfg = json.load(m)
            metrics = metrics_cfg.items()
            input_docs = {"factsheet": factsheet}

            result_json = {"trust_score": 0, "pillars": []}
            final_score = 0
            result_print = []
            for key, value in metrics:
                pillar = TrustPillar(key, value, input_docs, use_weights)
                score, result = pillar.evaluate()
                weight = weights.get(key) / 100
                final_score += weight * score
                result_print.append([key, score])
                result_json["pillars"].append(result)
            final_score = round(final_score, 2)
            result_json["trust_score"] = final_score
            write_results_json(results_file, result_json)
            
            graphics = Graphics(self.scenario_start_time, scenario_name)
            graphics.graphics()

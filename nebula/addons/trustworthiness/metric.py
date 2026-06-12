import json
import logging
import os

from nebula.addons.trustworthiness.graphics import Graphics
from nebula.addons.trustworthiness.pillar import TrustPillar
from nebula.addons.trustworthiness.helpers.csv_io import write_results_json

dirname = os.path.dirname(__file__)

logger = logging.getLogger(__name__)


def get_eval_metrics_file(federation_prefix, factsheet, default_file_name):
    data_type = str(factsheet.get("data", {}).get("type", "")).strip().lower()

    if data_type not in {"images", "tabular"}:
        return os.path.join(dirname, "configs", default_file_name)

    metrics_file_name = f"eval_metrics_{federation_prefix}_{data_type}.json"
    metrics_file = os.path.join(dirname, "configs", metrics_file_name)

    return metrics_file if os.path.exists(metrics_file) else os.path.join(dirname, "configs", default_file_name)


class TrustMetricManager:
    """
    Manager class to help store the output directory and handle calls from the FL framework.
    """

    def __init__(self, scenario_start_time, federation, participant=None):
        if federation == "DFL" or federation == "SDFL":
            self.federation_prefix = "dfl"
            self.factsheet_file_nm = f"factsheet_participant_{participant}.json"
            self.eval_metrics_file_nm = "eval_metrics_dfl.json"
            self.nebula_trust_results_nm = f"nebula_trust_results_{participant}.json"
            self.scenario_start_time = scenario_start_time
        else:
            self.federation_prefix = "cfl"
            self.factsheet_file_nm = "factsheet.json"
            self.eval_metrics_file_nm = "eval_metrics_cfl.json"
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
        results_file = os.path.join(os.environ.get('NEBULA_LOGS_DIR'), scenario_name, "trustworthiness", self.nebula_trust_results_nm)

        if not os.path.exists(factsheet_file):
            logger.error(f"{factsheet_file} is missing! Please check documentation.")
            return

        with open(factsheet_file, "r") as f:
            factsheet = json.load(f)

        metrics_cfg_file = get_eval_metrics_file(self.federation_prefix, factsheet, self.eval_metrics_file_nm)

        if not os.path.exists(metrics_cfg_file):
            logger.error(f"{metrics_cfg_file} is missing! Please check documentation.")
            return

        with open(metrics_cfg_file, "r") as m:
            metrics_cfg = json.load(m)
            metrics = metrics_cfg.items()
            input_docs = {"factsheet": factsheet}

            result_json = {"trust_score": 0, "pillars": []}
            final_score = 0
            result_print = []
            for key, value in metrics:
                pillar = TrustPillar(key, value, input_docs, use_weights, user_weights=weights)
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

    def evaluate_participant(self, experiment_name, weights, participant_id, use_weights=False):
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
        results_file = os.path.join(os.environ.get('NEBULA_LOGS_DIR'), scenario_name, "trustworthiness", self.nebula_trust_results_nm)

        if not os.path.exists(factsheet_file):
            logger.error(f"{factsheet_file} is missing! Please check documentation.")
            return

        with open(factsheet_file, "r") as f:
            factsheet = json.load(f)

        metrics_cfg_file = get_eval_metrics_file(self.federation_prefix, factsheet, self.eval_metrics_file_nm)

        if not os.path.exists(metrics_cfg_file):
            logger.error(f"{metrics_cfg_file} is missing! Please check documentation.")
            return

        with open(metrics_cfg_file, "r") as m:
            raw_metrics_cfg: str = m.read()
            raw_metrics_cfg = raw_metrics_cfg.replace("factsheet", f"factsheet_participant_{participant_id}")
            metrics_cfg = json.loads(raw_metrics_cfg)

            metrics = metrics_cfg.items()
            input_docs = {f"factsheet_participant_{participant_id}": factsheet}

            result_json = {"trust_score": 0, "pillars": []}
            final_score = 0
            result_print = []
            for key, value in metrics:
                pillar = TrustPillar(key, value, input_docs, use_weights, user_weights=weights)
                score, result = pillar.evaluate()
                weight = weights.get(key) / 100
                final_score += weight * score
                result_print.append([key, score])
                result_json["pillars"].append(result)
            final_score = round(final_score, 2)
            result_json["trust_score"] = final_score
            write_results_json(results_file, result_json)

            graphics = Graphics(self.scenario_start_time, scenario_name, participant_id)
            graphics.graphics_dfl(participant_id)

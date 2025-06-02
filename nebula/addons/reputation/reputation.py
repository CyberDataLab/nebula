import logging
import random
import time
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import torch

from nebula.addons.functions import print_msg_box
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import AggregationEvent, RoundStartEvent, UpdateReceivedEvent
from nebula.core.utils.helper import (
    cosine_metric,
    euclidean_metric,
    jaccard_metric,
    manhattan_metric,
    minkowski_metric,
    pearson_correlation_metric,
)

if TYPE_CHECKING:
    from nebula.config.config import Config
    from nebula.core.engine import Engine


class Metrics:
    def __init__(
        self,
        num_round=None,
        current_round=None,
        fraction_changed=None,
        threshold=None,
        latency=None,
    ):
        self.fraction_of_params_changed = {
            "fraction_changed": fraction_changed,
            "threshold": threshold,
            "round": num_round,
        }

        self.model_arrival_latency = {"latency": latency, "round": num_round, "round_received": current_round}

        self.model_arrival_latency = {"latency": latency, "round": num_round, "round_received": current_round}

        self.messages = []
        self.similarity = []


class Reputation:
    """
    Class to define and manage the reputation of a participant in the network.

    The class handles collection of metrics, calculation of static and dynamic reputation,
    updating history, and communication of reputation scores to neighbors.
    """

    def __init__(self, engine: "Engine", config: "Config"):
        """
        Initialize the Reputation system.
        """

    def __init__(self, engine: "Engine", config: "Config"):
        self._engine = engine
        self._config = config
        self.fraction_of_params_changed = {}
        self.history_data = {}
        self.metric_weights = {}
        self.reputation = {}
        self.reputation_with_feedback = {}
        self.reputation_with_all_feedback = {}
        self.rejected_nodes = set()
        self.round_timing_info = {}
        self._messages_received_from_sources = {}
        self.reputation_history = {}
        self.number_message_history = {}
        self.neighbor_reputation_history = {}
        self.fraction_changed_history = {}
        self.messages_number_message = []
        self.previous_threshold_number_message = {}
        self.previous_std_dev_number_message = {}
        self.messages_model_arrival_latency = {}
        self.model_arrival_latency_history = {}
        self._addr = engine.addr
        self._log_dir = engine.log_dir
        self.connection_metrics = []

        neighbors: str = self._config.participant["network_args"]["neighbors"]
        self.connection_metrics = {}
        for nei in neighbors.split():
            self.connection_metrics[f"{nei}"] = Metrics()

        self._with_reputation = self._config.participant["defense_args"]["with_reputation"]
        self._reputation_metrics = self._config.participant["defense_args"]["reputation_metrics"]
        if isinstance(self._reputation_metrics, list):
            expected_metrics = [
                "model_similarity",
                "num_messages",
                "model_arrival_latency",
                "fraction_parameters_changed",
            ]
            self._reputation_metrics = {key: key in self._reputation_metrics for key in expected_metrics}
        self._initial_reputation = float(self._config.participant["defense_args"]["initial_reputation"])
        self._weighting_factor = self._config.participant["defense_args"]["weighting_factor"]
        self._weight_model_arrival_latency = float(
            self._config.participant["defense_args"]["weight_model_arrival_latency"]
        )
        self._weight_model_similarity = float(self._config.participant["defense_args"]["weight_model_similarity"])
        self._weight_num_messages = float(self._config.participant["defense_args"]["weight_num_messages"])
        self._weight_fraction_params_changed = float(
            self._config.participant["defense_args"]["weight_fraction_params_changed"]
        )

        msg = f"Reputation system: {self._with_reputation}"
        msg += f"\nReputation metrics: {self._reputation_metrics}"
        msg += f"\nInitial reputation: {self._initial_reputation}"
        msg += f"\nWeighting factor: {self._weighting_factor}"
        if self._weighting_factor == "static":
            msg += f"\nWeight model arrival latency: {self._weight_model_arrival_latency}"
            msg += f"\nWeight model similarity: {self._weight_model_similarity}"
            msg += f"\nWeight number of messages: {self._weight_num_messages}"
            msg += f"\nWeight fraction of parameters changed: {self._weight_fraction_params_changed}"
        print_msg_box(msg=msg, indent=2, title="Defense information")

    @property
    def engine(self):
        return self._engine

    def save_data(
        self,
        type_data,
        nei,
        addr,
        num_round=None,
        time=None,
        current_round=None,
        fraction_changed=None,
        threshold=None,
        latency=None,
    ):
        """
        Save data between nodes and aggregated models.
        """

        try:
            combined_data = {}

            if addr == nei:
                return

            if type_data == "number_message":
                combined_data["number_message"] = {
                    "time": time,
                    "current_round": current_round,
                }
            elif type_data == "fraction_of_params_changed":
                combined_data["fraction_of_params_changed"] = {
                    "fraction_changed": fraction_changed,
                    "threshold": threshold,
                    "current_round": current_round,
                }
            elif type_data == "model_arrival_latency":
                combined_data["model_arrival_latency"] = {
                    "latency": latency,
                    "round": num_round,
                    "round_received": current_round,
                }

            if nei in self.connection_metrics:
                if type_data == "number_message":
                    if not isinstance(self.connection_metrics[nei].messages, list):
                        self.connection_metrics[nei].messages = []
                    self.connection_metrics[nei].messages.append(combined_data["number_message"])
                elif type_data == "fraction_of_params_changed":
                    self.connection_metrics[nei].fraction_of_params_changed.update(
                        combined_data["fraction_of_params_changed"]
                    )
                elif type_data == "model_arrival_latency":
                    self.connection_metrics[nei].model_arrival_latency.update(combined_data["model_arrival_latency"])

        except Exception:
            logging.exception("Error saving data")

    async def setup(self):
        """
        Setup the reputation system by subscribing to various events.

        This function enables the reputation system and subscribes to events based on active metrics.
        """
        if self._with_reputation:
            logging.info("Reputation system enabled")
            await EventManager.get_instance().subscribe_node_event(RoundStartEvent, self.on_round_start)
            await EventManager.get_instance().subscribe_node_event(AggregationEvent, self.calculate_reputation)
            if self._reputation_metrics.get("model_similarity", False):
                await EventManager.get_instance().subscribe_node_event(UpdateReceivedEvent, self.recollect_similarity)
            if self._reputation_metrics.get("fraction_parameters_changed", False):
                await EventManager.get_instance().subscribe_node_event(
                    UpdateReceivedEvent, self.recollect_fraction_of_parameters_changed
                )
            if self._reputation_metrics.get("model_arrival_latency", False):
                await EventManager.get_instance().subscribe_node_event(
                    UpdateReceivedEvent, self.recollect_model_arrival_latency
                )
            if self._reputation_metrics.get("num_messages", False):
                await EventManager.get_instance().subscribe(("model", "update"), self.recollect_number_message)
                await EventManager.get_instance().subscribe(("model", "initialization"), self.recollect_number_message)
                await EventManager.get_instance().subscribe(("control", "alive"), self.recollect_number_message)
                await EventManager.get_instance().subscribe(
                    ("federation", "federation_models_included"), self.recollect_number_message
                )
                # await EventManager.get_instance().subscribe(("reputation", "share"), self.recollect_number_message)

    def init_reputation(
        self, addr, federation_nodes=None, round_num=None, last_feedback_round=None, init_reputation=None
    ):
        """
        Initialize the reputation system.
        """
        if not federation_nodes:
            logging.error("init_reputation | No federation nodes provided")
            return

        if self._with_reputation:
            neighbors = self.is_valid_ip(federation_nodes)

            if not neighbors:
                logging.error("init_reputation | No neighbors found")
                return

            for nei in neighbors:
                if nei not in self.reputation:
                    self.reputation[nei] = {
                        "reputation": init_reputation,
                        "round": round_num,
                        "last_feedback_round": last_feedback_round,
                    }
                elif self.reputation[nei].get("reputation") is None:
                    self.reputation[nei]["reputation"] = init_reputation
                    self.reputation[nei]["round"] = round_num
                    self.reputation[nei]["last_feedback_round"] = last_feedback_round

                avg_reputation = self.save_reputation_history_in_memory(self._addr, nei, init_reputation)

                metrics_data = {
                    "addr": addr,
                    "nei": nei,
                    "round": round_num,
                    "reputation_without_feedback": avg_reputation,
                }

                self.metrics(
                    metrics_data,
                    addr,
                    nei,
                    type="reputation",
                    update_field="reputation_without_feedback",
                )

    def is_valid_ip(self, federation_nodes):
        """
        Check if the IP addresses are valid.
        """
        valid_ip = []
        for i in federation_nodes:
            valid_ip.append(i)

        return valid_ip

    def _calculate_static_reputation(
        self,
        addr,
        nei,
        metric_messages_number,
        metric_similarity,
        metric_fraction,
        metric_model_arrival_latency,
        weight_messages_number,
        weight_similarity,
        weight_fraction,
        weight_model_arrival_latency,
    ):
        """
        Calculate the static reputation of a participant.

        Args:
            addr (str): The IP address of the participant.
            nei (str): The IP address of the participant.
            metric_messages_number (float): The number of messages.
            metric_similarity (float): The similarity between models.
            metric_fraction (float): The fraction of parameters changed.
            metric_model_arrival_latency (float): The model arrival latency.
            weight_messages_number (float): The weight of the number of messages.
            weight_similarity (float): The weight of the similarity.
            weight_fraction (float): The weight of the fraction.
            weight_model_arrival_latency (float): The weight of the model arrival latency.

        Returns:
            float: The static reputation of the participant.
        """

        static_weights = {
            "num_messages": weight_messages_number,
            "model_similarity": weight_similarity,
            "fraction_parameters_changed": weight_fraction,
            "model_arrival_latency": weight_model_arrival_latency,
        }

        metric_values = {
            "num_messages": metric_messages_number,
            "model_similarity": metric_similarity,
            "fraction_parameters_changed": metric_fraction,
            "model_arrival_latency": metric_model_arrival_latency,
        }

        reputation_static = sum(
            metric_values[metric_name] * static_weights[metric_name] for metric_name in static_weights
        )
        logging.info(f"Static reputation for node {nei} at round {self.engine.get_round()}: {reputation_static}")

        avg_reputation = self.save_reputation_history_in_memory(self.engine.addr, nei, reputation_static)

        metrics_data = {
            "addr": addr,
            "nei": nei,
            "round": self.engine.get_round(),
            "reputation_without_feedback": avg_reputation,
        }

        for metric_name in metric_values:
            metrics_data[f"average_{metric_name}"] = static_weights[metric_name]

        self._update_reputation_record(nei, avg_reputation, metrics_data)

    async def _calculate_dynamic_reputation(self, addr, neighbors):
        """
        Calculate the dynamic reputation of a participant.

        Args:
            addr (str): The IP address of the participant.
            neighbors (list): The list of neighbors.

        Returns:
            dict: The dynamic reputation of the participant.
        """
        average_weights = {}

        for metric_name in self.history_data.keys():
            if self._reputation_metrics.get(metric_name, False):
                valid_entries = [
                    entry
                    for entry in self.history_data[metric_name]
                    if entry["round"] >= self._engine.get_round() and entry.get("weight") not in [None, -1]
                ]

                if valid_entries:
                    average_weight = sum([entry["weight"] for entry in valid_entries]) / len(valid_entries)
                    average_weights[metric_name] = average_weight
                else:
                    average_weights[metric_name] = 0

        for nei in neighbors:
            metric_values = {}
            for metric_name in self.history_data.keys():
                if self._reputation_metrics.get(metric_name, False):
                    for entry in self.history_data.get(metric_name, []):
                        if (
                            entry["round"] == self._engine.get_round()
                            and entry["metric_name"] == metric_name
                            and entry["nei"] == nei
                        ):
                            metric_values[metric_name] = entry["metric_value"]
                            break

            if all(metric_name in metric_values for metric_name in average_weights):
                reputation_with_weights = sum(
                    metric_values.get(metric_name, 0) * average_weights[metric_name] for metric_name in average_weights
                )
                logging.info(
                    f"Dynamic reputation with weights for {nei} at round {self.engine.get_round()}: {reputation_with_weights}"
                )

                avg_reputation = self.save_reputation_history_in_memory(self.engine.addr, nei, reputation_with_weights)

                metrics_data = {
                    "addr": addr,
                    "nei": nei,
                    "round": self.engine.get_round(),
                    "reputation_without_feedback": avg_reputation,
                }

                for metric_name in metric_values:
                    metrics_data[f"average_{metric_name}"] = average_weights[metric_name]

                self._update_reputation_record(nei, avg_reputation, metrics_data)

    def _update_reputation_record(self, nei, reputation, data):
        """
        Update the reputation record of a participant.

        Args:
            nei (str): The IP address of the participant.
            reputation (float): The reputation of the participant.
            data (dict): The data to update.
        """
        if nei not in self.reputation:
            self.reputation[nei] = {
                "reputation": reputation,
                "round": self._engine.get_round(),
                "last_feedback_round": -1,
            }
        else:
            self.reputation[nei]["reputation"] = reputation
            self.reputation[nei]["round"] = self._engine.get_round()

        logging.info(f"Reputation of node {nei}: {self.reputation[nei]['reputation']}")
        # if self.reputation[nei]["reputation"] < 0.75:
        if self.reputation[nei]["reputation"] < 0.6 and self._engine.get_round() > 0:
            self.rejected_nodes.add(nei)
            logging.info(f"Rejected node {nei} at round {self._engine.get_round()}")

        self.metrics(
            data,
            self._addr,
            nei,
            type="reputation",
            update_field="reputation_without_feedback",
        )

    def calculate_weighted_values(
        self,
        avg_messages_number_message_normalized,
        similarity_reputation,
        fraction_score_asign,
        avg_model_arrival_latency,
        history_data,
        current_round,
        addr,
        nei,
        reputation_metrics,
    ):
        """
        Calculate the weighted values for each metric.
        """
        if current_round is not None:
            normalized_weights = {}
            required_keys = [
                "num_messages",
                "model_similarity",
                "fraction_parameters_changed",
                "model_arrival_latency",
            ]

            for key in required_keys:
                if key not in history_data:
                    history_data[key] = []

            metrics = {
                "num_messages": avg_messages_number_message_normalized,
                "model_similarity": similarity_reputation,
                "fraction_parameters_changed": fraction_score_asign,
                "model_arrival_latency": avg_model_arrival_latency,
            }

            active_metrics = {k: v for k, v in metrics.items() if reputation_metrics.get(k, False)}
            num_active_metrics = len(active_metrics)

            for metric_name, current_value in active_metrics.items():
                history_data[metric_name].append({
                    "round": current_round,
                    "addr": addr,
                    "nei": nei,
                    "metric_name": metric_name,
                    "metric_value": current_value,
                    "weight": None,
                })

            adjusted_weights = {}

            if current_round >= 1 and num_active_metrics > 0:
                desviations = {}
                for metric_name, current_value in active_metrics.items():
                    historical_values = history_data[metric_name]

                    metric_values = [
                        entry["metric_value"]
                        for entry in historical_values
                        if "metric_value" in entry and entry["metric_value"] != 0
                    ]

                    if metric_values:
                        mean_value = np.mean(metric_values)
                    else:
                        mean_value = 0

                    deviation = abs(current_value - mean_value)
                    desviations[metric_name] = deviation

                if all(deviation == 0.0 for deviation in desviations.values()):
                    random_weights = [random.random() for _ in range(num_active_metrics)]
                    total_random_weight = sum(random_weights)
                    normalized_weights = {
                        metric_name: weight / total_random_weight
                        for metric_name, weight in zip(active_metrics, random_weights, strict=False)
                    }
                else:
                    max_desviation = max(desviations.values()) if desviations else 1
                    normalized_weights = {
                        metric_name: (desviation / max_desviation) for metric_name, desviation in desviations.items()
                    }

                    total_weight = sum(normalized_weights.values())
                    if total_weight > 0:
                        normalized_weights = {
                            metric_name: weight / total_weight for metric_name, weight in normalized_weights.items()
                        }
                    else:
                        normalized_weights = {metric_name: 1 / num_active_metrics for metric_name in active_metrics}

                mean_deviation = np.mean(list(desviations.values()))
                dynamic_min_weight = max(0.1, mean_deviation / (mean_deviation + 1))

                total_adjusted_weight = 0

                for metric_name, weight in normalized_weights.items():
                    if weight < dynamic_min_weight:
                        adjusted_weights[metric_name] = dynamic_min_weight
                    else:
                        adjusted_weights[metric_name] = weight
                    total_adjusted_weight += adjusted_weights[metric_name]

                if total_adjusted_weight > 1:
                    for metric_name in adjusted_weights:
                        adjusted_weights[metric_name] /= total_adjusted_weight
                    total_adjusted_weight = 1
            else:
                adjusted_weights = {metric_name: 1 / num_active_metrics for metric_name in active_metrics}

            for metric_name, current_value in active_metrics.items():
                weight = adjusted_weights.get(metric_name, -1)
                for entry in history_data[metric_name]:
                    if entry["metric_name"] == metric_name and entry["round"] == current_round and entry["nei"] == nei:
                        entry["weight"] = weight

    async def calculate_value_metrics(self, addr, nei, metrics_active=None):
        """
        Calculate the reputation of each participant based on the data stored in self.connection_metrics.

        Args:
            addr (str): Source IP address.
            nei (str): Destination IP address.
            metrics_active (dict): The active metrics.
        """

        messages_number_message_normalized = 0
        messages_number_message_count = 0
        avg_messages_number_message_normalized = 0
        score_fraction = 0
        fraction_score_asign = 0
        messages_model_arrival_latency_normalized = 0
        avg_model_arrival_latency = 0
        similarity_reputation = 0
        fraction_neighbors_scores = None

        try:
            current_round = self._engine.get_round()
            metrics_instance = self.connection_metrics.get(nei)
            if not metrics_instance:
                logging.warning(f"No metrics found for neighbor {nei}")
                return (
                    avg_messages_number_message_normalized,
                    similarity_reputation,
                    fraction_score_asign,
                    avg_model_arrival_latency,
                )

            if metrics_active.get("num_messages", False):
                filtered_messages = [
                    msg for msg in metrics_instance.messages if msg.get("current_round") == current_round
                ]
                for msg in filtered_messages:
                    self.messages_number_message.append({
                        "number_message": msg.get("time"),
                        "current_round": msg.get("current_round"),
                        "key": (addr, nei),
                    })

                messages_number_message_normalized, messages_number_message_count = self.manage_metric_number_message(
                    self.messages_number_message, addr, nei, current_round, True
                )
                avg_messages_number_message_normalized = self.save_number_message_history(
                    addr, nei, messages_number_message_normalized, current_round
                )
                if avg_messages_number_message_normalized is None and current_round > 4:
                    avg_messages_number_message_normalized = self.number_message_history[(addr, nei)][
                        current_round - 1
                    ]["avg_number_message"]

            if metrics_active.get("fraction_parameters_changed", False):
                if metrics_instance.fraction_of_params_changed.get("current_round") == current_round:
                    fraction_changed = metrics_instance.fraction_of_params_changed.get("fraction_changed")
                    threshold = metrics_instance.fraction_of_params_changed.get("threshold")
                    current_round = metrics_instance.fraction_of_params_changed.get("current_round")
                    score_fraction = self.analyze_anomalies(
                        addr,
                        nei,
                        current_round,
                        fraction_changed,
                        threshold,
                    )

                if current_round >= 1:
                    key_current = (addr, nei, current_round)

                    if score_fraction > 0:
                        past_scores = []
                        for i in range(1, 5):
                            key_prev = (addr, nei, current_round - i)
                            score_prev = self.fraction_changed_history.get(key_prev, {}).get("finally_fraction_score")
                            if score_prev is not None and score_prev > 0:
                                past_scores.append(score_prev)

                        if past_scores:
                            avg_past = sum(past_scores) / len(past_scores)
                            fraction_score_asign = score_fraction * 0.2 + avg_past * 0.8
                        else:
                            fraction_score_asign = score_fraction

                        self.fraction_changed_history[key_current]["finally_fraction_score"] = fraction_score_asign

                    else:
                        key_prev = (addr, nei, current_round - 1)
                        prev_score = self.fraction_changed_history.get(key_prev, {}).get("finally_fraction_score")

                        if prev_score is not None:
                            fraction_score_asign = prev_score * 0.1
                        else:
                            if fraction_neighbors_scores is None:
                                fraction_neighbors_scores = {}

                            for key, value in self.fraction_changed_history.items():
                                score = value.get("finally_fraction_score")
                                if score is not None:
                                    fraction_neighbors_scores[key] = score

                            fraction_score_asign = (
                                np.mean(list(fraction_neighbors_scores.values())) if fraction_neighbors_scores else 0
                            )

                        if key_current not in self.fraction_changed_history:
                            self.fraction_changed_history[key_current] = {}

                        self.fraction_changed_history[key_current]["finally_fraction_score"] = fraction_score_asign
                else:
                    fraction_score_asign = 0

            if metrics_active.get("model_arrival_latency", False):
                if metrics_instance.model_arrival_latency.get("round_received") == current_round:
                    round_num = metrics_instance.model_arrival_latency.get("round")
                    latency = metrics_instance.model_arrival_latency.get("latency")
                    messages_model_arrival_latency_normalized = self.manage_model_arrival_latency(
                        addr, nei, latency, current_round, round_num
                    )

                if messages_model_arrival_latency_normalized >= 0:
                    avg_model_arrival_latency = self.save_model_arrival_latency_history(
                        nei, messages_model_arrival_latency_normalized, current_round
                    )
                    if avg_model_arrival_latency is None and current_round > 4:
                        avg_model_arrival_latency = self.model_arrival_latency_history[(addr, nei)][current_round - 1][
                            "score"
                        ]

            if current_round >= 1 and metrics_active.get("model_similarity", False):
                similarity_reputation = self.calculate_similarity_from_metrics(nei, current_round)
            else:
                similarity_reputation = 0

            self.create_graphics_to_metrics(
                messages_number_message_count,
                avg_messages_number_message_normalized,
                similarity_reputation,
                fraction_score_asign,
                avg_model_arrival_latency,
                addr,
                nei,
                current_round,
                self.engine.total_rounds,
            )

            return (
                avg_messages_number_message_normalized,
                similarity_reputation,
                fraction_score_asign,
                avg_model_arrival_latency,
            )
        except Exception as e:
            logging.exception(f"Error calculating reputation. Type: {type(e).__name__}")
            return 0, 0, 0, 0

    def create_graphics_to_metrics(
        self,
        number_message_count,
        number_message_norm,
        similarity,
        fraction,
        model_arrival_latency,
        addr,
        nei,
        current_round,
        total_rounds,
    ):
        """
        Create graphics to metrics.
        """

        if current_round is not None and current_round < total_rounds:
            model_arrival_latency_dict = {f"R-Model_arrival_latency_reputation/{addr}": {nei: model_arrival_latency}}
            messages_number_message_count_dict = {
                f"R-Count_messages_number_message_reputation/{addr}": {nei: number_message_count}
            }
            messages_number_message_norm_dict = {f"R-number_message_reputation/{addr}": {nei: number_message_norm}}
            similarity_dict = {f"R-Similarity_reputation/{addr}": {nei: similarity}}
            fraction_dict = {f"R-Fraction_reputation/{addr}": {nei: fraction}}

            if messages_number_message_count_dict is not None:
                self.engine.trainer._logger.log_data(messages_number_message_count_dict, step=current_round)

            if messages_number_message_norm_dict is not None:
                self.engine.trainer._logger.log_data(messages_number_message_norm_dict, step=current_round)

            if similarity_dict is not None:
                self.engine.trainer._logger.log_data(similarity_dict, step=current_round)

            if fraction_dict is not None:
                self.engine.trainer._logger.log_data(fraction_dict, step=current_round)

            if model_arrival_latency_dict is not None:
                self.engine.trainer._logger.log_data(model_arrival_latency_dict, step=current_round)

            data = {
                "addr": addr,
                "nei": nei,
                "round": current_round,
                "number_message_count": number_message_count,
                "number_message_norm": number_message_norm,
                "similarity": similarity,
                "fraction": fraction,
                "model_arrival_latency": model_arrival_latency,
            }
            self.metrics(data, addr, nei, type="reputation")

    def analyze_anomalies(
        self,
        addr,
        nei,
        current_round,
        fraction_changed,
        threshold,
    ):
        """
        Analyze anomalies in the fraction of parameters changed.

        Returns:
            float: The fraction score between 0 and 1.
        """
        try:
            key = (addr, nei, current_round)
            penalization_factor_fraction = 0.0
            penalization_factor_threshold = 0.0

            if key not in self.fraction_changed_history:
                self.fraction_changed_history[key] = {
                    "fraction_changed": fraction_changed or 0,
                    "threshold": threshold or 0,
                    "fraction_score": None,
                    "fraction_anomaly": False,
                    "threshold_anomaly": False,
                    "mean_fraction": None,
                    "std_dev_fraction": None,
                    "mean_threshold": None,
                    "std_dev_threshold": None,
                }

            current_fraction = self.fraction_changed_history[key]["fraction_changed"]
            current_threshold = self.fraction_changed_history[key]["threshold"]
            if current_round == 0:
                self.fraction_changed_history[key].update({
                    "mean_fraction": current_fraction,
                    "std_dev_fraction": 0.0,
                    "mean_threshold": current_threshold,
                    "std_dev_threshold": 0.0,
                    "fraction_score": 1.0,
                })

                mean_fraction_prev = current_fraction
                std_dev_fraction_prev = 0.0
                mean_threshold_prev = current_threshold
                std_dev_threshold_prev = 0.0
                upper_mean_fraction_prev = None
                upper_mean_threshold_prev = None
                fraction_anomaly = False
                threshold_anomaly = False
                fraction_value = 1.0
                threshold_value = 1.0
                fraction_score = 1.0

            else:
                prev_key = None
                for i in range(1, current_round + 1):
                    candidate_key = (addr, nei, current_round - i)
                    candidate_data = self.fraction_changed_history.get(candidate_key, {})
                    if all(
                        candidate_data.get(k) is not None
                        for k in ["mean_fraction", "std_dev_fraction", "mean_threshold", "std_dev_threshold"]
                    ):
                        prev_key = candidate_key
                        break

                if prev_key is None:
                    logging.warning(f"No valid previous stats found for {addr}, {nei}, round {current_round}")
                else:
                    prev_data = self.fraction_changed_history[prev_key]
                    mean_fraction_prev = prev_data.get("mean_fraction")
                    std_dev_fraction_prev = prev_data.get("std_dev_fraction")
                    mean_threshold_prev = prev_data.get("mean_threshold")
                    std_dev_threshold_prev = prev_data.get("std_dev_threshold")

                    upper_mean_fraction_prev = (mean_fraction_prev + std_dev_fraction_prev) * 1.20
                    upper_mean_threshold_prev = (mean_threshold_prev + std_dev_threshold_prev) * 1.15

                    fraction_anomaly = current_fraction > upper_mean_fraction_prev
                    threshold_anomaly = current_threshold > upper_mean_threshold_prev

                    self.fraction_changed_history[key]["fraction_anomaly"] = fraction_anomaly
                    self.fraction_changed_history[key]["threshold_anomaly"] = threshold_anomaly

                    if fraction_anomaly:
                        penalization_factor_fraction = (
                            abs(current_fraction - mean_fraction_prev) / mean_fraction_prev if mean_fraction_prev else 1
                        )
                        fraction_value = 1 - (1 / (1 + np.exp(-penalization_factor_fraction)))
                    else:
                        fraction_value = 1.0

                    if threshold_anomaly:
                        penalization_factor_threshold = (
                            abs(current_threshold - mean_threshold_prev) / mean_threshold_prev
                            if mean_threshold_prev
                            else 1
                        )
                        threshold_value = 1 - (1 / (1 + np.exp(-penalization_factor_threshold)))
                    else:
                        threshold_value = 1.0

                    fraction_weight = 0.5
                    threshold_weight = 0.5
                    fraction_score = fraction_weight * fraction_value + threshold_weight * threshold_value

                    self.fraction_changed_history[key]["mean_fraction"] = (current_fraction + mean_fraction_prev) / 2
                    self.fraction_changed_history[key]["std_dev_fraction"] = np.sqrt(
                        ((current_fraction - mean_fraction_prev) ** 2 + std_dev_fraction_prev**2) / 2
                    )
                    self.fraction_changed_history[key]["std_dev_fraction"] = np.sqrt(
                        ((current_fraction - mean_fraction_prev) ** 2 + std_dev_fraction_prev**2) / 2
                    )
                    self.fraction_changed_history[key]["mean_threshold"] = (current_threshold + mean_threshold_prev) / 2
                    self.fraction_changed_history[key]["std_dev_threshold"] = np.sqrt(
                        ((0.1 * (current_threshold - mean_threshold_prev) ** 2) + std_dev_threshold_prev**2) / 2
                    )
                    self.fraction_changed_history[key]["fraction_score"] = fraction_score

            data = {
                "addr": addr,
                "nei": nei,
                "current_round": current_round,
                "fraction_changed": current_fraction,
                "threshold": current_threshold,
                "mean_fraction": mean_fraction_prev,
                "std_dev_fraction": std_dev_fraction_prev,
                "mean_threshold": mean_threshold_prev,
                "std_dev_threshold": std_dev_threshold_prev,
                "upper_mean_fraction": upper_mean_fraction_prev,
                "upper_mean_threshold": upper_mean_threshold_prev,
                "fraction_anomaly": fraction_anomaly,
                "threshold_anomaly": threshold_anomaly,
                "penalization_factor_fraction": penalization_factor_fraction or 0,
                "penalization_factor_threshold": penalization_factor_threshold or 0,
                "fraction_value": fraction_value,
                "threshold_value": threshold_value,
                "fraction_score": fraction_score,
            }

            self.metrics(data, addr, nei, type="fraction_changed")
            return max(fraction_score, 0)

        except Exception:
            logging.exception("Error analyzing anomalies")
            return -1

    def manage_model_arrival_latency(self, addr, nei, latency, current_round, round_num):
        """
        Manage the model_arrival_latency metric using latency.

        Args:
            addr (str): Source IP address.
            nei (str): Destination IP address.
            latency (float): Latency value for the current model_arrival_latency.
            current_round (int): The current round of the program.
            round_num (int): The round number of the model_arrival_latency.

        Returns:
            float: Normalized score between 0 and 1 for model_arrival_latency.
        """
        try:
            current_key = nei

            if current_round not in self.model_arrival_latency_history:
                self.model_arrival_latency_history[current_round] = {}

            self.model_arrival_latency_history[current_round][current_key] = {
                "latency": latency,
                "score": 0.0,
            }

            mean_latency = 0
            difference = 0

            if current_round >= 1:
                target_round = (
                    current_round - 1 if (current_round - 1) in self.model_arrival_latency_history else current_round
                )

                all_latencies = [
                    data["latency"]
                    for data in self.model_arrival_latency_history.get(target_round, {}).values()
                    if data.get("latency") not in (None, 0.0)
                ]

                mean_latency = np.mean(all_latencies) if all_latencies else 0
                aument_mean = mean_latency * 1.4
                if latency is not None:
                    difference = latency - mean_latency
                    if latency <= aument_mean:
                        score = 1.0
                    else:
                        score = 1 / (1 + np.exp(abs(difference) / mean_latency)) if mean_latency != 0 else 0.0
                else:
                    logging.info(f"latency is None in round {current_round} for nei {nei}")
                    score = -0.5

                self.model_arrival_latency_history[current_round][current_key].update({
                    "mean_latency": mean_latency,
                    "score": score,
                })
            else:
                score = 0

            data = {
                "addr": addr,
                "nei": nei,
                "round": round_num,
                "current_round": current_round,
                "latency": latency,
                "mean_latency": mean_latency if current_round >= 1 else None,
                "aument_latency": aument_mean if current_round >= 1 else None,
                "difference": difference if current_round >= 1 else None,
                "score": score,
            }

            self.metrics(data, addr, nei, type="model_arrival_latency")

            return score

        except Exception as e:
            logging.exception(f"Error managing model_arrival_latency: {e}")
            return 0

    def save_model_arrival_latency_history(self, nei, model_arrival_latency, round_num):
        """
        Save the model_arrival_latency history of a participant (addr) regarding its neighbor (nei) in memory.
        Use 3 rounds for the average.
        Args:
            nei (str): The neighboring node involved.
            model_arrival_latency (float): The model_arrival_latency value to be saved.
            round_num (int): The current round number.

        Returns:
            float: The smoothed average model_arrival_latency including the current round.
        """
        try:
            current_key = nei

            if round_num not in self.model_arrival_latency_history:
                self.model_arrival_latency_history[round_num] = {}

            if current_key not in self.model_arrival_latency_history[round_num]:
                self.model_arrival_latency_history[round_num][current_key] = {}

            self.model_arrival_latency_history[round_num][current_key].update({
                "score": model_arrival_latency,
            })

            if model_arrival_latency > 0 and round_num >= 1:
                past_values = []
                for r in range(round_num - 3, round_num):
                    val = (
                        self.model_arrival_latency_history.get(r, {})
                        .get(current_key, {})
                        .get("avg_model_arrival_latency", None)
                    )
                    if val is not None and val != 0:
                        past_values.append(val)

                if past_values:
                    avg_past = sum(past_values) / len(past_values)
                    avg_model_arrival_latency = model_arrival_latency * 0.2 + avg_past * 0.8
                else:
                    avg_model_arrival_latency = model_arrival_latency
            elif model_arrival_latency == 0 and round_num >= 1:
                previous_avg = (
                    self.model_arrival_latency_history.get(round_num - 1, {})
                    .get(current_key, {})
                    .get("avg_model_arrival_latency", None)
                )
                avg_model_arrival_latency = previous_avg * 0.1 if previous_avg is not None else 0
            elif model_arrival_latency < 0 and round_num >= 1:
                avg_model_arrival_latency = abs(model_arrival_latency) * 0.3
            else:
                avg_model_arrival_latency = 0

            self.model_arrival_latency_history[round_num][current_key]["avg_model_arrival_latency"] = (
                avg_model_arrival_latency
            )

            return avg_model_arrival_latency
        except Exception:
            logging.exception("Error saving model_arrival_latency history")

    def manage_metric_number_message(
        self, messages_number_message: list, addr: str, nei: str, current_round: int, metric_active: bool = True
    ) -> tuple[float, int]:
        try:
            if current_round == 0 or not metric_active:
                return 0.0, 0

            current_addr_nei = (addr, nei)

            relevant_messages = [
                msg
                for msg in messages_number_message
                if msg["key"] == current_addr_nei and msg["current_round"] == current_round
            ]
            messages_count = len(relevant_messages)

            previous_round = current_round - 1
            all_messages_previous_round = [
                m for m in messages_number_message if m.get("current_round") == previous_round
            ]

            neighbor_counts = {}
            for m in all_messages_previous_round:
                key = m.get("key")
                neighbor_counts[key] = neighbor_counts.get(key, 0) + 1

            counts_all_neighbors = list(neighbor_counts.values())

            percentile_reference = np.percentile(counts_all_neighbors, 25) if counts_all_neighbors else 0
            std_dev = np.std(counts_all_neighbors) if counts_all_neighbors else 0
            mean_messages_all_neighbors = np.mean(counts_all_neighbors) if counts_all_neighbors else 0
            aument_mean = mean_messages_all_neighbors * 2 if current_round <= 3 else mean_messages_all_neighbors * 1.1
            # aument_mean =  mean_messages_all_neighbors * 1.8 if current_round <= 1 else mean_messages_all_neighbors * 1.1

            relative_increase = (
                (messages_count - percentile_reference) / percentile_reference if percentile_reference > 0 else 0
            )
            dynamic_margin = (std_dev + 1) / (np.log1p(percentile_reference) + 1)

            normalized_messages = 1.0
            was_penalized = False
            if relative_increase > dynamic_margin:
                penalty_ratio = np.log1p(relative_increase - dynamic_margin) / (np.log1p(dynamic_margin + 1e-6) + 1e-6)
                normalized_messages *= np.exp(-(penalty_ratio**2))

            extra_penalty = 0.0
            if mean_messages_all_neighbors > 0 and messages_count > aument_mean:
                extra_penalty = (messages_count - mean_messages_all_neighbors) / (mean_messages_all_neighbors + 1e-6)
                amplification = 1 + (aument_mean / (mean_messages_all_neighbors + 1e-6))
                normalized_messages *= np.exp(-((extra_penalty * amplification) ** 2))

            if was_penalized and current_round > 1:
                prev_score = (
                    self.number_message_history.get((addr, nei), {})
                    .get(current_round - 1, {})
                    .get("normalized_messages")
                )
                if prev_score is not None and prev_score < 0.9:
                    normalized_messages *= 0.9

            normalized_messages = max(0.001, normalized_messages)

            if (addr, nei) not in self.number_message_history:
                self.number_message_history[(addr, nei)] = {}
            self.number_message_history[(addr, nei)][current_round] = {"normalized_messages": normalized_messages}

            normalized_messages = max(0.001, normalized_messages)

            data = {
                "addr": addr,
                "nei": nei,
                "round": current_round,
                "messages_count": messages_count,
                "percentile_reference": percentile_reference,
                "dynamic_margin": dynamic_margin,
                "relative_increase": relative_increase,
                "std_dev": std_dev,
                "mean_all_neighbors": mean_messages_all_neighbors,
                "aument_mean": aument_mean,
                "extra_penalty": extra_penalty,
                "normalized_messages": normalized_messages,
            }
            self.metrics(data, addr, nei, type="number_message")

            return normalized_messages, messages_count

        except Exception:
            logging.exception("Error managing metric number_message")
            return 0.0, 0

    def save_number_message_history(self, addr, nei, messages_number_message_normalized, current_round):
        """
        Save the number_message history of a participant (addr) regarding its neighbor (nei) in memory.
        Uses a weighted average of the past 3 rounds to smooth the result.

        Returns:
            float: The weighted average including the current round.
        """
        try:
            key = (addr, nei)
            avg_number_message = 0

            if key not in self.number_message_history:
                self.number_message_history[key] = {}

            if current_round not in self.number_message_history[key]:
                self.number_message_history[key][current_round] = {}

            self.number_message_history[key][current_round].update({
                "number_message": messages_number_message_normalized,
            })

            if messages_number_message_normalized > 0 and current_round >= 1:
                past_values = []
                for r in range(current_round - 3, current_round):
                    val = self.number_message_history.get(key, {}).get(r, {}).get("avg_number_message", None)
                    if val is not None and val != 0:
                        past_values.append(val)

                if past_values:
                    avg_past = sum(past_values) / len(past_values)
                    # avg_number_message = messages_number_message_normalized * 0.9 + avg_past * 0.1
                    avg_number_message = messages_number_message_normalized * 0.1 + avg_past * 0.9
                else:
                    avg_number_message = messages_number_message_normalized
            elif messages_number_message_normalized == 0 and current_round >= 1:
                previous_avg = (
                    self.number_message_history.get(key, {}).get(current_round - 1, {}).get("avg_number_message", None)
                )
                avg_number_message = previous_avg * 0.1 if previous_avg is not None else 0
            elif messages_number_message_normalized < 0 and current_round >= 1:
                avg_number_message = abs(messages_number_message_normalized) * 0.3
            else:
                avg_number_message = 0

            self.number_message_history[key][current_round]["avg_number_message"] = avg_number_message

            return avg_number_message
        except Exception:
            logging.exception("Error saving number_message history")
            return -1

    def save_reputation_history_in_memory(self, addr, nei, reputation):
        """
        Save the reputation history of a participant (addr) regarding its neighbor (nei) in memory
        and calculate the average reputation.

        Args:
            addr (str): The identifier of the node whose reputation is being saved.
            nei (str): The neighboring node involved.
            reputation (float): The reputation value to be saved.

        Returns:
            float: The cumulative reputation including the current round.
        """
        try:
            key = (addr, nei)

            if key not in self.reputation_history:
                self.reputation_history[key] = {}

            self.reputation_history[key][self._engine.get_round()] = reputation
            avg_reputation = 0

            # With the last 3 rounds
            # rounds = sorted(self.reputation_history[key].keys(), reverse=True)[:3]
            # if len(rounds) >= 3:
            #     selected_rounds = rounds[:3]
            #     weights = [0.5, 0.3, 0.2]
            # elif len(rounds) == 2:
            #     selected_rounds = rounds[:2]
            #     weights = [0.6, 0.4] if selected_rounds[0] > selected_rounds[1] else [0, 0]
            # elif len(rounds) == 1:
            #     selected_rounds = rounds
            #     weights = [1.0]
            # else:
            #     return 0  # No reputation to average

            # values = [self.reputation_history[key][r] for r in selected_rounds]
            # avg_reputation = sum(v * w for v, w in zip(values, weights)) / sum(weights)

            # return avg_reputation

            # With the last 2 rounds
            rounds = sorted(self.reputation_history[key].keys(), reverse=True)[:2]
            current_round = self._engine.get_round()
            if len(rounds) >= 2:
                current_round = rounds[0]
                previous_round = rounds[1]

                current_rep = self.reputation_history[key][current_round]
                previous_rep = self.reputation_history[key][previous_round]
                logging.info(f"Current reputation: {current_rep}, Previous reputation: {previous_rep}")

                avg_reputation = (current_rep * 0.9) + (previous_rep * 0.1)
                logging.info(f"Reputation ponderated: {avg_reputation}")
            else:
                avg_reputation = self.reputation_history[key][current_round]
            return avg_reputation

            # for i, n_round in enumerate(rounds, start=1):
            #     rep = self.reputation_history[key][n_round]
            #     decay_factor = self.calculate_decay_rate(rep) ** i
            #     total_reputation += rep * decay_factor
            #     total_weights += decay_factor
            #     logging.info(
            #         f"Round: {n_round}, Reputation: {rep}, Decay: {decay_factor}, Total reputation: {total_reputation}"
            #     )

            # avg_reputation = total_reputation / total_weights
            # if total_weights > 0:
            #     return avg_reputation
            # else:
            #     return -1

        except Exception:
            logging.exception("Error saving reputation history")
            return -1

    def calculate_decay_rate(self, reputation):
        """
        Calculate the decay rate for a reputation value.

        Args:
            reputation (float): Reputation value.

        Returns:
            float: Decay rate.
        """

        if reputation > 0.8:
            return 0.9  # Very low decay
        elif reputation > 0.7:
            return 0.8  # Medium decay
        elif reputation > 0.6:
            return 0.6  # Low decay
        elif reputation > 0.4:
            return 0.2  # High decay
        else:
            return 0.1  # Very high decay

    def calculate_similarity_from_metrics(self, nei, current_round):
        """
        Calculate the similarity value from the stored metrics in the 'similarity'
        attribute of the Metrics instance for the given neighbor (nei) and current round.

        Args:
            nei (str): The IP address of the neighbor.
            current_round (int): The current round number.

        Returns:
            float: The computed similarity value.
        """
        similarity_value = 0.0

        metrics_instance = self.connection_metrics.get(nei)
        if metrics_instance is None:
            logging.error(f"No metrics instance found for neighbor {nei}")
            return similarity_value

        for metric in metrics_instance.similarity:
            source_ip = metric.get("nei")
            round_in_metric = metric.get("round")

            # if source_ip == nei and round_in_metric == current_round:
            if source_ip == nei:
                weight_cosine = 0.25
                weight_euclidean = 0.25
                weight_manhattan = 0.25
                weight_pearson = 0.25

                cosine = float(metric.get("cosine", 0))
                euclidean = float(metric.get("euclidean", 0))
                manhattan = float(metric.get("manhattan", 0))
                pearson_correlation = float(metric.get("pearson_correlation", 0))

                similarity_value = (
                    weight_cosine * cosine
                    + weight_euclidean * euclidean
                    + weight_manhattan * manhattan
                    + weight_pearson * pearson_correlation
                )

        return similarity_value

    def metrics(self, data, addr, nei, type, update_field=None):
        current_dir = os.path.join(self._log_dir, "reputation")
        csv_path = os.path.join(current_dir, "metrics", type, f"{addr}_{nei}_{type}.csv")
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)

        if type != "reputation":
            try:
                with open(csv_path, mode="a", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=data.keys())
                    if file.tell() == 0:
                        writer.writeheader()
                    writer.writerow(data)
            except Exception:
                logging.exception("Error saving messages number_message data to CSV")
        else:
            rows = []
            updated = False

            fieldnames = [
                "addr",
                "nei",
                "round",
                "number_message_count",
                "number_message_norm",
                "similarity",
                "fraction",
                "model_arrival_latency",
                "reputation_without_feedback",
                "reputation_with_feedback",
                "average_model_arrival_latency",
                "average_model_similarity",
                "average_fraction_parameters_changed",
                "average_num_messages",
            ]

            if os.path.exists(csv_path):
                with open(csv_path, newline="") as file:
                    rows = list(csv.DictReader(file))

                if update_field:
                    for row in rows:
                        if int(row["round"]) == int(data["round"]):
                            row.update(data)
                            updated = True
                            break

            if not updated:
                rows.append(data)

            with open(csv_path, mode="w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

    async def calculate_reputation(self, ae: AggregationEvent):
        """
        Calculate the reputation of the node based on the active metrics.

        Args:
            ae (AggregationEvent): The aggregation event.
        """
        (updates, _, _) = await ae.get_event_data()
        if self._with_reputation:
            logging.info(f"Calculating reputation at round {self._engine.get_round()}")
            logging.info(f"Active metrics: {self._reputation_metrics}")
            logging.info(f"rejected nodes at round {self._engine.get_round()}: {self.rejected_nodes}")
            self.rejected_nodes.clear()
            logging.info(f"Rejected nodes clear: {self.rejected_nodes}")

            neighbors = set(await self._engine._cm.get_addrs_current_connections(only_direct=True))
            history_data = self.history_data

            for nei in neighbors:
                (
                    metric_messages_number,
                    metric_similarity,
                    metric_fraction,
                    metric_model_arrival_latency,
                ) = await self.calculate_value_metrics(
                    self._addr,
                    nei,
                    metrics_active=self._reputation_metrics,
                )

                if self._weighting_factor == "dynamic":
                    self.calculate_weighted_values(
                        metric_messages_number,
                        metric_similarity,
                        metric_fraction,
                        metric_model_arrival_latency,
                        history_data,
                        self._engine.get_round(),
                        self._addr,
                        nei,
                        self._reputation_metrics,
                    )

                if self._weighting_factor == "static" and self._engine.get_round() >= 1:
                    self._calculate_static_reputation(
                        self._addr,
                        nei,
                        metric_messages_number,
                        metric_similarity,
                        metric_fraction,
                        metric_model_arrival_latency,
                        self._weight_num_messages,
                        self._weight_model_similarity,
                        self._weight_fraction_params_changed,
                        self._weight_model_arrival_latency,
                    )

            if self._weighting_factor == "dynamic" and self._engine.get_round() >= 1:
                await self._calculate_dynamic_reputation(self._addr, neighbors)

            if self._engine.get_round() < 1 and self._with_reputation:
                federation = self._engine.config.participant["network_args"]["neighbors"].split()
                self.init_reputation(
                    self._addr,
                    federation_nodes=federation,
                    round_num=self._engine.get_round(),
                    last_feedback_round=-1,
                    init_reputation=self._initial_reputation,
                )

            status = await self.include_feedback_in_reputation()
            if status:
                logging.info(f"Feedback included in reputation at round {self._engine.get_round()}")
            else:
                logging.info(f"Feedback not included in reputation at round {self._engine.get_round()}")

            if self.reputation is not None:
                self.create_graphic_reputation(
                    self._addr,
                    self._engine.get_round(),
                )

                await self.update_process_aggregation(updates)
                await self.send_reputation_to_neighbors(neighbors)

    async def send_reputation_to_neighbors(self, neighbors):
        """
        Send the calculated reputation to the neighbors.
        """
        for nei, data in self.reputation.items():
            if data["reputation"] is not None:
                neighbors_to_send = [neighbor for neighbor in neighbors if neighbor != nei]

                for neighbor in neighbors_to_send:
                    message = self._engine.cm.create_message(
                        "reputation",
                        "share",
                        node_id=nei,
                        score=float(data["reputation"]),
                        round=self._engine.get_round(),
                    )
                    await self._engine.cm.send_message(neighbor, message)
                    logging.info(
                        f"Sending reputation to node {nei} from node {neighbor} with reputation {data['reputation']}"
                    )

                metrics_data = {
                    "addr": self._addr,
                    "nei": nei,
                    "round": self._engine.get_round(),
                    "reputation_with_feedback": data["reputation"],
                }

                self.metrics(
                    metrics_data,
                    self._addr,
                    nei,
                    type="reputation",
                    update_field="reputation_with_feedback",
                )

    def create_graphic_reputation(self, addr, round_num):
        """
        Create a graphic with the reputation of a node in a specific round.
        """
        try:
            reputation_dict_with_values = {
                f"Reputation/{addr}": {
                    node_id: float(data["reputation"])
                    for node_id, data in self.reputation.items()
                    if data["reputation"] is not None
                }
            }

            logging.info(f"Reputation dict: {reputation_dict_with_values}")
            self._engine.trainer._logger.log_data(reputation_dict_with_values, step=round_num)

        except Exception:
            logging.exception("Error creating reputation graphic")

    async def update_process_aggregation(self, updates):
        """
        Update the process of aggregation by removing rejected nodes from the updates and
        scaling the weights of the models based on their reputation.
        """
        # Reject node if the reputation is below 0.6 from the updates
        for rn in self.rejected_nodes:
            if rn in updates:
                updates.pop(rn)

        # Scale the model weights based on the reputation of the nodes
        if self.engine.get_round() >= 1:
            for nei in list(updates.keys()):
                if nei in self.reputation:
                    rep = self.reputation[nei].get("reputation", 0)
                    if rep >= 0.6:
                        weight = (rep - 0.6) / (1.0 - 0.6)
                        model_dict = updates[nei][0]
                        extra_data = updates[nei][1]

                        scaled_model = {k: v * weight for k, v in model_dict.items()}
                        updates[nei] = (scaled_model, extra_data)

                        logging.info(f"✅ Nei {nei} with reputation {rep:.4f}, scaled model with weight {weight:.4f}")
                    else:
                        logging.info(f"⛔ Nei {nei} with reputation {rep:.4f}, model rejected")

        logging.info(f"Updates after rejected nodes: {list(updates.keys())}")
        logging.info(f"Nodes rejected: {self.rejected_nodes}")

    async def include_feedback_in_reputation(self):
        """
        Include feedback of neighbors in the reputation.
        """
        weight_current_reputation = 0.9
        weight_feedback = 0.1

        if self.reputation_with_all_feedback is None:
            logging.info("No feedback received.")
            return False

        updated = False

        for (current_node, node_ip, round_num), scores in self.reputation_with_all_feedback.items():
            if not scores:
                logging.info(f"No feedback received for node {node_ip} in round {round_num}")
                continue

            if node_ip not in self.reputation:
                logging.info(f"No reputation for node {node_ip}")
                continue

            if (
                "last_feedback_round" in self.reputation[node_ip]
                and self.reputation[node_ip]["last_feedback_round"] >= round_num
            ):
                continue

            avg_feedback = sum(scores) / len(scores)
            logging.info(f"Receive feedback to node {node_ip} with average score {avg_feedback}")

            current_reputation = self.reputation[node_ip]["reputation"]
            if current_reputation is None:
                logging.info(f"No reputation calculate for node {node_ip}.")
                continue

            combined_reputation = (current_reputation * weight_current_reputation) + (avg_feedback * weight_feedback)
            logging.info(f"Combined reputation for node {node_ip} in round {round_num}: {combined_reputation}")

            self.reputation[node_ip] = {
                "reputation": combined_reputation,
                "round": self._engine.get_round(),
                "last_feedback_round": round_num,
            }
            updated = True
            logging.info(f"Updated self.reputation for {node_ip}: {self.reputation[node_ip]}")

        if updated:
            return True
        else:
            return False

    async def on_round_start(self, rse: RoundStartEvent):
        """
        Handle the start of a new round and initialize the round timing information.
        """
        (round_id, start_time, expected_nodes) = await rse.get_event_data()
        if round_id not in self.round_timing_info:
            self.round_timing_info[round_id] = {}
        self.round_timing_info[round_id]["start_time"] = start_time
        expected_nodes.difference_update(self.rejected_nodes)
        expected_nodes = list(expected_nodes)
        self._recalculate_pending_latencies(round_id)

    async def recollect_model_arrival_latency(self, ure: UpdateReceivedEvent):
        (decoded_model, weight, source, round_num, local) = await ure.get_event_data()
        current_round = self._engine.get_round()

        # logging.info(f"Model from source {source}, round {round_num}, current_round {current_round}")

        self.round_timing_info.setdefault(round_num, {})

        if round_num == current_round:
            self._process_current_round(round_num, source)
        elif round_num > current_round:
            self.round_timing_info[round_num]["pending_recalculation"] = True
            self.round_timing_info[round_num].setdefault("pending_sources", set()).add(source)
            logging.info(f"Model from future round {round_num} stored, pending recalculation.")
        else:
            self._process_past_round(round_num, source)

        self._recalculate_pending_latencies(current_round)

    def _process_current_round(self, round_num, source):
        """
        Process models that arrive in the current round.
        """
        if "start_time" in self.round_timing_info[round_num]:
            current_time = time.time()
            self.round_timing_info[round_num].setdefault("model_received_time", {})
            existing_time = self.round_timing_info[round_num]["model_received_time"].get(source)
            if existing_time is None or current_time < existing_time:
                self.round_timing_info[round_num]["model_received_time"][source] = current_time

            start_time = self.round_timing_info[round_num]["start_time"]
            duration = current_time - start_time
            self.round_timing_info[round_num]["duration"] = duration

            logging.info(f"Source {source}, round {round_num}, duration: {duration:.4f} seconds")

            self.save_data(
                "model_arrival_latency",
                source,
                self._addr,
                num_round=round_num,
                current_round=self._engine.get_round(),
                latency=duration,
            )
        else:
            logging.info(f"Start time not yet available for round {round_num}.")

    def _process_past_round(self, round_num, source):
        """
        Process models that arrive in past rounds.
        """
        logging.info(f"Model from past round {round_num} received, storing for recalculation.")
        current_time = time.time()
        self.round_timing_info.setdefault(round_num, {})
        self.round_timing_info[round_num].setdefault("model_received_time", {})
        existing_time = self.round_timing_info[round_num]["model_received_time"].get(source)
        if existing_time is None or current_time < existing_time:
            self.round_timing_info[round_num]["model_received_time"][source] = current_time

        prev_start_time = self.round_timing_info.get(round_num, {}).get("start_time")
        if prev_start_time:
            duration = current_time - prev_start_time
            self.round_timing_info[round_num]["duration"] = duration

            # logging.info(f"Source {source}, calculated latency using start_time at round {round_num}: {duration:.4f} seconds")

            self.save_data(
                "model_arrival_latency",
                source,
                self._addr,
                num_round=round_num,
                current_round=self._engine.get_round(),
                latency=duration,
            )
        else:
            logging.info(f"Start time for previous round {round_num - 1} not available yet.")

    def _recalculate_pending_latencies(self, current_round):
        """
        Recalculate latencies for rounds that have pending recalculation.
        """
        logging.info("Recalculating latencies for rounds with pending recalculation.")
        for r_num, r_data in self.round_timing_info.items():
            new_time = time.time()
            if r_data.get("pending_recalculation"):
                if "start_time" in r_data and "model_received_time" in r_data:
                    r_data.setdefault("model_received_time", {})

                    for src in list(r_data["pending_sources"]):
                        existing_time = r_data["model_received_time"].get(src)
                        if existing_time is None or new_time < existing_time:
                            r_data["model_received_time"][src] = new_time
                        duration = new_time - r_data["start_time"]
                        r_data["duration"] = duration

                        logging.info(f"[Recalc] Source {src}, round {r_num}, duration: {duration:.4f} s")
                        # logging.info(f"Source {src}, round {r_num}, recalculated duration: {duration:.4f} seconds")

                        self.save_data(
                            "model_arrival_latency",
                            src,
                            self._addr,
                            num_round=r_num,
                            current_round=current_round,
                            latency=duration,
                        )

                    r_data["pending_sources"].clear()
                    r_data["pending_recalculation"] = False

    async def recollect_similarity(self, ure: UpdateReceivedEvent):
        (decoded_model, weight, nei, round_num, local) = await ure.get_event_data()
        if self._with_reputation and self._reputation_metrics.get("model_similarity"):
            if self._engine.config.participant["adaptive_args"]["model_similarity"]:
                if nei != self._addr:
                    logging.info("🤖  handle_model_message | Checking model similarity")
                    cosine_value = cosine_metric(
                        self._engine.trainer.get_model_parameters(),
                        decoded_model,
                        similarity=True,
                    )
                    euclidean_value = euclidean_metric(
                        self._engine.trainer.get_model_parameters(),
                        decoded_model,
                        similarity=True,
                    )
                    minkowski_value = minkowski_metric(
                        self._engine.trainer.get_model_parameters(),
                        decoded_model,
                        p=2,
                        similarity=True,
                    )
                    manhattan_value = manhattan_metric(
                        self._engine.trainer.get_model_parameters(),
                        decoded_model,
                        similarity=True,
                    )
                    pearson_correlation_value = pearson_correlation_metric(
                        self._engine.trainer.get_model_parameters(),
                        decoded_model,
                        similarity=True,
                    )
                    jaccard_value = jaccard_metric(
                        self._engine.trainer.get_model_parameters(),
                        decoded_model,
                        similarity=True,
                    )
                    similarity_metrics = {
                        "timestamp": datetime.now(),
                        "nei": nei,
                        "round": round_num,
                        "current_round": self._engine.get_round(),
                        "cosine": cosine_value,
                        "euclidean": euclidean_value,
                        "minkowski": minkowski_value,
                        "manhattan": manhattan_value,
                        "pearson_correlation": pearson_correlation_value,
                        "jaccard": jaccard_value,
                    }

                    if nei in self.connection_metrics:
                        self.connection_metrics[nei].similarity.append(similarity_metrics)
                    else:
                        logging.warning(f"No metrics instance found for neighbor {nei}")

                    if cosine_value < 0.6:
                        logging.info("🤖  handle_model_message | Model similarity is less than 0.6")
                        self.rejected_nodes.add(nei)

    async def recollect_number_message(self, source, message):
        if source != self._addr:
            current_time = time.time()
            if current_time:
                self.save_data(
                    "number_message",
                    source,
                    self._addr,
                    time=current_time,
                    current_round=self._engine.get_round(),
                )

    async def recollect_fraction_of_parameters_changed(self, ure: UpdateReceivedEvent):
        (decoded_model, weight, source, round_num, local) = await ure.get_event_data()

        current_round = self._engine.get_round()
        parameters_local = self._engine.trainer.get_model_parameters()
        parameters_received = decoded_model
        differences = []
        total_params = 0
        changed_params = 0
        changes_record = {}
        prev_threshold = None

        if source in self.fraction_of_params_changed and current_round - 1 in self.fraction_of_params_changed[source]:
            prev_threshold = self.fraction_of_params_changed[source][current_round - 1][-1]["threshold"]

        for key in parameters_local.keys():
            # logging.info(f"🤖  fraction_of_parameters_changed | Key: {key}")
            if key in parameters_received:
                local_tensor = parameters_local[key].cpu()
                received_tensor = parameters_received[key].cpu()
                diff = torch.abs(local_tensor - received_tensor)
                differences.extend(diff.flatten().tolist())
                total_params += diff.numel()
                # logging.info(f"🤖  fraction_of_parameters_changed | Total params: {total_params}")

        if differences:
            mean_threshold = torch.mean(torch.tensor(differences)).item()
            current_threshold = (prev_threshold + mean_threshold) / 2 if prev_threshold is not None else mean_threshold
        else:
            current_threshold = 0

        for key in parameters_local.keys():
            if key in parameters_received:
                local_tensor = parameters_local[key].cpu()
                received_tensor = parameters_received[key].cpu()
                diff = torch.abs(local_tensor - received_tensor)
                num_changed = torch.sum(diff > current_threshold).item()
                changed_params += num_changed
                if num_changed > 0:
                    changes_record[key] = num_changed

        fraction_changed = changed_params / total_params if total_params > 0 else 0.0

        if source not in self.fraction_of_params_changed:
            self.fraction_of_params_changed[source] = {}
        if current_round not in self.fraction_of_params_changed[source]:
            self.fraction_of_params_changed[source][current_round] = []

        self.fraction_of_params_changed[source][current_round].append({
            "fraction_changed": fraction_changed,
            "total_params": total_params,
            "changed_params": changed_params,
            "threshold": current_threshold,
            "changes_record": changes_record,
        })

        self.save_data(
            "fraction_of_params_changed",
            source,
            self._addr,
            current_round=current_round,
            fraction_changed=fraction_changed,
            threshold=current_threshold,
        )

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
        """
        Initialize a Metrics instance to store various evaluation metrics for a participant.

        Args:
            num_round (optional): The current round number.
            current_round (optional): The round when the metric is measured.
            fraction_changed (optional): Fraction of parameters changed.
            threshold (optional): Threshold used for evaluating changes.
            latency (optional): Latency value for model arrival.
        """
        self.fraction_of_params_changed = {
            "fraction_changed": fraction_changed,
            "threshold": threshold,
            "round": num_round,
        }

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

        Args:
            engine (Engine): The engine instance providing the runtime context.
            config (Config): The configuration object with participant settings.
        """
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
        self.previous_percentile_25_number_message = {}
        self.previous_percentile_85_number_message = {}
        self._addr = engine.addr
        self._log_dir = engine.log_dir
        self._idx = engine.idx
        self.connection_metrics = {}

        neighbors: str = self._config.participant["network_args"]["neighbors"]
        for nei in neighbors.split():
            self.connection_metrics[f"{nei}"] = Metrics()

        reputation_config = self._config.participant["defense_args"]["reputation"]
        self._enabled = reputation_config["enabled"]
        self._metrics = reputation_config["metrics"]
        self._initial_reputation = float(reputation_config["initial_reputation"])
        self._weighting_factor = reputation_config["weighting_factor"]

        # Extract weights from metrics if using static weighting
        if self._weighting_factor == "static":
            self._weight_model_arrival_latency = float(
                self._metrics.get("model_arrival_latency", {}).get("weight", 0.25)
            )
            self._weight_model_similarity = float(self._metrics.get("model_similarity", {}).get("weight", 0.25))
            self._weight_num_messages = float(self._metrics.get("num_messages", {}).get("weight", 0.25))
            self._weight_fraction_params_changed = float(
                self._metrics.get("fraction_parameters_changed", {}).get("weight", 0.25)
            )
        else:
            self._metrics["model_arrival_latency"]["weight"] = 0.25
            self._metrics["model_similarity"]["weight"] = 0.25
            self._metrics["num_messages"]["weight"] = 0.25
            self._metrics["fraction_parameters_changed"]["weight"] = 0.25
            self._weight_model_arrival_latency = 0.25
            self._weight_model_similarity = 0.25
            self._weight_num_messages = 0.25
            self._weight_fraction_params_changed = 0.25

        msg = f"Reputation system: {self._enabled}"
        msg += f"\nReputation metrics: {self._metrics}"
        msg += f"\nInitial reputation: {self._initial_reputation}"
        msg += f"\nWeighting factor: {self._weighting_factor}"
        msg += f"\nWeight model arrival latency: {self._weight_model_arrival_latency}"
        msg += f"\nWeight model similarity: {self._weight_model_similarity}"
        msg += f"\nWeight number of messages: {self._weight_num_messages}"
        msg += f"\nWeight fraction of parameters changed: {self._weight_fraction_params_changed}"
        print_msg_box(msg=msg, indent=2, title="Defense information")

    @property
    def engine(self):
        """Return the engine instance."""
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
        total_params=None,
        changed_params=None,
        threshold=None,
        changes_record=None,
        latency=None,
    ):
        """
        Save data received from nodes for further reputation calculations.

        Args:
            type_data (str): The type of data being saved ("number_message", "fraction_of_params_changed", or "model_arrival_latency").
            nei (str): The neighbor node address.
            addr (str): The current node address.
            num_round (optional): The round number associated with the data.
            time (optional): Timestamp or time value.
            current_round (optional): The current round number.
            fraction_changed (optional): Fraction of parameters changed.
            total_params (optional): Total number of parameters.
            changed_params (optional): Number of changed parameters.
            threshold (optional): Threshold used for metrics.
            changes_record (optional): Record of parameter changes.
            latency (optional): Latency value.
        """
        try:
            if addr == nei:
                return

            combined_data = {}

            if type_data == "number_message":
                combined_data["number_message"] = {
                    "time": time,
                    "current_round": current_round,
                }
            elif type_data == "fraction_of_params_changed":
                combined_data["fraction_of_params_changed"] = {
                    "fraction_changed": fraction_changed,
                    "threshold": threshold,
                    "round": num_round,
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
        """Set up the reputation system by subscribing to relevant events."""
        if self._enabled:
            await EventManager.get_instance().subscribe_node_event(RoundStartEvent, self.on_round_start)
            await EventManager.get_instance().subscribe_node_event(AggregationEvent, self.calculate_reputation)
            if self._metrics.get("model_similarity", {}).get("enabled", False):
                await EventManager.get_instance().subscribe_node_event(UpdateReceivedEvent, self.recollect_similarity)
            if self._metrics.get("fraction_parameters_changed", {}).get("enabled", False):
                await EventManager.get_instance().subscribe_node_event(
                    UpdateReceivedEvent, self.recollect_fraction_of_parameters_changed
                )
            if self._metrics.get("num_messages", {}).get("enabled", False):
                await EventManager.get_instance().subscribe(("model", "update"), self.recollect_number_message)
                await EventManager.get_instance().subscribe(("model", "initialization"), self.recollect_number_message)
                await EventManager.get_instance().subscribe(("control", "alive"), self.recollect_number_message)
                await EventManager.get_instance().subscribe(
                    ("federation", "federation_models_included"), self.recollect_number_message
                )
                await EventManager.get_instance().subscribe(("reputation", "share"), self.recollect_number_message)
            if self._metrics.get("model_arrival_latency", {}).get("enabled", False):
                await EventManager.get_instance().subscribe_node_event(
                    UpdateReceivedEvent, self.recollect_model_arrival_latency
                )

    def init_reputation(
        self, addr, federation_nodes=None, round_num=None, last_feedback_round=None, init_reputation=None
    ):
        """
        Initialize the reputation for each federation node.

        Args:
            addr (str): The address of the current node.
            federation_nodes (list): List of federation nodes' addresses.
            round_num (int): The current round number.
            last_feedback_round (int): The last round in which feedback was provided.
            init_reputation (float): The initial reputation value.
        """
        if not federation_nodes:
            logging.error("init_reputation | No federation nodes provided")
            return

        if self._enabled:
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

    def is_valid_ip(self, federation_nodes):
        """
        Check if the IP addresses provided are valid.

        Args:
            federation_nodes (list): List of federation node addresses.

        Returns:
            list: A list of valid IP addresses.
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
        Calculate the static reputation of a participant using fixed weights.

        Args:
            addr (str): The IP address of the current node.
            nei (str): The neighbor node's IP address.
            metric_messages_number (float): Metric value for number of messages.
            metric_similarity (float): Metric value for model similarity.
            metric_fraction (float): Metric value for fraction of parameters changed.
            metric_model_arrival_latency (float): Metric value for model arrival latency.
            weight_messages_number (float): Weight for number of messages.
            weight_similarity (float): Weight for model similarity.
            weight_fraction (float): Weight for fraction of parameters changed.
            weight_model_arrival_latency (float): Weight for model arrival latency.
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
        Calculate the dynamic reputation of a participant based on historical metric data.

        Args:
            addr (str): The address of the current node.
            neighbors (list): List of neighbor node addresses.

        Returns:
            dict: Updated dynamic reputation values.
        """
        average_weights = {}

        for metric_name in self.history_data.keys():
            if self._metrics.get(metric_name, False):
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
            for metric_name in self.history_data:
                if self._metrics.get(metric_name, False):
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
        Update the reputation record of a neighbor.

        Args:
            nei (str): The neighbor node's address.
            reputation (float): The computed reputation value.
            data (dict): Additional metrics data associated with the reputation.
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
        if self.reputation[nei]["reputation"] < 0.6:
            self.rejected_nodes.add(nei)
            logging.info(f"Rejected node {nei} at round {self._engine.get_round()}")

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
        Calculate the weighted values for each metric based on current measurements and historical data.

        Args:
            avg_messages_number_message_normalized (float): Normalized average message count.
            similarity_reputation (float): Reputation score based on model similarity.
            fraction_score_asign (float): Score assigned from fraction of parameters changed.
            avg_model_arrival_latency (float): Average model arrival latency.
            history_data (dict): Historical metrics data.
            current_round (int): The current round number.
            addr (str): The address of the current node.
            nei (str): The neighbor node's address.
            reputation_metrics (dict): Dictionary indicating which metrics are active.
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

            if current_round >= 5 and num_active_metrics > 0:
                desviations = {}
                for metric_name, current_value in active_metrics.items():
                    historical_values = history_data[metric_name]

                    metric_values = [
                        entry["metric_value"]
                        for entry in historical_values
                        if "metric_value" in entry and entry["metric_value"] != 0
                    ]

                    mean_value = np.mean(metric_values) if metric_values else 0

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
                        normalized_weights = dict.fromkeys(active_metrics, 1 / num_active_metrics)

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
                adjusted_weights = dict.fromkeys(active_metrics, 1 / num_active_metrics)

            for metric_name, current_value in active_metrics.items():
                weight = adjusted_weights.get(metric_name, -1)
                for entry in history_data[metric_name]:
                    if entry["metric_name"] == metric_name and entry["round"] == current_round and entry["nei"] == nei:
                        entry["weight"] = weight

    async def calculate_value_metrics(self, log_dir, id_node, addr, nei, metrics_active=None):
        """
        Calculate various metrics (message count, model similarity, fraction of parameters changed, and model arrival latency)
        for a given neighbor node based on stored connection data.

        Args:
            log_dir (str): Directory for log files.
            id_node (str): Identifier for the node.
            addr (str): The address of the current node.
            nei (str): The neighbor node's address.
            metrics_active (dict): Dictionary indicating which metrics are active.

        Returns:
            tuple: A tuple containing:
                - avg_messages_number_message_normalized (float)
                - similarity_reputation (float)
                - fraction_score_asign (float)
                - avg_model_arrival_latency (float)
        """
        messages_number_message_normalized = 0
        messages_number_message_count = 0
        avg_messages_number_message_normalized = 0
        fraction_score_normalized = 0
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
                if metrics_instance.fraction_of_params_changed.get("round") == current_round:
                    fraction_changed = metrics_instance.fraction_of_params_changed.get("fraction_changed")
                    threshold = metrics_instance.fraction_of_params_changed.get("threshold")
                    fraction_score_normalized = self.analyze_anomalies(
                        addr,
                        nei,
                        current_round,
                        current_round,  # Assumes round_received is the current round.
                        fraction_changed,
                        threshold,
                    )

            if metrics_active.get("model_arrival_latency", False):
                if metrics_instance.model_arrival_latency.get("round_received") == current_round:
                    round_latency = metrics_instance.model_arrival_latency.get("round")
                    latency = metrics_instance.model_arrival_latency.get("latency")
                    messages_model_arrival_latency_normalized = self.manage_model_arrival_latency(
                        round_latency, addr, nei, latency, current_round
                    )

            if current_round >= 5 and metrics_active.get("model_similarity", False):
                similarity_reputation = self.calculate_similarity_from_metrics(nei, current_round)
            else:
                similarity_reputation = 0

            if messages_model_arrival_latency_normalized >= 0:
                avg_model_arrival_latency = self.save_model_arrival_latency_history(
                    addr, nei, messages_model_arrival_latency_normalized, current_round
                )
                if avg_model_arrival_latency is None and current_round > 4:
                    avg_model_arrival_latency = self.model_arrival_latency_history[(addr, nei)][current_round - 1][
                        "score"
                    ]

            if self.messages_number_message is not None:
                messages_number_message_normalized, messages_number_message_count = self.manage_metric_number_message(
                    self.messages_number_message, addr, nei, current_round, metrics_active.get("num_messages", False)
                )
                avg_messages_number_message_normalized = self.save_number_message_history(
                    addr, nei, messages_number_message_normalized, current_round
                )
                if avg_messages_number_message_normalized is None and current_round > 4:
                    avg_messages_number_message_normalized = self.number_message_history[(addr, nei)][
                        current_round - 1
                    ]["avg_number_message"]

            if current_round >= 5:
                if fraction_score_normalized > 0:
                    key_previous_round = (addr, nei, current_round - 1) if current_round - 1 > 0 else None
                    fraction_previous_round = None

                    if key_previous_round is not None and key_previous_round in self.fraction_changed_history:
                        fraction_score_prev = self.fraction_changed_history[key_previous_round].get("fraction_score")
                        fraction_previous_round = fraction_score_prev if fraction_score_prev is not None else None

                    if fraction_previous_round is not None:
                        fraction_score_asign = fraction_score_normalized * 0.8 + fraction_previous_round * 0.2
                        self.fraction_changed_history[(addr, nei, current_round)]["fraction_score"] = (
                            fraction_score_asign
                        )
                    else:
                        fraction_score_asign = fraction_score_normalized
                        self.fraction_changed_history[(addr, nei, current_round)]["fraction_score"] = (
                            fraction_score_asign
                        )
                else:
                    fraction_previous_round = None
                    key_previous_round = (addr, nei, current_round - 1) if current_round - 1 > 0 else None
                    if key_previous_round is not None and key_previous_round in self.fraction_changed_history:
                        fraction_score_prev = self.fraction_changed_history[key_previous_round].get("fraction_score")
                        fraction_previous_round = fraction_score_prev if fraction_score_prev is not None else None

                    if fraction_previous_round is not None:
                        fraction_score_asign = fraction_previous_round - (fraction_previous_round * 0.5)
                    else:
                        if fraction_neighbors_scores is None:
                            fraction_neighbors_scores = {}

                        for key, value in self.fraction_changed_history.items():
                            score = value.get("fraction_score")
                            if score is not None:
                                fraction_neighbors_scores[key] = score

                        if fraction_neighbors_scores:
                            fraction_score_asign = np.mean(list(fraction_neighbors_scores.values()))
                        else:
                            fraction_score_asign = 0
            else:
                fraction_score_asign = 0

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
        Create and log graphics representing different metric values over the rounds.

        Args:
            number_message_count (int): Count of messages.
            number_message_norm (float): Normalized number of messages.
            similarity (float): Similarity metric value.
            fraction (float): Fraction score metric.
            model_arrival_latency (float): Latency metric score.
            addr (str): The current node's address.
            nei (str): The neighbor node's address.
            current_round (int): The current round number.
            total_rounds (int): Total rounds in the session.
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

    def analyze_anomalies(
        self,
        addr,
        nei,
        round_num,
        current_round,
        fraction_changed,
        threshold,
    ):
        """
        Analyze anomalies in the fraction of parameters changed and calculate a corresponding score.

        Args:
            addr (str): The source node's address.
            nei (str): The neighbor node's address.
            round_num (int): The round number for the metric.
            current_round (int): The current round number.
            fraction_changed (float): Fraction of parameters changed.
            threshold (float): Threshold value for changes.

        Returns:
            float: A normalized fraction score between 0 and 1.
        """
        try:
            key = (addr, nei, round_num)

            if key not in self.fraction_changed_history:
                prev_key = (addr, nei, round_num - 1)
                if round_num > 0 and prev_key in self.fraction_changed_history:
                    previous_data = self.fraction_changed_history[prev_key]
                    fraction_changed = (
                        fraction_changed if fraction_changed is not None else previous_data["fraction_changed"]
                    )
                    threshold = threshold if threshold is not None else previous_data["threshold"]
                else:
                    fraction_changed = fraction_changed if fraction_changed is not None else 0
                    threshold = threshold if threshold is not None else 0

                self.fraction_changed_history[key] = {
                    "fraction_changed": fraction_changed,
                    "threshold": threshold,
                    "fraction_score": None,
                    "fraction_anomaly": False,
                    "threshold_anomaly": False,
                    "mean_fraction": None,
                    "std_dev_fraction": None,
                    "mean_threshold": None,
                    "std_dev_threshold": None,
                }

            if round_num < 5:
                past_fractions = []
                past_thresholds = []

                for r in range(round_num):
                    past_key = (addr, nei, r)
                    if past_key in self.fraction_changed_history:
                        past_fractions.append(self.fraction_changed_history[past_key]["fraction_changed"])
                        past_thresholds.append(self.fraction_changed_history[past_key]["threshold"])

                if past_fractions:
                    mean_fraction = np.mean(past_fractions)
                    std_dev_fraction = np.std(past_fractions)
                    self.fraction_changed_history[key]["mean_fraction"] = mean_fraction
                    self.fraction_changed_history[key]["std_dev_fraction"] = std_dev_fraction

                if past_thresholds:
                    mean_threshold = np.mean(past_thresholds)
                    std_dev_threshold = np.std(past_thresholds)
                    self.fraction_changed_history[key]["mean_threshold"] = mean_threshold
                    self.fraction_changed_history[key]["std_dev_threshold"] = std_dev_threshold

                return 0
            else:
                fraction_value = 0
                threshold_value = 0
                prev_key = (addr, nei, round_num - 1)
                if prev_key not in self.fraction_changed_history:
                    for i in range(0, round_num + 1):
                        potential_prev_key = (addr, nei, round_num - i)
                        if potential_prev_key in self.fraction_changed_history:
                            mean_fraction_prev = self.fraction_changed_history[potential_prev_key]["mean_fraction"]
                            if mean_fraction_prev is not None:
                                prev_key = potential_prev_key
                                break

                if prev_key:
                    mean_fraction_prev = self.fraction_changed_history[prev_key]["mean_fraction"]
                    std_dev_fraction_prev = self.fraction_changed_history[prev_key]["std_dev_fraction"]
                    mean_threshold_prev = self.fraction_changed_history[prev_key]["mean_threshold"]
                    std_dev_threshold_prev = self.fraction_changed_history[prev_key]["std_dev_threshold"]

                    current_fraction = self.fraction_changed_history[key]["fraction_changed"]
                    current_threshold = self.fraction_changed_history[key]["threshold"]

                    upper_mean_fraction_prev = (mean_fraction_prev + std_dev_fraction_prev) * 1.05
                    upper_mean_threshold_prev = (mean_threshold_prev + std_dev_threshold_prev) * 1.10

                    fraction_anomaly = current_fraction > upper_mean_fraction_prev
                    threshold_anomaly = current_threshold > upper_mean_threshold_prev

                    self.fraction_changed_history[key]["fraction_anomaly"] = fraction_anomaly
                    self.fraction_changed_history[key]["threshold_anomaly"] = threshold_anomaly

                    penalization_factor_fraction = (
                        abs(current_fraction - mean_fraction_prev) / mean_fraction_prev
                        if mean_fraction_prev != 0
                        else 1
                    )
                    penalization_factor_threshold = (
                        abs(current_threshold - mean_threshold_prev) / mean_threshold_prev
                        if mean_threshold_prev != 0
                        else 1
                    )

                    k_fraction = penalization_factor_fraction if penalization_factor_fraction != 0 else 1
                    k_threshold = penalization_factor_threshold if penalization_factor_threshold != 0 else 1

                    if fraction_anomaly:
                        fraction_value = (
                            1 - (1 / (1 + np.exp(-k_fraction)))
                            if current_fraction is not None and mean_fraction_prev is not None
                            else 0
                        )
                    else:
                        fraction_value = (
                            1 - (1 / (1 + np.exp(k_fraction)))
                            if current_fraction is not None and mean_fraction_prev is not None
                            else 0
                        )

                    if threshold_anomaly:
                        threshold_value = (
                            1 - (1 / (1 + np.exp(-k_threshold)))
                            if current_threshold is not None and mean_threshold_prev is not None
                            else 0
                        )
                    else:
                        threshold_value = (
                            1 - (1 / (1 + np.exp(k_threshold)))
                            if current_threshold is not None and mean_threshold_prev is not None
                            else 0
                        )

                    fraction_weight = 0.5
                    threshold_weight = 0.5

                    fraction_score = fraction_weight * fraction_value + threshold_weight * threshold_value

                    self.fraction_changed_history[key]["mean_fraction"] = (current_fraction + mean_fraction_prev) / 2
                    self.fraction_changed_history[key]["std_dev_fraction"] = np.sqrt(
                        ((current_fraction - mean_fraction_prev) ** 2 + std_dev_fraction_prev**2) / 2
                    )
                    self.fraction_changed_history[key]["mean_threshold"] = (current_threshold + mean_threshold_prev) / 2
                    self.fraction_changed_history[key]["std_dev_threshold"] = np.sqrt(
                        ((0.1 * (current_threshold - mean_threshold_prev) ** 2) + std_dev_threshold_prev**2) / 2
                    )

                    return max(fraction_score, 0)
                else:
                    return -1
        except Exception:
            logging.exception("Error analyzing anomalies")
            return -1

    def manage_model_arrival_latency(self, round_num, addr, nei, latency, current_round):
        """
        Manage the model arrival latency metric and normalize it based on historical latencies.

        Args:
            round_num (int): The round number when the model was sent.
            addr (str): The address of the current node.
            nei (str): The neighbor node's address.
            latency (float): The measured latency.
            current_round (int): The current round number.

        Returns:
            float: Normalized latency score between 0 and 1.
        """
        try:
            current_key = nei

            if current_round not in self.model_arrival_latency_history:
                self.model_arrival_latency_history[current_round] = {}

            self.model_arrival_latency_history[current_round][current_key] = {
                "latency": latency,
                "score": 0.0,
            }

            prev_mean_latency = 0
            prev_percentil_0 = 0
            prev_percentil_25 = 0
            difference = 0

            if current_round >= 5:
                all_latencies = [
                    data["latency"]
                    for r in self.model_arrival_latency_history
                    for key, data in self.model_arrival_latency_history[r].items()
                    if "latency" in data and data["latency"] != 0
                ]

                prev_mean_latency = np.mean(all_latencies) if all_latencies else 0
                prev_percentil_0 = np.percentile(all_latencies, 0) if all_latencies else 0
                prev_percentil_25 = np.percentile(all_latencies, 25) if all_latencies else 0

                k = 0.1
                prev_mean_latency += k * (prev_percentil_25 - prev_percentil_0)

                difference = latency - prev_mean_latency
                if latency <= prev_mean_latency:
                    score = 1.0
                else:
                    score = 1 / (1 + np.exp(abs(difference) / prev_mean_latency))

                if round_num < current_round:
                    round_diff = current_round - round_num
                    penalty_factor = round_diff * 0.1
                    penalty = penalty_factor * (1 - score)
                    score -= penalty * score

                self.model_arrival_latency_history[current_round][current_key].update({
                    "mean_latency": prev_mean_latency,
                    "percentil_0": prev_percentil_0,
                    "percentil_25": prev_percentil_25,
                    "score": score,
                })
            else:
                score = 0

            return score

        except Exception as e:
            logging.exception(f"Error managing model_arrival_latency: {e}")
            return 0

    def save_model_arrival_latency_history(self, addr, nei, model_arrival_latency, round_num):
        """
        Save and update the model arrival latency history in memory.

        Args:
            addr (str): The current node's address.
            nei (str): The neighbor node's address.
            model_arrival_latency (float): The normalized latency score.
            round_num (int): The current round number.

        Returns:
            float: The updated average model arrival latency.
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

            if model_arrival_latency > 0 and round_num > 5:
                previous_avg = (
                    self.model_arrival_latency_history.get(round_num - 1, {})
                    .get(current_key, {})
                    .get("avg_model_arrival_latency", None)
                )

                if previous_avg is not None:
                    avg_model_arrival_latency = (
                        model_arrival_latency * 0.8 + previous_avg * 0.2
                        if previous_avg is not None
                        else model_arrival_latency
                    )
                else:
                    avg_model_arrival_latency = model_arrival_latency - (model_arrival_latency * 0.05)
            elif model_arrival_latency == 0 and round_num > 5:
                previous_avg = (
                    self.model_arrival_latency_history.get(round_num - 1, {})
                    .get(current_key, {})
                    .get("avg_model_arrival_latency", None)
                )
                avg_model_arrival_latency = previous_avg - (previous_avg * 0.05)
            else:
                avg_model_arrival_latency = model_arrival_latency

            self.model_arrival_latency_history[round_num][current_key]["avg_model_arrival_latency"] = (
                avg_model_arrival_latency
            )

            return avg_model_arrival_latency
        except Exception:
            logging.exception("Error saving model_arrival_latency history")

    def manage_metric_number_message(self, messages_number_message, addr, nei, current_round, metric_active=True):
        """
        Manage and normalize the number of messages metric using percentiles.

        Args:
            messages_number_message (list): List containing message data.
            addr (str): The current node's address.
            nei (str): The neighbor node's address.
            current_round (int): The current round number.
            metric_active (bool): Flag indicating whether the metric is active.

        Returns:
            tuple: A tuple with the normalized number_message value (float) and the count of messages (int).
        """
        try:
            if current_round == 0:
                return 0.0, 0

            if not metric_active:
                return 0.0, 0

            previous_round = current_round

            current_addr_nei = (addr, nei)
            relevant_messages = [
                msg
                for msg in messages_number_message
                if msg["key"] == current_addr_nei and msg["current_round"] == previous_round
            ]
            messages_count = len(relevant_messages) if relevant_messages else 0

            rounds_to_consider = []
            if previous_round >= 4:
                rounds_to_consider = [previous_round - 4, previous_round - 3, previous_round - 2, previous_round - 1]
            elif previous_round == 3:
                rounds_to_consider = [0, 1, 2, 3]
            elif previous_round == 2:
                rounds_to_consider = [0, 1, 2]
            elif previous_round == 1:
                rounds_to_consider = [0, 1]
            elif previous_round == 0:
                rounds_to_consider = [0]

            previous_counts = [
                len([m for m in messages_number_message if m["key"] == current_addr_nei and m["current_round"] == r])
                for r in rounds_to_consider
            ]

            self.previous_percentile_25_number_message[current_addr_nei] = (
                np.percentile(previous_counts, 25) if previous_counts else 0
            )
            self.previous_percentile_85_number_message[current_addr_nei] = (
                np.percentile(previous_counts, 85) if previous_counts else 0
            )

            normalized_messages = 1.0
            relative_position = 0

            if previous_round > 4:
                percentile_25 = self.previous_percentile_25_number_message.get(current_addr_nei, 0)
                percentile_85 = self.previous_percentile_85_number_message.get(current_addr_nei, 0)
                if messages_count > percentile_85:
                    relative_position = (messages_count - percentile_85) / (percentile_85 - percentile_25)
                    normalized_messages = np.exp(-relative_position)

                normalized_messages = max(0.01, normalized_messages)

            return normalized_messages, messages_count
        except Exception:
            logging.exception("Error managing metric number_message")
            return 0.0, 0

    def save_number_message_history(self, addr, nei, messages_number_message_normalized, current_round):
        """
        Save the normalized number_message history in memory and calculate a weighted average.

        Args:
            addr (str): The current node's address.
            nei (str): The neighbor node's address.
            messages_number_message_normalized (float): The normalized number_message value.
            current_round (int): The current round number.

        Returns:
            float: The weighted average of the number_message metric.
        """
        try:
            key = (addr, nei)
            avg_number_message = 0

            if key not in self.number_message_history:
                self.number_message_history[key] = {}

            self.number_message_history[key][current_round] = {"number_message": messages_number_message_normalized}

            if messages_number_message_normalized != 0 and current_round > 4:
                previous_avg = (
                    self.number_message_history[key].get(current_round - 1, {}).get("avg_number_message", None)
                )
                if previous_avg is not None:
                    avg_number_message = messages_number_message_normalized * 0.8 + previous_avg * 0.2
                else:
                    avg_number_message = messages_number_message_normalized

                self.number_message_history[key][current_round]["avg_number_message"] = avg_number_message
            else:
                avg_number_message = 0

            return avg_number_message
        except Exception:
            logging.exception("Error saving number_message history")
            return -1

        except Exception as e:
            logging.exception(f"Error managing model_arrival_latency latency: {e}")
            return 0.0

    def save_reputation_history_in_memory(self, addr, nei, reputation):
        """
        Save the reputation history for a neighbor and compute an average reputation.

        Args:
            addr (str): The current node's address.
            nei (str): The neighbor node's address.
            reputation (float): The computed reputation for the current round.

        Returns:
            float: The updated (weighted) reputation.
        """
        try:
            key = (addr, nei)

            if key not in self.reputation_history:
                self.reputation_history[key] = {}

            self.reputation_history[key][self._engine.get_round()] = reputation

            avg_reputation = 0
            current_round = self._engine.get_round()
            rounds = sorted(self.reputation_history[key].keys(), reverse=True)[:2]

            if len(rounds) >= 2:
                current_round = rounds[0]
                previous_round = rounds[1]

                current_rep = self.reputation_history[key][current_round]
                previous_rep = self.reputation_history[key][previous_round]
                logging.info(f"Current reputation: {current_rep}, Previous reputation: {previous_rep}")

                avg_reputation = (current_rep * 0.8) + (previous_rep * 0.2)
                logging.info(f"Reputation ponderated: {avg_reputation}")
            else:
                avg_reputation = self.reputation_history[key][current_round]

            return avg_reputation

        except Exception:
            logging.exception("Error saving reputation history")
            return -1

    def calculate_decay_rate(self, reputation):
        """
        Calculate the decay rate for a given reputation value.

        Args:
            reputation (float): The current reputation value.

        Returns:
            float: The decay rate.
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
        Calculate the similarity score based on stored similarity metrics.

        Args:
            nei (str): The neighbor node's address.
            current_round (int): The current round number.

        Returns:
            float: The aggregated similarity score.
        """
        similarity_value = 0.0

        metrics_instance = self.connection_metrics.get(nei)
        if metrics_instance is None:
            logging.error(f"No metrics instance found for neighbor {nei}")
            return similarity_value

        for metric in metrics_instance.similarity:
            source_ip = metric.get("nei")
            round_in_metric = metric.get("round")

            if source_ip == nei and round_in_metric == current_round:
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

    async def calculate_reputation(self, ae: AggregationEvent):
        """
        Calculate and update the reputation for all neighbor nodes based on active metrics.

        This method processes the aggregated updates and then, based on the selected weighting factor (static or dynamic),
        calculates the reputation. It also includes feedback and sends the reputation scores to neighbors.

        Args:
            ae (AggregationEvent): The event containing aggregated updates.
        """
        (updates, _, _) = await ae.get_event_data()
        if self._enabled:
            logging.info(f"Calculating reputation at round {self._engine.get_round()}")
            logging.info(f"Active metrics: {self._metrics}")
            logging.info(f"rejected nodes at round {self._engine.get_round()}: {self.rejected_nodes}")

            neighbors = set(await self._engine._cm.get_addrs_current_connections(only_direct=True))
            history_data = self.history_data

            for nei in neighbors:
                (
                    metric_messages_number,
                    metric_similarity,
                    metric_fraction,
                    metric_model_arrival_latency,
                ) = await self.calculate_value_metrics(
                    self._log_dir,
                    self._idx,
                    self._addr,
                    nei,
                    metrics_active=self._metrics,
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
                        self._metrics,
                    )

                if self._weighting_factor == "static" and self._engine.get_round() >= 5:
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

            if self._weighting_factor == "dynamic" and self._engine.get_round() >= 5:
                await self._calculate_dynamic_reputation(self._addr, neighbors)

            if self._engine.get_round() < 5 and self._enabled:
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
        Send the calculated reputation scores to all neighbors.

        Args:
            neighbors (iterable): An iterable of neighbor node addresses.
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

    def create_graphic_reputation(self, addr, round_num):
        """
        Create a graphical representation of the reputation scores and log the data.

        Args:
            addr (str): The current node's address.
            round_num (int): The current round number.
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
        Update the aggregation process by removing nodes that have been rejected.

        Args:
            updates (dict): The dictionary of updates.
        """
        for rn in self.rejected_nodes:
            if rn in updates:
                updates.pop(rn)

        logging.info(f"Updates after rejected nodes: {list(updates.keys())}")
        self.rejected_nodes.clear()
        logging.info(f"rejected nodes after clear at round {self._engine.get_round()}: {self.rejected_nodes}")

    async def include_feedback_in_reputation(self):
        """
        Integrate feedback scores into the current reputation values.

        The final reputation is computed as a weighted sum of the current reputation and the average feedback.

        Returns:
            bool: True if feedback was successfully included, False otherwise.
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
        Event handler for the start of a round. It stores the start time and updates the expected nodes.

        Args:
            rse (RoundStartEvent): The event data containing round start information.
        """
        (round_id, start_time, expected_nodes) = await rse.get_event_data()
        if round_id not in self.round_timing_info:
            self.round_timing_info[round_id] = {}
        self.round_timing_info[round_id]["start_time"] = start_time
        expected_nodes.difference_update(self.rejected_nodes)

    async def recollect_model_arrival_latency(self, ure: UpdateReceivedEvent):
        """
        Event handler to record the model arrival latency when an update is received.

        Args:
            ure (UpdateReceivedEvent): The event data for a model update.
        """
        (decoded_model, weight, source, round_num, local) = await ure.get_event_data()

        # Exclude the node itself from the calculation
        if source == self._addr:
            return

        current_time = time.time()
        current_round = round_num

        if current_round not in self.round_timing_info:
            self.round_timing_info[current_round] = {}

        if "model_received_time" not in self.round_timing_info[current_round]:
            self.round_timing_info[current_round]["model_received_time"] = {}

        if source not in self.round_timing_info[current_round]["model_received_time"]:
            self.round_timing_info[current_round]["model_received_time"][source] = current_time

            if "start_time" in self.round_timing_info[current_round]:
                start = self.round_timing_info[current_round]["start_time"]
                received_time = self.round_timing_info[current_round]["model_received_time"][source]
                duration = received_time - start
                self.round_timing_info[current_round]["duration"] = duration
                logging.info(f"Source {source} , round {current_round}, duration: {duration:.4f} seconds")

                self.save_data(
                    "model_arrival_latency",
                    source,
                    self._addr,
                    num_round=current_round,
                    current_round=self._engine.get_round(),
                    latency=duration,
                )
        else:
            logging.info(f"Model arrival latency already calculated for node {source} in round {current_round}")

    async def recollect_similarity(self, ure: UpdateReceivedEvent):
        """
        Event handler to recollect and store model similarity metrics when an update is received.

        Args:
            ure (UpdateReceivedEvent): The event data containing model update information.
        """
        (decoded_model, weight, nei, round_num, local) = await ure.get_event_data()
        if self._enabled and self._metrics.get("model_similarity"):
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
                        logging.info(f"Stored similarity metrics for {nei}: {similarity_metrics}")
                    else:
                        logging.warning(f"No metrics instance found for neighbor {nei}")

                    if cosine_value < 0.6:
                        logging.info("🤖  handle_model_message | Model similarity is less than 0.6")
                        self.rejected_nodes.add(nei)

    async def recollect_number_message(self, source, message):
        """
        Event handler to collect message count metrics when a message is received.

        Args:
            source (str): The source node's address.
            message: The received message (content not used directly).
        """
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
        """
        Event handler to recollect the fraction of parameters changed when an update is received.

        Args:
            ure (UpdateReceivedEvent): The event data containing model update information.
        """
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
            if key in parameters_received:
                local_tensor = parameters_local[key].cpu()
                received_tensor = parameters_received[key].cpu()
                diff = torch.abs(local_tensor - received_tensor)
                differences.extend(diff.flatten().tolist())
                total_params += diff.numel()

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
            current_round,
            fraction_changed=fraction_changed,
            total_params=total_params,
            changed_params=changed_params,
            threshold=current_threshold,
            changes_record=changes_record,
        )

import logging
import random
import time
import numpy as np
import torch

from datetime import datetime
from typing import TYPE_CHECKING
from nebula.addons.functions import print_msg_box
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import AggregationEvent, RoundStartEvent, UpdateReceivedEvent, DuplicatedMessageEvent
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
    
    REPUTATION_THRESHOLD = 0.6
    SIMILARITY_THRESHOLD = 0.6
    INITIAL_ROUND_FOR_REPUTATION = 1
    INITIAL_ROUND_FOR_FRACTION = 1
    HISTORY_ROUNDS_LOOKBACK = 4
    WEIGHTED_HISTORY_ROUNDS = 3
    FRACTION_ANOMALY_MULTIPLIER = 1.20
    THRESHOLD_ANOMALY_MULTIPLIER = 1.15
    
    # Augmentation factors
    LATENCY_AUGMENT_FACTOR = 1.4
    MESSAGE_AUGMENT_FACTOR_EARLY = 2.0
    MESSAGE_AUGMENT_FACTOR_NORMAL = 1.1
    
    # Penalty and decay factors
    HISTORICAL_PENALTY_THRESHOLD = 0.9
    NEGATIVE_LATENCY_PENALTY = 0.3
    CURRENT_VALUE_WEIGHT_HIGH = 0.9
    CURRENT_VALUE_WEIGHT_LOW = 0.2
    PAST_VALUE_WEIGHT_HIGH = 0.8
    PAST_VALUE_WEIGHT_LOW = 0.1
    ZERO_VALUE_DECAY_FACTOR = 0.1
    REPUTATION_CURRENT_WEIGHT = 0.9
    REPUTATION_FEEDBACK_WEIGHT = 0.1
    THRESHOLD_VARIANCE_MULTIPLIER = 0.1
    DYNAMIC_MIN_WEIGHT_THRESHOLD = 0.1
    REPUTATION_SCALING_THRESHOLD = 0.7
    REPUTATION_SCALING_RANGE = 0.3

    def __init__(self, engine: "Engine", config: "Config"):
        """
        Initialize the Reputation system.

        Args:
            engine (Engine): The engine instance providing the runtime context.
            config (Config): The configuration object with participant settings.
        """
        self._engine = engine
        self._config = config
        self._addr = engine.addr
        self._log_dir = engine.log_dir
        self._idx = engine.idx
        
        self._initialize_data_structures()
        self._configure_constants()
        self._load_configuration()
        self._setup_connection_metrics()
        self._configure_metric_weights()
        self._log_initialization_info()

    def _configure_constants(self):
        """Configure system constants from config or use defaults."""
        reputation_config = self._config.participant.get("defense_args", {}).get("reputation", {})
        constants_config = reputation_config.get("constants", {})
        
        self.REPUTATION_THRESHOLD = constants_config.get("reputation_threshold", self.REPUTATION_THRESHOLD)
        self.SIMILARITY_THRESHOLD = constants_config.get("similarity_threshold", self.SIMILARITY_THRESHOLD)
        self.INITIAL_ROUND_FOR_REPUTATION = constants_config.get("initial_round_for_reputation", self.INITIAL_ROUND_FOR_REPUTATION)
        self.INITIAL_ROUND_FOR_FRACTION = constants_config.get("initial_round_for_fraction", self.INITIAL_ROUND_FOR_FRACTION)
        self.HISTORY_ROUNDS_LOOKBACK = constants_config.get("history_rounds_lookback", self.HISTORY_ROUNDS_LOOKBACK)
        self.WEIGHTED_HISTORY_ROUNDS = constants_config.get("weighted_history_rounds", self.WEIGHTED_HISTORY_ROUNDS)
        self.FRACTION_ANOMALY_MULTIPLIER = constants_config.get("fraction_anomaly_multiplier", self.FRACTION_ANOMALY_MULTIPLIER)
        self.THRESHOLD_ANOMALY_MULTIPLIER = constants_config.get("threshold_anomaly_multiplier", self.THRESHOLD_ANOMALY_MULTIPLIER)
        self.LATENCY_AUGMENT_FACTOR = constants_config.get("latency_augment_factor", self.LATENCY_AUGMENT_FACTOR)
        self.MESSAGE_AUGMENT_FACTOR_EARLY = constants_config.get("message_augment_factor_early", self.MESSAGE_AUGMENT_FACTOR_EARLY)
        self.MESSAGE_AUGMENT_FACTOR_NORMAL = constants_config.get("message_augment_factor_normal", self.MESSAGE_AUGMENT_FACTOR_NORMAL)
        self.HISTORICAL_PENALTY_THRESHOLD = constants_config.get("historical_penalty_threshold", self.HISTORICAL_PENALTY_THRESHOLD)
        self.NEGATIVE_LATENCY_PENALTY = constants_config.get("negative_latency_penalty", self.NEGATIVE_LATENCY_PENALTY)
        self.CURRENT_VALUE_WEIGHT_HIGH = constants_config.get("current_value_weight_high", self.CURRENT_VALUE_WEIGHT_HIGH)
        self.CURRENT_VALUE_WEIGHT_LOW = constants_config.get("current_value_weight_low", self.CURRENT_VALUE_WEIGHT_LOW)
        self.PAST_VALUE_WEIGHT_HIGH = constants_config.get("past_value_weight_high", self.PAST_VALUE_WEIGHT_HIGH)
        self.PAST_VALUE_WEIGHT_LOW = constants_config.get("past_value_weight_low", self.PAST_VALUE_WEIGHT_LOW)
        self.ZERO_VALUE_DECAY_FACTOR = constants_config.get("zero_value_decay_factor", self.ZERO_VALUE_DECAY_FACTOR)
        self.REPUTATION_CURRENT_WEIGHT = constants_config.get("reputation_current_weight", self.REPUTATION_CURRENT_WEIGHT)
        self.REPUTATION_FEEDBACK_WEIGHT = constants_config.get("reputation_feedback_weight", self.REPUTATION_FEEDBACK_WEIGHT)
        self.THRESHOLD_VARIANCE_MULTIPLIER = constants_config.get("threshold_variance_multiplier", self.THRESHOLD_VARIANCE_MULTIPLIER)
        self.DYNAMIC_MIN_WEIGHT_THRESHOLD = constants_config.get("dynamic_min_weight_threshold", self.DYNAMIC_MIN_WEIGHT_THRESHOLD)
        self.REPUTATION_SCALING_THRESHOLD = constants_config.get("reputation_scaling_threshold", self.REPUTATION_SCALING_THRESHOLD)
        self.REPUTATION_SCALING_RANGE = constants_config.get("reputation_scaling_range", self.REPUTATION_SCALING_RANGE)

    def _initialize_data_structures(self):
        """Initialize all data structures used by the reputation system."""
        self.reputation = {}
        self.reputation_with_feedback = {}
        self.reputation_with_all_feedback = {}
        self.reputation_history = {}
        self.rejected_nodes = set()
        self.fraction_of_params_changed = {}
        self.history_data = {}
        self.metric_weights = {}
        self.connection_metrics = {}
        self.messages_number_message = []
        self.number_message_history = {}
        self._messages_received_from_sources = {}
        self.round_timing_info = {}
        self.neighbor_reputation_history = {}
        self.fraction_changed_history = {}
        self.messages_model_arrival_latency = {}
        self.model_arrival_latency_history = {}
        self.previous_threshold_number_message = {}
        self.previous_std_dev_number_message = {}
        self.previous_percentile_25_number_message = {}
        self.previous_percentile_85_number_message = {}

    def _load_configuration(self):
        """Load and validate reputation configuration."""
        reputation_config = self._config.participant["defense_args"]["reputation"]
        self._enabled = reputation_config["enabled"]
        self._metrics = reputation_config["metrics"]
        self._initial_reputation = float(reputation_config["initial_reputation"])
        self._weighting_factor = reputation_config["weighting_factor"]

        if not isinstance(self._metrics, dict):
            logging.error(f"Invalid metrics configuration: expected dict, got {type(self._metrics)}")
            self._metrics = {}

    def _setup_connection_metrics(self):
        """Initialize metrics for each neighbor."""
        neighbors_str = self._config.participant["network_args"]["neighbors"]
        for neighbor in neighbors_str.split():
            self.connection_metrics[neighbor] = Metrics()

    def _configure_metric_weights(self):
        """Configure weights for different metrics based on weighting factor."""
        default_weight = 0.25
        metric_names = ["model_arrival_latency", "model_similarity", "num_messages", "fraction_parameters_changed"]
        
        if self._weighting_factor == "static":
            self._weight_model_arrival_latency = float(
                self._metrics.get("model_arrival_latency", {}).get("weight", default_weight)
            )
            self._weight_model_similarity = float(
                self._metrics.get("model_similarity", {}).get("weight", default_weight)
            )
            self._weight_num_messages = float(
                self._metrics.get("num_messages", {}).get("weight", default_weight)
            )
            self._weight_fraction_params_changed = float(
                self._metrics.get("fraction_parameters_changed", {}).get("weight", default_weight)
            )
        else:
            for metric_name in metric_names:
                if metric_name not in self._metrics:
                    self._metrics[metric_name] = {}
                elif not isinstance(self._metrics[metric_name], dict):
                    self._metrics[metric_name] = {"enabled": bool(self._metrics[metric_name])}
                self._metrics[metric_name]["weight"] = default_weight
            
            self._weight_model_arrival_latency = default_weight
            self._weight_model_similarity = default_weight
            self._weight_num_messages = default_weight
            self._weight_fraction_params_changed = default_weight

    def _log_initialization_info(self):
        """Log initialization information."""
        msg = f"Reputation system: {self._enabled}"
        msg += f"\nReputation metrics: {self._metrics}"
        msg += f"\nInitial reputation: {self._initial_reputation}"
        print_msg_box(msg=msg, indent=2, title="Defense information")

    @property
    def engine(self):
        return self._engine

    def _is_metric_enabled(self, metric_name: str, metrics_config: dict = None) -> bool:
        """
        Check if a specific metric is enabled based on the provided configuration.
        
        Args:
            metric_name (str): The name of the metric to check.
            metrics_config (dict, optional): The configuration dictionary for metrics. 
                                           If None, uses the instance's _metrics.
            
        Returns:
            bool: True if the metric is enabled, False otherwise.
        """
        config_to_use = metrics_config if metrics_config is not None else getattr(self, '_metrics', None)
        
        if not isinstance(config_to_use, dict):
            if metrics_config is not None:
                logging.warning(f"metrics_config is not a dictionary: {type(metrics_config)}")
            else:
                logging.warning("_metrics is not properly initialized")
            return False
            
        metric_config = config_to_use.get(metric_name)
        if metric_config is None:
            return False

        if isinstance(metric_config, dict):
            return metric_config.get('enabled', True)
        return bool(metric_config)

    def save_data(
        self,
        type_data: str,
        nei: str,
        addr: str,
        num_round: int = None,
        time: float = None,
        current_round: int = None,
        fraction_changed: float = None,
        threshold: float = None,
        latency: float = None,
    ):
        """
        Save data between nodes and aggregated models.
        
        Args:
            type_data: Type of data to save ('number_message', 'fraction_of_params_changed', 'model_arrival_latency')
            nei: Neighbor identifier
            addr: Address identifier
            num_round: Round number
            time: Timestamp
            current_round: Current round number
            fraction_changed: Fraction of parameters changed
            threshold: Threshold value
            latency: Latency value
        """
        if addr == nei:
            return

        if nei not in self.connection_metrics:
            logging.warning(f"Neighbor {nei} not found in connection_metrics")
            return

        try:
            metrics_instance = self.connection_metrics[nei]
            
            if type_data == "number_message":
                message_data = {"time": time, "current_round": current_round}
                if not isinstance(metrics_instance.messages, list):
                    metrics_instance.messages = []
                metrics_instance.messages.append(message_data)
            elif type_data == "fraction_of_params_changed":
                fraction_data = {
                    "fraction_changed": fraction_changed,
                    "threshold": threshold,
                    "current_round": current_round,
                }
                metrics_instance.fraction_of_params_changed.update(fraction_data)
            elif type_data == "model_arrival_latency":
                latency_data = {
                    "latency": latency,
                    "round": num_round,
                    "round_received": current_round,
                }
                metrics_instance.model_arrival_latency.update(latency_data)
            else:
                logging.warning(f"Unknown data type: {type_data}")

        except Exception:
            logging.exception(f"Error saving data for type {type_data} and neighbor {nei}")

    async def setup(self):
        """Set up the reputation system by subscribing to relevant events."""
        if self._enabled:
            await EventManager.get_instance().subscribe_node_event(RoundStartEvent, self.on_round_start)
            await EventManager.get_instance().subscribe_node_event(AggregationEvent, self.calculate_reputation)
            if self._is_metric_enabled("model_similarity"):
                await EventManager.get_instance().subscribe_node_event(UpdateReceivedEvent, self.recollect_similarity)
            if self._is_metric_enabled("fraction_parameters_changed"):
                await EventManager.get_instance().subscribe_node_event(
                    UpdateReceivedEvent, self.recollect_fraction_of_parameters_changed
                )
            if self._is_metric_enabled("model_arrival_latency"):
                await EventManager.get_instance().subscribe_node_event(
                    UpdateReceivedEvent, self.recollect_model_arrival_latency
                )
            if self._is_metric_enabled("num_messages"):
                await EventManager.get_instance().subscribe(("model", "update"), self.recollect_number_message)
                await EventManager.get_instance().subscribe(("model", "initialization"), self.recollect_number_message)
                await EventManager.get_instance().subscribe(("control", "alive"), self.recollect_number_message)
                await EventManager.get_instance().subscribe(
                    ("federation", "federation_models_included"), self.recollect_number_message
                )
                await EventManager.get_instance().subscribe_node_event(DuplicatedMessageEvent, self.recollect_duplicated_number_message)

    def init_reputation(
        self, federation_nodes=None, round_num=None, last_feedback_round=None, init_reputation=None
    ):
        """
        Initialize the reputation system.
        
        Args:
            federation_nodes: List of federation node identifiers
            round_num: Current round number  
            last_feedback_round: Last round that received feedback
            init_reputation: Initial reputation value to assign
        """
        if not self._enabled:
            return
            
        if not self._validate_init_parameters(federation_nodes, round_num, init_reputation):
            return
            
        neighbors = self._validate_federation_nodes(federation_nodes)
        if not neighbors:
            logging.error("init_reputation | No valid neighbors found")
            return

        self._initialize_neighbor_reputations(neighbors, round_num, last_feedback_round, init_reputation)

    def _validate_init_parameters(self, federation_nodes, round_num, init_reputation) -> bool:
        """Validate initialization parameters."""
        if not federation_nodes:
            logging.error("init_reputation | No federation nodes provided")
            return False
            
        if round_num is None:
            logging.warning("init_reputation | Round number not provided")
            
        if init_reputation is None:
            logging.warning("init_reputation | Initial reputation value not provided")
            
        return True

    def _initialize_neighbor_reputations(self, neighbors: list, round_num: int, last_feedback_round: int, init_reputation: float):
        """Initialize reputation entries for all neighbors."""
        for nei in neighbors:
            self._create_or_update_reputation_entry(nei, round_num, last_feedback_round, init_reputation)
            self.save_reputation_history_in_memory(self._addr, nei, init_reputation)

    def _create_or_update_reputation_entry(self, nei: str, round_num: int, last_feedback_round: int, init_reputation: float):
        """Create or update a single reputation entry."""
        reputation_data = {
            "reputation": init_reputation,
            "round": round_num,
            "last_feedback_round": last_feedback_round,
        }
        
        if nei not in self.reputation:
            self.reputation[nei] = reputation_data
        elif self.reputation[nei].get("reputation") is None:
            self.reputation[nei].update(reputation_data)

    def _validate_federation_nodes(self, federation_nodes) -> list:
        """
        Validate and filter federation nodes.
        
        Args:
            federation_nodes: List of federation node identifiers
            
        Returns:
            list: List of valid node identifiers
        """
        if not federation_nodes:
            return []
            
        valid_nodes = [node for node in federation_nodes if node and str(node).strip()]
        
        if not valid_nodes:
            logging.warning("No valid federation nodes found after filtering")
            
        return valid_nodes

    def _calculate_static_reputation(
        self,
        addr: str,
        nei: str,
        metric_values: dict,
    ):
        """
        Calculate the static reputation of a participant using weighted metrics.

        Args:
            addr: The participant's address
            nei: The neighbor's address  
            metric_values: Dictionary with metric values
        """
        static_weights = {
            "num_messages": self._weight_num_messages,
            "model_similarity": self._weight_model_similarity,
            "fraction_parameters_changed": self._weight_fraction_params_changed,
            "model_arrival_latency": self._weight_model_arrival_latency,
        }

        reputation_static = sum(
            metric_values.get(metric_name, 0) * static_weights[metric_name] 
            for metric_name in static_weights
        )
        
        logging.info(f"Static reputation for node {nei} at round {self.engine.get_round()}: {reputation_static}")

        avg_reputation = self.save_reputation_history_in_memory(self.engine.addr, nei, reputation_static)

        metrics_data = {
            "addr": addr,
            "nei": nei,
            "round": self.engine.get_round(),
            "reputation_without_feedback": avg_reputation,
            **{f"average_{name}": weight for name, weight in static_weights.items()}
        }

        self._update_reputation_record(nei, avg_reputation, metrics_data)

    async def _calculate_dynamic_reputation(self, addr, neighbors):
        """
        Calculate the dynamic reputation of a participant.

        Args:
            addr (str): The IP address of the participant.
            neighbors (list): The list of neighbors.
        """
        if not hasattr(self, '_metrics') or self._metrics is None:
            logging.warning("_metrics is not properly initialized")
            return

        average_weights = self._calculate_average_weights()
        self._process_neighbors_reputation(addr, neighbors, average_weights)

    def _calculate_average_weights(self):
        """Calculate average weights for all enabled metrics."""
        average_weights = {}
        
        for metric_name in self.history_data.keys():
            if self._is_metric_enabled(metric_name):
                average_weights[metric_name] = self._get_metric_average_weight(metric_name)
        
        return average_weights
    
    def _get_metric_average_weight(self, metric_name):
        """Get the average weight for a specific metric."""
        if metric_name not in self.history_data or not self.history_data[metric_name]:
            logging.debug(f"No history data available for metric: {metric_name}")
            return 0
        
        valid_entries = [
            entry for entry in self.history_data[metric_name]
            if (entry.get("round") is not None and 
                entry["round"] >= self._engine.get_round() and 
                entry.get("weight") not in [None, -1])
        ]
        
        if not valid_entries:
            return 0
            
        try:
            weights = [entry["weight"] for entry in valid_entries if entry.get("weight") is not None]
            return sum(weights) / len(weights) if weights else 0
        except (TypeError, ZeroDivisionError) as e:
            logging.warning(f"Error calculating average weight for {metric_name}: {e}")
            return 0
    
    def _process_neighbors_reputation(self, addr, neighbors, average_weights):
        """Process reputation calculation for all neighbors."""
        for nei in neighbors:
            metric_values = self._get_neighbor_metric_values(nei)
            
            if all(metric_name in metric_values for metric_name in average_weights):
                self._update_neighbor_reputation(addr, nei, metric_values, average_weights)
    
    def _get_neighbor_metric_values(self, nei):
        """Get metric values for a specific neighbor in the current round."""
        metric_values = {}
        
        for metric_name in self.history_data:
            if self._is_metric_enabled(metric_name):
                for entry in self.history_data.get(metric_name, []):
                    if (entry.get("round") == self._engine.get_round() and
                        entry.get("metric_name") == metric_name and
                        entry.get("nei") == nei):
                        metric_values[metric_name] = entry.get("metric_value", 0)
                        break
        
        return metric_values
    
    def _update_neighbor_reputation(self, addr, nei, metric_values, average_weights):
        """Update reputation for a specific neighbor."""
        reputation_with_weights = sum(
            metric_values.get(metric_name, 0) * average_weights[metric_name] 
            for metric_name in average_weights
        )
        
        logging.info(
            f"Dynamic reputation with weights for {nei} at round {self._engine.get_round()}: {reputation_with_weights}"
        )

        avg_reputation = self.save_reputation_history_in_memory(self._engine.addr, nei, reputation_with_weights)

        metrics_data = {
            "addr": addr,
            "nei": nei,
            "round": self._engine.get_round(),
            "reputation_without_feedback": avg_reputation,
        }

        for metric_name in metric_values:
            metrics_data[f"average_{metric_name}"] = average_weights[metric_name]

        self._update_reputation_record(nei, avg_reputation, metrics_data)

    def _update_reputation_record(self, nei: str, reputation: float, data: dict):
        """
        Update the reputation record of a participant.

        Args:
            nei: The neighbor identifier
            reputation: The reputation value
            data: Additional data to update (currently unused)
        """
        current_round = self._engine.get_round()
        
        if nei not in self.reputation:
            self.reputation[nei] = {
                "reputation": reputation,
                "round": current_round,
                "last_feedback_round": -1,
            }
        else:
            self.reputation[nei]["reputation"] = reputation
            self.reputation[nei]["round"] = current_round

        logging.info(f"Reputation of node {nei}: {self.reputation[nei]['reputation']}")
        
        if self.reputation[nei]["reputation"] < self.REPUTATION_THRESHOLD and current_round > 0:
            self.rejected_nodes.add(nei)
            logging.info(f"Rejected node {nei} at round {current_round}")

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
        if current_round is None:
            return

        self._ensure_history_data_structure(history_data)
        active_metrics = self._get_active_metrics(
            avg_messages_number_message_normalized,
            similarity_reputation,
            fraction_score_asign,
            avg_model_arrival_latency,
            reputation_metrics
        )
        self._add_current_metrics_to_history(active_metrics, history_data, current_round, addr, nei)
        
        if current_round >= self.INITIAL_ROUND_FOR_REPUTATION and len(active_metrics) > 0:
            adjusted_weights = self._calculate_dynamic_weights(active_metrics, history_data)
        else:
            adjusted_weights = self._calculate_uniform_weights(active_metrics)
        
        self._update_history_with_weights(active_metrics, history_data, adjusted_weights, current_round, nei)

    def _ensure_history_data_structure(self, history_data: dict):
        """Ensure all required keys exist in history data structure."""
        required_keys = [
            "num_messages",
            "model_similarity", 
            "fraction_parameters_changed",
            "model_arrival_latency",
        ]
        
        for key in required_keys:
            if key not in history_data:
                history_data[key] = []

    def _get_active_metrics(
        self,
        avg_messages_number_message_normalized,
        similarity_reputation,
        fraction_score_asign,
        avg_model_arrival_latency,
        reputation_metrics
    ) -> dict:
        """Get the dictionary of active metrics based on configuration."""
        all_metrics = {
            "num_messages": avg_messages_number_message_normalized,
            "model_similarity": similarity_reputation,
            "fraction_parameters_changed": fraction_score_asign,
            "model_arrival_latency": avg_model_arrival_latency,
        }
        
        return {k: v for k, v in all_metrics.items() if self._is_metric_enabled(k, reputation_metrics)}

    def _add_current_metrics_to_history(self, active_metrics: dict, history_data: dict, current_round: int, addr: str, nei: str):
        """Add current metric values to history data."""
        for metric_name, current_value in active_metrics.items():
            history_data[metric_name].append({
                "round": current_round,
                "addr": addr,
                "nei": nei,
                "metric_name": metric_name,
                "metric_value": current_value,
                "weight": None,
            })

    def _calculate_dynamic_weights(self, active_metrics: dict, history_data: dict) -> dict:
        """Calculate dynamic weights based on metric deviations."""
        deviations = self._calculate_metric_deviations(active_metrics, history_data)
        
        if all(deviation == 0.0 for deviation in deviations.values()):
            return self._generate_random_weights(active_metrics)
        else:
            normalized_weights = self._normalize_deviation_weights(deviations)
            return self._adjust_weights_with_minimum(normalized_weights, deviations)

    def _calculate_metric_deviations(self, active_metrics: dict, history_data: dict) -> dict:
        """Calculate deviations of current metrics from historical means."""
        deviations = {}
        
        for metric_name, current_value in active_metrics.items():
            historical_values = history_data[metric_name]
            metric_values = [
                entry["metric_value"]
                for entry in historical_values
                if "metric_value" in entry and entry["metric_value"] != 0
            ]
            
            mean_value = np.mean(metric_values) if metric_values else 0
            deviation = abs(current_value - mean_value)
            deviations[metric_name] = deviation
            
        return deviations

    def _generate_random_weights(self, active_metrics: dict) -> dict:
        """Generate random normalized weights when all deviations are zero."""
        num_metrics = len(active_metrics)
        random_weights = [random.random() for _ in range(num_metrics)]
        total_random_weight = sum(random_weights)
        
        return {
            metric_name: weight / total_random_weight
            for metric_name, weight in zip(active_metrics, random_weights, strict=False)
        }

    def _normalize_deviation_weights(self, deviations: dict) -> dict:
        """Normalize weights based on deviations."""
        max_deviation = max(deviations.values()) if deviations else 1
        normalized_weights = {
            metric_name: (deviation / max_deviation) 
            for metric_name, deviation in deviations.items()
        }
        
        total_weight = sum(normalized_weights.values())
        if total_weight > 0:
            return {
                metric_name: weight / total_weight 
                for metric_name, weight in normalized_weights.items()
            }
        else:
            num_metrics = len(deviations)
            return dict.fromkeys(deviations.keys(), 1 / num_metrics)

    def _adjust_weights_with_minimum(self, normalized_weights: dict, deviations: dict) -> dict:
        """Apply minimum weight constraints and renormalize."""
        mean_deviation = np.mean(list(deviations.values()))
        dynamic_min_weight = max(self.DYNAMIC_MIN_WEIGHT_THRESHOLD, mean_deviation / (mean_deviation + 1))
        
        adjusted_weights = {}
        total_adjusted_weight = 0
        
        for metric_name, weight in normalized_weights.items():
            adjusted_weight = max(weight, dynamic_min_weight)
            adjusted_weights[metric_name] = adjusted_weight
            total_adjusted_weight += adjusted_weight
        
        # Renormalize if total weight exceeds 1
        if total_adjusted_weight > 1:
            for metric_name in adjusted_weights:
                adjusted_weights[metric_name] /= total_adjusted_weight
                
        return adjusted_weights

    def _calculate_uniform_weights(self, active_metrics: dict) -> dict:
        """Calculate uniform weights for all active metrics."""
        num_metrics = len(active_metrics)
        if num_metrics == 0:
            return {}
        return dict.fromkeys(active_metrics, 1 / num_metrics)

    def _update_history_with_weights(self, active_metrics: dict, history_data: dict, weights: dict, current_round: int, nei: str):
        """Update history entries with calculated weights."""
        for metric_name in active_metrics:
            weight = weights.get(metric_name, -1)
            for entry in history_data[metric_name]:
                if (entry["metric_name"] == metric_name and 
                    entry["round"] == current_round and 
                    entry["nei"] == nei):
                    entry["weight"] = weight

    async def calculate_value_metrics(self, addr, nei, metrics_active=None):
        """
        Calculate the reputation of each participant based on the data stored in self.connection_metrics.

        Args:
            addr (str): Source IP address.
            nei (str): Destination IP address.
            metrics_active (dict): The active metrics.
        """
        try:
            current_round = self._engine.get_round()
            metrics_instance = self.connection_metrics.get(nei)
            
            if not metrics_instance:
                logging.warning(f"No metrics found for neighbor {nei}")
                return self._get_default_metric_values()

            metric_results = {
                "messages": self._process_num_messages_metric(metrics_instance, addr, nei, current_round, metrics_active),
                "fraction": self._process_fraction_parameters_metric(metrics_instance, addr, nei, current_round, metrics_active),
                "latency": self._process_model_arrival_latency_metric(metrics_instance, addr, nei, current_round, metrics_active),
                "similarity": self._process_model_similarity_metric(nei, current_round, metrics_active)
            }

            self._log_metrics_graphics(metric_results, addr, nei, current_round)
            
            return (
                metric_results["messages"]["avg"],
                metric_results["similarity"],
                metric_results["fraction"],
                metric_results["latency"]
            )

        except Exception as e:
            logging.exception(f"Error calculating reputation. Type: {type(e).__name__}")
            return 0, 0, 0, 0

    def _get_default_metric_values(self) -> tuple:
        """Return default metric values when no metrics instance is found."""
        return (0, 0, 0, 0)

    def _process_num_messages_metric(self, metrics_instance, addr: str, nei: str, current_round: int, metrics_active) -> dict:
        """Process the number of messages metric."""
        if not self._is_metric_enabled("num_messages", metrics_active):
            return {"normalized": 0, "count": 0, "avg": 0}

        filtered_messages = [
            msg for msg in metrics_instance.messages if msg.get("current_round") == current_round
        ]
        
        for msg in filtered_messages:
            self.messages_number_message.append({
                "number_message": msg.get("time"),
                "current_round": msg.get("current_round"),
                "key": (addr, nei),
            })

        normalized, count = self.manage_metric_number_message(
            self.messages_number_message, addr, nei, current_round, True
        )
        
        avg = self.save_number_message_history(addr, nei, normalized, current_round)
        
        if avg is None and current_round > self.HISTORY_ROUNDS_LOOKBACK:
            avg = self.number_message_history[(addr, nei)][current_round - 1]["avg_number_message"]

        return {"normalized": normalized, "count": count, "avg": avg or 0}

    def _process_fraction_parameters_metric(self, metrics_instance, addr: str, nei: str, current_round: int, metrics_active) -> float:
        """Process the fraction of parameters changed metric."""
        if not self._is_metric_enabled("fraction_parameters_changed", metrics_active):
            return 0

        score_fraction = 0
        if metrics_instance.fraction_of_params_changed.get("current_round") == current_round:
            fraction_changed = metrics_instance.fraction_of_params_changed.get("fraction_changed")
            threshold = metrics_instance.fraction_of_params_changed.get("threshold")
            score_fraction = self.analyze_anomalies(addr, nei, current_round, fraction_changed, threshold)

        if current_round >= self.INITIAL_ROUND_FOR_FRACTION:
            return self._calculate_fraction_score_assignment(addr, nei, current_round, score_fraction)
        else:
            return 0

    def _calculate_fraction_score_assignment(self, addr: str, nei: str, current_round: int, score_fraction: float) -> float:
        """Calculate the final fraction score assignment."""
        key_current = (addr, nei, current_round)

        if score_fraction > 0:
            return self._calculate_positive_fraction_score(addr, nei, current_round, score_fraction, key_current)
        else:
            return self._calculate_zero_fraction_score(addr, nei, current_round, key_current)

    def _calculate_positive_fraction_score(self, addr: str, nei: str, current_round: int, score_fraction: float, key_current: tuple) -> float:
        """Calculate fraction score when current score is positive."""
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
        return fraction_score_asign

    def _calculate_zero_fraction_score(self, addr: str, nei: str, current_round: int, key_current: tuple) -> float:
        """Calculate fraction score when current score is zero."""
        key_prev = (addr, nei, current_round - 1)
        prev_score = self.fraction_changed_history.get(key_prev, {}).get("finally_fraction_score")

        if prev_score is not None:
            fraction_score_asign = prev_score * self.ZERO_VALUE_DECAY_FACTOR
        else:
            fraction_neighbors_scores = {
                key: value.get("finally_fraction_score")
                for key, value in self.fraction_changed_history.items()
                if value.get("finally_fraction_score") is not None
            }
            fraction_score_asign = np.mean(list(fraction_neighbors_scores.values())) if fraction_neighbors_scores else 0

        if key_current not in self.fraction_changed_history:
            self.fraction_changed_history[key_current] = {}

        self.fraction_changed_history[key_current]["finally_fraction_score"] = fraction_score_asign
        return fraction_score_asign

    def _process_model_arrival_latency_metric(self, metrics_instance, addr: str, nei: str, current_round: int, metrics_active) -> float:
        """Process the model arrival latency metric."""
        if not self._is_metric_enabled("model_arrival_latency", metrics_active):
            return 0

        latency_normalized = 0
        if metrics_instance.model_arrival_latency.get("round_received") == current_round:
            round_num = metrics_instance.model_arrival_latency.get("round")
            latency = metrics_instance.model_arrival_latency.get("latency")
            latency_normalized = self.manage_model_arrival_latency(addr, nei, latency, current_round, round_num)

        if latency_normalized >= 0:
            avg_latency = self.save_model_arrival_latency_history(nei, latency_normalized, current_round)
            if avg_latency is None and current_round > 1:
                avg_latency = self.model_arrival_latency_history[(addr, nei)][current_round - 1]["score"]
            return avg_latency or 0
        
        return 0

    def _process_model_similarity_metric(self, nei: str, current_round: int, metrics_active) -> float:
        """Process the model similarity metric."""
        if current_round >= 1 and self._is_metric_enabled("model_similarity", metrics_active):
            return self.calculate_similarity_from_metrics(nei, current_round)
        return 0

    def _log_metrics_graphics(self, metric_results: dict, addr: str, nei: str, current_round: int):
        """Log graphics for all calculated metrics."""
        self.create_graphics_to_metrics(
            metric_results["messages"]["count"],
            metric_results["messages"]["avg"],
            metric_results["similarity"],
            metric_results["fraction"],
            metric_results["latency"],
            addr,
            nei,
            current_round,
            self.engine.total_rounds,
        )

    def create_graphics_to_metrics(
        self,
        number_message_count: float,
        number_message_norm: float,
        similarity: float,
        fraction: float,
        model_arrival_latency: float,
        addr: str,
        nei: str,
        current_round: int,
        total_rounds: int,
    ):
        """
        Create and log graphics for reputation metrics.
        
        Args:
            number_message_count: Count of messages for logging
            number_message_norm: Normalized message metric
            similarity: Similarity metric value
            fraction: Fraction of parameters changed metric
            model_arrival_latency: Model arrival latency metric
            addr: Address identifier
            nei: Neighbor identifier
            current_round: Current round number
            total_rounds: Total number of rounds
        """
        if current_round is None or current_round >= total_rounds:
            return
            
        self.engine.trainer._logger.log_data(
            {f"R-Model_arrival_latency_reputation/{addr}": {nei: model_arrival_latency}}, 
            step=current_round
        )
        self.engine.trainer._logger.log_data(
            {f"R-Count_messages_number_message_reputation/{addr}": {nei: number_message_count}}, 
            step=current_round
        )
        self.engine.trainer._logger.log_data(
            {f"R-number_message_reputation/{addr}": {nei: number_message_norm}}, 
            step=current_round
        )
        self.engine.trainer._logger.log_data(
            {f"R-Similarity_reputation/{addr}": {nei: similarity}}, 
            step=current_round
        )
        self.engine.trainer._logger.log_data(
            {f"R-Fraction_reputation/{addr}": {nei: fraction}}, 
            step=current_round
        )

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
            self._initialize_fraction_history_entry(key, fraction_changed, threshold)
            
            if current_round == 0:
                return self._handle_initial_round_anomalies(key, fraction_changed, threshold)
            else:
                return self._handle_subsequent_round_anomalies(key, addr, nei, current_round, fraction_changed, threshold)

        except Exception:
            logging.exception("Error analyzing anomalies")
            return -1

    def _initialize_fraction_history_entry(self, key: tuple, fraction_changed: float, threshold: float):
        """Initialize fraction history entry if it doesn't exist."""
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

    def _handle_initial_round_anomalies(self, key: tuple, fraction_changed: float, threshold: float) -> float:
        """Handle anomaly analysis for the initial round (round 0)."""
        self.fraction_changed_history[key].update({
            "mean_fraction": fraction_changed,
            "std_dev_fraction": 0.0,
            "mean_threshold": threshold,
            "std_dev_threshold": 0.0,
            "fraction_score": 1.0,
        })
        return 1.0

    def _handle_subsequent_round_anomalies(
        self, key: tuple, addr: str, nei: str, current_round: int, fraction_changed: float, threshold: float
    ) -> float:
        """Handle anomaly analysis for subsequent rounds."""
        prev_stats = self._find_previous_valid_stats(addr, nei, current_round)
        
        if prev_stats is None:
            logging.warning(f"No valid previous stats found for {addr}, {nei}, round {current_round}")
            return 1.0
            
        anomalies = self._detect_anomalies(fraction_changed, threshold, prev_stats)
        values = self._calculate_anomaly_values(fraction_changed, threshold, prev_stats, anomalies)
        fraction_score = self._calculate_combined_score(values)
        self._update_fraction_statistics(key, fraction_changed, threshold, prev_stats, anomalies, fraction_score)
        
        return max(fraction_score, 0)

    def _find_previous_valid_stats(self, addr: str, nei: str, current_round: int) -> dict:
        """Find the most recent valid statistics from previous rounds."""
        for i in range(1, current_round + 1):
            candidate_key = (addr, nei, current_round - i)
            candidate_data = self.fraction_changed_history.get(candidate_key, {})
            
            required_keys = ["mean_fraction", "std_dev_fraction", "mean_threshold", "std_dev_threshold"]
            if all(candidate_data.get(k) is not None for k in required_keys):
                return candidate_data
                
        return None

    def _detect_anomalies(self, current_fraction: float, current_threshold: float, prev_stats: dict) -> dict:
        """Detect if current values are anomalous compared to previous statistics."""
        upper_mean_fraction = (prev_stats["mean_fraction"] + prev_stats["std_dev_fraction"]) * self.FRACTION_ANOMALY_MULTIPLIER
        upper_mean_threshold = (prev_stats["mean_threshold"] + prev_stats["std_dev_threshold"]) * self.THRESHOLD_ANOMALY_MULTIPLIER
        
        return {
            "fraction_anomaly": current_fraction > upper_mean_fraction,
            "threshold_anomaly": current_threshold > upper_mean_threshold,
            "upper_mean_fraction": upper_mean_fraction,
            "upper_mean_threshold": upper_mean_threshold,
        }

    def _calculate_anomaly_values(
        self, current_fraction: float, current_threshold: float, prev_stats: dict, anomalies: dict
    ) -> dict:
        """Calculate penalty values for fraction and threshold anomalies."""
        fraction_value = 1.0
        threshold_value = 1.0
        
        if anomalies["fraction_anomaly"]:
            mean_fraction_prev = prev_stats["mean_fraction"]
            if mean_fraction_prev > 0:
                penalization_factor = abs(current_fraction - mean_fraction_prev) / mean_fraction_prev
                fraction_value = 1 - (1 / (1 + np.exp(-penalization_factor)))
        
        if anomalies["threshold_anomaly"]:
            mean_threshold_prev = prev_stats["mean_threshold"]
            if mean_threshold_prev > 0:
                penalization_factor = abs(current_threshold - mean_threshold_prev) / mean_threshold_prev
                threshold_value = 1 - (1 / (1 + np.exp(-penalization_factor)))
        
        return {
            "fraction_value": fraction_value,
            "threshold_value": threshold_value,
        }

    def _calculate_combined_score(self, values: dict) -> float:
        """Calculate the combined fraction score from individual values."""
        fraction_weight = 0.5
        threshold_weight = 0.5
        return fraction_weight * values["fraction_value"] + threshold_weight * values["threshold_value"]

    def _update_fraction_statistics(
        self, key: tuple, current_fraction: float, current_threshold: float, 
        prev_stats: dict, anomalies: dict, fraction_score: float
    ):
        """Update the fraction statistics for the current round."""
        self.fraction_changed_history[key]["fraction_anomaly"] = anomalies["fraction_anomaly"]
        self.fraction_changed_history[key]["threshold_anomaly"] = anomalies["threshold_anomaly"]
        
        self.fraction_changed_history[key]["mean_fraction"] = (current_fraction + prev_stats["mean_fraction"]) / 2
        self.fraction_changed_history[key]["mean_threshold"] = (current_threshold + prev_stats["mean_threshold"]) / 2
        
        fraction_variance = ((current_fraction - prev_stats["mean_fraction"]) ** 2 + prev_stats["std_dev_fraction"] ** 2) / 2
        threshold_variance = ((self.THRESHOLD_VARIANCE_MULTIPLIER * (current_threshold - prev_stats["mean_threshold"]) ** 2) + prev_stats["std_dev_threshold"] ** 2) / 2
        
        self.fraction_changed_history[key]["std_dev_fraction"] = np.sqrt(fraction_variance)
        self.fraction_changed_history[key]["std_dev_threshold"] = np.sqrt(threshold_variance)
        self.fraction_changed_history[key]["fraction_score"] = fraction_score

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
            
            self._initialize_latency_round_entry(current_round, current_key, latency)
            
            if current_round >= 1:
                score = self._calculate_latency_score(current_round, current_key, latency)
                self._update_latency_entry_with_score(current_round, current_key, score)
            else:
                score = 0

            return score

        except Exception as e:
            logging.exception(f"Error managing model_arrival_latency: {e}")
            return 0

    def _initialize_latency_round_entry(self, current_round: int, current_key: str, latency: float):
        """Initialize latency entry for the current round."""
        if current_round not in self.model_arrival_latency_history:
            self.model_arrival_latency_history[current_round] = {}

        self.model_arrival_latency_history[current_round][current_key] = {
            "latency": latency,
            "score": 0.0,
        }

    def _calculate_latency_score(self, current_round: int, current_key: str, latency: float) -> float:
        """Calculate the latency score based on historical data."""
        target_round = self._get_target_round_for_latency(current_round)
        all_latencies = self._get_all_latencies_for_round(target_round)
        
        if not all_latencies:
            return 0.0
            
        mean_latency = np.mean(all_latencies)
        augment_mean = mean_latency * self.LATENCY_AUGMENT_FACTOR
        
        if latency is None:
            logging.info(f"latency is None in round {current_round} for nei {current_key}")
            return -0.5
            
        if latency <= augment_mean:
            return 1.0
        else:
            return 1 / (1 + np.exp(abs(latency - mean_latency) / mean_latency)) if mean_latency != 0 else 0.0

    def _get_target_round_for_latency(self, current_round: int) -> int:
        """Get the target round for latency calculation."""
        target_round = current_round - 1
        return target_round if target_round in self.model_arrival_latency_history else current_round

    def _get_all_latencies_for_round(self, target_round: int) -> list:
        """Get all valid latencies for the target round."""
        return [
            data["latency"]
            for data in self.model_arrival_latency_history.get(target_round, {}).values()
            if data.get("latency") not in (None, 0.0)
        ]

    def _update_latency_entry_with_score(self, current_round: int, current_key: str, score: float):
        """Update the latency entry with calculated score and mean."""
        target_round = self._get_target_round_for_latency(current_round)
        all_latencies = self._get_all_latencies_for_round(target_round)
        mean_latency = np.mean(all_latencies) if all_latencies else 0
        
        self.model_arrival_latency_history[current_round][current_key].update({
            "mean_latency": mean_latency,
            "score": score,
        })

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
            
            self._initialize_latency_history_entry(round_num, current_key, model_arrival_latency)
            
            if model_arrival_latency > 0 and round_num >= 1:
                avg_model_arrival_latency = self._calculate_latency_weighted_average_positive(
                    round_num, current_key, model_arrival_latency
                )
            elif model_arrival_latency == 0 and round_num >= 1:
                avg_model_arrival_latency = self._calculate_latency_weighted_average_zero(
                    round_num, current_key
                )
            elif model_arrival_latency < 0 and round_num >= 1:
                avg_model_arrival_latency = abs(model_arrival_latency) * self.NEGATIVE_LATENCY_PENALTY
            else:
                avg_model_arrival_latency = 0

            self.model_arrival_latency_history[round_num][current_key]["avg_model_arrival_latency"] = (
                avg_model_arrival_latency
            )

            return avg_model_arrival_latency
            
        except Exception:
            logging.exception("Error saving model_arrival_latency history")

    def _initialize_latency_history_entry(self, round_num: int, current_key: str, latency_value: float):
        """Initialize latency history entry for the given round and key."""
        if round_num not in self.model_arrival_latency_history:
            self.model_arrival_latency_history[round_num] = {}

        if current_key not in self.model_arrival_latency_history[round_num]:
            self.model_arrival_latency_history[round_num][current_key] = {}

        self.model_arrival_latency_history[round_num][current_key].update({
            "score": latency_value,
        })

    def _calculate_latency_weighted_average_positive(self, round_num: int, current_key: str, current_value: float) -> float:
        """Calculate weighted average for positive latency values."""
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
            return current_value * self.CURRENT_VALUE_WEIGHT_LOW + avg_past * self.PAST_VALUE_WEIGHT_HIGH
        else:
            return current_value

    def _calculate_latency_weighted_average_zero(self, round_num: int, current_key: str) -> float:
        """Calculate weighted average when current latency value is zero."""
        previous_avg = (
            self.model_arrival_latency_history.get(round_num - 1, {})
            .get(current_key, {})
            .get("avg_model_arrival_latency", None)
        )
        return previous_avg * self.ZERO_VALUE_DECAY_FACTOR if previous_avg is not None else 0

    def manage_metric_number_message(
        self, messages_number_message: list, addr: str, nei: str, current_round: int, metric_active: bool = True
    ) -> tuple[float, int]:
        """
        Manage the number of messages metric for a specific neighbor.
        
        Args:
            messages_number_message: List of message data
            addr: Source address
            nei: Neighbor address
            current_round: Current round number
            metric_active: Whether the metric is active
            
        Returns:
            Tuple of (normalized_messages, messages_count)
        """
        try:
            if current_round == 0 or not metric_active:
                return 0.0, 0

            messages_count = self._count_relevant_messages(messages_number_message, addr, nei, current_round)
            neighbor_stats = self._calculate_neighbor_statistics(messages_number_message, current_round)
            
            normalized_messages = self._calculate_normalized_messages(messages_count, neighbor_stats)
            
            normalized_messages = self._apply_historical_penalty(
                normalized_messages, addr, nei, current_round
            )
            
            self._store_message_history(addr, nei, current_round, normalized_messages)
            normalized_messages = max(0.001, normalized_messages)

            return normalized_messages, messages_count

        except Exception:
            logging.exception("Error managing metric number_message")
            return 0.0, 0

    def _count_relevant_messages(self, messages: list, addr: str, nei: str, current_round: int) -> int:
        """Count messages relevant to the current address-neighbor pair and round."""
        current_addr_nei = (addr, nei)
        relevant_messages = [
            msg for msg in messages
            if msg["key"] == current_addr_nei and msg["current_round"] == current_round
        ]
        return len(relevant_messages)

    def _calculate_neighbor_statistics(self, messages: list, current_round: int) -> dict:
        """Calculate statistical metrics for all neighbors in the previous round."""
        previous_round = current_round - 1
        all_messages_previous_round = [
            m for m in messages if m.get("current_round") == previous_round
        ]

        neighbor_counts = {}
        for m in all_messages_previous_round:
            key = m.get("key")
            neighbor_counts[key] = neighbor_counts.get(key, 0) + 1

        counts_all_neighbors = list(neighbor_counts.values())
        
        if not counts_all_neighbors:
            return {
                "percentile_reference": 0,
                "std_dev": 0,
                "mean_messages": 0,
                "augment_mean": 0,
            }

        mean_messages = np.mean(counts_all_neighbors)
        
        return {
            "percentile_reference": np.percentile(counts_all_neighbors, 25),
            "std_dev": np.std(counts_all_neighbors),
            "mean_messages": mean_messages,
            "augment_mean": mean_messages * self.MESSAGE_AUGMENT_FACTOR_EARLY if current_round <= self.INITIAL_ROUND_FOR_REPUTATION else mean_messages * self.MESSAGE_AUGMENT_FACTOR_NORMAL,
        }

    def _calculate_normalized_messages(self, messages_count: int, neighbor_stats: dict) -> float:
        """Calculate normalized message score with relative and extra penalties."""
        normalized_messages = 1.0
        penalties_applied = []
        
        relative_increase = self._calculate_relative_increase(messages_count, neighbor_stats["percentile_reference"])
        dynamic_margin = self._calculate_dynamic_margin(neighbor_stats)
        
        if relative_increase > dynamic_margin:
            penalty_ratio = self._calculate_penalty_ratio(relative_increase, dynamic_margin)
            normalized_messages *= np.exp(-(penalty_ratio**2))
            penalties_applied.append(f"relative_penalty({penalty_ratio:.3f})")

        if self._should_apply_extra_penalty(messages_count, neighbor_stats):
            extra_penalty_factor = self._calculate_extra_penalty_factor(messages_count, neighbor_stats)
            normalized_messages *= np.exp(-((extra_penalty_factor) ** 2))
            penalties_applied.append(f"extra_penalty({extra_penalty_factor:.3f})")

        if penalties_applied:
            logging.debug(f"Message penalties applied: {', '.join(penalties_applied)} -> score: {normalized_messages:.4f}")

        return normalized_messages

    def _calculate_relative_increase(self, messages_count: int, percentile_reference: float) -> float:
        """Calculate the relative increase compared to percentile reference."""
        if percentile_reference > 0:
            raw_relative_increase = (messages_count - percentile_reference) / percentile_reference
            return np.log1p(raw_relative_increase)
        return 0.0

    def _calculate_dynamic_margin(self, neighbor_stats: dict) -> float:
        """Calculate dynamic margin for penalty application."""
        std_dev = neighbor_stats["std_dev"]
        percentile_reference = neighbor_stats["percentile_reference"]
        return (std_dev + 1) / (np.log1p(percentile_reference) + 1)

    def _calculate_penalty_ratio(self, relative_increase: float, dynamic_margin: float) -> float:
        """Calculate penalty ratio for relative increase penalty."""
        epsilon = 1e-6  # Small constant to avoid division by zero
        return np.log1p(relative_increase - dynamic_margin) / (np.log1p(dynamic_margin + epsilon) + epsilon)

    def _should_apply_extra_penalty(self, messages_count: int, neighbor_stats: dict) -> bool:
        """Determine if extra penalty should be applied."""
        return (neighbor_stats["mean_messages"] > 0 and 
                messages_count > neighbor_stats["augment_mean"])

    def _calculate_extra_penalty_factor(self, messages_count: int, neighbor_stats: dict) -> float:
        """Calculate the extra penalty factor."""
        epsilon = 1e-6
        mean_messages = neighbor_stats["mean_messages"]
        augment_mean = neighbor_stats["augment_mean"]
        
        extra_penalty = (messages_count - mean_messages) / (mean_messages + epsilon)
        amplification = 1 + (augment_mean / (mean_messages + epsilon))
        return extra_penalty * amplification

    def _apply_historical_penalty(self, normalized_messages: float, addr: str, nei: str, current_round: int) -> float:
        """Apply historical penalty based on previous round's score."""
        if current_round <= 1:
            return normalized_messages
            
        prev_data = (
            self.number_message_history.get((addr, nei), {})
            .get(current_round - 1, {})
        )
        
        prev_score = prev_data.get("normalized_messages")
        was_previously_penalized = prev_data.get("was_penalized", False)
        
        if prev_score is not None and prev_score < self.HISTORICAL_PENALTY_THRESHOLD:
            original_score = normalized_messages
            
            if was_previously_penalized:
                penalty_factor = self.HISTORICAL_PENALTY_THRESHOLD * 0.8
                logging.debug(f"Repeated penalty applied to {nei}: stricter historical penalty")
            else:
                penalty_factor = self.HISTORICAL_PENALTY_THRESHOLD
            
            normalized_messages *= penalty_factor
            logging.debug(f"Historical penalty applied to {nei}: {original_score:.4f} -> {normalized_messages:.4f} (prev_score: {prev_score:.4f}, was_penalized: {was_previously_penalized})")
            
        return normalized_messages

    def _store_message_history(self, addr: str, nei: str, current_round: int, normalized_messages: float):
        """Store the normalized messages in history."""
        key = (addr, nei)
        if key not in self.number_message_history:
            self.number_message_history[key] = {}
        
        was_penalized = normalized_messages < 1.0
        
        self.number_message_history[key][current_round] = {
            "normalized_messages": normalized_messages,
            "was_penalized": was_penalized,
            "penalty_severity": 1.0 - normalized_messages if was_penalized else 0.0
        }

    def save_number_message_history(self, addr, nei, messages_number_message_normalized, current_round):
        """
        Save the number_message history of a participant (addr) regarding its neighbor (nei) in memory.
        Uses a weighted average of the past 3 rounds to smooth the result.

        Returns:
            float: The weighted average including the current round.
        """
        try:
            key = (addr, nei)
            
            self._initialize_message_history_entry(key, current_round, messages_number_message_normalized)
            
            if messages_number_message_normalized > 0 and current_round >= 1:
                avg_number_message = self._calculate_weighted_average_positive(key, current_round, messages_number_message_normalized)
            elif messages_number_message_normalized == 0 and current_round >= 1:
                avg_number_message = self._calculate_weighted_average_zero(key, current_round)
            elif messages_number_message_normalized < 0 and current_round >= 1:
                avg_number_message = abs(messages_number_message_normalized) * self.NEGATIVE_LATENCY_PENALTY
            else:
                avg_number_message = 0

            self.number_message_history[key][current_round]["avg_number_message"] = avg_number_message
            return avg_number_message
            
        except Exception:
            logging.exception("Error saving number_message history")
            return -1

    def _initialize_message_history_entry(self, key: tuple, current_round: int, messages_normalized: float):
        """Initialize message history entry for the given key and round."""
        if key not in self.number_message_history:
            self.number_message_history[key] = {}

        if current_round not in self.number_message_history[key]:
            self.number_message_history[key][current_round] = {}

        self.number_message_history[key][current_round].update({
            "number_message": messages_normalized,
        })

    def _calculate_weighted_average_positive(self, key: tuple, current_round: int, current_value: float) -> float:
        """Calculate weighted average for positive message values."""
        past_values = []
        for r in range(current_round - self.WEIGHTED_HISTORY_ROUNDS, current_round):
            val = self.number_message_history.get(key, {}).get(r, {}).get("avg_number_message", None)
            if val is not None and val != 0:
                past_values.append(val)

        if past_values:
            avg_past = sum(past_values) / len(past_values)
            return current_value * self.CURRENT_VALUE_WEIGHT_HIGH + avg_past * self.PAST_VALUE_WEIGHT_LOW
        else:
            return current_value

    def _calculate_weighted_average_zero(self, key: tuple, current_round: int) -> float:
        """Calculate weighted average when current message value is zero."""
        previous_avg = (
            self.number_message_history.get(key, {})
            .get(current_round - 1, {})
            .get("avg_number_message", None)
        )
        return previous_avg * self.ZERO_VALUE_DECAY_FACTOR if previous_avg is not None else 0

    def save_reputation_history_in_memory(self, addr: str, nei: str, reputation: float) -> float:
        """
        Save reputation history and calculate weighted average.

        Args:
            addr: The node's identifier
            nei: The neighboring node identifier  
            reputation: The reputation value to save

        Returns:
            float: The weighted average reputation
        """
        try:
            key = (addr, nei)
            current_round = self._engine.get_round()
            
            if key not in self.reputation_history:
                self.reputation_history[key] = {}

            self.reputation_history[key][current_round] = reputation

            rounds = sorted(self.reputation_history[key].keys(), reverse=True)[:2]
            
            if len(rounds) >= 2:
                current_rep = self.reputation_history[key][rounds[0]]
                previous_rep = self.reputation_history[key][rounds[1]]
                
                current_weight = self.REPUTATION_CURRENT_WEIGHT
                previous_weight = self.REPUTATION_FEEDBACK_WEIGHT
                avg_reputation = (current_rep * current_weight) + (previous_rep * previous_weight)
                
                logging.info(f"Current reputation: {current_rep}, Previous reputation: {previous_rep}")
                logging.info(f"Reputation ponderated: {avg_reputation}")
            else:
                avg_reputation = reputation
                
            return avg_reputation

        except Exception:
            logging.exception("Error saving reputation history")
            return -1

    def calculate_similarity_from_metrics(self, nei: str, current_round: int) -> float:
        """
        Calculate the similarity value from stored similarity metrics.

        Args:
            nei: The neighbor identifier
            current_round: The current round number

        Returns:
            float: The computed similarity value (0.0 if no metrics found)
        """
        try:
            metrics_instance = self.connection_metrics.get(nei)
            if not metrics_instance:
                return 0.0

            relevant_metrics = [
                metric for metric in metrics_instance.similarity 
                if metric.get("nei") == nei and metric.get("current_round") == current_round
            ]
            
            if not relevant_metrics:
                relevant_metrics = [
                    metric for metric in metrics_instance.similarity 
                    if metric.get("nei") == nei
                ]
                
            if not relevant_metrics:
                return 0.0
            neighbor_metric = relevant_metrics[-1]

            similarity_weights = {
                "cosine": 0.25,
                "euclidean": 0.25, 
                "manhattan": 0.25,
                "pearson_correlation": 0.25,
            }

            similarity_value = sum(
                similarity_weights[metric_name] * float(neighbor_metric.get(metric_name, 0))
                for metric_name in similarity_weights
            )

            return max(0.0, min(1.0, similarity_value))
            
        except Exception:
            return 0.0

    async def calculate_reputation(self, ae: AggregationEvent):
        """
        Calculate the reputation of the node based on the active metrics.

        Args:
            ae (AggregationEvent): The aggregation event.
        """
        if not self._enabled:
            return

        (updates, _, _) = await ae.get_event_data()
        self._log_reputation_calculation_start()
        
        neighbors = set(await self._engine._cm.get_addrs_current_connections(only_direct=True))
        
        await self._process_neighbor_metrics(neighbors)
        await self._calculate_reputation_by_factor(neighbors)
        await self._handle_initial_reputation()
        await self._process_feedback()
        await self._finalize_reputation_calculation(updates, neighbors)

    def _log_reputation_calculation_start(self):
        """Log the start of reputation calculation with relevant information."""
        current_round = self._engine.get_round()
        logging.info(f"Calculating reputation at round {current_round}")
        logging.info(f"Active metrics: {self._metrics}")
        logging.info(f"rejected nodes at round {current_round}: {self.rejected_nodes}")
        self.rejected_nodes.clear()
        logging.info(f"Rejected nodes clear: {self.rejected_nodes}")

    async def _process_neighbor_metrics(self, neighbors):
        """Process metrics for each neighbor."""
        for nei in neighbors:
            metrics = await self.calculate_value_metrics(
                self._addr, nei, metrics_active=self._metrics
            )
            
            if self._weighting_factor == "dynamic":
                self._process_dynamic_metrics(nei, metrics)
            elif self._weighting_factor == "static" and self._engine.get_round() >= 1:
                self._process_static_metrics(nei, metrics)

    def _process_dynamic_metrics(self, nei, metrics):
        """Process metrics for dynamic weighting factor."""
        (metric_messages_number, metric_similarity, metric_fraction, metric_model_arrival_latency) = metrics
        
        self.calculate_weighted_values(
            metric_messages_number,
            metric_similarity,
            metric_fraction,
            metric_model_arrival_latency,
            self.history_data,
            self._engine.get_round(),
            self._addr,
            nei,
            self._metrics,
        )

    def _process_static_metrics(self, nei, metrics):
        """Process metrics for static weighting factor."""
        (metric_messages_number, metric_similarity, metric_fraction, metric_model_arrival_latency) = metrics
        
        metric_values_dict = {
            "num_messages": metric_messages_number,
            "model_similarity": metric_similarity,
            "fraction_parameters_changed": metric_fraction,
            "model_arrival_latency": metric_model_arrival_latency,
        }
        self._calculate_static_reputation(self._addr, nei, metric_values_dict)

    async def _calculate_reputation_by_factor(self, neighbors):
        """Calculate reputation based on the weighting factor."""
        if self._weighting_factor == "dynamic" and self._engine.get_round() >= 1:
            await self._calculate_dynamic_reputation(self._addr, neighbors)

    async def _handle_initial_reputation(self):
        """Handle reputation initialization for the first round."""
        if self._engine.get_round() < 1 and self._enabled:
            federation = self._engine.config.participant["network_args"]["neighbors"].split()
            self.init_reputation(
                federation_nodes=federation,
                round_num=self._engine.get_round(),
                last_feedback_round=-1,
                init_reputation=self._initial_reputation,
            )

    async def _process_feedback(self):
        """Process and include feedback in reputation."""
        status = await self.include_feedback_in_reputation()
        current_round = self._engine.get_round()
        
        if status:
            logging.info(f"Feedback included in reputation at round {current_round}")
        else:
            logging.info(f"Feedback not included in reputation at round {current_round}")

    async def _finalize_reputation_calculation(self, updates, neighbors):
        """Finalize reputation calculation by creating graphics and sending data."""
        if self.reputation is not None:
            self.create_graphic_reputation(self._addr, self._engine.get_round())
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

    def create_graphic_reputation(self, addr: str, round_num: int):
        """
        Log reputation data for visualization.
        
        Args:
            addr: The node address
            round_num: The round number for logging step
        """
        try:
            valid_reputations = {
                node_id: float(data["reputation"])
                for node_id, data in self.reputation.items()
                if data.get("reputation") is not None
            }
            
            if valid_reputations:
                reputation_data = {f"Reputation/{addr}": valid_reputations}
                self._engine.trainer._logger.log_data(reputation_data, step=round_num)

        except Exception:
            logging.exception("Error creating reputation graphic")

    async def update_process_aggregation(self, updates):
        """
        Update the process of aggregation by removing rejected nodes from the updates and
        scaling the weights of the models based on their reputation.
        """
        for rn in self.rejected_nodes:
            if rn in updates:
                updates.pop(rn)

        if self.engine.get_round() >= 1:
            for nei in list(updates.keys()):
                if nei in self.reputation:
                    rep = self.reputation[nei].get("reputation", 0)
                    if rep >= self.REPUTATION_SCALING_THRESHOLD:
                        weight = (rep - self.REPUTATION_SCALING_THRESHOLD) / self.REPUTATION_SCALING_RANGE
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
        weight_current_reputation = self.REPUTATION_CURRENT_WEIGHT
        weight_feedback = self.REPUTATION_FEEDBACK_WEIGHT

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
        """
        Collect and analyze model similarity metrics.
        
        Args:
            ure: UpdateReceivedEvent containing model and metadata
        """
        (decoded_model, weight, nei, round_num, local) = await ure.get_event_data()
        
        if not (self._enabled and self._is_metric_enabled("model_similarity")):
            return
            
        if not self._engine.config.participant["adaptive_args"]["model_similarity"]:
            return
            
        if nei == self._addr:
            return
            
        logging.info("🤖  handle_model_message | Checking model similarity")
        
        local_model = self._engine.trainer.get_model_parameters()
        similarity_values = self._calculate_all_similarity_metrics(local_model, decoded_model)
        
        similarity_metrics = {
            "timestamp": datetime.now(),
            "nei": nei,
            "round": round_num,
            "current_round": self._engine.get_round(),
            **similarity_values
        }

        self._store_similarity_metrics(nei, similarity_metrics)
        self._check_similarity_threshold(nei, similarity_values["cosine"])

    def _calculate_all_similarity_metrics(self, local_model: dict, received_model: dict) -> dict:
        """Calculate all similarity metrics between two models."""
        if not local_model or not received_model:
            return {
                "cosine": 0.0,
                "euclidean": 0.0,
                "manhattan": 0.0,
                "pearson_correlation": 0.0,
                "jaccard": 0.0,
                "minkowski": 0.0,
            }
        
        similarity_functions = [
            ("cosine", cosine_metric),
            ("euclidean", euclidean_metric),
            ("manhattan", manhattan_metric),
            ("pearson_correlation", pearson_correlation_metric),
            ("jaccard", jaccard_metric),
        ]
        
        similarity_values = {}
        
        for name, metric_func in similarity_functions:
            try:
                similarity_values[name] = metric_func(local_model, received_model, similarity=True)
            except Exception:
                similarity_values[name] = 0.0
        
        try:
            similarity_values["minkowski"] = minkowski_metric(
                local_model, received_model, p=2, similarity=True
            )
        except Exception:
            similarity_values["minkowski"] = 0.0
        
        return similarity_values

    def _store_similarity_metrics(self, nei: str, similarity_metrics: dict):
        """Store similarity metrics for the given neighbor."""
        if nei not in self.connection_metrics:
            self.connection_metrics[nei] = Metrics()
            
        self.connection_metrics[nei].similarity.append(similarity_metrics)

    def _check_similarity_threshold(self, nei: str, cosine_value: float):
        """Check if cosine similarity is below threshold and mark node if necessary."""
        if cosine_value < self.SIMILARITY_THRESHOLD:
            logging.info("🤖  handle_model_message | Model similarity is less than threshold")
            self.rejected_nodes.add(nei)

    async def recollect_number_message(self, source, message):
        """Record a number message from a source."""
        self._record_message_data(source)

    async def recollect_duplicated_number_message(self, dme: DuplicatedMessageEvent):
        """Record a duplicated message event."""
        event_data = await dme.get_event_data()
        if isinstance(event_data, tuple):
            source = event_data[0]
        else:
            source = event_data
        self._record_message_data(source)

    def _record_message_data(self, source: str):
        """Record message data for the given source if it's not the current address."""
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
        Collect and analyze the fraction of parameters that changed between models.
        
        Args:
            ure: UpdateReceivedEvent containing model and metadata
        """
        (decoded_model, weight, source, round_num, local) = await ure.get_event_data()
        
        current_round = self._engine.get_round()
        parameters_local = self._engine.trainer.get_model_parameters()
        
        prev_threshold = self._get_previous_threshold(source, current_round)
        differences = self._calculate_parameter_differences(parameters_local, decoded_model)
        current_threshold = self._calculate_threshold(differences, prev_threshold)
        
        changed_params, total_params, changes_record = self._count_changed_parameters(
            parameters_local, decoded_model, current_threshold
        )
        
        fraction_changed = changed_params / total_params if total_params > 0 else 0.0
        
        self._store_fraction_data(source, current_round, {
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

    def _get_previous_threshold(self, source: str, current_round: int) -> float:
        """Get the threshold from the previous round for the given source."""
        if (source in self.fraction_of_params_changed and 
            current_round - 1 in self.fraction_of_params_changed[source]):
            return self.fraction_of_params_changed[source][current_round - 1][-1]["threshold"]
        return None

    def _calculate_parameter_differences(self, local_params: dict, received_params: dict) -> list:
        """Calculate absolute differences between local and received parameters."""
        differences = []
        for key in local_params.keys():
            if key in received_params:
                local_tensor = local_params[key].cpu()
                received_tensor = received_params[key].cpu()
                diff = torch.abs(local_tensor - received_tensor)
                differences.extend(diff.flatten().tolist())
        return differences

    def _calculate_threshold(self, differences: list, prev_threshold: float) -> float:
        """Calculate the threshold for determining parameter changes."""
        if not differences:
            return 0
            
        mean_threshold = torch.mean(torch.tensor(differences)).item()
        if prev_threshold is not None:
            return (prev_threshold + mean_threshold) / 2
        return mean_threshold

    def _count_changed_parameters(self, local_params: dict, received_params: dict, threshold: float) -> tuple:
        """Count the number of parameters that changed above the threshold."""
        total_params = 0
        changed_params = 0
        changes_record = {}
        
        for key in local_params.keys():
            if key in received_params:
                local_tensor = local_params[key].cpu()
                received_tensor = received_params[key].cpu()
                diff = torch.abs(local_tensor - received_tensor)
                total_params += diff.numel()
                
                num_changed = torch.sum(diff > threshold).item()
                changed_params += num_changed
                
                if num_changed > 0:
                    changes_record[key] = num_changed
                    
        return changed_params, total_params, changes_record

    def _store_fraction_data(self, source: str, current_round: int, data: dict):
        """Store fraction data in the internal data structure."""
        if source not in self.fraction_of_params_changed:
            self.fraction_of_params_changed[source] = {}
        if current_round not in self.fraction_of_params_changed[source]:
            self.fraction_of_params_changed[source][current_round] = []
            
        self.fraction_of_params_changed[source][current_round].append(data)

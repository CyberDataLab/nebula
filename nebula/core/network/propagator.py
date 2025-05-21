import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING, Any

from nebula.addons.functions import print_msg_box

if TYPE_CHECKING:
    from nebula.config.config import Config
    from nebula.core.aggregation.aggregator import Aggregator
    from nebula.core.engine import Engine
    from nebula.core.training.lightning import Lightning


class PropagationStrategy(ABC):
    @abstractmethod
    def is_node_eligible(self, node: str) -> bool:
        pass

    @abstractmethod
    def prepare_model_payload(self, node: str) -> tuple[Any, float] | None:
        pass


class InitialModelPropagation(PropagationStrategy):
    def __init__(self, aggregator: "Aggregator", trainer: "Lightning", engine: "Engine"):
        self.aggregator = aggregator
        self.trainer = trainer
        self.engine = engine

    def get_round(self):
        return self.engine.get_round()

    def is_node_eligible(self, node: str) -> bool:
        return node not in self.engine.cm.get_ready_connections()

    def prepare_model_payload(self, node: str) -> tuple[Any, float] | None:
        return (
            self.trainer.get_model_parameters(initialize=True),
            self.trainer.DEFAULT_MODEL_WEIGHT,
        )


class StableModelPropagation(PropagationStrategy):
    def __init__(self, aggregator: "Aggregator", trainer: "Lightning", engine: "Engine"):
        self.aggregator = aggregator
        self.trainer = trainer
        self.engine = engine
        self.addr = self.engine.get_addr()

    def get_round(self):
        return self.engine.get_round()

    def is_node_eligible(self, node: str) -> bool:
        return (node not in self.aggregator.get_nodes_pending_models_to_aggregate()) or (
            self.engine.cm.connections[node].get_federated_round() < self.get_round()
        )

    def prepare_model_payload(self, node: str) -> tuple[Any, float] | None:
        return self.trainer.get_model_parameters(), self.trainer.get_model_weight()


class Propagator:
    def __init__(self):
        self._cm = None

    @property
    def cm(self):
        if not self._cm:
            from nebula.core.network.communications import CommunicationsManager

            self._cm = CommunicationsManager.get_instance()
            return self._cm
        else:
            return self._cm

    def start(self):
        self.engine: Engine = self.cm.engine
        self.config: Config = self.cm.get_config()
        self.addr = self.cm.get_addr()
        self.aggregator: Aggregator = self.engine.aggregator
        self.trainer: Lightning = self.engine._trainer

        self.status_history = deque(maxlen=self.config.participant["propagator_args"]["history_size"])

        self.interval = self.config.participant["propagator_args"]["propagate_interval"]
        self.model_interval = self.config.participant["propagator_args"]["propagate_model_interval"]
        self.early_stop = self.config.participant["propagator_args"]["propagation_early_stop"]
        self.stable_rounds_count = 0

        # Propagation strategies (adapt to the specific use case)
        self.strategies = {
            "initialization": InitialModelPropagation(self.aggregator, self.trainer, self.engine),
            "stable": StableModelPropagation(self.aggregator, self.trainer, self.engine),
        }
        print_msg_box(
            msg="Starting propagator functionality...\nModel propagation through the network",
            indent=2,
            title="Propagator",
        )

    def get_round(self):
        return self.engine.get_round()

    def update_and_check_neighbors(self, strategy, eligible_neighbors):
        # Update the status of eligible neighbors
        current_status = [n for n in eligible_neighbors]

        # Check if the deque is full and the new status is different from the last one
        if self.status_history and current_status != self.status_history[-1]:
            logging.info(
                f"Status History deque is full and the new status is different from the last one: {list(self.status_history)}"
            )
            self.status_history.append(current_status)
            return True

        # Add the current status to the deque
        logging.info(f"Adding current status to the deque: {current_status}")
        self.status_history.append(current_status)

        # If the deque is full and all elements are the same, stop propagation
        if len(self.status_history) == self.status_history.maxlen and all(
            s == self.status_history[0] for s in self.status_history
        ):
            logging.info(
                f"Propagator exited for {self.status_history.maxlen} equal rounds: {list(self.status_history)}"
            )
            return False

        return True

    def reset_status_history(self):
        self.status_history.clear()

    async def propagate(self, strategy_id: str):
        self.reset_status_history()
        if strategy_id not in self.strategies:
            logging.info(f"Strategy {strategy_id} not found.")
            return False
        if self.get_round() is None:
            logging.info("Propagation halted: round is not set.")
            return False

        strategy = self.strategies[strategy_id]
        logging.info(f"Starting model propagation with strategy: {strategy_id}")

        current_connections = await self.cm.get_addrs_current_connections(only_direct=True)
        eligible_neighbors = [
            neighbor_addr for neighbor_addr in current_connections if strategy.is_node_eligible(neighbor_addr)
        ]
        logging.info(f"Eligible neighbors for model propagation: {eligible_neighbors}")
        if not eligible_neighbors:
            logging.info("Propagation complete: No eligible neighbors.")
            return False

        logging.info("Checking repeated statuses during propagation")
        if not self.update_and_check_neighbors(strategy, eligible_neighbors):
            logging.info("Exiting propagation due to repeated statuses.")
            return False

        model_params, weight = strategy.prepare_model_payload(None)
        if model_params:
            serialized_model = (
                model_params if isinstance(model_params, bytes) else self.trainer.serialize_model(model_params)
            )
        else:
            serialized_model = None

        round_number = -1 if strategy_id == "initialization" else self.get_round()
        parameters = serialized_model
        message = self.cm.create_message("model", "", round_number, parameters, weight)
        for neighbor_addr in eligible_neighbors:
            logging.info(
                f"Sending model to {neighbor_addr} with round {self.get_round()}: weight={weight} | size={sys.getsizeof(serialized_model) / (1024** 2) if serialized_model is not None else 0} MB"
            )
            asyncio.create_task(self.cm.send_message(neighbor_addr, message, "model"))
            # asyncio.create_task(self.cm.send_model(neighbor_addr, round_number, serialized_model, weight))

        await asyncio.sleep(self.interval)
        return True

    async def get_model_information(self, dest_addr, strategy_id: str, init=False):
        if not init:
            if strategy_id not in self.strategies:
                logging.info(f"Strategy {strategy_id} not found.")
                return None
            if self.get_round() is None:
                logging.info("Propagation halted: round is not set.")
                return None

        strategy = self.strategies[strategy_id]
        logging.info(f"Preparing model information with strategy to make an offer: {strategy_id}")

        model_params, weight = strategy.prepare_model_payload(None)
        rounds = self.engine.total_rounds

        if model_params:
            serialized_model = (
                model_params if isinstance(model_params, bytes) else self.trainer.serialize_model(model_params)
            )
            return (serialized_model, rounds, self.get_round())

        return None

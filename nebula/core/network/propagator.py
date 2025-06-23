import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from collections import deque
from nebula.core.nebulaevents import ModelPropagationEvent
from nebula.core.eventmanager import EventManager
from typing import TYPE_CHECKING, Any

from nebula.addons.functions import print_msg_box

if TYPE_CHECKING:
    from nebula.config.config import Config
    from nebula.core.aggregation.aggregator import Aggregator
    from nebula.core.engine import Engine
    from nebula.core.training.lightning import Lightning


class PropagationStrategy(ABC):
    """
    Abstract base class defining the interface for model propagation strategies.

    Subclasses implement eligibility checks and payload preparation for sending
    model updates to specific nodes in the federation.
    """

    @abstractmethod
    async def is_node_eligible(self, node: str) -> bool:
        """
        Determine whether a given node should receive the model payload.

        Args:
            node (str): The address or identifier of the target node.

        Returns:
            bool: True if the node is eligible to receive the payload, False otherwise.
        """
        pass

    @abstractmethod
    def prepare_model_payload(self, node: str) -> tuple[Any, float] | None:
        """
        Prepare the model data and weight for transmission to a node.

        Args:
            node (str): The address or identifier of the target node.

        Returns:
            tuple[Any, float] | None: A tuple containing the model object and its associated weight,
                                       or None if no payload should be sent.
        """
        pass


class InitialModelPropagation(PropagationStrategy):
    """
    Propagation strategy for sending the initial model to all newly connected nodes.

    Sends a fresh model initialized by the trainer with a default weight.
    """

    def __init__(self, aggregator: "Aggregator", trainer: "Lightning", engine: "Engine"):
        """
        Args:
            aggregator (Aggregator): The aggregator coordinating model rounds.
            trainer (Lightning): The local trainer instance providing model parameters.
            engine (Engine): The engine managing rounds and connections.
        """
        self.aggregator = aggregator
        self.trainer = trainer
        self.engine = engine

    async def get_round(self):
        """
        Get the current training round number from the engine.

        Returns:
            int: The current round index.
        """
        return await self.engine.get_round()

    async def is_node_eligible(self, node: str) -> bool:
        """
        Determine if a node has not yet received the initial model.

        Args:
            node (str): The identifier of the target node.

        Returns:
            bool: True if the node is not already in the ready connections list.
        """
        return node not in self.engine.cm.get_ready_connections()

    def prepare_model_payload(self, node: str) -> tuple[Any, float] | None:
        """
        Prepare the initial model parameters and default weight.

        Args:
            node (str): The identifier of the target node (not used in payload).

        Returns:
            tuple[Any, float]: The initialized model parameters and default model weight.
        """
        return (
            self.trainer.get_model_parameters(initialize=True),
            self.trainer.DEFAULT_MODEL_WEIGHT,
        )


class StableModelPropagation(PropagationStrategy):
    """
    Propagation strategy for sending model updates after the initial round.

    Sends the latest trained model to neighbors.
    """

    def __init__(self, aggregator: "Aggregator", trainer: "Lightning", engine: "Engine"):
        """
        Args:
            aggregator (Aggregator): The aggregator coordinating model rounds.
            trainer (Lightning): The local trainer instance providing model parameters and weight.
            engine (Engine): The engine managing rounds, connections, and addresses.
        """
        self.aggregator = aggregator
        self.trainer = trainer
        self.engine = engine
        self.addr = self.engine.get_addr()

    async def get_round(self):
        """
        Get the current training round number from the engine.

        Returns:
            int: The current round index.
        """
        return await self.engine.get_round()

    async def is_node_eligible(self, node: str) -> bool:
        """
        Determine if a node requires a model update based on aggregation state.

        Args:
            node (str): The identifier of the target node.

        Returns:
            bool: True if the node is pending aggregation or its last federated round
                  is less than the current round.
        """
        return (node not in self.aggregator.get_nodes_pending_models_to_aggregate()) or (
            self.engine.cm.connections[node].get_federated_round() < await self.get_round()
        )

    def prepare_model_payload(self, node: str) -> tuple[Any, float] | None:
        """
        Prepare the current model parameters and their corresponding weight.

        Args:
            node (str): The identifier of the target node (not used in payload).

        Returns:
            tuple[Any, float]: The model parameters and model weight for propagation.
        """
        return self.trainer.get_model_parameters(), self.trainer.get_model_weight()


class Propagator:
    """
    Service responsible for propagating messages throughout the federation network.

    The Propagator performs:
      - Broadcasting discovery or control messages to all relevant peers.
      - Managing propagation strategies (e.g., flood, gossip, or efficient spanning tree).
      - Tracking propagation state to avoid infinite loops or redundant sends.
      - Coordinating with the CommunicationsManager and Forwarder for message dispatch.

    Designed to work asynchronously, ensuring timely and scalable message dissemination
    across dynamically changing network topologies.
    """

    def __init__(self):
        self._cm = None
        self._running = asyncio.Event()

    @property
    def cm(self):
        """
        Lazy-load and return the CommunicationsManager instance for sending messages.

        Returns:
            CommunicationsManager: The singleton communications manager.
        """
        if not self._cm:
            from nebula.core.network.communications import CommunicationsManager

            self._cm = CommunicationsManager.get_instance()
            return self._cm
        else:
            return self._cm

    async def start(self):
        """
        Initialize the Propagator by retrieving core components and configuration,
        setting up propagation intervals, history buffer, and strategy instances.

        This method must be called before any propagation cycles to ensure that
        all dependencies (engine, trainer, aggregator, etc.) are available.
        """
        await EventManager.get_instance().subscribe_node_event(ModelPropagationEvent, self._propagate)
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
        self._running.set()

    async def get_round(self):
        """
        Retrieve the current federated learning round number.

        Returns:
            int: The current round index from the engine.
        """
        return await self.engine.get_round()

    def update_and_check_neighbors(self, strategy, eligible_neighbors):
        """
        Update the history of eligible neighbors and determine if propagation should continue.

        Appends the current list of eligible neighbors to a bounded history. If the history
        buffer fills with identical entries, propagation is halted to prevent redundant sends.

        Args:
            strategy (PropagationStrategy): The propagation strategy in use.
            eligible_neighbors (list): List of neighbor addresses eligible for propagation.

        Returns:
            bool: True if propagation should continue, False if it should stop due to repeated history.
        """
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
        """
        Clear the history buffer of neighbor eligibility statuses.

        This is typically done at the start of a new propagation cycle.
        """
        self.status_history.clear()

    async def _propagate(self, mpe: ModelPropagationEvent):
        """
        Execute a single propagation cycle using the specified strategy.

        1. Resets status history.
        2. Validates the strategy and current round.
        3. Identifies eligible neighbors.
        4. Updates history and checks for repeated statuses.
        5. Prepares and serializes the model payload.
        6. Sends the model message to each eligible neighbor.
        7. Waits for the configured interval before concluding.

        Args:
            strategy_id (str): Key identifying which propagation strategy to use
                            (e.g., "initialization" or "stable").

        Returns:
            bool: True if propagation occurred (payload sent), False if halted early.
        """
        eligible_neighbors, strategy_id = await mpe.get_event_data()
        
        self.reset_status_history()
        if strategy_id not in self.strategies:
            logging.info(f"Strategy {strategy_id} not found.")
            return False
        if await self.get_round() is None:
            logging.info("Propagation halted: round is not set.")
            return False

        strategy = self.strategies[strategy_id]
        logging.info(f"Starting model propagation with strategy: {strategy_id}")

        # current_connections = await self.cm.get_addrs_current_connections(only_direct=True)
        # eligible_neighbors = [
        #     neighbor_addr for neighbor_addr in current_connections if await strategy.is_node_eligible(neighbor_addr)
        # ]
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

        current_round = await self.get_round()
        round_number = -1 if strategy_id == "initialization" else current_round
        parameters = serialized_model
        message = self.cm.create_message("model", "", round_number, parameters, weight)
        for neighbor_addr in eligible_neighbors:
            logging.info(
                f"Sending model to {neighbor_addr} with round {await self.get_round()}: weight={weight} | size={sys.getsizeof(serialized_model) / (1024** 2) if serialized_model is not None else 0} MB"
            )
            asyncio.create_task(self.cm.send_message(neighbor_addr, message, "model"))
            # asyncio.create_task(self.cm.send_model(neighbor_addr, round_number, serialized_model, weight))

        await asyncio.sleep(self.interval)
        return True

    async def get_model_information(self, dest_addr, strategy_id: str, init=False):
        """
        Retrieve the serialized model payload and round metadata for making an offer to a node.

        Args:
            dest_addr (str): The address of the destination node.
            strategy_id (str): Key identifying which propagation strategy to use.
            init (bool, optional): If True, bypasses strategy and round validation (used for initial offers). Defaults to False.

        Returns:
            tuple(bytes, int, int) | None:
                A tuple containing:
                - serialized_model (bytes): The model payload ready for transmission.
                - total_rounds (int): The configured total number of rounds.
                - current_round (int): The current federated learning round.
                Returns None if the strategy is invalid, the round is unset, or no payload is prepared.
        """
        if not init:
            if strategy_id not in self.strategies:
                logging.info(f"Strategy {strategy_id} not found.")
                return None
            if await self.get_round() is None:
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
            return (serialized_model, rounds, await self.get_round())

        return None

    async def stop(self):
        logging.info("🌐  Stopping Propagator module...")
        self._running.clear()

    async def is_running(self):
        return self._running.is_set()

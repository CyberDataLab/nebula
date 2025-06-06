import logging
from nebula.addons.attacks.attacks import create_attack
from nebula.config.config import Config
from nebula.core.engine import Engine
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateReceivedEvent
from nebula.core.training.lightning import Lightning

from enum import Enum

class MaliciousNode(Engine):
    """
    Specialized Engine subclass representing a malicious participant in the Federated Learning scenario.

    This node behaves similarly to a standard node but is designed to simulate adversarial or faulty behavior
    within the federation. It can be used for testing the robustness of the FL protocol, defense mechanisms,
    and detection strategies.

    Inherits from:
        Engine: The base class that defines the main control flow of the Federated Learning process.

    Typical malicious behaviors may include (depending on the scenario configuration):
        - Sending incorrect or poisoned model updates.
        - Dropping or delaying messages.
        - Attempting to manipulate the reputation or aggregation process.
        - Participating inconsistently to mimic byzantine or selfish nodes.

    Attributes:
        Inherits all attributes from the base Engine class, but may override key methods related to
        training, aggregation, message handling, or reporting.

    Note:
        The behavior of this class is driven by scenario configuration parameters and any overridden methods
        implementing specific attack strategies.

    Usage:
        This class should be instantiated and used in place of the normal Engine to simulate a malicious node.
        It integrates seamlessly into the existing federation infrastructure.
    """
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )
        self.attack = create_attack(self)
        self.aggregator_bening = self._aggregator

    async def _extended_learning_cycle(self):
        try:
            await self.attack.attack()
        except Exception:
            attack_name = self.config.participant["adversarial_args"]["attack_params"]["attacks"]
            logging.exception(f"Attack {attack_name} failed")

        if self.role.value == "aggregator":
            await AggregatorNode._extended_learning_cycle(self)
        if self.role.value == "trainer":
            await TrainerNode._extended_learning_cycle(self)
        if self.role.value == "server":
            await ServerNode._extended_learning_cycle(self)


class AggregatorNode(Engine):
    """
    Node in the Federated Learning system with full training capabilities and additional responsibilities 
    as an aggregator within the federation.

    This class extends `Engine`, inheriting the full Federated Learning pipeline, including:
        - Local model training
        - Communication and model sharing with neighboring nodes
        - Participation in the aggregation process

    Additional Role:
        AggregatorNode is distinguished by its responsibility to **perform model aggregation** from
        other participants in its neighborhood or federation scope. This may include:
            - Collecting local model updates from neighbors
            - Applying aggregation functions (e.g., weighted averaging)
            - Updating and distributing the aggregated model
            - Managing round synchronization where necessary

    Use Cases:
        - Decentralized or partially decentralized federations where aggregation is distributed
        - Scenarios with multiple aggregators to increase resilience and scalability
        - Hybrid setups with rotating or dynamically elected aggregators

    Attributes:
        Inherits all attributes and methods from the `Engine` class. Aggregator-specific behaviors are
        typically handled via the `Aggregator` component and configuration parameters.

    Note:
        While this node performs aggregation, it also fully participates in training—its role is dual:
        **trainer and aggregator**, which makes it a powerful actor in the federation topology.
    """
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )

    async def _extended_learning_cycle(self):
        # Define the functionality of the aggregator node
        await self.trainer.test()
        await self.trainning_in_progress_lock.acquire_async()
        await self.trainer.train()
        await self.trainning_in_progress_lock.release_async()

        self_update_event = UpdateReceivedEvent(
            self.trainer.get_model_parameters(), self.trainer.get_model_weight(), self.addr, self.round
        )
        await EventManager.get_instance().publish_node_event(self_update_event)

        await self.cm.propagator.propagate("stable")
        await self._waiting_model_updates()


class ServerNode(Engine):
    """
    Server node extending the Engine class to manage the federation from a centralized perspective.

    This node does NOT perform local model training. Instead, it:
        - Tests the aggregated global model.
        - Performs model aggregation from participant updates.
        - Propagates the aggregated global model to participant nodes.

    Main functionalities:
        - Coordinating the aggregation of models received from participant nodes.
        - Evaluating the aggregated global model to monitor performance.
        - Disseminating the updated global model back to the federation.
        - Managing communication and synchronization signals within the federation.

    Typical use cases:
        - Centralized federated learning setups where training happens at participant nodes.
        - Server node acts as the aggregator and evaluator of global model.
        - Ensures the integrity and progress of the federated learning process by managing rounds and updates.

    Attributes:
        Inherits all attributes and methods from `Engine` with specialized logic for aggregation,
        evaluation, and propagation of the global model.

    Note:
        The ServerNode does not execute training itself but relies on receiving model updates from
        participant nodes for aggregation.
    """
    
    from datetime import datetime
    
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )
        self._start_time = ServerNode.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    async def _extended_learning_cycle(self):
        # Define the functionality of the server node
        await self.trainer.test()

        self_update_event = UpdateReceivedEvent(
            self.trainer.get_model_parameters(), self.trainer.BYPASS_MODEL_WEIGHT, self.addr, self.round
        )
        await EventManager.get_instance().publish_node_event(self_update_event)

        await self._waiting_model_updates()
        await self.cm.propagator.propagate("stable")


class TrainerNode(Engine):
    """
    Trainer node extending the Engine class responsible exclusively for local training and model propagation.

    This node:
        - Performs local model training using its own data.
        - Propagates the locally trained model updates to aggregator or server nodes.
    
    It does NOT perform model aggregation.

    Main functionalities:
        - Training the model locally according to the federated learning protocol.
        - Sending updated model parameters to aggregator nodes or server.
        - Managing communication related to local training progress and updates.
    
    Typical use cases:
        - Participant nodes in federated learning that contribute local updates.
        - Nodes focusing solely on improving their local model and sharing updates.

    Attributes:
        Inherits all attributes and methods from `Engine` but change behavior to exclude aggregation steps.

    Note:
        Aggregation responsibilities are delegated to other nodes (e.g., ServerNode or AggregatorNode).
    """
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )

    async def _extended_learning_cycle(self):
        # Define the functionality of the trainer node
        logging.info("Waiting global update | Assign _waiting_global_update = True")

        await self.trainer.test()
        await self.trainer.train()

        self_update_event = UpdateReceivedEvent(
            self.trainer.get_model_parameters(), self.trainer.get_model_weight(), self.addr, self.round, local=True
        )
        await EventManager.get_instance().publish_node_event(self_update_event)

        await self.cm.propagator.propagate("stable")
        await self._waiting_model_updates()


class IdleNode(Engine):
    """
    Idle node extending the Engine class responsible for passively participating in the federated learning network.

    This node:
        - Does not perform any local model training.
        - Waits to receive and potentially forward model updates.
    
    It does NOT train models or perform aggregation.

    Main functionalities:
        - Passively waiting for model updates from other nodes.
        - Handling communication related to received model updates.
    
    Typical use cases:
        - Passive participants in federated learning.
        - Nodes with no data or limited resources that cannot contribute training but need to stay in sync.
        - Observers or relays within the federated network.

    Attributes:
        Inherits all attributes and methods from `Engine` but alters behavior to exclude training and aggregation.

    Note:
        Training and aggregation responsibilities are delegated to other nodes (e.g., TrainerNode, ServerNode).
    """
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )

    async def _extended_learning_cycle(self):
        # Define the functionality of the idle node
        logging.info("Waiting global update | Assign _waiting_global_update = True")
        await self._waiting_model_updates()
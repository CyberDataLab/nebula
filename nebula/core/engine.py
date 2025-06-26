import asyncio
import logging
import os
import random
import socket
import time

import docker

from nebula.core.noderole import factory_role_behavior, change_role_behavior, Role, RoleBehavior
from nebula.addons.functions import print_msg_box
from nebula.addons.reporter import Reporter
from nebula.addons.reputation.reputation import Reputation
from nebula.core.addonmanager import AddondManager
from nebula.core.aggregation.aggregator import create_aggregator
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import (
    AggregationEvent,
    ExperimentFinishEvent,
    RoundEndEvent,
    RoundStartEvent,
    UpdateNeighborEvent,
    UpdateReceivedEvent,
    ExperimentFinishEvent,
    ModelPropagationEvent,
)
from nebula.core.network.communications import CommunicationsManager
from nebula.core.role import Role, factory_node_role
from nebula.core.situationalawareness.situationalawareness import SituationalAwareness
from nebula.core.utils.locker import Locker

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("fsspec").setLevel(logging.WARNING)
logging.getLogger("matplotlib").setLevel(logging.ERROR)
logging.getLogger("aim").setLevel(logging.ERROR)
logging.getLogger("plotly").setLevel(logging.ERROR)

import pdb
import sys

from nebula.config.config import Config
from nebula.core.training.lightning import Lightning


def handle_exception(exc_type, exc_value, exc_traceback):
    logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    pdb.set_trace()
    pdb.post_mortem(exc_traceback)


def signal_handler(sig, frame):
    print("Signal handler called with signal", sig)
    print("Exiting gracefully")
    sys.exit(0)


def print_banner():
    banner = """
                    ███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗
                    ████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗
                    ██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║
                    ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║
                    ██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║
                    ╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
                      A Platform for Decentralized Federated Learning

                      Developed by:
                       • Enrique Tomás Martínez Beltrán
                       • Alberto Huertas Celdrán
                       • Alejandro Avilés Serrano
                       • Fernando Torres Vega

                      https://nebula-dfl.com / https://nebula-dfl.eu
            """
    logging.info(f"\n{banner}\n")


class Engine:
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        self.config = config
        self.idx = config.participant["device_args"]["idx"]
        self.experiment_name = config.participant["scenario_args"]["name"]
        self.ip = config.participant["network_args"]["ip"]
        self.port = config.participant["network_args"]["port"]
        self.addr = config.participant["network_args"]["addr"]
        
        self.name = config.participant["device_args"]["name"]
        self.client = docker.from_env()

        print_banner()

        self._trainer = None
        self._aggregator = None
        self.round = None
        self.total_rounds = None
        self.federation_nodes = set()
        self._federation_nodes_lock = Locker("federation_nodes_lock", async_lock=True)
        self.initialized = False
        self.log_dir = os.path.join(config.participant["tracking_args"]["log_dir"], self.experiment_name)

        self.security = security

        self._trainer = trainer(model, datamodule, config=self.config)
        self._aggregator = create_aggregator(config=self.config, engine=self)

        self._secure_neighbors = []
        self._is_malicious = self.config.participant["adversarial_args"]["attack_params"]["attacks"] != "No Attack"

        role = config.participant["device_args"]["role"]
        self._role_behavior: RoleBehavior = factory_role_behavior(role, self, config)
        self._role_behavior_performance_lock = Locker("role_behavior_performance_lock", async_lock=True)

        print_msg_box(
            msg=f"Name {self.name}\nRole: {self._role_behavior.get_role_name()}",
            indent=2,
            title="Node information",
        )

        msg = f"Trainer: {self._trainer.__class__.__name__}"
        msg += f"\nDataset: {self.config.participant['data_args']['dataset']}"
        msg += f"\nIID: {self.config.participant['data_args']['iid']}"
        msg += f"\nModel: {model.__class__.__name__}"
        msg += f"\nAggregation algorithm: {self._aggregator.__class__.__name__}"
        msg += f"\nNode behavior: {'malicious' if self._is_malicious else 'benign'}"
        print_msg_box(msg=msg, indent=2, title="Scenario information")
        print_msg_box(
            msg=f"Logging type: {self._trainer.logger.__class__.__name__}",
            indent=2,
            title="Logging information",
        )

        self.learning_cycle_lock = Locker(name="learning_cycle_lock", async_lock=True)
        self.federation_setup_lock = Locker(name="federation_setup_lock", async_lock=True)
        self.federation_ready_lock = Locker(name="federation_ready_lock", async_lock=True)
        self.round_lock = Locker(name="round_lock", async_lock=True)
        self._round_in_process_lock = Locker("round_in_process_lock", async_lock=True)
        self.config.reload_config_file()

        self._cm = CommunicationsManager(engine=self)

        self._reporter = Reporter(config=self.config, trainer=self.trainer)

        self._sinchronized_status = True
        self.sinchronized_status_lock = Locker(name="sinchronized_status_lock")

        self.trainning_in_progress_lock = Locker(name="trainning_in_progress_lock", async_lock=True)

        event_manager = EventManager.get_instance(verbose=False)
        self._addon_manager = AddondManager(self, self.config)

        # Additional Components
        if "situational_awareness" in self.config.participant:
            self._situational_awareness = SituationalAwareness(self.config, self)
        else:
            self._situational_awareness = None

        if self.config.participant["defense_args"]["reputation"]["enabled"]:
            self._reputation = Reputation(engine=self, config=self.config)

    @property
    def cm(self):
        """Communication Manager"""
        return self._cm

    @property
    def reporter(self):
        """Reporter"""
        return self._reporter

    @property
    def aggregator(self):
        """Aggregator"""
        return self._aggregator

    @property
    def trainer(self):
        """Trainer"""
        return self._trainer
    
    @property
    def rb(self):
        """Role Behavior"""
        return self._role_behavior

    @property
    def sa(self):
        """Situational Awareness Module"""
        return self._situational_awareness

    def get_aggregator_type(self):
        return type(self.aggregator)

    def get_addr(self):
        return self.addr

    def get_config(self):
        return self.config

    async def get_federation_nodes(self):
        async with self._federation_nodes_lock:
            return self.federation_nodes.copy()

    async def update_federation_nodes(self, federation_nodes):
        async with self._federation_nodes_lock:
            self.federation_nodes = federation_nodes

    def get_initialization_status(self):
        return self.initialized

    def set_initialization_status(self, status):
        self.initialized = status

    async def get_round(self):
        async with self.round_lock:
            current_round = self.round
        return current_round

    def get_federation_ready_lock(self):
        return self.federation_ready_lock

    def get_federation_setup_lock(self):
        return self.federation_setup_lock

    def get_trainning_in_progress_lock(self):
        return self.trainning_in_progress_lock

    def get_round_lock(self):
        return self.round_lock

    def set_round(self, new_round):
        logging.info(f"🤖  Update round count | from: {self.round} | to round: {new_round}")
        self.round = new_round
        self.trainer.set_current_round(new_round)

    """                                                     ##############################
                                                            #       MODEL CALLBACKS      #
                                                            ##############################
    """

    async def model_initialization_callback(self, source, message):
        logging.info(f"🤖  handle_model_message | Received model initialization from {source}")
        try:
            model = self.trainer.deserialize_model(message.parameters)
            self.trainer.set_model_parameters(model, initialize=True)
            logging.info("🤖  Init Model | Model Parameters Initialized")
            self.set_initialization_status(True)
            await (
                self.get_federation_ready_lock().release_async()
            )  # Enable learning cycle once the initialization is done
            try:
                await (
                    self.get_federation_ready_lock().release_async()
                )  # Release the lock acquired at the beginning of the engine
            except RuntimeError:
                pass
        except RuntimeError:
            pass

    async def model_update_callback(self, source, message):
        logging.info(f"🤖  handle_model_message | Received model update from {source} with round {message.round}")
        if not self.get_federation_ready_lock().locked() and len(await self.get_federation_nodes()) == 0:
            logging.info("🤖  handle_model_message | There are no defined federation nodes")
            return
        decoded_model = self.trainer.deserialize_model(message.parameters)
        updt_received_event = UpdateReceivedEvent(decoded_model, message.weight, source, message.round)
        await EventManager.get_instance().publish_node_event(updt_received_event)

    """                                                     ##############################
                                                            #      General callbacks     #
                                                            ##############################
    """

    async def _discovery_discover_callback(self, source, message):
        logging.info(
            f"🔍  handle_discovery_message | Trigger | Received discovery message from {source} (network propagation)"
        )
        current_connections = await self.cm.get_addrs_current_connections(myself=True)
        if source not in current_connections:
            logging.info(f"🔍  handle_discovery_message | Trigger | Connecting to {source} indirectly")
            await self.cm.connect(source, direct=False)
        async with self.cm.get_connections_lock():
            if source in self.cm.connections:
                # Update the latitude and longitude of the node (if already connected)
                if (
                    message.latitude is not None
                    and -90 <= message.latitude <= 90
                    and message.longitude is not None
                    and -180 <= message.longitude <= 180
                ):
                    self.cm.connections[source].update_geolocation(message.latitude, message.longitude)
                else:
                    logging.warning(
                        f"🔍  Invalid geolocation received from {source}: latitude={message.latitude}, longitude={message.longitude}"
                    )

    async def _control_alive_callback(self, source, message):
        logging.info(f"🔧  handle_control_message | Trigger | Received alive message from {source}")
        current_connections = await self.cm.get_addrs_current_connections(myself=True)
        if source in current_connections:
            try:
                await self.cm.health.alive(source)
            except Exception as e:
                logging.exception(f"Error updating alive status in connection: {e}")
        else:
            logging.error(f"❗️  Connection {source} not found in connections...")

    async def _control_leadership_transfer_callback(self, source, message):
        logging.info(f"🔧  handle_control_message | Trigger | Received leadership transfer message from {source}")
        
        if await self._round_in_process_lock.locked_async():
            logging.info("Learning cycle is executing, role behavior will be modified next round")
            await self.rb.set_next_role(Role.AGGREGATOR, source_to_notificate=source)
        else:
            try:
                logging.info("Trying to modify Role behavior")
                lock_task = asyncio.create_task(self._round_in_process_lock.acquire_async())
                await asyncio.wait_for(lock_task, timeout=3)
                self._role_behavior = change_role_behavior(self.rb, Role.AGGREGATOR, self, self.config)
                await self.rb.set_next_role(Role.AGGREGATOR)
                await self.update_self_role()
                await self._round_in_process_lock.release_async()
            except TimeoutError:
                logging.info("Learning cycle is locked, role behavior will be modified next round")
                await self.rb.set_next_role(Role.AGGREGATOR, source_to_notificate=source)

    async def _control_leadership_transfer_ack_callback(self, source, message):
        logging.info(f"🔧  handle_control_message | Trigger | Received leadership transfer ack message from {source}")
        # No concurrence of difference ack received treated, be aware of that.
        if await self._round_in_process_lock.locked_async():
            logging.info("Learning cycle is executing, role behavior will be modified next round")
            await self.rb.set_next_role(Role.TRAINER)
        else:
            try:
                lock_task = asyncio.create_task(self._round_in_process_lock.acquire_async())
                await asyncio.wait_for(lock_task, timeout=3)

                logging.info("Role behavior could be executed...")
                await self.rb.set_next_role(Role.TRAINER)
                await self.update_self_role()

                await self._round_in_process_lock.release_async()

            except TimeoutError:
                logging.info("Learning cycle is locked, role behavior will be modified next round")
                await self.rb.set_next_role(Role.TRAINER)
        

    async def _connection_connect_callback(self, source, message):
        logging.info(f"🔗  handle_connection_message | Trigger | Received connection message from {source}")
        current_connections = await self.cm.get_addrs_current_connections(myself=True)
        if source not in current_connections:
            logging.info(f"🔗  handle_connection_message | Trigger | Connecting to {source}")
            await self.cm.connect(source, direct=True)

    async def _connection_disconnect_callback(self, source, message):
        logging.info(f"🔗  handle_connection_message | Trigger | Received disconnection message from {source}")
        await self.cm.disconnect(source, mutual_disconnection=False)

    async def _federation_federation_ready_callback(self, source, message):
        logging.info(f"📝  handle_federation_message | Trigger | Received ready federation message from {source}")
        if self.config.participant["device_args"]["start"]:
            logging.info(f"📝  handle_federation_message | Trigger | Adding ready connection {source}")
            await self.cm.add_ready_connection(source)

    async def _federation_federation_start_callback(self, source, message):
        logging.info(f"📝  handle_federation_message | Trigger | Received start federation message from {source}")
        await self.create_trainer_module()

    async def _federation_federation_models_included_callback(self, source, message):
        logging.info(f"📝  handle_federation_message | Trigger | Received aggregation finished message from {source}")
        current_round = await self.get_round()
        try:
            await self.cm.get_connections_lock().acquire_async()
            if current_round is not None and source in self.cm.connections:
                try:
                    if message is not None and len(message.arguments) > 0:
                        self.cm.connections[source].update_round(int(message.arguments[0])) if message.round in [
                            current_round - 1,
                            current_round,
                        ] else None
                except Exception as e:
                    logging.exception(f"Error updating round in connection: {e}")
            else:
                logging.error(f"Connection not found for {source}")
        except Exception as e:
            logging.exception(f"Error updating round in connection: {e}")
        finally:
            await self.cm.get_connections_lock().release_async()

    async def _reputation_share_callback(self, source, message):
        try:
            logging.info(f"handle_reputation_message | Trigger | Received reputation message from {source} | Node: {message.node_id} | Score: {message.score} | Round: {message.round}")

            current_node = self.addr
            nei = message.node_id

            if hasattr(self, '_reputation') and self._reputation is not None:
                if current_node != nei:
                    key = (current_node, nei, message.round)
                    if key not in self._reputation.reputation_with_all_feedback:
                        self._reputation.reputation_with_all_feedback[key] = []
                    self._reputation.reputation_with_all_feedback[key].append(message.score)
        except Exception as e:
            logging.exception(f"Error handling reputation message: {e}")

    """                                                     ##############################
                                                            #    REGISTERING CALLBACKS   #
                                                            ##############################
    """

    async def register_events_callbacks(self):
        await self.init_message_callbacks()
        await EventManager.get_instance().subscribe_node_event(AggregationEvent, self.broadcast_models_include)

    async def init_message_callbacks(self):
        logging.info("Registering callbacks for MessageEvents...")
        await self.register_message_events_callbacks()
        # Additional callbacks not registered automatically
        await self.register_message_callback(("model", "initialization"), "model_initialization_callback")
        await self.register_message_callback(("model", "update"), "model_update_callback")

    async def register_message_events_callbacks(self):
        me_dict = self.cm.get_messages_events()
        message_events = [
            (message_name, message_action)
            for (message_name, message_actions) in me_dict.items()
            for message_action in message_actions
        ]
        for event_type, action in message_events:
            callback_name = f"_{event_type}_{action}_callback"
            method = getattr(self, callback_name, None)

            if callable(method):
                await EventManager.get_instance().subscribe((event_type, action), method)

    async def register_message_callback(self, message_event: tuple[str, str], callback: str):
        event_type, action = message_event
        method = getattr(self, callback, None)
        if callable(method):
            await EventManager.get_instance().subscribe((event_type, action), method)

    """                                                     ##############################
                                                            #    ENGINE FUNCTIONALITY    #
                                                            ##############################
    """

    async def _aditional_node_start(self):
        """
        Starts the initialization process for an additional node joining the federation.

        This method triggers the situational awareness module to initiate a late connection
        process to discover and join the federation. Once connected, it starts the learning
        process asynchronously.
        """
        logging.info(f"Aditional node | {self.addr} | going to stablish connection with federation")
        await self.sa.start_late_connection_process()
        # continue ..
        logging.info("Creating trainer service to start the federation process..")
        asyncio.create_task(self._start_learning_late())

    async def update_neighbors(self, removed_neighbor_addr, neighbors, remove=False):
        """
        Updates the internal list of federation neighbors and publishes a neighbor update event.

        Args:
            removed_neighbor_addr (str): Address of the neighbor that was removed (or affected).
            neighbors (set): The updated set of current federation neighbors.
            remove (bool): Flag indicating whether the specified neighbor was removed (True)
                        or added (False).

        Publishes:
            UpdateNeighborEvent: An event describing the neighbor update, for use by listeners.
        """
        await self.update_federation_nodes(neighbors)
        updt_nei_event = UpdateNeighborEvent(removed_neighbor_addr, remove)
        asyncio.create_task(EventManager.get_instance().publish_node_event(updt_nei_event))

    async def broadcast_models_include(self, age: AggregationEvent):
        """
        Broadcasts a message to federation neighbors indicating that aggregation is ready.

        Args:
            age (AggregationEvent): The event containing information about the completed aggregation.

        Sends:
            federation_models_included: A message containing the round number of the aggregation.
        """
        logging.info(f"🔄  Broadcasting MODELS_INCLUDED for round {await self.get_round()}")
        current_round = await self.get_round()
        message = self.cm.create_message(
            "federation", "federation_models_included", [str(arg) for arg in [current_round]]
        )
        asyncio.create_task(self.cm.send_message_to_neighbors(message))

    async def update_model_learning_rate(self, new_lr):
        """
        Updates the learning rate of the current training model.

        Args:
            new_lr (float): The new learning rate to apply to the trainer model.

        This method ensures that the operation is protected by a lock to avoid
        conflicts with ongoing training operations.
        """
        await self.trainning_in_progress_lock.acquire_async()
        logging.info("Update | learning rate modified...")
        self.trainer.update_model_learning_rate(new_lr)
        await self.trainning_in_progress_lock.release_async()

    async def _start_learning_late(self):
        """
        Initializes the training process for a node joining the federation after it has already started.

        This method retrieves the training configuration from the situational awareness module,
        including the model parameters, total number of training rounds, current round, and number
        of epochs. It initializes the model and the trainer accordingly, and starts the learning cycle.

        Locks:
            - Acquires and releases `learning_cycle_lock` to ensure exclusive access during setup.
            - Acquires and updates `round` via `round_lock`.
            - Releases `federation_ready_lock` to indicate that the node is ready to begin learning.

        Handles:
            - Late start by setting model parameters and synchronization state.
            - Runtime exceptions gracefully in case of double lock releases or other race conditions.

        Logs important initialization information and direct connection state before training begins.
        """
        await self.learning_cycle_lock.acquire_async()
        try:
            model_serialized, rounds, round, _epochs = await self.sa.get_trainning_info()
            self.total_rounds = rounds
            epochs = _epochs
            await self.get_round_lock().acquire_async()
            self.round = round
            await self.get_round_lock().release_async()
            await self.learning_cycle_lock.release_async()
            print_msg_box(
                msg="Starting Federated Learning process...",
                indent=2,
                title="Start of the experiment late",
            )
            logging.info(f"Trainning setup | total rounds: {rounds} | current round: {round} | epochs: {epochs}")
            direct_connections = await self.cm.get_addrs_current_connections(only_direct=True)
            logging.info(f"Initial DIRECT connections: {direct_connections}")
            await asyncio.sleep(1)
            try:
                logging.info("🤖  Initializing model...")
                await asyncio.sleep(1)
                model = self.trainer.deserialize_model(model_serialized)
                self.trainer.set_model_parameters(model, initialize=True)
                logging.info("Model Parameters Initialized")
                self.set_initialization_status(True)
                await (
                    self.get_federation_ready_lock().release_async()
                )  # Enable learning cycle once the initialization is done
                try:
                    await (
                        self.get_federation_ready_lock().release_async()
                    )  # Release the lock acquired at the beginning of the engine
                except RuntimeError:
                    pass
            except RuntimeError:
                pass

            self.trainer.set_epochs(epochs)
            self.trainer.set_current_round(round)
            self.trainer.create_trainer()
            await self._learning_cycle()

        finally:
            if await self.learning_cycle_lock.locked_async():
                await self.learning_cycle_lock.release_async()

    async def create_trainer_module(self):
        asyncio.create_task(self._start_learning())
        logging.info("Started trainer module...")

    async def start_communications(self):
        """
        Initializes communication with neighboring nodes and registers internal event callbacks.

        This method performs the following steps:
        1. Registers all event callbacks used by the node.
        2. Parses the list of initial neighbors from the configuration and initiates communications with them.
        3. Waits for half of the configured grace time to allow initial network stabilization.

        This grace period provides time for initial peer discovery and message exchange
        before other services or training processes begin.
        """
        await self.register_events_callbacks()
        initial_neighbors = self.config.participant["network_args"]["neighbors"].split()
        await self.cm.start_communications(initial_neighbors)
        await asyncio.sleep(self.config.participant["misc_args"]["grace_time_connection"] // 2)

    async def deploy_components(self):
        """
        Initializes and deploys the core components required for node operation in the federation.

        This method performs the following actions:
        1. Initializes the aggregator, which handles the model aggregation process.
        2. Optionally initializes the situational awareness module if enabled in the configuration.
        3. Sets up the reputation system if enabled.
        4. Starts the reporting service for logging and monitoring purposes.
        5. Deploys any additional add-ons registered via the addon manager.

        This method ensures all critical and optional components are ready before
        the federated learning process starts.
        """
        await self.aggregator.init()
        if "situational_awareness" in self.config.participant:
            await self.sa.init()
        if self.config.participant["defense_args"]["reputation"]["enabled"]:
            await self._reputation.setup()
        await self._reporter.start()
        await self._addon_manager.deploy_additional_services()

    async def deploy_federation(self):
        """
        Manages the startup logic for the federated learning process.

        The behavior is determined by the configuration:
        - If the device is responsible for starting the federation:
        1. Waits for a configured grace period to allow peers to initialize.
        2. Waits until the network is ready (all nodes are prepared).
        3. Sends a 'FEDERATION_START' message to notify neighbors.
        4. Initializes the trainer module and marks the node as ready.

        - If the device is not the starter:
        1. Sends a 'FEDERATION_READY' message to neighbors.
        2. Waits passively for a start signal from the initiating node.

        This function ensures proper synchronization and coordination before the federated rounds begin.
        """
        await self.federation_ready_lock.acquire_async()
        if self.config.participant["device_args"]["start"]:
            logging.info(
                f"💤  Waiting for {self.config.participant['misc_args']['grace_time_start_federation']} seconds to start the federation"
            )
            await asyncio.sleep(self.config.participant["misc_args"]["grace_time_start_federation"])
            if self.round is None:
                while not await self.cm.check_federation_ready():
                    await asyncio.sleep(1)
                logging.info("Sending FEDERATION_START to neighbors...")
                message = self.cm.create_message("federation", "federation_start")
                await self.cm.send_message_to_neighbors(message)
                await self.get_federation_ready_lock().release_async()
                await self.create_trainer_module()
                self.set_initialization_status(True)
            else:
                logging.info("Federation already started")

        else:
            logging.info("Sending FEDERATION_READY to neighbors...")
            message = self.cm.create_message("federation", "federation_ready")
            await self.cm.send_message_to_neighbors(message)
            logging.info("💤  Waiting until receiving the start signal from the start node")

    async def _start_learning(self):
        """
        Starts the federated learning process from the beginning if no prior round exists.

        This method performs the following sequence:
        1. Acquires the learning cycle lock to ensure exclusive execution.
        2. If no round has been initialized:
        - Reads total rounds and epochs from the configuration.
        - Sets the initial round to 0 and releases the round lock.
        - Waits for the federation to be ready if the device is not the starter.
        - If the device is the starter, it propagates the initial model to neighbors.
        - Sets the number of epochs and creates the trainer instance.
        - Initiates the federated learning cycle.
        3. If a round already exists and the lock is still held, it is released to avoid deadlock.

        This method ensures that the learning process is initialized safely and only once,
        synchronizing startup across nodes and managing dependencies on federation readiness.
        """
        await self.learning_cycle_lock.acquire_async()
        try:
            if self.round is None:
                self.total_rounds = self.config.participant["scenario_args"]["rounds"]
                epochs = self.config.participant["training_args"]["epochs"]
                await self.get_round_lock().acquire_async()
                self.round = 0
                await self.get_round_lock().release_async()
                await self.learning_cycle_lock.release_async()
                print_msg_box(
                    msg="Starting Federated Learning process...",
                    indent=2,
                    title="Start of the experiment",
                )
                direct_connections = await self.cm.get_addrs_current_connections(only_direct=True)
                undirected_connections = await self.cm.get_addrs_current_connections(only_undirected=True)
                logging.info(
                    f"Initial DIRECT connections: {direct_connections} | Initial UNDIRECT participants: {undirected_connections}"
                )
                logging.info("💤  Waiting initialization of the federation...")
                # Lock to wait for the federation to be ready (only affects the first round, when the learning starts)
                # Only applies to non-start nodes --> start node does not wait for the federation to be ready
                await self.get_federation_ready_lock().acquire_async()
                if self.config.participant["device_args"]["start"]:
                    logging.info("Propagate initial model updates.")
                    
                    mpe = ModelPropagationEvent(await self.cm.get_addrs_current_connections(only_direct=True, myself=False), "initialization")
                    await EventManager.get_instance().publish_node_event(mpe)
                    
                    await self.get_federation_ready_lock().release_async()

                self.trainer.set_epochs(epochs)
                self.trainer.create_trainer()

                await self._learning_cycle()
            else:
                if await self.learning_cycle_lock.locked_async():
                    await self.learning_cycle_lock.release_async()
        finally:
            if await self.learning_cycle_lock.locked_async():
                await self.learning_cycle_lock.release_async()

    async def _waiting_model_updates(self):
        """
        Waits for the model aggregation results and updates the local model accordingly.

        This method:
        1. Awaits the result of the aggregation from the aggregator component.
        2. If aggregation parameters are successfully received:
        - Updates the local model with the aggregated parameters.
        3. If no parameters are returned:
        - Logs an error indicating aggregation failure.

        This method is called after local training and before proceeding to the next round,
        ensuring the model is synchronized with the federation's latest aggregated state.
        """
        logging.info(f"💤  Waiting convergence in round {self.round}.")
        params = await self.aggregator.get_aggregation()
        if params is not None:
            logging.info(
                f"_waiting_model_updates | Aggregation done for round {self.round}, including parameters in local model."
            )
            self.trainer.set_model_parameters(params)
        else:
            logging.error("Aggregation finished with no parameters")

    def print_round_information(self):
        print_msg_box(
            msg=f"Round {self.round} of {self.total_rounds} started.",
            indent=2,
            title="Round information",
        )

    async def learning_cycle_finished(self):
        current_round = await self.get_round()
        if not current_round or not self.total_rounds:
            return False
        else:
            return current_round >= self.total_rounds
        
    async def resolve_missing_updates(self):
        """
        Delegates the resolution strategy for missing updates to the current role behavior.

        This function is called when the node receives no model updates from neighbors
        and needs to apply a fallback strategy depending on its role (e.g., using default weights
        if aggregator, or local model if trainer).

        Returns:
            The result of the role-specific resolution strategy.
        """
        logging.info(f"Using Role behavior: {self.rb.get_role_name()} conflict resolve strategy")
        return await self.rb.resolve_missing_updates()
    
    async def update_self_role(self):
        """
        Checks whether a role update is required and performs the transition if necessary.

        If a new role has been assigned (i.e., self.rb.update_role_needed() is True),
        this function updates the role behavior accordingly and notifies the source
        that initiated the role transfer, if applicable.

        It logs the role change and spawns an async task to send a control message
        acknowledging the update to the initiating node.

        Raises:
            Any exceptions from change_role_behavior or communication logic.
        """
        if await self.rb.update_role_needed():
            logging.info("Starting Role Behavior modification...")
            from_role = self.rb.get_role_name()
            next_role = await self.rb.get_next_role()
            source_to_notificate = await self.rb.get_source_to_notificate()
            self._role_behavior: RoleBehavior = change_role_behavior(self.rb, next_role, self, self.config)
            to_role = self.rb.get_role_name()
            logging.info(f"Role behavior changing from: {from_role} to {to_role}")
            self.config.participant["device_args"]["role"] = to_role
            if source_to_notificate:
                logging.info(f"Sending role modification ACK to transferer: {source_to_notificate}")
                message = self.cm.create_message("control", "leadership_transfer_ack")
                asyncio.create_task(self.cm.send_message(source_to_notificate, message))
             
    async def _learning_cycle(self):
        """
        Main asynchronous loop for executing the Federated Learning process across multiple rounds.

        This method orchestrates the entire lifecycle of each federated learning round, including:
        1. Starting each round:
        - Updating the list of federation nodes.
        - Publishing a `RoundStartEvent` for local and global monitoring.
        - Preparing the trainer and aggregator components.
        2. Running the core learning logic via `_extended_learning_cycle`.
        3. Ending each round:
        - Publishing a `RoundEndEvent`.
        - Releasing and updating the current round state in the configuration.
        - Invoking callbacks for the trainer to handle end-of-round logic.

        After completing all rounds:
        - Finalizes the trainer by calling `on_learning_cycle_end()` and optionally performs testing.
        - Reports the scenario status to the controller if required.
        - Optionally stops the Docker container if deployed in a containerized environment.

        This function blocks (awaits) until the full FL process concludes.
        """
        while self.round is not None and self.round < self.total_rounds:
            async with self._round_in_process_lock:
                current_time = time.time()
                print_msg_box(
                    msg=f"Round {self.round} of {self.total_rounds - 1} started (max. {self.total_rounds} rounds)",
                    indent=2,
                    title="Round information",
                )
                
                await self.update_self_role()
                
                logging.info(f"Federation nodes: {self.federation_nodes}")
                await self.update_federation_nodes(
                    await self.cm.get_addrs_current_connections(only_direct=True, myself=True)
                )
                expected_nodes = await self.rb.select_nodes_to_wait()
                rse = RoundStartEvent(self.round, current_time, expected_nodes)
                await EventManager.get_instance().publish_node_event(rse)
                self.trainer.on_round_start()
                logging.info(f"Expected nodes: {expected_nodes}")
                direct_connections = await self.cm.get_addrs_current_connections(only_direct=True)
                undirected_connections = await self.cm.get_addrs_current_connections(only_undirected=True)
                
                logging.info(f"Direct connections: {direct_connections} | Undirected connections: {undirected_connections}")
                logging.info(f"[Role {self.rb.get_role_name()}] Starting learning cycle...")
                
                await self.aggregator.update_federation_nodes(expected_nodes)
                async with self._role_behavior_performance_lock:
                    await self.rb.extended_learning_cycle()

                current_time = time.time()
                ree = RoundEndEvent(self.round, current_time)
                await EventManager.get_instance().publish_node_event(ree)

                await self.get_round_lock().acquire_async()

                print_msg_box(
                    msg=f"Round {self.round} of {self.total_rounds - 1} finished (max. {self.total_rounds} rounds)",
                    indent=2,
                    title="Round information",
                )
                # await self.aggregator.reset()
                self.trainer.on_round_end()
                self.round += 1
                self.config.participant["federation_args"]["round"] = (
                    self.round
                )  # Set current round in config (send to the controller)
                await self.get_round_lock().release_async()

        # End of the learning cycle
        self.trainer.on_learning_cycle_end()

        await self.trainer.test()
        
        # Shutdown protocol
        await self._shutdown_protocol()
            
    async def _shutdown_protocol(self):
        logging.info("Starting graceful shutdown process...")
        
        # 1.- Publish Experiment Finish Event to the last update on modules
        logging.info("Publishing Experiment Finish Event...")
        efe = ExperimentFinishEvent()
        await EventManager.get_instance().publish_node_event(efe)

        # 2.- Log finish message
        print_msg_box(
            msg=f"FL process has been completed successfully (max. {self.total_rounds} rounds reached)",
            indent=2,
            title="End of the experiment",
        )
        # Report
        if self.config.participant["scenario_args"]["controller"] != "nebula-test":
            try:
                result = await self.reporter.report_scenario_finished()
                if result:
                    logging.info("📝  Scenario finished reported successfully")
                    await self.reporter.stop()
                else:
                    logging.error("📝  Error reporting scenario finished")
            except Exception as e:
                logging.exception(f"📝  Error during scenario finish report: {e}")

        # Call centralized shutdown
        await self.shutdown()
        return

    async def shutdown(self):
        logging.info("🚦 Engine shutdown initiated")

        # Stop addon services first
        try:
            await self._addon_manager.stop_additional_services()
        except Exception as e:
            logging.exception("Error stopping add-ons: %s", e)

        # Stop reporter
        try:
            await self._reporter.stop()
        except Exception as e:
            logging.exception("Error stopping reporter: %s", e)

        # Stop communications manager (includes forwarder, discoverer, propagator, ECS)
        try:
            await self.cm.stop()
        except Exception as e:
            logging.exception("Error stopping communications manager: %s", e)

        # Stop situational awareness
        try:
            if self.sa:
                await self.sa.stop()
        except Exception as e:
            logging.exception("Error stopping situational awareness: %s", e)

        # Task cleanup with improved handling
        logging.info("Starting graceful task cleanup...")
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        if tasks:
            logging.info(f"Found {len(tasks)} remaining tasks to clean up")
            for task in tasks:
                logging.info(f"  • Task: {task.get_name()} - {task}")
                logging.info(f"  • State: {task._state} - Done: {task.done()} - Cancelled: {task.cancelled()}")

            # Wait for tasks to complete naturally with shorter timeout
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=3)
            except asyncio.CancelledError:
                logging.warning(
                    "Timeout reached during task cleanup (CancelledError); proceeding with shutdown anyway."
                )
                # Do not re-raise, just continue
            except TimeoutError:
                logging.warning("Some tasks did not complete in time, forcing cancellation...")
                for task in tasks:
                    if not task.done():
                        task.cancel()
                # Wait a bit more for cancellations to take effect
                try:
                    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2)
                except asyncio.CancelledError:
                    logging.warning(
                        "Timeout reached during forced cancellation (CancelledError); proceeding with shutdown anyway."
                    )
                    # Do not re-raise, just continue
                except TimeoutError:
                    logging.warning("Some tasks still not responding to cancellation")
                    # Final aggressive cleanup - cancel all remaining tasks
                    remaining_tasks = [
                        t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()
                    ]
                    if remaining_tasks:
                        logging.warning(f"Forcing cancellation of {len(remaining_tasks)} remaining tasks")
                        for task in remaining_tasks:
                            task.cancel()
                        try:
                            await asyncio.wait_for(asyncio.gather(*remaining_tasks, return_exceptions=True), timeout=1)
                        except asyncio.CancelledError:
                            logging.warning(
                                "Timeout reached during final forced cancellation (CancelledError); proceeding with shutdown anyway."
                            )
                            # Do not re-raise, just continue
                        except TimeoutError:
                            logging.exception("Some tasks still not responding to forced cancellation")
            # Proceed anyway after all cancellation attempts
            logging.warning("Proceeding with shutdown even if some tasks are still pending/cancelled.")
        else:
            logging.info("No remaining tasks to clean up.")

        logging.info("✅ Engine shutdown complete")

        # Kill Docker container if running in Docker
        if self.config.participant["scenario_args"]["deployment"] == "docker":
            try:
                docker_id = socket.gethostname()
                logging.info(f"📦  Removing docker container with ID {docker_id}")
                container = self.client.containers.get(docker_id)
                container.remove(force=True)
                logging.info(f"📦  Successfully removed docker container {docker_id}")
            except Exception as e:
                logging.exception(f"📦  Error removing Docker container {docker_id}: {e}")
                # Try to force kill the container as last resort
                try:
                    import subprocess

                    subprocess.run(["docker", "rm", "-f", docker_id], check=False)
                    logging.info(f"📦  Forced removal of container {docker_id} via subprocess")
                except Exception as sub_e:
                    logging.exception(f"📦  Failed to force remove container {docker_id}: {sub_e}")

import asyncio
import logging
import os
import time

import docker

from nebula.addons.attacks.attacks import create_attack
from nebula.addons.functions import print_msg_box
from nebula.addons.reporter import Reporter
from nebula.addons.reputation.reputation import Reputation
from nebula.core.addonmanager import AddondManager
from nebula.core.aggregation.aggregator import create_aggregator
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import (
    AggregationEvent,
    RoundEndEvent,
    RoundStartEvent,
    UpdateNeighborEvent,
    UpdateReceivedEvent,
)
from nebula.core.network.communications import CommunicationsManager
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
                        Created by Enrique Tomás Martínez Beltrán
                          Featured by Alejandro Avilés Serrano
                            Featured by Fernando Torres Vega
                          https://github.com/CyberDataLab/nebula
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
        self.role = config.participant["device_args"]["role"]
        self.name = config.participant["device_args"]["name"]
        self.docker_id = config.participant["device_args"]["docker_id"]
        self.client = docker.from_env()

        print_banner()

        print_msg_box(
            msg=f"Name {self.name}\nRole: {self.role}",
            indent=2,
            title="Node information",
        )

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
        self._is_malicious = self.config.participant["adversarial_args"]["attacks"] != "No Attack"

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

        if self.config.participant["defense_args"]["with_reputation"]:
            self._reputation = Reputation(engine=self, config=self.config)

    @property
    def cm(self):
        return self._cm

    @property
    def reporter(self):
        return self._reporter

    @property
    def aggregator(self):
        return self._aggregator

    @property
    def trainer(self):
        return self._trainer

    @property
    def sa(self):
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

    def get_round(self):
        return self.round

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
        try:
            await self.cm.get_connections_lock().acquire_async()
            if self.round is not None and source in self.cm.connections:
                try:
                    if message is not None and len(message.arguments) > 0:
                        self.cm.connections[source].update_round(int(message.arguments[0])) if message.round in [
                            self.round - 1,
                            self.round,
                        ] else None
                except Exception as e:
                    logging.exception(f"Error updating round in connection: {e}")
            else:
                logging.error(f"Connection not found for {source}")
        except Exception as e:
            logging.exception(f"Error updating round in connection: {e}")
        finally:
            await self.cm.get_connections_lock().release_async()

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
        logging.info(f"Aditional node | {self.addr} | going to stablish connection with federation")
        await self.sa.start_late_connection_process()
        # continue ..
        logging.info("Creating trainer service to start the federation process..")
        asyncio.create_task(self._start_learning_late())

    async def update_neighbors(self, removed_neighbor_addr, neighbors, remove=False):
        await self.update_federation_nodes(neighbors)
        updt_nei_event = UpdateNeighborEvent(removed_neighbor_addr, remove)
        asyncio.create_task(EventManager.get_instance().publish_node_event(updt_nei_event))

    async def broadcast_models_include(self, age: AggregationEvent):
        logging.info(f"🔄  Broadcasting MODELS_INCLUDED for round {self.get_round()}")
        message = self.cm.create_message(
            "federation", "federation_models_included", [str(arg) for arg in [self.get_round()]]
        )
        asyncio.create_task(self.cm.send_message_to_neighbors(message))

    async def update_model_learning_rate(self, new_lr):
        await self.trainning_in_progress_lock.acquire_async()
        logging.info("Update | learning rate modified...")
        self.trainer.update_model_learning_rate(new_lr)
        await self.trainning_in_progress_lock.release_async()

    async def _start_learning_late(self):
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
        await self.register_events_callbacks()
        initial_neighbors = self.config.participant["network_args"]["neighbors"].split()
        await self.cm.start_communications(initial_neighbors)
        await asyncio.sleep(self.config.participant["misc_args"]["grace_time_connection"] // 2)

    async def deploy_components(self):
        await self.aggregator.init()
        if "situational_awareness" in self.config.participant:
            await self.sa.init()
        if self.config.participant["defense_args"]["with_reputation"]:
            await self._reputation.setup()
        await self._reporter.start()
        await self._addon_manager.deploy_additional_services()

    async def deploy_federation(self):
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
                    await self.cm.propagator.propagate("initialization")
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

    def learning_cycle_finished(self):
        return not (self.round < self.total_rounds)

    async def _learning_cycle(self):
        while self.round is not None and self.round < self.total_rounds:
            current_time = time.time()
            print_msg_box(
                msg=f"Round {self.round} of {self.total_rounds - 1} started (max. {self.total_rounds} rounds)",
                indent=2,
                title="Round information",
            )
            logging.info(f"Federation nodes: {self.federation_nodes}")
            await self.update_federation_nodes(
                await self.cm.get_addrs_current_connections(only_direct=True, myself=True)
            )
            expected_nodes = await self.get_federation_nodes()
            rse = RoundStartEvent(self.round, current_time, expected_nodes)
            await EventManager.get_instance().publish_node_event(rse)
            self.trainer.on_round_start()
            logging.info(f"Expected nodes: {expected_nodes}")
            direct_connections = await self.cm.get_addrs_current_connections(only_direct=True)
            undirected_connections = await self.cm.get_addrs_current_connections(only_undirected=True)
            logging.info(f"Direct connections: {direct_connections} | Undirected connections: {undirected_connections}")
            logging.info(f"[Role {self.role}] Starting learning cycle...")
            await self.aggregator.update_federation_nodes(expected_nodes)
            await self._extended_learning_cycle()

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
        print_msg_box(
            msg=f"FL process has been completed successfully (max. {self.total_rounds} rounds reached)",
            indent=2,
            title="End of the experiment",
        )
        # Report
        if self.config.participant["scenario_args"]["controller"] != "nebula-test":
            result = await self.reporter.report_scenario_finished()
            if result:
                pass
            else:
                logging.error("Error reporting scenario finished")

        logging.info("Checking if all my connections reached the total rounds...")
        while not self.cm.check_finished_experiment():
            await asyncio.sleep(1)

        await asyncio.sleep(5)

        # Kill itself
        if self.config.participant["scenario_args"]["deployment"] == "docker":
            try:
                self.client.containers.get(self.docker_id).stop()
            except Exception as e:
                print(f"Error stopping Docker container with ID {self.docker_id}: {e}")

    async def _extended_learning_cycle(self):
        """
        This method is called in each round of the learning cycle. It is used to extend the learning cycle with additional
        functionalities. The method is called in the _learning_cycle method.
        """
        pass


class MaliciousNode(Engine):
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
            attack_name = self.config.participant["adversarial_args"]["attacks"]
            logging.exception(f"Attack {attack_name} failed")

        if self.role == "aggregator":
            await AggregatorNode._extended_learning_cycle(self)
        if self.role == "trainer":
            await TrainerNode._extended_learning_cycle(self)
        if self.role == "server":
            await ServerNode._extended_learning_cycle(self)


class AggregatorNode(Engine):
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
        # Define the functionality of the server node
        await self.trainer.test()

        self_update_event = UpdateReceivedEvent(
            self.trainer.get_model_parameters(), self.trainer.BYPASS_MODEL_WEIGHT, self.addr, self.round
        )
        await EventManager.get_instance().publish_node_event(self_update_event)

        await self._waiting_model_updates()
        await self.cm.propagator.propagate("stable")


class TrainerNode(Engine):
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

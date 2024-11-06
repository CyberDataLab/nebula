import asyncio
import logging
import os

import docker
import numpy as np
import time
from datetime import datetime, timedelta
from nebula.addons.functions import print_msg_box
from nebula.addons.attacks.attacks import create_attack
from nebula.addons.reporter import Reporter
from nebula.core.aggregation.aggregator import create_aggregator, create_malicious_aggregator, create_target_aggregator
from nebula.core.eventmanager import EventManager, event_handler
from nebula.core.network.communications import CommunicationsManager
from nebula.core.pb import nebula_pb2
from nebula.core.utils.locker import Locker

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("fsspec").setLevel(logging.WARNING)
logging.getLogger("matplotlib").setLevel(logging.ERROR)
logging.getLogger("aim").setLevel(logging.ERROR)
logging.getLogger("plotly").setLevel(logging.ERROR)

from nebula.config.config import Config
from nebula.core.training.lightning import Lightning
from nebula.core.utils.helper import cosine_metric
from nebula.core.reputation.Reputation import Reputation
import sys
import pdb


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
                        https://github.com/enriquetomasmb/nebula
                """
    logging.info(f"\n{banner}\n")


class Engine:
    def __init__(
        self,
        model,
        dataset,
        config=Config,
        trainer=Lightning,
        security=False,
        model_poisoning=False,
        poisoned_ratio=0,
        noise_type="gaussian",
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

        print_msg_box(msg=f"Name {self.name}\nRole: {self.role}", indent=2, title="Node information")

        self._trainer = None
        self._aggregator = None
        self.round = None
        self.total_rounds = None
        self.federation_nodes = set()
        self.initialized = False
        self.log_dir = os.path.join(config.participant["tracking_args"]["log_dir"], self.experiment_name)

        self.security = security
        self.model_poisoning = model_poisoning
        self.poisoned_ratio = poisoned_ratio
        self.noise_type = noise_type
        self.rejected_nodes = set()
        self.change_weight_nodes = set()

        # Reputation
        reputation_file = f'nebula/core/reputation/reputation.txt'

        with open(reputation_file) as f:
            self.reputation_file = f.read()

        if self.reputation_file == 'True':
            self.reputation_instance = Reputation(self)
            self.reputation = {} # Reputation of the node
            self.reputation_with_feedback = {} # Reputation of the node with feedback
            self.start_time_communication = 0
        
        #self.stop_message_reputation = threading.Event()

        self._trainer = trainer(model, dataset, config=self.config)
        self._aggregator = create_aggregator(config=self.config, engine=self)

        self._secure_neighbors = []
        self._is_malicious = True if self.config.participant["adversarial_args"]["attacks"] != "No Attack" else False

        msg = f"Trainer: {self._trainer.__class__.__name__}"
        msg += f"\nDataset: {self.config.participant['data_args']['dataset']}"
        msg += f"\nIID: {self.config.participant['data_args']['iid']}"
        msg += f"\nModel: {model.__class__.__name__}"
        msg += f"\nAggregation algorithm: {self._aggregator.__class__.__name__}"
        msg += f"\nNode behavior: {'malicious' if self._is_malicious else 'benign'}"
        print_msg_box(msg=msg, indent=2, title="Scenario information")
        print_msg_box(msg=f"Logging type: {self._trainer.logger.__class__.__name__}", indent=2, title="Logging information")

        self.with_reputation = self.config.participant["defense_args"]["with_reputation"]
        self.is_dynamic_topology = self.config.participant["defense_args"]["is_dynamic_topology"]
        self.is_dynamic_aggregation = self.config.participant["defense_args"]["is_dynamic_aggregation"]
        self.target_aggregation = create_target_aggregator(config=self.config, engine=self) if self.is_dynamic_aggregation else None
        msg = f"Reputation system: {self.with_reputation}\nDynamic topology: {self.is_dynamic_topology}\nDynamic aggregation: {self.is_dynamic_aggregation}"
        msg += f"\nTarget aggregation: {self.target_aggregation.__class__.__name__}" if self.is_dynamic_aggregation else ""
        print_msg_box(msg=msg, indent=2, title="Defense information")

        self.learning_cycle_lock = Locker(name="learning_cycle_lock", async_lock=True)
        self.federation_setup_lock = Locker(name="federation_setup_lock", async_lock=True)
        self.federation_ready_lock = Locker(name="federation_ready_lock", async_lock=True)
        self.round_lock = Locker(name="round_lock", async_lock=True)

        self.config.reload_config_file()

        self._cm = CommunicationsManager(engine=self)
        # Set the communication manager in the model (send messages from there)
        self.trainer.model.set_communication_manager(self._cm)

        self._reporter = Reporter(config=self.config, trainer=self.trainer, cm=self.cm)

        self._event_manager = EventManager(
            default_callbacks=[
                self._discovery_discover_callback,
                self._control_alive_callback,
                self._connection_connect_callback,
                self._connection_disconnect_callback,
                self._federation_ready_callback,
                self._start_federation_callback,
                self._federation_models_included_callback,
            ]
        )

        # Register additional callbacks
        self._event_manager.register_event((nebula_pb2.FederationMessage, nebula_pb2.FederationMessage.Action.REPUTATION), self._reputation_callback)
        # ... add more callbacks here

    @property
    def cm(self):
        return self._cm

    @property
    def reporter(self):
        return self._reporter

    @property
    def event_manager(self):
        return self._event_manager

    @property
    def aggregator(self):
        return self._aggregator

    def get_aggregator_type(self):
        return type(self.aggregator)

    @property
    def trainer(self):
        return self._trainer

    def get_addr(self):
        return self.addr

    def get_config(self):
        return self.config

    def get_federation_nodes(self):
        return self.federation_nodes

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

    def get_round_lock(self):
        return self.round_lock

    def get_reputation(self):
        return self.reputation

    @event_handler(nebula_pb2.DiscoveryMessage, nebula_pb2.DiscoveryMessage.Action.DISCOVER)
    async def _discovery_discover_callback(self, source, message):
        logging.info(f"🔍  handle_discovery_message | Trigger | Received discovery message from {source} (network propagation)")
        current_connections = await self.cm.get_addrs_current_connections(myself=True)
        if source not in current_connections:
            logging.info(f"🔍  handle_discovery_message | Trigger | Connecting to {source} indirectly")
            await self.cm.connect(source, direct=False)
        async with self.cm.get_connections_lock():
            if source in self.cm.connections:
                # Update the latitude and longitude of the node (if already connected)
                if message.latitude is not None and -90 <= message.latitude <= 90 and message.longitude is not None and -180 <= message.longitude <= 180:
                    self.cm.connections[source].update_geolocation(message.latitude, message.longitude)
                else:
                    logging.warning(f"🔍  Invalid geolocation received from {source}: latitude={message.latitude}, longitude={message.longitude}")

    @event_handler(nebula_pb2.ControlMessage, nebula_pb2.ControlMessage.Action.ALIVE)
    async def _control_alive_callback(self, source, message):
        logging.info(f"🔧  handle_control_message | Trigger | Received alive message from {source}")
        current_connections = await self.cm.get_addrs_current_connections(myself=True)
        if source in current_connections:
            try:
                await self.cm.health.alive(source)
            except Exception as e:
                logging.error(f"Error updating alive status in connection: {e}")
        else:
            logging.error(f"❗️  Connection {source} not found in connections...")

    @event_handler(nebula_pb2.ConnectionMessage, nebula_pb2.ConnectionMessage.Action.CONNECT)
    async def _connection_connect_callback(self, source, message):
        logging.info(f"🔗  handle_connection_message | Trigger | Received connection message from {source}")
        current_connections = await self.cm.get_addrs_current_connections(myself=True)
        if source not in current_connections:
            logging.info(f"🔗  handle_connection_message | Trigger | Connecting to {source}")
            await self.cm.connect(source, direct=True)

    @event_handler(nebula_pb2.ConnectionMessage, nebula_pb2.ConnectionMessage.Action.DISCONNECT)
    async def _connection_disconnect_callback(self, source, message):
        logging.info(f"🔗  handle_connection_message | Trigger | Received disconnection message from {source}")
        await self.cm.disconnect(source, mutual_disconnection=False)

    @event_handler(nebula_pb2.FederationMessage, nebula_pb2.FederationMessage.Action.FEDERATION_READY)
    async def _federation_ready_callback(self, source, message):
        logging.info(f"📝  handle_federation_message | Trigger | Received ready federation message from {source}")
        if self.config.participant["device_args"]["start"]:
            logging.info(f"📝  handle_federation_message | Trigger | Adding ready connection {source}")
            await self.cm.add_ready_connection(source)

    @event_handler(nebula_pb2.FederationMessage, nebula_pb2.FederationMessage.Action.FEDERATION_START)
    async def _start_federation_callback(self, source, message):
        logging.info(f"📝  handle_federation_message | Trigger | Received start federation message from {source}")
        await self.create_trainer_module()

    @event_handler(nebula_pb2.FederationMessage, nebula_pb2.FederationMessage.Action.REPUTATION)
    async def _reputation_callback(self, source, message):
        malicious_nodes = message.arguments  # List of malicious nodes
        if self.with_reputation:
            if len(malicious_nodes) > 0 and not self._is_malicious:
                if self.is_dynamic_topology:
                    await self._disrupt_connection_using_reputation(malicious_nodes)
                if self.is_dynamic_aggregation and self.aggregator != self.target_aggregation:
                    await self._dynamic_aggregator(self.aggregator.get_nodes_pending_models_to_aggregate(), malicious_nodes)

    @event_handler(nebula_pb2.FederationMessage, nebula_pb2.FederationMessage.Action.FEDERATION_MODELS_INCLUDED)
    async def _federation_models_included_callback(self, source, message):
        logging.info(f"📝  handle_federation_message | Trigger | Received aggregation finished message from {source}")
        try:
            await self.cm.get_connections_lock().acquire_async()
            if self.round is not None and source in self.cm.connections:
                try:
                    if message is not None and len(message.arguments) > 0:
                        self.cm.connections[source].update_round(int(message.arguments[0])) if message.round in [self.round - 1, self.round] else None
                except Exception as e:
                    logging.error(f"Error updating round in connection: {e}")
            else:
                logging.error(f"Connection not found for {source}")
        except Exception as e:
            logging.error(f"Error updating round in connection: {e}")
        finally:
            await self.cm.get_connections_lock().release_async()

    async def create_trainer_module(self):
        asyncio.create_task(self._start_learning())
        logging.info(f"Started trainer module...")

    async def start_communications(self):
        logging.info(f"Neighbors: {self.config.participant['network_args']['neighbors']}")
        logging.info(f"💤  Cold start time: {self.config.participant['misc_args']['grace_time_connection']} seconds before connecting to the network")
        await asyncio.sleep(self.config.participant["misc_args"]["grace_time_connection"])
        await self.cm.start()
        initial_neighbors = self.config.participant["network_args"]["neighbors"].split()
        for i in initial_neighbors:
            addr = f"{i.split(':')[0]}:{i.split(':')[1]}"
            await self.cm.connect(addr, direct=True)
            await asyncio.sleep(1)
        while not self.cm.verify_connections(initial_neighbors):
            await asyncio.sleep(1)
        current_connections = await self.cm.get_addrs_current_connections()
        logging.info(f"Connections verified: {current_connections}")
        await self._reporter.start()
        await self.cm.deploy_additional_services()
        await asyncio.sleep(self.config.participant["misc_args"]["grace_time_connection"] // 2)

    async def deploy_federation(self):
        await self.federation_ready_lock.acquire_async()
        if self.config.participant["device_args"]["start"]:
            logging.info(f"💤  Waiting for {self.config.participant['misc_args']['grace_time_start_federation']} seconds to start the federation")
            await asyncio.sleep(self.config.participant["misc_args"]["grace_time_start_federation"])
            if self.round is None:
                while not await self.cm.check_federation_ready():
                    await asyncio.sleep(1)
                logging.info(f"Sending FEDERATION_START to neighbors...")
                message = self.cm.mm.generate_federation_message(nebula_pb2.FederationMessage.Action.FEDERATION_START)
                await self.cm.send_message_to_neighbors(message)
                await self.get_federation_ready_lock().release_async()
                await self.create_trainer_module()
                
                await self.manage_message_federation("federation")
            else:
                logging.info(f"Federation already started")

        else:
            logging.info(f"Sending FEDERATION_READY to neighbors...")
            message = self.cm.mm.generate_federation_message(nebula_pb2.FederationMessage.Action.FEDERATION_READY)
            await self.cm.send_message_to_neighbors(message)
            logging.info(f"💤  Waiting until receiving the start signal from the start node")
            await self.manage_message_federation("federation")

    async def manage_message_federation(self, action):
        neighbors = set(await self.cm.get_addrs_current_connections(only_direct=True))
        for nei in neighbors:
            self.cm.store_send_timestamp(nei, self.round, action)

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
                print_msg_box(msg=f"Starting Federated Learning process...", indent=2, title="Start of the experiment")
                direct_connections = await self.cm.get_addrs_current_connections(only_direct=True)
                undirected_connections = await self.cm.get_addrs_current_connections(only_undirected=True)
                logging.info(f"Initial DIRECT connections: {direct_connections} | Initial UNDIRECT participants: {undirected_connections}")
                logging.info(f"💤  Waiting initialization of the federation...")
                # Lock to wait for the federation to be ready (only affects the first round, when the learning starts)
                # Only applies to non-start nodes --> start node does not wait for the federation to be ready
                await self.get_federation_ready_lock().acquire_async()
                if self.config.participant["device_args"]["start"]:
                    logging.info(f"Propagate initial model updates.")
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

    async def _disrupt_connection_using_reputation(self, malicious_nodes):
        malicious_nodes = list(set(malicious_nodes) & set(self.get_current_connections()))
        logging.info(f"Disrupting connection with malicious nodes at round {self.round}")
        logging.info(f"Removing {malicious_nodes} from {self.get_current_connections()}")
        logging.info(f"Current connections before aggregation at round {self.round}: {self.get_current_connections()}")
        for malicious_node in malicious_nodes:
            if (self.get_name() != malicious_node) and (malicious_node not in self._secure_neighbors):
                await self.cm.disconnect(malicious_node)
        logging.info(f"Current connections after aggregation at round {self.round}: {self.get_current_connections()}")

        await self._connect_with_benign(malicious_nodes)

    async def _connect_with_benign(self, malicious_nodes):
        lower_threshold = 1
        higher_threshold = len(self.federation_nodes) - 1
        if higher_threshold < lower_threshold:
            higher_threshold = lower_threshold

        benign_nodes = [i for i in self.federation_nodes if i not in malicious_nodes]
        logging.info(f"_reputation_callback benign_nodes at round {self.round}: {benign_nodes}")
        if len(self.get_current_connections()) <= lower_threshold:
            for node in benign_nodes:
                if len(self.get_current_connections()) <= higher_threshold and self.get_name() != node:
                    connected = await self.cm.connect(node)
                    if connected:
                        logging.info(f"Connect new connection with at round {self.round}: {connected}")

    async def _dynamic_aggregator(self, aggregated_models_weights, malicious_nodes):
        logging.info(f"malicious detected at round {self.round}, change aggergation protocol!")
        if self.aggregator != self.target_aggregation:
            logging.info(f"Current aggregator is: {self.aggregator}")
            self.aggregator = self.target_aggregation
            await self.aggregator.update_federation_nodes(self.federation_nodes)

            for subnodes in aggregated_models_weights.keys():
                sublist = subnodes.split()
                (submodel, weights) = aggregated_models_weights[subnodes]
                for node in sublist:
                    if node not in malicious_nodes:
                        await self.aggregator.include_model_in_buffer(submodel, weights, source=self.get_name(), round=self.round)
            logging.info(f"Current aggregator is: {self.aggregator}")

    async def _waiting_model_updates(self):
        logging.info(f"💤  Waiting convergence in round {self.round}.")
        params = await self.aggregator.get_aggregation()
        if params is not None:
            logging.info(f"_waiting_model_updates | Aggregation done for round {self.round}, including parameters in local model.")
            self.trainer.set_model_parameters(params)
        else:
            logging.error(f"Aggregation finished with no parameters")

    async def _reputation_feedback(self):
        if self._cm.reputation_with_all_feedback is not None:
            logging.info(f"reputation with feedback {self._cm.reputation_with_all_feedback}")
            current_round = self.round
            for(current_node, node_ip, round_num), scores in self._cm.reputation_with_all_feedback.items():
                if round_num == current_round:
                    if scores:
                        avg_feedback = sum(scores) / len(scores)
                        logging.info(f"Receive feedback to node {node_ip} with average score {avg_feedback}")

                    logging.info(f"self.reputation: {self.reputation}")
                    for ip, data in self.reputation.items():
                        ip = ip.split(":")[0]
                        if ip == node_ip:
                            logging.info(f"IP: {ip}")
                            current_reputation = data["reputation"]
                            logging.info(f"Current reputation {current_reputation}")
                        else: 
                            current_reputation = None

                        if current_reputation is not None:
                            logging.info(f"Current reputation for node {node_ip} in round {round_num}: {current_reputation}")
                            combined_reputation = (current_reputation + avg_feedback) / 2
                            logging.info(f"Combined reputation for node {node_ip} in round {round_num}: {combined_reputation}")

                            self.reputation_with_feedback[node_ip] = combined_reputation
                            logging.info(f"Self.reputation_with_feedback: {self.reputation_with_feedback}")

            if self.reputation_with_feedback is not None:
                reputation_with_feedback_dict_with_values = {
                    f"Reputation_with_feedback/{self.addr}": {
                        node_id: float(data) for node_id, data in self.reputation_with_feedback.items() if data is not None
                    }
                }

                self.trainer._logger.log_data(reputation_with_feedback_dict_with_values, step=self.round)

    async def _calculate_reputation(self):
        logging.info(f"rejected nodes at round {self.round}: {self.rejected_nodes}")
        if self.rejected_nodes is not None:
             self.rejected_nodes.clear()
        logging.info(f"rejected nodes after clear at round {self.round}: {self.rejected_nodes}")

        logging.info(f"change weight nodes at round {self.round}: {self.change_weight_nodes}")
        if self.change_weight_nodes is not None:
             self.change_weight_nodes.clear()
        logging.info(f"change weight nodes after clear at round {self.round}: {self.change_weight_nodes}")

        current_round = self.get_round()
        if self.reputation_file == 'True':
            neighbors = set(await self.cm.get_addrs_current_connections(only_direct=True))
            
            for nei in neighbors:
                avg_reputation = self.reputation_instance.calculate_reputation(
                    self.config.participant["scenario_args"]["name"], 
                    self.log_dir, 
                    self.idx, 
                    self.addr, 
                    nei, 
                    current_round= current_round
                )

                if nei not in self.reputation:
                    self.reputation[nei] = {"reputation": avg_reputation, "round": self.round, "last_feedback_round": -1}
                else:
                    self.reputation[nei]["reputation"] = avg_reputation
                    self.reputation[nei]["round"] = self.round

                if self.reputation[nei]["reputation"] is not None:
                    logging.info(f"Reputation of node {nei}: {self.reputation[nei]['reputation']}")
                    if self.reputation[nei]["reputation"] <= 0.6:
                        # logging.info(f"Rejected node: {nei}")
                        # if nei in self.rejected_nodes:
                        #     penalization_round, penalized_rounds = self.rejected_nodes[nei]
                        #     if penalization_round == current_round:
                        #         logging.info(f"Node {nei} already penalized in the current round {current_round}. No additional penalty applied.")
                        #     else:
                        #         logging.info(f"Node {nei} penalized in a previous round {penalization_round}. Increasing penalized rounds to {penalized_rounds + 1}.")
                        #         self.rejected_nodes[nei] = (penalization_round, penalized_rounds + 1)
                        # else:
                        #     self.rejected_nodes[nei] = (current_round, 1)
                        self.rejected_nodes.add(nei)
                        logging.info(f"Rejected nodes: {self.rejected_nodes}")
                    elif 0.6 < self.reputation[nei]["reputation"] < 0.8:
                        logging.info(f"Change weight node: {nei}")
                        self.change_weight_nodes.add(nei)

            await self.include_feedback_in_reputation()

                # for node, (penalization_round, penalized_rounds) in list(self.rejected_nodes.items()):
                #     if current_round - penalization_round >= 3:
                #         logging.info(f"Removing node {node} from rejected nodes")
                #         self.rejected_nodes.pop(node, None)

            if self.reputation is not None:
                reputation_dict_with_values = {
                    f"Reputation/{self.addr}": {
                        node_id: float(data["reputation"]) for node_id, data in self.reputation.items() if data["reputation"] is not None
                    }
                }

                logging.info(f"Reputation dict: {reputation_dict_with_values}")
                self.trainer._logger.log_data(reputation_dict_with_values, step=self.round)
                
                for nei, data in self.reputation.items():
                    if data["reputation"] is not None:
                        message_data = self.cm.mm.generate_reputation_message(
                            node_id=nei, 
                            score=data["reputation"], 
                            round=data["round"],
                        )
                        self.cm.store_send_timestamp(nei, current_round, "reputation")
                        await self.cm.send_message_to_neighbors(message_data, [nei])

            # await self._reputation_feedback()

    async def include_feedback_in_reputation(self):
        if self._cm.reputation_with_all_feedback is not None:
            current_round = self.get_round()
            for(current_node, node_ip, round_num), scores in self._cm.reputation_with_all_feedback.items():
                
                if node_ip in self.reputation and "last_feedback_round" in self.reputation[node_ip]:
                    if self.reputation[node_ip]["last_feedback_round"] >= round_num:
                        #logging.info(f"Feedback already included in reputation for node {node_ip} in round {round_num}. Skipping...")
                        continue
                
                
                logging.info(f"current_node: {current_node} | node_ip: {node_ip} | round_num: {round_num} | scores: {scores}")
                if scores:
                    avg_feedback = sum(scores) / len(scores)
                    logging.info(f"Receive feedback to node {node_ip} with average score {avg_feedback}")

                    logging.info(f"self.reputation: {self.reputation}")
                    if node_ip in self.reputation:
                        current_reputation = self.reputation[node_ip]["reputation"]
                        logging.info(f"Current reputation for node {node_ip}: {current_reputation}")
                    else:
                        logging.info(f"No node {node_ip} in reputation history.")

                    if current_reputation:
                        combined_reputation = (current_reputation + avg_feedback) / 2
                        logging.info(f"Combined reputation for node {node_ip} in round {round_num}: {combined_reputation}")
                    else:
                        combined_reputation = current_reputation
                        logging.info(f"No reputation calculate for node {node_ip}.")

                    self.reputation[node_ip] = {
                        "reputation": combined_reputation,
                        "round": current_round,
                        "last_feedback_round": round_num  # Registrar la última ronda de feedback procesada
                    }

                    logging.info(f"Updated self.reputation for {node_ip}: {self.reputation[node_ip]}")

    async def _learning_cycle(self):
        while self.round is not None and self.round < self.total_rounds:
            print_msg_box(msg=f"Round {self.round} of {self.total_rounds} started.", indent=2, title="Round information")
            self.trainer.on_round_start()
            self.federation_nodes = await self.cm.get_addrs_current_connections(only_direct=True, myself=True)
            logging.info(f"Federation nodes: {self.federation_nodes}")
            direct_connections = await self.cm.get_addrs_current_connections(only_direct=True)
            undirected_connections = await self.cm.get_addrs_current_connections(only_undirected=True)
            logging.info(f"Direct connections: {direct_connections} | Undirected connections: {undirected_connections}")
            logging.info(f"[Role {self.role}] Starting learning cycle...")
            await self.aggregator.update_federation_nodes(self.federation_nodes)
            await self._extended_learning_cycle()

            await self._calculate_reputation()

            await self.get_round_lock().acquire_async()
            print_msg_box(msg=f"Round {self.round} of {self.total_rounds} finished.", indent=2, title="Round information")
            await self.aggregator.reset()
            self.trainer.on_round_end()

            self.round = self.round + 1
            self.config.participant["federation_args"]["round"] = self.round  # Set current round in config (send to the controller)
            await self.get_round_lock().release_async()

        # End of the learning cycle
        self.trainer.on_learning_cycle_end()
        await self.trainer.test()
        self.round = None
        self.total_rounds = None
        print_msg_box(msg=f"Federated Learning process has been completed.", indent=2, title="End of the experiment")
        # Report
        if self.config.participant["scenario_args"]["controller"] != "nebula-test":
            result = await self.reporter.report_scenario_finished()
            if result:
                pass
            else:
                logging.error(f"Error reporting scenario finished")

        logging.info(f"Checking if all my connections reached the total rounds...")
        while not self.cm.check_finished_experiment():
            await asyncio.sleep(1)

        # Enable loggin info
        logging.getLogger().disabled = True

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

    def reputation_calculation(self, aggregated_models_weights):
        cossim_threshold = 0.5
        loss_threshold = 0.5

        current_models = {}
        for subnodes in aggregated_models_weights.keys():
            sublist = subnodes.split()
            submodel = aggregated_models_weights[subnodes][0]
            for node in sublist:
                current_models[node] = submodel

        malicious_nodes = []
        reputation_score = {}
        local_model = self.trainer.get_model_parameters()
        untrusted_nodes = list(current_models.keys())
        logging.info(f"reputation_calculation untrusted_nodes at round {self.round}: {untrusted_nodes}")

        for untrusted_node in untrusted_nodes:
            logging.info(f"reputation_calculation untrusted_node at round {self.round}: {untrusted_node}")
            logging.info(f"reputation_calculation self.get_name() at round {self.round}: {self.get_name()}")
            if untrusted_node != self.get_name():
                untrusted_model = current_models[untrusted_node]
                cossim = cosine_metric(local_model, untrusted_model, similarity=True)
                logging.info(f"reputation_calculation cossim at round {self.round}: {untrusted_node}: {cossim}")
                self.trainer._logger.log_data({f"Reputation/cossim_{untrusted_node}": cossim}, step=self.round)

                avg_loss = self.trainer.validate_neighbour_model(untrusted_model)
                logging.info(f"reputation_calculation avg_loss at round {self.round} {untrusted_node}: {avg_loss}")
                self.trainer._logger.log_data({f"Reputation/avg_loss_{untrusted_node}": avg_loss}, step=self.round)
                reputation_score[untrusted_node] = (cossim, avg_loss)

                if cossim < cossim_threshold or avg_loss > loss_threshold:
                    malicious_nodes.append(untrusted_node)
                else:
                    self._secure_neighbors.append(untrusted_node)

        return malicious_nodes, reputation_score

    async def send_reputation(self, malicious_nodes):
        logging.info(f"Sending REPUTATION to the rest of the topology: {malicious_nodes}")
        message = self.cm.mm.generate_federation_message(nebula_pb2.FederationMessage.Action.REPUTATION, malicious_nodes)
        await self.cm.send_message_to_neighbors(message)


class MaliciousNode(Engine):

    def __init__(self, model, dataset, config=Config, trainer=Lightning, security=False, model_poisoning=False, poisoned_ratio=0, noise_type="gaussian"):
        super().__init__(model, dataset, config, trainer, security, model_poisoning, poisoned_ratio, noise_type)
        self.attack = create_attack(config.participant["adversarial_args"]["attacks"])
        self.fit_time = 0.0
        self.extra_time = 0.0

        self.round_start_attack = 6
        self.round_stop_attack = 9

        self.aggregator_bening = self._aggregator

    # async def _extended_learning_cycle(self):
    #     current_cycle_round = self.round % 11

    #     if current_cycle_round == 0 or (current_cycle_round in range(3, 5 + 1)) or (current_cycle_round in range(8, 10 + 1)):
    #         logging.info(f"Round {self.round}: Benign behavior.")
    #         self._aggregator = self.aggregator_bening
    #     else:
    #         logging.info(f"Round {self.round}: Malicious behavior.")
    #         self._aggregator = create_malicious_aggregator(self._aggregator, self.attack)

    #     await AggregatorNode._extended_learning_cycle(self)

    async def flood_attack(self, message, repetitions=10, interval=0.05):
        neighbors = set(await self.cm.get_addrs_current_connections(only_direct=True))
        for nei in neighbors:
            for i in range(repetitions):
                message_data = self.cm.mm.generate_flood_attack_message(
                    attacker_id=self.addr,
                    frequency=int(i),
                    duration=int(interval*1000),
                    target_node=nei,
                )
                await self.cm.send_message_to_neighbors(message_data, neighbors={nei})
                logging.info(f"Flood attack message sent to {nei} - Attempt {i + 1}/{repetitions}.")
                await asyncio.sleep(interval)
                self.cm.store_send_timestamp(nei, self.round, "flood_attack")

    async def _extended_learning_cycle(self):
        if self.round in range(self.round_start_attack, self.round_stop_attack):
            logging.info(f"Changing aggregation function maliciously...")
            await self.flood_attack("flood_attack", repetitions=10, interval=0.05)
            self._aggregator = create_malicious_aggregator(self._aggregator, self.attack)
        elif self.round == self.round_stop_attack:
            logging.info(f"Changing aggregation function benignly...")
            self._aggregator = self.aggregator_bening

        await AggregatorNode._extended_learning_cycle(self)

class AggregatorNode(Engine):
    def __init__(self, model, dataset, config=Config, trainer=Lightning, security=False, model_poisoning=False, poisoned_ratio=0, noise_type="gaussian"):
        super().__init__(model, dataset, config, trainer, security, model_poisoning, poisoned_ratio, noise_type)

    async def _extended_learning_cycle(self):
        # Define the functionality of the aggregator node
        await self.trainer.test()
        await self.trainer.train()

        await self.aggregator.include_model_in_buffer(self.trainer.get_model_parameters(), self.trainer.get_model_weight(), source=self.addr, round=self.round)

        await self.cm.propagator.propagate("stable")
        await self._waiting_model_updates()


class ServerNode(Engine):
    def __init__(self, model, dataset, config=Config, trainer=Lightning, security=False, model_poisoning=False, poisoned_ratio=0, noise_type="gaussian"):
        super().__init__(model, dataset, config, trainer, security, model_poisoning, poisoned_ratio, noise_type)

    async def _extended_learning_cycle(self):
        # Define the functionality of the server node
        await self.trainer.test()

        # In the first round, the server node doest take into account the initial model parameters for the aggregation
        await self.aggregator.include_model_in_buffer(self.trainer.get_model_parameters(), self.trainer.BYPASS_MODEL_WEIGHT, source=self.addr, round=self.round)
        await self._waiting_model_updates()
        await self.cm.propagator.propagate("stable")


class TrainerNode(Engine):
    def __init__(self, model, dataset, config=Config, trainer=Lightning, security=False, model_poisoning=False, poisoned_ratio=0, noise_type="gaussian"):
        super().__init__(model, dataset, config, trainer, security, model_poisoning, poisoned_ratio, noise_type)

    async def _extended_learning_cycle(self):
        # Define the functionality of the trainer node
        logging.info(f"Waiting global update | Assign _waiting_global_update = True")
        self.aggregator.set_waiting_global_update()

        await self.trainer.test()
        await self.trainer.train()

        await self.aggregator.include_model_in_buffer(
            self.trainer.get_model_parameters(), self.trainer.get_model_weight(), source=self.addr, round=self.round, local=True
        )

        await self.cm.propagator.propagate("stable")
        await self._waiting_model_updates()


class IdleNode(Engine):
    def __init__(self, model, dataset, config=Config, trainer=Lightning, security=False, model_poisoning=False, poisoned_ratio=0, noise_type="gaussian"):
        super().__init__(model, dataset, config, trainer, security, model_poisoning, poisoned_ratio, noise_type)

    async def _extended_learning_cycle(self):
        # Define the functionality of the idle node
        logging.info(f"Waiting global update | Assign _waiting_global_update = True")
        self.aggregator.set_waiting_global_update()
        await self._waiting_model_updates()

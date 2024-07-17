import hashlib
import logging
import sys
import os
import traceback
import collections
from datetime import datetime
import requests
import asyncio
import subprocess

from nebula.addons.mobility import Mobility
from nebula.core.network.discoverer import Discoverer
from nebula.core.network.forwarder import Forwarder
from nebula.core.network.health import Health
from nebula.core.network.propagator import Propagator
from nebula.core.pb import nebula_pb2
from nebula.core.network.messages import MessagesManager
from nebula.core.network.connection import Connection
from nebula.core.network.nebulamulticasting import NebulaConnectionService

from nebula.core.utils.locker import Locker
from nebula.core.utils.helper import (
    cosine_metric,
    euclidean_metric,
    minkowski_metric,
    manhattan_metric,
    pearson_correlation_metric,
    jaccard_metric,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nebula.core.engine import Engine


class CommunicationsManager:

    def __init__(self, engine: "Engine"):
        logging.info("🌐  Initializing Communications Manager")
        self._engine = engine
        self.addr = engine.get_addr()
        self.host = self.addr.split(":")[0]
        self.port = int(self.addr.split(":")[1])
        self.config = engine.get_config()
        self.id = str(self.config.participant["device_args"]["idx"])

        self.register_endpoint = f'http://{self.config.participant["scenario_args"]["controller"]}/nebula/dashboard/{self.config.participant["scenario_args"]["name"]}/node/register'
        self.wait_endpoint = f'http://{self.config.participant["scenario_args"]["controller"]}/nebula/dashboard/{self.config.participant["scenario_args"]["name"]}/node/wait'

        self._connections = {}
        self.connections_lock = Locker(name="connections_lock")
        self.connections_manager_lock = Locker(name="connections_manager_lock", async_lock=True)
        self.connection_attempt_lock_incoming = Locker(name="connection_attempt_lock_incoming", async_lock=True)
        self.connection_attempt_lock_outgoing = Locker(name="connection_attempt_lock_outgoing", async_lock=True)
        # Pending connections to be established
        self.pending_connections = set()
        self.incoming_connections = {}
        self.outgoing_connections = {}

        self._mm = MessagesManager(addr=self.addr, config=self.config, cm=self)
        self.received_messages_hashes = collections.deque(maxlen=self.config.participant["message_args"]["max_local_messages"])
        self.receive_messages_lock = Locker(name="receive_messages_lock")

        self._discoverer = Discoverer(addr=self.addr, config=self.config, cm=self)
        self._health = Health(addr=self.addr, config=self.config, cm=self)
        self._forwarder = Forwarder(config=self.config, cm=self)
        self._propagator = Propagator(cm=self)
        self._mobility = Mobility(config=self.config, cm=self)

        # List of connections to reconnect {addr: addr, tries: 0}
        self.connections_reconnect = []
        self.max_connections = 1000
        self.network_engine = None
        
        # Connection service to communicate with external devices
        self._external_connection_service = None
        
        # The line below is neccesary when mobility would be set up
        if self.config.participant["mobility_args"]["mobility"] and not self.config.participant["mobility_args"]["late_creation"]:
            self._external_connection_service = NebulaConnectionService(self.addr)
            self.ecs.start()

        self.stop_network_engine = asyncio.Event()

    @property
    def engine(self):
        return self._engine

    @property
    def connections(self):
        return self._connections

    @property
    def mm(self):
        return self._mm

    @property
    def discoverer(self):
        return self._discoverer

    @property
    def health(self):
        return self._health

    @property
    def forwarder(self):
        return self._forwarder

    @property
    def propagator(self):
        return self._propagator

    @property
    def mobility(self):
        return self._mobility
    
    @property
    def ecs(self):
        return self._external_connection_service

    async def handle_incoming_message(self, data, addr_from):
        try:
            message_wrapper = nebula_pb2.Wrapper()
            message_wrapper.ParseFromString(data)
            source = message_wrapper.source
            if source == self.addr:
                return
            if message_wrapper.HasField("discovery_message"):
                if self.include_received_message_hash(hashlib.md5(data).hexdigest()):
                    self.forwarder.forward(data, addr_from=addr_from)
                    await self.handle_discovery_message(source, message_wrapper.discovery_message)
            elif message_wrapper.HasField("control_message"):
                await self.handle_control_message(source, message_wrapper.control_message)
            elif message_wrapper.HasField("federation_message"):
                if self.include_received_message_hash(hashlib.md5(data).hexdigest()):
                    self.forwarder.forward(data, addr_from=addr_from)
                    await self.handle_federation_message(source, message_wrapper.federation_message)
            elif message_wrapper.HasField("model_message"):
                if self.include_received_message_hash(hashlib.md5(data).hexdigest()):
                    # TODO: Improve the technique. Now only forward model messages if the node is a proxy
                    # Need to update the expected model messages receiving during the round
                    # Round -1 is the initialization round --> all nodes should receive the model
                    if self.config.participant["device_args"]["proxy"] or message_wrapper.model_message.round == -1:
                        self.forwarder.forward(data, addr_from=addr_from)
                    await self.handle_model_message(source, message_wrapper.model_message)
            elif message_wrapper.HasField("connection_message"):
                await self.handle_connection_message(source, message_wrapper.connection_message)
            elif message_wrapper.HasField("discover_message"):
                if self.include_received_message_hash(hashlib.md5(data).hexdigest()):
                    await self.handle_discover_message(source, message_wrapper.discover_message)
            elif message_wrapper.HasField("offer_message"):
                if self.include_received_message_hash(hashlib.md5(data).hexdigest()):
                    await self.handle_offer_message(source, message_wrapper.offer_message)
            elif message_wrapper.HasField("link_message"):
                if self.include_received_message_hash(hashlib.md5(data).hexdigest()):
                    await self.handle_offer_message(source, message_wrapper.link_message)
            else:
                logging.info(f"Unknown handler for message: {message_wrapper}")
        except Exception as e:
            logging.error(f"📥  handle_incoming_message | Error while processing: {e}")
            logging.error(traceback.format_exc())

    async def handle_discovery_message(self, source, message):
        logging.info(f"🔍  handle_discovery_message | Received [Action {message.action}] from {source} (network propagation)")
        try:
            await self.engine.event_manager.trigger_event(source, message)
        except Exception as e:
            logging.error(f"🔍  handle_discovery_message | Error while processing: {e}")

    async def handle_control_message(self, source, message):
        logging.info(f"🔧  handle_control_message | Received [Action {message.action}] from {source} with log {message.log}")
        try:
            await self.engine.event_manager.trigger_event(source, message)
        except Exception as e:
            logging.error(f"🔧  handle_control_message | Error while processing: {message.action} {message.log} | {e}")

    async def handle_federation_message(self, source, message):
        logging.info(f"📝  handle_federation_message | Received [Action {message.action}] from {source} with arguments {message.arguments}")
        try:
            await self.engine.event_manager.trigger_event(source, message)
        except Exception as e:
            logging.error(f"📝  handle_federation_message | Error while processing: {message.action} {message.arguments} | {e}")

    async def handle_model_message(self, source, message):
        logging.info(f"🤖  handle_model_message | Received model from {source} with round {message.round}")
        if self.get_round() is not None:
            self.engine.get_round_lock().acquire()
            current_round = self.get_round()
            self.engine.get_round_lock().release()
            if message.round != current_round and message.round != -1:
                logging.info(f"❗️  handle_model_message | Received a model from a different round | Model round: {message.round} | Current round: {current_round}")
                return
            if not self.engine.get_federation_ready_lock().locked() and len(self.engine.get_federation_nodes()) == 0:
                logging.info(f"🤖  handle_model_message | There are no defined federation nodes")
                return
            try:
                # get_federation_ready_lock() is locked when the model is being initialized (first round)
                # non-starting nodes receive the initialized model from the starting node
                if not self.engine.get_federation_ready_lock().locked() or self.engine.get_initialization_status():
                    decoded_model = self.engine.trainer.deserialize_model(message.parameters)
                    if self.config.participant["adaptive_args"]["model_similarity"]:
                        logging.info(f"🤖  handle_model_message | Checking model similarity")
                        cosine_value = cosine_metric(self.trainer.get_model_parameters(), decoded_model, similarity=True)
                        euclidean_value = euclidean_metric(self.trainer.get_model_parameters(), decoded_model, similarity=True)
                        minkowski_value = minkowski_metric(self.trainer.get_model_parameters(), decoded_model, p=2, similarity=True)
                        manhattan_value = manhattan_metric(self.trainer.get_model_parameters(), decoded_model, similarity=True)
                        pearson_correlation_value = pearson_correlation_metric(self.trainer.get_model_parameters(), decoded_model, similarity=True)
                        jaccard_value = jaccard_metric(self.trainer.get_model_parameters(), decoded_model, similarity=True)
                        with open(f"{self.log_dir}/participant_{self.idx}_similarity.csv", "a+") as f:
                            if os.stat(f"{self.log_dir}/participant_{self.idx}_similarity.csv").st_size == 0:
                                f.write("timestamp,source_ip,nodes,round,current_round,cosine,euclidean,minkowski,manhattan,pearson_correlation,jaccard\n")
                            f.write(f"{datetime.now()}, {source}, {message.round}, {current_round}, {cosine_value}, {euclidean_value}, {minkowski_value}, {manhattan_value}, {pearson_correlation_value}, {jaccard_value}\n")

                    model_weight = message.weight * self.engine.get_weight_modifier(source)
                    await self.engine.aggregator.include_model_in_buffer(
                        decoded_model,
                        model_weight,
                        source=source,
                        round=message.round,
                    )

                else:
                    if message.round != -1:
                        # Be sure that the model message is from the initialization round (round = -1)
                        return
                    logging.info(f"🤖  handle_model_message | Initializing model (executed by {source})")
                    try:
                        model = self.engine.trainer.deserialize_model(message.parameters)
                        self.engine.trainer.set_model_parameters(model, initialize=True)
                        logging.info(f"🤖  handle_model_message | Model Parameters Initialized")
                        self.engine.set_initialization_status(True)
                        self.engine.get_federation_ready_lock().release()  # Enable learning cycle once the initialization is done
                        try:
                            self.engine.get_federation_ready_lock().release()  # Release the lock acquired at the beginning of the engine
                        except RuntimeError:
                            pass
                    except RuntimeError:
                        pass

            except Exception as e:
                logging.error(f"🤖  handle_model_message | Unknown error adding model: {e}")
                logging.error(traceback.format_exc())

        else:
            logging.info(f"🤖  handle_model_message | Tried to add a model while learning is not running")
        return

    async def handle_connection_message(self, source, message):
        try:
            await self.engine.event_manager.trigger_event(source, message)
        except Exception as e:
            logging.error(f"🔗  handle_connection_message | Error while processing: {message.action} | {e}")

    async def handle_discover_message(self, source, message):
        logging.info(f"🔍  handle_discover_message | Received [Action {message.action}] from {source}")
        try:
            await self.engine.event_manager.trigger_event(source, message)
        except Exception as e:
            logging.error(f"🔍  handle_discover_message | Error while processing: {e}")

    async def handle_offer_message(self, source, message):
        logging.info(f"🔍  handle_offer_message | Received [Action {message.action}] from {source} with arguments {message.arguments}")
        try:
            await self.engine.event_manager.trigger_event(source, message)
        except Exception as e:
            logging.error(f"🔍  handle_offer_message | Error while processing: {message.action} {message.arguments} | {e}")

    async def handle_link_message(self, source, message):
        logging.info(f"🔍  handle_link_message | Received [Action {message.action}] from {source} with arguments {message.arguments}")
        try:
            await self.engine.event_manager.trigger_event(source, message)
        except Exception as e:
            logging.error(f"🔍  handle_link_message | Error while processing: {message.action} {message.arguments} | {e}")

    def start_external_connection_service(self):
        self.ecs = NebulaConnectionService(self.addr)
        self.ecs.start()
        
    def stop_external_connection_service(self):
        self.ecs.stop()    
        
    def init_external_connection_service(self):
        self.ecs = NebulaConnectionService(self.addr)
        self.start_external_connection_service()    
        
    async def establish_connection_with_federation(self, message):
        """
            Using ExternalConnectionService to get addrs on local network, after that
            stablishment of TCP connection and send the message broadcasted

        Args:
            message to be sent
        """
        addrs = self.ecs.find_federation()
        for addr in addrs:
            await self.cm.connect(addr, direct=False)
            await self.send_message(addr, message)

    def get_connections_lock(self):
        return self.connections_lock

    def get_config(self):
        return self.config

    def get_addr(self):
        return self.addr

    def get_round(self):
        return self.engine.get_round()

    async def start(self):
        logging.info(f"🌐  Starting Communications Manager...")
        await self.deploy_network_engine()

    async def deploy_network_engine(self):
        logging.info(f"🌐  Deploying Network engine...")
        self.network_engine = await asyncio.start_server(self.handle_connection_wrapper, self.host, self.port)
        self.network_task = asyncio.create_task(self.network_engine.serve_forever(), name="Network Engine")
        logging.info(f"🌐  Network engine deployed at host {self.host} and port {self.port}")

    async def handle_connection_wrapper(self, reader, writer):
        asyncio.create_task(self.handle_connection(reader, writer))

    async def handle_connection(self, reader, writer):

        async def process_connection(reader, writer):
            try:
                addr = writer.get_extra_info("peername")
                connected_node_id = await reader.readline()
                connected_node_id = connected_node_id.decode("utf-8").strip()
                connected_node_port = addr[1]
                if ":" in connected_node_id:
                    connected_node_id, connected_node_port = connected_node_id.split(":")
                connection_addr = f"{addr[0]}:{connected_node_port}"
                direct = await reader.readline()
                direct = direct.decode("utf-8").strip()
                direct = True if direct == "True" else False
                logging.info(f"🔗  [incoming] Connection from {addr} - {connection_addr} [id {connected_node_id} | port {connected_node_port} | direct {direct}] (incoming)")

                if self.id == connected_node_id:
                    logging.info("🔗  [incoming] Connection with yourself is not allowed")
                    writer.write("CONNECTION//CLOSE\n".encode("utf-8"))
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return

                async with self.connections_manager_lock:
                    if len(self.connections) >= self.max_connections:
                        logging.info("🔗  [incoming] Maximum number of connections reached")
                        logging.info(f"🔗  [incoming] Sending CONNECTION//CLOSE to {addr}")
                        writer.write("CONNECTION//CLOSE\n".encode("utf-8"))
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                        return

                    logging.info(f"🔗  [incoming] Connections: {self.connections}")
                    if connection_addr in self.connections:
                        logging.info(f"🔗  [incoming] Already connected with {self.connections[connection_addr]}")
                        logging.info(f"🔗  [incoming] Sending CONNECTION//EXISTS to {addr}")
                        writer.write("CONNECTION//EXISTS\n".encode("utf-8"))
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                        return

                    if connection_addr in self.pending_connections:
                        logging.info(f"🔗  [incoming] Connection with {connection_addr} is already pending")
                        if int(self.host.split(".")[3]) < int(addr[0].split(".")[3]):
                            logging.info(f"🔗  [incoming] Closing incoming connection since self.host < host  (from {connection_addr})")
                            writer.write("CONNECTION//CLOSE\n".encode("utf-8"))
                            await writer.drain()
                            writer.close()
                            await writer.wait_closed()
                            return
                        else:
                            logging.info(f"🔗  [incoming] Closing outgoing connection since self.host >= host (from {connection_addr})")
                            if connection_addr in self.outgoing_connections:
                                out_reader, out_writer = self.outgoing_connections.pop(connection_addr)
                                out_writer.write("CONNECTION//CLOSE\n".encode("utf-8"))
                                await out_writer.drain()
                                out_writer.close()
                                await out_writer.wait_closed()

                    logging.info(f"🔗  [incoming] Including {connection_addr} in pending connections")
                    self.pending_connections.add(connection_addr)
                    self.incoming_connections[connection_addr] = (reader, writer)

                logging.info(f"🔗  [incoming] Creating new connection with {addr} (id {connected_node_id})")
                await writer.drain()
                connection = Connection(
                    self,
                    reader,
                    writer,
                    connected_node_id,
                    addr[0],
                    connected_node_port,
                    direct=direct,
                    config=self.config,
                )
                async with self.connections_manager_lock:
                    logging.info(f"🔗  [incoming] Including {connection_addr} in connections")
                    self.connections[connection_addr] = connection
                    logging.info(f"🔗  [incoming] Sending CONNECTION//NEW to {addr}")
                    writer.write("CONNECTION//NEW\n".encode("utf-8"))
                    await writer.drain()
                    writer.write(f"{self.id}\n".encode("utf-8"))
                    await writer.drain()
                    await connection.start()

            except Exception as e:
                logging.error(f"❗️  [incoming] Error while handling connection with {addr}: {e}")
            finally:
                if connection_addr in self.pending_connections:
                    logging.info(f"🔗  [incoming] Removing {connection_addr} from pending connections: {self.pending_connections}")
                    self.pending_connections.remove(connection_addr)
                if connection_addr in self.incoming_connections:
                    logging.info(f"🔗  [incoming] Removing {connection_addr} from incoming connections: {self.incoming_connections.keys()}")
                    self.incoming_connections.pop(connection_addr)

        await process_connection(reader, writer)

    async def stop(self):
        logging.info(f"🌐  Stopping Communications Manager... [Removing connections and stopping network engine]")
        connections = list(self.connections.values())
        for node in connections:
            await node.stop()
        if hasattr(self, "server"):
            self.network_engine.close()
            await self.network_engine.wait_closed()
            self.network_task.cancel()

    async def run_reconnections(self):
        for connection in self.connections_reconnect:
            if connection["addr"] in self.connections:
                connection["tries"] = 0
                logging.info(f"🔗  Node {connection.addr} is still connected!")
            else:
                connection["tries"] += 1
                await self.connect(connection["addr"])

    def verify_connections(self, neighbors):
        # Return True if all neighbors are connected
        if all(neighbor in self.connections for neighbor in neighbors):
            return True
        return False

    async def network_wait(self):
        await self.stop_network_engine.wait()

    async def deploy_additional_services(self):
        logging.info(f"🌐  Deploying additional services...")
        self._generate_network_conditions()
        self._forwarder.start()
        self._discoverer.start()
        self._health.start()
        self._propagator.start()
        self._mobility.start()

    def _generate_network_conditions(self):
        # TODO: Implement selection of network conditions from frontend
        if self.config.participant["network_args"]["simulation"]:
            interface = self.config.participant["network_args"]["interface"]
            bandwidth = self.config.participant["network_args"]["bandwidth"]
            delay = self.config.participant["network_args"]["delay"]
            delay_distro = self.config.participant["network_args"]["delay-distro"]
            delay_distribution = self.config.participant["network_args"]["delay-distribution"]
            loss = self.config.participant["network_args"]["loss"]
            duplicate = self.config.participant["network_args"]["duplicate"]
            corrupt = self.config.participant["network_args"]["corrupt"]
            reordering = self.config.participant["network_args"]["reordering"]
            logging.info(f"🌐  Network simulation is enabled | Interface: {interface} | Bandwidth: {bandwidth} | Delay: {delay} | Delay Distro: {delay_distro} | Delay Distribution: {delay_distribution} | Loss: {loss} | Duplicate: {duplicate} | Corrupt: {corrupt} | Reordering: {reordering}")
            try:
                results = subprocess.run(
                    [
                        "tcset",
                        str(interface),
                        "--rate",
                        str(bandwidth),
                        "--delay",
                        str(delay),
                        "--delay-distro",
                        str(delay_distro),
                        "--delay-distribution",
                        str(delay_distribution),
                        "--loss",
                        str(loss),
                        "--duplicate",
                        str(duplicate),
                        "--corrupt",
                        str(corrupt),
                        "--reordering",
                        str(reordering),
                    ],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except Exception as e:
                logging.error(f"🌐  Network simulation error: {e}")
                return
        else:
            logging.info("🌐  Network simulation is disabled. Using default network conditions...")

    def _reset_network_conditions(self):
        interface = self.config.participant["network_args"]["interface"]
        logging.info(f"🌐  Resetting network conditions")
        try:
            results = subprocess.run(
                ["tcdel", str(interface), "--all"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as e:
            logging.error(f"❗️  Network simulation error: {e}")
            return

    def _set_network_conditions(
        self,
        interface="eth0",
        network="192.168.50.2",
        bandwidth="5Gbps",
        delay="0ms",
        delay_distro="0ms",
        delay_distribution="normal",
        loss="0%",
        duplicate="0%",
        corrupt="0%",
        reordering="0%",
    ):
        logging.info(
            f"🌐  Changing network conditions | Interface: {interface} | Network: {network} | Bandwidth: {bandwidth} | Delay: {delay} | Delay Distro: {delay_distro} | Delay Distribution: {delay_distribution} | Loss: {loss} | Duplicate: {duplicate} | Corrupt: {corrupt} | Reordering: {reordering}"
        )
        try:
            results = subprocess.run(
                [
                    "tcset",
                    str(interface),
                    "--network",
                    str(network) if network is not None else "",
                    "--rate",
                    str(bandwidth),
                    "--delay",
                    str(delay),
                    "--delay-distro",
                    str(delay_distro),
                    "--delay-distribution",
                    str(delay_distribution),
                    "--loss",
                    str(loss),
                    "--duplicate",
                    str(duplicate),
                    "--corrupt",
                    str(corrupt),
                    "--reordering",
                    str(reordering),
                    "--change",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as e:
            logging.error(f"❗️  Network simulation error: {e}")
            return

    def include_received_message_hash(self, hash_message):
        try:
            self.receive_messages_lock.acquire()
            if hash_message in self.received_messages_hashes:
                # logging.info(f"❗️  handle_incoming_message | Ignoring message already received.")
                return False
            self.received_messages_hashes.append(hash_message)
            if len(self.received_messages_hashes) % 100 == 0:
                logging.info(f"📥  Received {len(self.received_messages_hashes)} messages")
            return True
        except Exception as e:
            logging.error(f"❗️  handle_incoming_message | Error including message hash: {e}")
            return False
        finally:
            self.receive_messages_lock.release()

    async def send_message_to_neighbors(self, message, neighbors=None, interval=0):
        if neighbors is None:
            neighbors = set(self.get_all_addrs_current_connections(only_direct=True))
            logging.info(f"Sending message to ALL neighbors: {neighbors}")
        else:
            logging.info(f"Sending message to neighbors: {neighbors}")

        for neighbor in set(neighbors):
            await self.send_message(neighbor, message)
            await asyncio.sleep(interval)

    async def send_message(self, dest_addr, message):
        try:
            self.get_connections_lock().acquire()
            conn = self.connections[dest_addr]
            corutine = conn.send(data=message)
            asyncio.run_coroutine_threadsafe(corutine, conn.loop)
        except Exception as e:
            logging.error(f"❗️  Cannot send message {message} to {dest_addr}. Error: {str(e)}")
            await self.disconnect(dest_addr, mutual_disconnection=False)
        finally:
            self.get_connections_lock().release()

    async def send_model(self, dest_addr, round, serialized_model, weight=1):
        try:
            self.get_connections_lock().acquire()
            conn = self.connections[dest_addr]
            logging.info(f"Sending model to {dest_addr} with round {round}: weight={weight} | size={sys.getsizeof(serialized_model) / (1024 ** 2) if serialized_model is not None else 0} MB")
            message = self.mm.generate_model_message(round, serialized_model, weight)
            corutine = conn.send(data=message)
            asyncio.run_coroutine_threadsafe(corutine, conn.loop)
        except Exception as e:
            logging.error(f"❗️  Cannot send model to {dest_addr}: {str(e)}")
            await self.disconnect(dest_addr, mutual_disconnection=False)
        finally:
            self.get_connections_lock().release()

    async def establish_connection(self, addr, direct=True, reconnect=False):
        logging.info(f"🔗  [outgoing] Establishing connection with {addr} (direct: {direct})")

        async def process_establish_connection(addr, direct, reconnect):
            try:
                host = str(addr.split(":")[0])
                port = str(addr.split(":")[1])
                if host == self.host and port == self.port:
                    logging.info("🔗  [outgoing] Connection with yourself is not allowed")
                    return False

                async with self.connections_manager_lock:
                    if addr in self.connections:
                        logging.info(f"🔗  [outgoing] Already connected with {self.connections[addr]}")
                        return False
                    if addr in self.pending_connections:
                        logging.info(f"🔗  [outgoing] Connection with {addr} is already pending")
                        if int(self.host.split(".")[3]) >= int(host.split(".")[3]):
                            logging.info(f"🔗  [outgoing] Closing outgoing connection since self.host >= host (from {addr})")
                            return False
                        else:
                            logging.info(f"🔗  [outgoing] Closing incoming connection since self.host < host (from {addr})")
                            if addr in self.incoming_connections:
                                inc_reader, inc_writer = self.incoming_connections.pop(addr)
                                inc_writer.write("CONNECTION//CLOSE\n".encode("utf-8"))
                                await inc_writer.drain()
                                inc_writer.close()
                                await inc_writer.wait_closed()

                    self.pending_connections.add(addr)
                    logging.info(f"🔗  [outgoing] Including {addr} in pending connections: {self.pending_connections}")

                logging.info(f"🔗  [outgoing] Openning connection with {host}:{port}")
                reader, writer = await asyncio.open_connection(host, port)
                logging.info(f"🔗  [outgoing] Connection opened with {writer.get_extra_info('peername')}")

                async with self.connections_manager_lock:
                    self.outgoing_connections[addr] = (reader, writer)

                writer.write(f"{self.id}:{self.port}\n".encode("utf-8"))
                await writer.drain()
                writer.write(f"{direct}\n".encode("utf-8"))
                await writer.drain()

                connection_status = await reader.readline()
                connection_status = connection_status.decode("utf-8").strip()

                logging.info(f"🔗  [outgoing] Received connection status {connection_status} (from {addr})")
                logging.info(f"🔗  [outgoing] Connections: {self.connections}")

                if connection_status == "CONNECTION//CLOSE":
                    logging.info(f"🔗  [outgoing] Connection with {addr} closed")
                    if addr in self.pending_connections:
                        logging.info(f"🔗  [outgoing] Removing {addr} from pending connections: {self.pending_connections}")
                        self.pending_connections.remove(addr)
                    if addr in self.outgoing_connections:
                        logging.info(f"🔗  [outgoing] Removing {addr} from outgoing connections: {self.outgoing_connections.keys()}")
                        self.outgoing_connections.pop(addr)
                    if addr in self.incoming_connections:
                        logging.info(f"🔗  [outgoing] Removing {addr} from incoming connections: {self.incoming_connections.keys()}")
                        self.incoming_connections.pop(addr)
                    writer.close()
                    await writer.wait_closed()
                    return False
                elif connection_status == "CONNECTION//PENDING":
                    logging.info(f"🔗  [outgoing] Connection with {addr} is already pending")
                    writer.close()
                    await writer.wait_closed()
                    return False
                elif connection_status == "CONNECTION//EXISTS":
                    logging.info(f"🔗  [outgoing] Already connected {self.connections[addr]}")
                    writer.close()
                    await writer.wait_closed()
                    return True
                elif connection_status == "CONNECTION//NEW":
                    async with self.connections_manager_lock:
                        connected_node_id = await reader.readline()
                        connected_node_id = connected_node_id.decode("utf-8").strip()
                        logging.info(f"🔗  [outgoing] Received connected node id: {connected_node_id} (from {addr})")
                        logging.info(f"🔗  [outgoing] Creating new connection with {host}:{port} (id {connected_node_id})")
                        connection = Connection(self, reader, writer, connected_node_id, host, port, direct=direct, config=self.config)
                        self.connections[addr] = connection
                        await connection.start()
                else:
                    logging.info(f"🔗  [outgoing] Unknown connection status {connection_status}")
                    writer.close()
                    await writer.wait_closed()
                    return False

                if reconnect:
                    logging.info(f"🔗  [outgoing] Reconnection check is enabled on node {addr}")
                    self.connections_reconnect.append({"addr": addr, "tries": 0})

                self.config.add_neighbor_from_config(addr)
                return True
            except Exception as e:
                logging.info(f"❗️  [outgoing] Error adding direct connected neighbor {addr}: {str(e)}")
                return False
            finally:
                if addr in self.pending_connections:
                    logging.info(f"🔗  [outgoing] Removing {addr} from pending connections: {self.pending_connections}")
                    self.pending_connections.remove(addr)
                if addr in self.outgoing_connections:
                    logging.info(f"🔗  [outgoing] Removing {addr} from outgoing connections: {self.outgoing_connections.keys()}")
                    self.outgoing_connections.pop(addr)
                if addr in self.incoming_connections:
                    logging.info(f"🔗  [outgoing] Removing {addr} from incoming connections: {self.incoming_connections.keys()}")
                    self.incoming_connections.pop(addr)

        asyncio.create_task(process_establish_connection(addr, direct, reconnect))

    async def connect(self, addr, direct=True):
        self.get_connections_lock().acquire()
        duplicated = addr in self.connections.keys()
        self.get_connections_lock().release()
        if duplicated:
            if direct:  # Upcoming direct connection
                if not self.connections[addr].get_direct():
                    logging.info(f"🔗  [outgoing] Upgrading non direct connected neighbor {addr} to direct connection")
                    return await self.establish_connection(addr, direct=True, reconnect=False)
                else:  # Upcoming undirected connection
                    logging.info(f"🔗  [outgoing] Already direct connected neighbor {addr}, reconnecting...")
                    return await self.establish_connection(addr, direct=True, reconnect=False)
            else:
                logging.info(f"❗️  Cannot add a duplicate {addr} (undirected connection), already connected")
                return False
        else:
            if direct:
                return await self.establish_connection(addr, direct=True, reconnect=False)
            else:
                return await self.establish_connection(addr, direct=False, reconnect=False)

    async def register(self):
        data = {"node": self.addr}
        logging.info(f"Registering node {self.addr} in the controller")
        response = requests.post(self.register_endpoint, json=data)
        if response.status_code == 200:
            logging.info(f"Node {self.addr} registered successfully in the controller")
        else:
            logging.error(f"Error registering node {self.addr} in the controller")

    async def wait_for_controller(self):
        while True:
            response = requests.get(self.wait_endpoint)
            if response.status_code == 200:
                logging.info(f"Continue signal received from controller")
                break
            else:
                logging.info(f"Waiting for controller signal...")
            await asyncio.sleep(1)

    async def disconnect(self, dest_addr, mutual_disconnection=True):
        logging.info(f"Trying to disconnect {dest_addr}")
        if dest_addr not in self.connections:
            logging.info(f"Connection {dest_addr} not found")
            return
        try:
            if mutual_disconnection:
                coroutine = self.connections[dest_addr].send(data=self.mm.generate_connection_message(nebula_pb2.ConnectionMessage.Action.DISCONNECT))
                asyncio.run_coroutine_threadsafe(coroutine, self.connections[dest_addr].loop)
                await asyncio.sleep(1)
                self.connections[dest_addr].stop()
        except Exception as e:
            logging.error(f"❗️  Error while disconnecting {dest_addr}: {str(e)}")
        if dest_addr in self.connections:
            logging.info(f"Removing {dest_addr} from connections")
            del self.connections[dest_addr]
        current_connections = set(self.get_all_addrs_current_connections(only_direct=True))
        logging.info(f"Current connections: {current_connections}")
        self.config.update_neighbors_from_config(current_connections, dest_addr)

    def get_all_addrs_current_connections(self, only_direct=False, only_undirected=False):
        try:
            self.get_connections_lock().acquire()
            if only_direct:
                return {addr for addr, conn in self.connections.items() if conn.get_direct()}
            elif only_undirected:
                return {addr for addr, conn in self.connections.items() if not conn.get_direct()}
            else:
                return set(self.connections.keys())
        finally:
            self.get_connections_lock().release()

    def get_addrs_current_connections(self, only_direct=False, only_undirected=False, myself=False):
        current_connections = set(self.get_all_addrs_current_connections(only_direct=only_direct, only_undirected=only_undirected))
        if myself:
            current_connections.add(self.addr)
        return current_connections

    def get_connection_by_addr(self, addr):
        try:
            self.get_connections_lock().acquire()
            for key, conn in self.connections.items():
                if addr in key:
                    return conn
            return None
        except Exception as e:
            logging.error(f"Error getting connection by address: {e}")
            return None
        finally:
            self.get_connections_lock().release()

    def get_direct_connections(self):
        try:
            self.get_connections_lock().acquire()
            return {conn for _, conn in self.connections.items() if conn.get_direct()}
        finally:
            self.get_connections_lock().release()

    def get_undirect_connections(self):
        try:
            self.get_connections_lock().acquire()
            return {conn for _, conn in self.connections.items() if not conn.get_direct()}
        finally:
            self.get_connections_lock().release()

    def get_nearest_connections(self, top: int = 1):
        try:
            self.get_connections_lock().acquire()
            sorted_connections = sorted(
                self.connections.values(),
                key=lambda conn: (conn.get_neighbor_distance() if conn.get_neighbor_distance() is not None else float("inf")),
            )
            if top == 1:
                return sorted_connections[0]
            else:
                return sorted_connections[:top]
        finally:
            self.get_connections_lock().release()

    def get_ready_connections(self):
        return {addr for addr, conn in self.connections.items() if conn.get_ready()}

    def __str__(self):
        return f"Connections: {[str(conn) for conn in self.connections.values()]}"

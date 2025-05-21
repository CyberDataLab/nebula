import asyncio
import collections
import logging
from typing import TYPE_CHECKING

import requests

from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import MessageEvent
from nebula.core.network.blacklist import BlackList
from nebula.core.network.connection import Connection
from nebula.core.network.discoverer import Discoverer
from nebula.core.network.externalconnection.externalconnectionservice import factory_connection_service
from nebula.core.network.forwarder import Forwarder
from nebula.core.network.messages import MessagesManager
from nebula.core.network.propagator import Propagator
from nebula.core.utils.locker import Locker

if TYPE_CHECKING:
    from nebula.core.engine import Engine

BLACKLIST_EXPIRATION_TIME = 60

_COMPRESSED_MESSAGES = [
    "model",
    "offer_model"
]

class CommunicationsManager:
    _instance = None
    _lock = Locker("communications_manager_lock", async_lock=False)

    def __new__(cls, engine: "Engine"):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        """Obtain CommunicationsManager instance"""
        if cls._instance is None:
            raise ValueError("CommunicationsManager has not been initialized yet.")
        return cls._instance

    def __init__(self, engine: "Engine"):
        if hasattr(self, "_initialized") and self._initialized:
            return  # Avoid reinicialization

        logging.info("🌐  Initializing Communications Manager")
        self._engine = engine
        self.addr = engine.get_addr()
        self.host = self.addr.split(":")[0]
        self.port = int(self.addr.split(":")[1])
        self.config = engine.get_config()
        self.id = str(self.config.participant["device_args"]["idx"])

        self.register_endpoint = f"http://{self.config.participant['scenario_args']['controller']}/platform/dashboard/{self.config.participant['scenario_args']['name']}/node/register"
        self.wait_endpoint = f"http://{self.config.participant['scenario_args']['controller']}/platform/dashboard/{self.config.participant['scenario_args']['name']}/node/wait"

        self._connections: dict[str, Connection] = {}
        self.connections_lock = Locker(name="connections_lock", async_lock=True)
        self.connections_manager_lock = Locker(name="connections_manager_lock", async_lock=True)
        self.connection_attempt_lock_incoming = Locker(name="connection_attempt_lock_incoming", async_lock=True)
        self.connection_attempt_lock_outgoing = Locker(name="connection_attempt_lock_outgoing", async_lock=True)
        # Pending connections to be established
        self.pending_connections = set()
        self.incoming_connections = {}
        self.outgoing_connections = {}
        self.ready_connections = set()

        self._mm = MessagesManager(addr=self.addr, config=self.config)
        self.received_messages_hashes = collections.deque(
            maxlen=self.config.participant["message_args"]["max_local_messages"]
        )
        self.receive_messages_lock = Locker(name="receive_messages_lock", async_lock=True)

        self._discoverer = Discoverer(addr=self.addr, config=self.config)
        # self._health = Health(addr=self.addr, config=self.config)
        self._forwarder = Forwarder(config=self.config)
        self._propagator = Propagator()

        # List of connections to reconnect {addr: addr, tries: 0}
        self.connections_reconnect = []
        self.max_connections = 1000
        self.network_engine = None

        self.stop_network_engine = asyncio.Event()
        self.loop = asyncio.get_event_loop()
        max_concurrent_tasks = 5
        self.semaphore_send_model = asyncio.Semaphore(max_concurrent_tasks)

        self._blacklist = BlackList()

        # Connection service to communicate with external devices
        self._external_connection_service = factory_connection_service("nebula", self.addr)

        self._initialized = True
        logging.info("Communication Manager initialization completed")

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
    def ecs(self):
        return self._external_connection_service

    @property
    def bl(self):
        return self._blacklist

    async def check_federation_ready(self):
        # Check if all my connections are in ready_connections
        logging.info(
            f"🔗  check_federation_ready | Ready connections: {self.ready_connections} | Connections: {self.connections.keys()}"
        )
        if set(self.connections.keys()) == self.ready_connections:
            return True

    async def add_ready_connection(self, addr):
        self.ready_connections.add(addr)

    async def start_communications(self, initial_neighbors):
        logging.info(f"Neighbors: {self.config.participant['network_args']['neighbors']}")
        logging.info(
            f"💤  Cold start time: {self.config.participant['misc_args']['grace_time_connection']} seconds before connecting to the network"
        )
        await asyncio.sleep(self.config.participant["misc_args"]["grace_time_connection"])
        await self.start()
        for i in initial_neighbors:
            addr = f"{i.split(':')[0]}:{i.split(':')[1]}"
            await self.connect(addr, direct=True)
            await asyncio.sleep(1)
        while not self.verify_connections(initial_neighbors):
            await asyncio.sleep(1)
        current_connections = await self.get_addrs_current_connections()
        logging.info(f"Connections verified: {current_connections}")
        await self.deploy_additional_services()

    """                                                     ##############################
                                                            #    PROCESSING MESSAGES     #
                                                            ##############################
    """

    async def handle_incoming_message(self, data, addr_from):
        if not await self.bl.node_in_blacklist(addr_from):
            await self.mm.process_message(data, addr_from)

    async def forward_message(self, data, addr_from):
        logging.info("Forwarding message... ")
        await self.forwarder.forward(data, addr_from=addr_from)

    async def handle_message(self, message_event):
        asyncio.create_task(EventManager.get_instance().publish(message_event))

    async def handle_model_message(self, source, message):
        logging.info(f"🤖  handle_model_message | Received model from {source} with round {message.round}")
        if message.round == -1:
            model_init_event = MessageEvent(("model", "initialization"), source, message)
            asyncio.create_task(EventManager.get_instance().publish(model_init_event))
        else:
            model_updt_event = MessageEvent(("model", "update"), source, message)
            asyncio.create_task(EventManager.get_instance().publish(model_updt_event))

    def create_message(self, message_type: str, action: str = "", *args, **kwargs):
        return self.mm.create_message(message_type, action, *args, **kwargs)

    def get_messages_events(self):
        return self.mm.get_messages_events()

    """                                                     ##############################
                                                            #          BLACKLIST         #
                                                            ##############################
    """

    async def add_to_recently_disconnected(self, addr):
        await self.bl.add_recently_disconnected(addr)

    async def add_to_blacklist(self, addr):
        await self.bl.add_to_blacklist(addr)

    async def get_blacklist(self):
        return await self.bl.get_blacklist()

    async def apply_restrictions(self, nodes: set) -> set | None:
        return await self.bl.apply_restrictions(nodes)

    async def clear_restrictions(self):
        await self.bl.clear_restrictions()

    """                                                     ###############################
                                                            # EXTERNAL CONNECTION SERVICE #
                                                            ###############################
    """

    async def start_external_connection_service(self, run_service=True):
        if self.ecs == None:
            self._external_connection_service = factory_connection_service(self, self.addr)
        if run_service:
            await self.ecs.start()

    async def stop_external_connection_service(self):
        await self.ecs.stop()

    async def init_external_connection_service(self):
        await self.start_external_connection_service()

    async def is_external_connection_service_running(self):
        return self.ecs.is_running()

    async def start_beacon(self):
        await self.ecs.start_beacon()

    async def stop_beacon(self):
        await self.ecs.stop_beacon()

    async def modify_beacon_frequency(self, frequency):
        await self.ecs.modify_beacon_frequency(frequency)

    async def stablish_connection_to_federation(self, msg_type="discover_join", addrs_known=None):
        """
        Using ExternalConnectionService to get addrs on local network, after that
        stablishment of TCP connection and send the message broadcasted
        """
        addrs = []
        if addrs_known == None:
            logging.info("Searching federation process beginning...")
            addrs = await self.ecs.find_federation()
            logging.info(f"Found federation devices | addrs {addrs}")
        else:
            logging.info(f"Searching federation process beginning... | Using addrs previously known {addrs_known}")
            addrs = addrs_known

        msg = self.create_message("discover", msg_type)

        # Remove neighbors
        neighbors = await self.get_addrs_current_connections(only_direct=True, myself=True)
        addrs = set(addrs)
        if neighbors:
            addrs.difference_update(neighbors)

        # logging.info(f"neighbors: {neighbors} | addr filtered: {addrs}")
        discovers_sent = 0
        connections_made = set()
        if addrs:
            logging.info("Starting communications with devices found")
            max_tries = 5
            for addr in addrs:
                await self.connect(addr, direct=False, priority="high")
                connections_made.add(addr)
                await asyncio.sleep(1)
            for i in range(0, max_tries):
                if self.verify_any_connections(addrs):
                    break
                await asyncio.sleep(1)
            current_connections = await self.get_addrs_current_connections(only_undirected=True)
            logging.info(f"Connections verified after searching: {current_connections}")

            for addr in addrs:
                logging.info(f"Sending {msg_type} to addr: {addr}")
                asyncio.create_task(self.send_message(addr, msg))
                await asyncio.sleep(1)
                discovers_sent += 1
        return (discovers_sent, connections_made)

    """                                                     ##############################
                                                            #    OTHER FUNCTIONALITIES   #
                                                            ##############################
    """

    def get_connections_lock(self):
        return self.connections_lock

    def get_config(self):
        return self.config

    def get_addr(self):
        return self.addr

    def get_round(self):
        return self.engine.get_round()

    async def start(self):
        logging.info("🌐  Starting Communications Manager...")
        await self.deploy_network_engine()

    async def deploy_network_engine(self):
        logging.info("🌐  Deploying Network engine...")
        self.network_engine = await asyncio.start_server(self.handle_connection_wrapper, self.host, self.port)
        self.network_task = asyncio.create_task(self.network_engine.serve_forever(), name="Network Engine")
        logging.info(f"🌐  Network engine deployed at host {self.host} and port {self.port}")

    async def handle_connection_wrapper(self, reader, writer):
        asyncio.create_task(self.handle_connection(reader, writer))

    def create_message(self, message_type: str, action: str = "", *args, **kwargs):
        return self.mm.create_message(message_type, action, *args, **kwargs)

    async def handle_connection(self, reader, writer, priority="medium"):
        async def process_connection(reader, writer, priority="medium"):
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
                direct = direct == "True"
                logging.info(
                    f"🔗  [incoming] Connection from {addr} - {connection_addr} [id {connected_node_id} | port {connected_node_port} | direct {direct}] (incoming)"
                )

                blacklist = await self.bl.get_blacklist()
                if blacklist:
                    logging.info(f"blacklist: {blacklist}, source trying to connect: {connection_addr}")
                    if connection_addr in blacklist:
                        logging.info(f"🔗  [incoming] Rejecting connection from {connection_addr}, it is blacklisted.")
                        writer.close()
                        await writer.wait_closed()
                        return

                if self.id == connected_node_id:
                    logging.info("🔗  [incoming] Connection with yourself is not allowed")
                    writer.write(b"CONNECTION//CLOSE\n")
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return

                async with self.connections_manager_lock:
                    if len(self.connections) >= self.max_connections:
                        logging.info("🔗  [incoming] Maximum number of connections reached")
                        logging.info(f"🔗  [incoming] Sending CONNECTION//CLOSE to {addr}")
                        writer.write(b"CONNECTION//CLOSE\n")
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                        return

                    logging.info(f"🔗  [incoming] Connections: {self.connections}")
                    if connection_addr in self.connections:
                        logging.info(f"🔗  [incoming] Already connected with {self.connections[connection_addr]}")
                        logging.info(f"🔗  [incoming] Sending CONNECTION//EXISTS to {addr}")
                        writer.write(b"CONNECTION//EXISTS\n")
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                        return

                    if connection_addr in self.pending_connections:
                        logging.info(f"🔗  [incoming] Connection with {connection_addr} is already pending")
                        if int(self.host.split(".")[3]) < int(addr[0].split(".")[3]):
                            logging.info(
                                f"🔗  [incoming] Closing incoming connection since self.host < host  (from {connection_addr})"
                            )
                            writer.write(b"CONNECTION//CLOSE\n")
                            await writer.drain()
                            writer.close()
                            await writer.wait_closed()
                            return
                        else:
                            logging.info(
                                f"🔗  [incoming] Closing outgoing connection since self.host >= host (from {connection_addr})"
                            )
                            if connection_addr in self.outgoing_connections:
                                out_reader, out_writer = self.outgoing_connections.pop(connection_addr)
                                out_writer.write(b"CONNECTION//CLOSE\n")
                                await out_writer.drain()
                                out_writer.close()
                                await out_writer.wait_closed()

                    logging.info(f"🔗  [incoming] Including {connection_addr} in pending connections")
                    self.pending_connections.add(connection_addr)
                    self.incoming_connections[connection_addr] = (reader, writer)

                logging.info(f"🔗  [incoming] Creating new connection with {addr} (id {connected_node_id})")
                await writer.drain()
                connection = Connection(
                    reader,
                    writer,
                    connected_node_id,
                    addr[0],
                    connected_node_port,
                    direct=direct,
                    config=self.config,
                    prio=priority,
                )
                async with self.connections_manager_lock:
                    logging.info(f"🔗  [incoming] Including {connection_addr} in connections")
                    self.connections[connection_addr] = connection
                    logging.info(f"🔗  [incoming] Sending CONNECTION//NEW to {addr}")
                    writer.write(b"CONNECTION//NEW\n")
                    await writer.drain()
                    writer.write(f"{self.id}\n".encode())
                    await writer.drain()
                    await connection.start()

            except Exception as e:
                logging.exception(f"❗️  [incoming] Error while handling connection with {addr}: {e}")
            finally:
                if connection_addr in self.pending_connections:
                    logging.info(
                        f"🔗  [incoming] Removing {connection_addr} from pending connections: {self.pending_connections}"
                    )
                    self.pending_connections.remove(connection_addr)
                if connection_addr in self.incoming_connections:
                    logging.info(
                        f"🔗  [incoming] Removing {connection_addr} from incoming connections: {self.incoming_connections.keys()}"
                    )
                    self.incoming_connections.pop(connection_addr)

        await process_connection(reader, writer, priority)

    async def terminate_failed_reconnection(self, conn: Connection):
        connected_with = conn.addr
        await self.bl.add_recently_disconnected(connected_with)
        await self.disconnect(connected_with, mutual_disconnection=False)

    async def stop(self):
        logging.info("🌐  Stopping Communications Manager... [Removing connections and stopping network engine]")
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

    async def clear_unused_undirect_connections(self):
        async with self.connections_lock:
            for conn in self.connections.values():
                if not conn.direct and await conn.is_inactive():
                    logging.info(f"Cleaning unused connection: {conn.addr}")
                    asyncio.create_task(self.disconnect(conn.addr, mutual_disconnection=False))

    def verify_any_connections(self, neighbors):
        # Return True if any neighbors are connected
        if any(neighbor in self.connections for neighbor in neighbors):
            return True
        return False

    def verify_connections(self, neighbors):
        # Return True if all neighbors are connected
        return bool(all(neighbor in self.connections for neighbor in neighbors))

    async def network_wait(self):
        await self.stop_network_engine.wait()

    async def deploy_additional_services(self):
        logging.info("🌐  Deploying additional services...")
        await self._forwarder.start()

        # await self._discoverer.start()
        # await self._health.start()
        self._propagator.start()

    async def include_received_message_hash(self, hash_message):
        try:
            await self.receive_messages_lock.acquire_async()
            if hash_message in self.received_messages_hashes:
                logging.info("❗️  handle_incoming_message | Ignoring message already received.")
                return False
            self.received_messages_hashes.append(hash_message)
            if len(self.received_messages_hashes) % 10000 == 0:
                logging.info(f"📥  Received {len(self.received_messages_hashes)} messages")
            return True
        except Exception as e:
            logging.exception(f"❗️  handle_incoming_message | Error including message hash: {e}")
            return False
        finally:
            await self.receive_messages_lock.release_async()

    async def send_message_to_neighbors(self, message, neighbors=None, interval=0):
        if neighbors is None:
            current_connections = await self.get_all_addrs_current_connections(only_direct=True)
            neighbors = set(current_connections)
            logging.info(f"Sending message to ALL neighbors: {neighbors}")
        else:
            logging.info(f"Sending message to neighbors: {neighbors}")

        for neighbor in neighbors:
            asyncio.create_task(self.send_message(neighbor, message))
            if interval > 0:
                await asyncio.sleep(interval)

    async def send_message(self, dest_addr, message, message_type=""):
        is_compressed = message_type in _COMPRESSED_MESSAGES
        if not is_compressed:
            try:
                if dest_addr in self.connections:
                    conn = self.connections[dest_addr]
                    await conn.send(data=message)
            except Exception as e:
                logging.exception(f"❗️  Cannot send message {message} to {dest_addr}. Error: {e!s}")
                await self.disconnect(dest_addr, mutual_disconnection=False)
        else:
            async with self.semaphore_send_model:
                try:
                    conn = self.connections.get(dest_addr)
                    if conn is None:
                        logging.info(f"❗️  Connection with {dest_addr} not found")
                        return
                    await conn.send(data=message, is_compressed=True)
                except Exception as e:
                    logging.exception(f"❗️  Cannot send model to {dest_addr}: {e!s}")
                    await self.disconnect(dest_addr, mutual_disconnection=False)

    async def establish_connection(self, addr, direct=True, reconnect=False, priority="medium"):
        logging.info(f"🔗  [outgoing] Establishing connection with {addr} (direct: {direct})")

        async def process_establish_connection(addr, direct, reconnect, priority):
            try:
                host = str(addr.split(":")[0])
                port = str(addr.split(":")[1])
                if host == self.host and port == self.port:
                    logging.info("🔗  [outgoing] Connection with yourself is not allowed")
                    return False

                blacklist = await self.bl.get_blacklist()
                if blacklist:
                    logging.info(f"blacklist: {blacklist}, source trying to connect: {addr}")
                    if addr in blacklist:
                        logging.info(f"🔗  [incoming] Rejecting connection from {addr}, it is blacklisted.")
                        return

                async with self.connections_manager_lock:
                    if addr in self.connections:
                        logging.info(f"🔗  [outgoing] Already connected with {self.connections[addr]}")
                        if not self.connections[addr].get_direct() and (direct == True):
                            self.connections[addr].set_direct(direct)
                            return True
                        else:
                            return False
                    if addr in self.pending_connections:
                        logging.info(f"🔗  [outgoing] Connection with {addr} is already pending")
                        if int(self.host.split(".")[3]) >= int(host.split(".")[3]):
                            logging.info(
                                f"🔗  [outgoing] Closing outgoing connection since self.host >= host (from {addr})"
                            )
                            return False
                        else:
                            logging.info(
                                f"🔗  [outgoing] Closing incoming connection since self.host < host (from {addr})"
                            )
                            if addr in self.incoming_connections:
                                inc_reader, inc_writer = self.incoming_connections.pop(addr)
                                inc_writer.write(b"CONNECTION//CLOSE\n")
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

                writer.write(f"{self.id}:{self.port}\n".encode())
                await writer.drain()
                writer.write(f"{direct}\n".encode())
                await writer.drain()

                connection_status = await reader.readline()
                connection_status = connection_status.decode("utf-8").strip()

                logging.info(f"🔗  [outgoing] Received connection status {connection_status} (from {addr})")
                logging.info(f"🔗  [outgoing] Connections: {self.connections}")

                if connection_status == "CONNECTION//CLOSE":
                    logging.info(f"🔗  [outgoing] Connection with {addr} closed")
                    if addr in self.pending_connections:
                        logging.info(
                            f"🔗  [outgoing] Removing {addr} from pending connections: {self.pending_connections}"
                        )
                        self.pending_connections.remove(addr)
                    if addr in self.outgoing_connections:
                        logging.info(
                            f"🔗  [outgoing] Removing {addr} from outgoing connections: {self.outgoing_connections.keys()}"
                        )
                        self.outgoing_connections.pop(addr)
                    if addr in self.incoming_connections:
                        logging.info(
                            f"🔗  [outgoing] Removing {addr} from incoming connections: {self.incoming_connections.keys()}"
                        )
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
                        logging.info(
                            f"🔗  [outgoing] Creating new connection with {host}:{port} (id {connected_node_id})"
                        )
                        connection = Connection(
                            reader,
                            writer,
                            connected_node_id,
                            host,
                            port,
                            direct=direct,
                            config=self.config,
                            prio=priority,
                        )
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

                if direct:
                    self.config.add_neighbor_from_config(addr)
                return True
            except Exception as e:
                logging.info(f"❗️  [outgoing] Error adding direct connected neighbor {addr}: {e!s}")
                return False
            finally:
                if addr in self.pending_connections:
                    logging.info(f"🔗  [outgoing] Removing {addr} from pending connections: {self.pending_connections}")
                    self.pending_connections.remove(addr)
                if addr in self.outgoing_connections:
                    logging.info(
                        f"🔗  [outgoing] Removing {addr} from outgoing connections: {self.outgoing_connections.keys()}"
                    )
                    self.outgoing_connections.pop(addr)
                if addr in self.incoming_connections:
                    logging.info(
                        f"🔗  [outgoing] Removing {addr} from incoming connections: {self.incoming_connections.keys()}"
                    )
                    self.incoming_connections.pop(addr)

        asyncio.create_task(process_establish_connection(addr, direct, reconnect, priority))

    async def connect(self, addr, direct=True, priority="medium"):
        await self.get_connections_lock().acquire_async()
        duplicated = addr in self.connections
        await self.get_connections_lock().release_async()
        if duplicated:
            if direct:  # Upcoming direct connection
                if not self.connections[addr].get_direct():
                    logging.info(f"🔗  [outgoing] Upgrading non direct connected neighbor {addr} to direct connection")
                    return await self.establish_connection(addr, direct=True, reconnect=False, priority=priority)
                else:  # Upcoming undirected connection
                    logging.info(f"🔗  [outgoing] Already direct connected neighbor {addr}, reconnecting...")
                    return await self.establish_connection(addr, direct=True, reconnect=False, priority=priority)
            else:
                logging.info(f"❗️  Cannot add a duplicate {addr} (undirected connection), already connected")
                return False
        else:
            if direct:
                return await self.establish_connection(addr, direct=True, reconnect=False, priority=priority)
            else:
                return await self.establish_connection(addr, direct=False, reconnect=False, priority=priority)

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
                logging.info("Continue signal received from controller")
                break
            else:
                logging.info("Waiting for controller signal...")
            await asyncio.sleep(1)

    async def disconnect(self, dest_addr, mutual_disconnection=True, forced=False):
        removed = False
        is_neighbor = dest_addr in await self.get_addrs_current_connections(only_direct=True, myself=True)

        if forced:
            self.add_to_blacklist(dest_addr)

        logging.info(f"Trying to disconnect {dest_addr}")
        if dest_addr not in self.connections:
            logging.info(f"Connection {dest_addr} not found")
            return
        try:
            if mutual_disconnection:
                await self.connections[dest_addr].send(data=self.create_message("connection", "disconnect"))
                await asyncio.sleep(1)
                await self.connections[dest_addr].stop()
        except Exception as e:
            logging.exception(f"❗️  Error while disconnecting {dest_addr}: {e!s}")
        if dest_addr in self.connections:
            logging.info(f"Removing {dest_addr} from connections")
            # del self.connections[dest_addr]
            try:
                removed = True
                await self.connections[dest_addr].stop()
                del self.connections[dest_addr]
            except Exception as e:
                logging.exception(f"❗️  Error while removing connection {dest_addr}: {e!s}")
        current_connections = await self.get_all_addrs_current_connections(only_direct=True)
        current_connections = set(current_connections)
        logging.info(f"Current connections: {current_connections}")
        self.config.update_neighbors_from_config(current_connections, dest_addr)

        if removed:
            current_connections = await self.get_addrs_current_connections(only_direct=True, myself=True)
            if is_neighbor:
                await self.engine.update_neighbors(dest_addr, current_connections, remove=removed)

    async def remove_temporary_connection(self, temp_addr):
        logging.info(f"Removing temporary conneciton:{temp_addr}..")
        try:
            await self.get_connections_lock().acquire_async()
            self.connections.pop(temp_addr, None)
        finally:
            await self.get_connections_lock().release_async()

    async def get_all_addrs_current_connections(self, only_direct=False, only_undirected=False):
        try:
            await self.get_connections_lock().acquire_async()
            if only_direct:
                return {addr for addr, conn in self.connections.items() if conn.get_direct()}
            elif only_undirected:
                return {addr for addr, conn in self.connections.items() if not conn.get_direct()}
            else:
                return set(self.connections.keys())
        finally:
            await self.get_connections_lock().release_async()

    async def get_addrs_current_connections(self, only_direct=False, only_undirected=False, myself=False):
        current_connections = await self.get_all_addrs_current_connections(
            only_direct=only_direct, only_undirected=only_undirected
        )
        current_connections = set(current_connections)
        if myself:
            current_connections.add(self.addr)
        return current_connections

    async def get_connection_by_addr(self, addr):
        try:
            await self.get_connections_lock().acquire_async()
            for key, conn in self.connections.items():
                if addr in key:
                    return conn
            return None
        except Exception as e:
            logging.exception(f"Error getting connection by address: {e}")
            return None
        finally:
            await self.get_connections_lock().release_async()

    async def get_direct_connections(self):
        try:
            await self.get_connections_lock().acquire_async()
            return {conn for _, conn in self.connections.items() if conn.get_direct()}
        finally:
            await self.get_connections_lock().release_async()

    async def get_undirect_connections(self):
        try:
            await self.get_connections_lock().acquire_async()
            return {conn for _, conn in self.connections.items() if not conn.get_direct()}
        finally:
            await self.get_connections_lock().release_async()

    async def get_nearest_connections(self, top: int = 1):
        try:
            await self.get_connections_lock().acquire_async()
            sorted_connections = sorted(
                self.connections.values(),
                key=lambda conn: (
                    conn.get_neighbor_distance() if conn.get_neighbor_distance() is not None else float("inf")
                ),
            )
            if sorted_connections:
                if top == 1:
                    return sorted_connections[0]
                else:
                    return sorted_connections[:top]
            else:
                return None
        finally:
            await self.get_connections_lock().release_async()

    def get_ready_connections(self):
        return {addr for addr, conn in self.connections.items() if conn.get_ready()}

    def learning_finished(self):
        return self.engine.learning_cycle_finished()

    def check_finished_experiment(self):
        return all(
            conn.get_federated_round() == self.config.participant["scenario_args"]["rounds"] - 1
            for conn in self.connections.values()
        )

    def __str__(self):
        return f"Connections: {[str(conn) for conn in self.connections.values()]}"

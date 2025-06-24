import asyncio
import collections
import logging
from typing import TYPE_CHECKING

import requests

from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import MessageEvent, DuplicatedMessageEvent
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

_COMPRESSED_MESSAGES = ["model", "offer_model"]


class CommunicationsManager:
    """
    Singleton class responsible for managing all communications in the Nebula system.

    This class handles:
    - Sending and receiving protobuf messages between nodes.
    - Forwarding messages when acting as a proxy.
    - Managing known neighbors and communication topology.
    - Handling and dispatching incoming messages to the appropriate handlers.
    - Preventing message duplication via message hash tracking.

    It acts as a central coordinator for message-based interactions and is
    designed to work asynchronously to support non-blocking network operations.
    """

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
        self._ready_connections_lock = Locker("ready_connections_lock", async_lock=True)

        self._mm = MessagesManager(addr=self.addr, config=self.config)
        self.received_messages_hashes = collections.deque(
            maxlen=self.config.participant["message_args"]["max_local_messages"]
        )
        self.receive_messages_lock = Locker(name="receive_messages_lock", async_lock=True)

        self._discoverer = Discoverer(addr=self.addr, config=self.config)
        # self._health = Health(addr=self.addr, config=self.config)
        self._health = None
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
        self._running = asyncio.Event()
        logging.info("Communication Manager initialization completed")

    @property
    def engine(self):
        """
        Returns the main engine responsible for coordinating local training and aggregation.
        """
        return self._engine

    @property
    def connections(self):
        """
        Returns the current list of active connections to neighboring nodes.
        """
        return self._connections

    @property
    def mm(self):
        """
        Returns the MessagesManager instance, used to create and process protocol messages.
        """
        return self._mm

    @property
    def discoverer(self):
        """
        Returns the component responsible for discovering new nodes in the network.
        """
        return self._discoverer

    @property
    def health(self):
        """
        Returns the HealthMonitor component that checks and maintains node health status.
        """
        return self._health

    @property
    def forwarder(self):
        """
        Returns the message forwarder, responsible for forwarding messages to other nodes.
        """
        return self._forwarder

    @property
    def propagator(self):
        """
        Returns the component responsible for propagating messages throughout the network.
        """
        return self._propagator

    @property
    def ecs(self):
        """
        Returns the ExternalConnectionService for handling external network interactions.
        """
        return self._external_connection_service

    @property
    def bl(self):
        """
        Returns the blacklist manager, used to track and filter banned or disconnected nodes.
        """
        return self._blacklist

    async def check_federation_ready(self):
        # Check if all my connections are in ready_connections
        logging.info(
            f"🔗  check_federation_ready | Ready connections: {self.ready_connections} | Connections: {self.connections.keys()}"
        )
        async with self.connections_lock:
            async with self._ready_connections_lock:
                if set(self.connections.keys()) == self.ready_connections:
                    return True

    async def add_ready_connection(self, addr):
        async with self._ready_connections_lock:
            self.ready_connections.add(addr)

    async def start_communications(self, initial_neighbors):
        """
        Starts the communication services and connects to initial neighbors.

        Args:
            initial_neighbors (list): A list of neighbor addresses to connect to after startup.
        """
        self._running.set()
        logging.info(f"Neighbors: {self.config.participant['network_args']['neighbors']}")
        logging.info(
            f"💤  Cold start time: {self.config.participant['misc_args']['grace_time_connection']} seconds before connecting to the network"
        )
        await asyncio.sleep(self.config.participant["misc_args"]["grace_time_connection"])
        await self.start()
        neighbors = set(initial_neighbors)

        if self.addr in neighbors:
            neighbors.discard(self.addr)

        for addr in neighbors:
            await self.connect(addr, direct=True)
            await asyncio.sleep(1)
        while not await self.verify_connections(neighbors):
            await asyncio.sleep(1)
        current_connections = await self.get_addrs_current_connections()
        logging.info(f"Connections verified: {current_connections}")
        await self.deploy_additional_services()

    """                                                     ##############################
                                                            #    PROCESSING MESSAGES     #
                                                            ##############################
    """

    async def handle_incoming_message(self, data, addr_from):
        """
        Handles an incoming message if the sender is not blacklisted.

        Args:
            data (bytes): The raw message data.
            addr_from (str): The address of the sender.
        """
        if not await self.bl.node_in_blacklist(addr_from):
            await self.mm.process_message(data, addr_from)

    async def forward_message(self, data, addr_from):
        """
        Forwards a message to other nodes.

        Args:
            data (bytes): The message to be forwarded.
            addr_from (str): The address of the sender.
        """
        logging.info("Forwarding message... ")
        await self.forwarder.forward(data, addr_from=addr_from)

    async def handle_message(self, message_event):
        """
        Publishes a message event to the EventManager.

        Args:
            message_event (MessageEvent): The message event to publish.
        """
        asyncio.create_task(EventManager.get_instance().publish(message_event))

    async def handle_model_message(self, source, message):
        """
        Handles a model-related message and routes it as either initialization or update.

        Args:
            source (str): The sender's address.
            message (BaseMessage): The model message containing the round and payload.
        """
        logging.info(f"🤖  handle_model_message | Received model from {source} with round {message.round}")
        if message.round == -1:
            model_init_event = MessageEvent(("model", "initialization"), source, message)
            asyncio.create_task(EventManager.get_instance().publish(model_init_event))
        else:
            model_updt_event = MessageEvent(("model", "update"), source, message)
            asyncio.create_task(EventManager.get_instance().publish(model_updt_event))

    def create_message(self, message_type: str, action: str = "", *args, **kwargs):
        """
        Creates a new protocol message using the MessagesManager.

        Args:
            message_type (str): The type of message (e.g., 'model', 'discover').
            action (str, optional): An optional action to associate with the message.
            *args: Positional arguments for the message.
            **kwargs: Keyword arguments for the message.

        Returns:
            BaseMessage: The constructed message object.
        """
        return self.mm.create_message(message_type, action, *args, **kwargs)

    def get_messages_events(self):
        """
        Returns the mapping of message types to their respective events.

        Returns:
            dict: A dictionary of message event associations.
        """
        return self.mm.get_messages_events()

    """                                                     ##############################
                                                            #          BLACKLIST         #
                                                            ##############################
    """

    async def add_to_recently_disconnected(self, addr):
        """
        Adds the given address to the list of recently disconnected nodes.

        This is typically used for temporary disconnection tracking before reattempting communication.

        Args:
            addr (str): The address of the node to mark as recently disconnected.
        """
        await self.bl.add_recently_disconnected(addr)

    async def add_to_blacklist(self, addr):
        """
        Adds the given address to the blacklist, preventing any future connection attempts.

        Args:
            addr (str): The address of the node to blacklist.
        """
        await self.bl.add_to_blacklist(addr)

    async def get_blacklist(self):
        """
        Retrieves the current set of blacklisted node addresses.

        Returns:
            set: A set of addresses currently in the blacklist.
        """
        return await self.bl.get_blacklist()

    async def apply_restrictions(self, nodes: set) -> set | None:
        """
        Filters a set of node addresses by removing any that are restricted (e.g., blacklisted).

        Args:
            nodes (set): A set of node addresses to filter.

        Returns:
            set or None: A filtered set of addresses, or None if all were restricted.
        """
        return await self.bl.apply_restrictions(nodes)

    async def clear_restrictions(self):
        """
        Clears all temporary and permanent restrictions, including the blacklist and recently disconnected nodes.
        """
        await self.bl.clear_restrictions()

    """                                                     ###############################
                                                            # EXTERNAL CONNECTION SERVICE #
                                                            ###############################
    """

    async def start_external_connection_service(self, run_service=True):
        """
        Initializes and optionally starts the external connection service (ECS).

        Args:
            run_service (bool): Whether to start the ECS immediately after initialization. Defaults to True.
        """
        if self.ecs == None:
            self._external_connection_service = factory_connection_service(self, self.addr)
        if run_service:
            await self.ecs.start()

    async def stop_external_connection_service(self):
        """
        Stops the external connection service if it is running.
        """
        await self.ecs.stop()

    async def init_external_connection_service(self):
        """
        Initializes and starts the external connection service.
        """
        await self.start_external_connection_service()

    async def is_external_connection_service_running(self):
        """
        Checks if the external connection service is currently running.

        Returns:
            bool: True if the ECS is running, False otherwise.
        """
        return await self.ecs.is_running()

    async def start_beacon(self):
        """
        Starts the beacon emission process to announce the node's presence on the network.
        """
        await self.ecs.start_beacon()

    async def stop_beacon(self):
        """
        Stops the beacon emission process.
        """
        await self.ecs.stop_beacon()

    async def modify_beacon_frequency(self, frequency):
        """
        Modifies the frequency of the beacon emission.

        Args:
            frequency (float): The new frequency (in seconds) between beacon emissions.
        """
        await self.ecs.modify_beacon_frequency(frequency)

    async def stablish_connection_to_federation(self, msg_type="discover_join", addrs_known=None) -> tuple[int, set]:
        """
        Uses the ExternalConnectionService to discover and establish connections with other nodes in the federation.

        This method performs the following steps:
        1. Discovers nodes on the network (if `addrs_known` is not provided).
        2. Establishes TCP connections with discovered nodes.
        3. Sends a federation discovery message to them.

        Args:
            msg_type (str): The type of discovery message to send (e.g., 'discover_join' or 'discover_nodes').
            addrs_known (list, optional): A list of known addresses to use instead of performing discovery.

        Returns:
            tuple: A tuple containing:
                - discovers_sent (int): Number of discovery messages sent.
                - connections_made (set): Set of addresses to which connections were successfully initiated.
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
                if await self.verify_any_connections(addrs):
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
        """
        Returns the asynchronous lock object used to synchronize access to the connections dictionary.

        Returns:
            asyncio.Lock: The lock protecting the connections data structure.
        """
        return self.connections_lock

    def get_config(self):
        """
        Returns the configuration object associated with this communications manager.

        Returns:
            Config: The configuration instance containing settings and parameters.
        """
        return self.config

    def get_addr(self):
        """
        Returns the network address (host:port) of this node.

        Returns:
            str: The node's own address.
        """
        return self.addr

    def get_round(self):
        """
        Retrieves the current training round number from the engine.

        Returns:
            int: The current round number in the federated learning process.
        """
        return self.engine.get_round()

    async def start(self):
        """
        Starts the communications manager by deploying the network engine to accept incoming connections.

        This initializes the server and begins listening on the configured host and port.
        """
        logging.info("🌐  Starting Communications Manager...")
        await self.deploy_network_engine()

    async def deploy_network_engine(self):
        """
        Deploys and starts the network engine server that listens for incoming connections.

        Creates an asyncio server and schedules it to serve connections indefinitely.
        """
        logging.info("🌐  Deploying Network engine...")
        self.network_engine = await asyncio.start_server(self.handle_connection_wrapper, self.host, self.port)
        self.network_task = asyncio.create_task(self.network_engine.serve_forever(), name="Network Engine")
        logging.info(f"🌐  Network engine deployed at host {self.host} and port {self.port}")

    async def handle_connection_wrapper(self, reader, writer):
        asyncio.create_task(self.handle_connection(reader, writer))

    async def handle_connection(self, reader, writer, priority="medium"):
        """
        Wrapper coroutine to handle a new incoming connection.

        Schedules the actual connection handling coroutine as an asyncio task.

        Args:
            reader (asyncio.StreamReader): Stream reader for the connection.
            writer (asyncio.StreamWriter): Stream writer for the connection.
        """

        async def process_connection(reader, writer, priority="medium"):
            """
            Handles the lifecycle of a new incoming connection, including validation, authorization,
            and adding the connection to the manager.

            Performs checks such as blacklist verification, self-connection rejection, maximum connection limits,
            duplicate connection detection, and manages pending connections.

            Args:
                reader (asyncio.StreamReader): Stream reader for the connection.
                writer (asyncio.StreamWriter): Stream writer for the connection.
                priority (str, optional): Priority level for processing the connection. Defaults to "medium".
            """
            try:
                addr = writer.get_extra_info("peername")

                # Check if learning cycle has finished - reject new connections
                if self.engine.learning_cycle_finished():
                    logging.info(f"🔗  [incoming] Rejecting connection from {addr} because learning cycle has finished")
                    writer.write(b"CONNECTION//CLOSE\n")
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return

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
                    async with self.connections_lock:
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
                    async with self.connections_lock:
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
        """
        Handles the termination of a failed reconnection attempt.

        Marks the node as recently disconnected and closes the connection unilaterally
        (i.e., without requiring a mutual disconnection handshake).

        Args:
            conn (Connection): The connection object representing the failed reconnection.
        """
        connected_with = conn.addr
        await self.bl.add_recently_disconnected(connected_with)
        await self.disconnect(connected_with, mutual_disconnection=False)

    async def stop(self):
        logging.info("🌐  Stopping Communications Manager...")

        # Stop accepting new connections first
        if self.network_engine:
            logging.info("🌐  Closing network engine server...")
            self.network_engine.close()
            await self.network_engine.wait_closed()
            if hasattr(self, "network_task") and self.network_task:
                self.network_task.cancel()
                try:
                    await self.network_task
                except asyncio.CancelledError:
                    pass

        # Stop all existing connections
        async with self.connections_lock:
            connections = list(self.connections.values())
            for node in connections:
                await node.stop()

        # Stop additional services
        if self._forwarder:
            await self._forwarder.stop()
        if self.ecs:
            await self.ecs.stop()
        if self.discoverer:
            await self.discoverer.stop()
        if self.health:
            try:
                await self.health.stop()
            except Exception as e:
                logging.warning(f"Error stopping health service: {e}")
        if self._propagator:
            await self._propagator.stop()
        if self._blacklist:
            await self._blacklist.stop()

        self._running.clear()

        self.stop_network_engine.set()

        logging.info("🌐  Communications Manager stopped successfully")

    async def run_reconnections(self):
        for connection in self.connections_reconnect:
            if connection["addr"] in self.connections:
                connection["tries"] = 0
                logging.info(f"🔗  Node {connection.addr} is still connected!")
            else:
                connection["tries"] += 1
                await self.connect(connection["addr"])

    async def clear_unused_undirect_connections(self):
        """
        Cleans up inactive undirected connections.

        Iterates over the current connections, identifies those marked as inactive,
        and asynchronously disconnects them without requiring mutual disconnection.
        """
        async with self.connections_lock:
            inactive_connections = [conn for conn in self.connections.values() if await conn.is_inactive()]
        for conn in inactive_connections:
            logging.info(f"Cleaning unused connection: {conn.addr}")
            asyncio.create_task(self.disconnect(conn.addr, mutual_disconnection=False))

    async def verify_any_connections(self, neighbors):
        """
        Checks if at least one of the given neighbors is currently connected.

        Args:
            neighbors (iterable): A list or set of neighbor addresses to check.

        Returns:
            bool: True if at least one neighbor is connected, False otherwise.
        """
        # Return True if any neighbors are connected
        async with self.connections_lock:
            if any(neighbor in self.connections for neighbor in neighbors):
                return True
            return False

    async def verify_connections(self, neighbors):
        """
        Checks if all given neighbors are currently connected.

        Args:
            neighbors (iterable): A list or set of neighbor addresses to check.

        Returns:
            bool: True if all neighbors are connected, False otherwise.
        """
        # Return True if all neighbors are connected
        async with self.connections_lock:
            return bool(all(neighbor in self.connections for neighbor in neighbors))

    async def network_wait(self):
        await self.stop_network_engine.wait()

    async def deploy_additional_services(self):
        """
        Starts additional network-related services required for the communications manager.

        This includes asynchronously starting the forwarder service and synchronously starting the propagator service,
        enabling message forwarding and propagation functionalities within the network.
        """
        logging.info("🌐  Deploying additional services...")
        await self._forwarder.start()
        self._propagator.start()

    async def include_received_message_hash(self, hash_message, source):
        """
        Adds a received message hash to the tracking list if it hasn't been seen before.

        This prevents processing the same message multiple times in the network.

        Args:
            hash_message (str): The hash of the received message.

        Returns:
            bool: True if the hash was added (i.e., the message is new), False if it was already received.
        """
        try:
            await self.receive_messages_lock.acquire_async()
            if hash_message in self.received_messages_hashes:
                logging.info("❗️  handle_incoming_message | Ignoring message already received.")
                duplicated_event = DuplicatedMessageEvent(source, "Duplicated message received")
                asyncio.create_task(EventManager.get_instance().publish_node_event(duplicated_event))
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
        """
        Sends a message to all or specific neighbors.

        Args:
            message (Any): The message to send.
            neighbors (set, optional): A set of neighbor addresses to send the message to.
                If None, the message is sent to all direct neighbors.
            interval (float, optional): Delay in seconds between sending the message to each neighbor.
        """
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
        """
        Sends a message to a specific destination address, with optional compression for large messages.

        Args:
            dest_addr (str): The destination address of the message.
            message (Any): The message to send.
            message_type (str, optional): Type of message. If in _COMPRESSED_MESSAGES, it will be sent compressed.
        """
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
        """
        Establishes a TCP connection to a remote node, handling blacklist checks, pending connection tracking,
        and bidirectional handshake logic. Optionally upgrades an existing connection to direct, enforces
        reconnection retries, and assigns a connection priority.

        Args:
            addr (str): The target node address in "host:port" format.
            direct (bool, optional): Whether this connection should be marked as direct. Defaults to True.
            reconnect (bool, optional): If True, enable reconnection tracking for this node. Defaults to False.
            priority (str, optional): Priority level for this connection ("low", "medium", "high"). Defaults to "medium".

        Returns:
            bool: True if the connection action (new or upgrade) succeeded, False otherwise.
        """
        # Check if learning cycle has finished - don't establish new connections
        if self.engine.learning_cycle_finished():
            logging.info(f"🔗  [outgoing] Not establishing connection to {addr} because learning cycle has finished")
            return False

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
                    async with self.connections_lock:
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
                async with self.connections_lock:
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
                    async with self.connections_lock:
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
                        async with self.connections_lock:
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
        """
        Public method to initiate or upgrade a connection to a neighbor. Checks for existing connections,
        avoids duplicates, and delegates the actual establishment logic to `establish_connection`.

        Args:
            addr (str): The neighbor address in "host:port" format.
            direct (bool, optional): Whether the new connection should be direct. Defaults to True.
            priority (str, optional): Priority level for establishing the connection. Defaults to "medium".

        Returns:
            bool: True if the connection action (new or upgrade) succeeded, False otherwise.
        """
        async with self.connections_lock:
            duplicated = addr in self.connections
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
        while await self.is_running():
            response = requests.get(self.wait_endpoint)
            if response.status_code == 200:
                logging.info("Continue signal received from controller")
                break
            else:
                logging.info("Waiting for controller signal...")
            await asyncio.sleep(1)

    async def is_running(self):
        return self._running.is_set()

    async def disconnect(self, dest_addr, mutual_disconnection=True, forced=False):
        """
        Disconnects from a specified destination address and performs cleanup tasks.

        Args:
            dest_addr (str): The address of the node to disconnect from.
            mutual_disconnection (bool, optional): Whether to notify the peer about the disconnection. Defaults to True.
            forced (bool, optional): If True, the destination address will be blacklisted. Defaults to False.
        """
        logging.info(f"Trying to disconnect {dest_addr}")

        # Check if this is a direct neighbor before proceeding
        is_neighbor = dest_addr in await self.get_addrs_current_connections(only_direct=True, myself=True)

        # Add to blacklist if forced disconnection
        if forced:
            await self.add_to_blacklist(dest_addr)

        # Get the connection under lock to prevent race conditions
        async with self.connections_lock:
            if dest_addr not in self.connections:
                logging.info(f"Connection {dest_addr} not found")
                return
            conn = self.connections[dest_addr]

        try:
            # Attempt mutual disconnection if requested
            if mutual_disconnection:
                try:
                    await conn.send(data=self.create_message("connection", "disconnect"))
                    async with self.connections_lock:
                        if dest_addr in self.connections:
                            self.connections.pop(dest_addr)
                    await conn.stop()
                except Exception as e:
                    logging.warning(f"Failed to send disconnect message to {dest_addr}: {e!s}")
                    # Ensure connection is removed even if message sending fails
                    async with self.connections_lock:
                        if dest_addr in self.connections:
                            self.connections.pop(dest_addr)
                    await conn.stop()
            else:
                # For non-mutual disconnection, just stop and remove
                async with self.connections_lock:
                    if dest_addr in self.connections:
                        self.connections.pop(dest_addr)
                await conn.stop()

            # Update configuration and neighbors
            current_connections = await self.get_all_addrs_current_connections(only_direct=True)
            current_connections = set(current_connections)
            logging.info(f"Current connections after disconnection: {current_connections}")

            # Update configuration
            self.config.update_neighbors_from_config(current_connections, dest_addr)

            # Update engine if this was a direct neighbor
            if is_neighbor:
                current_connections = await self.get_addrs_current_connections(only_direct=True, myself=True)
                await self.engine.update_neighbors(dest_addr, current_connections, remove=True)

        except Exception as e:
            logging.exception(f"Error during disconnection of {dest_addr}: {e!s}")
            # Ensure connection is removed even if there's an error
            async with self.connections_lock:
                if dest_addr in self.connections:
                    self.connections.pop(dest_addr)
            try:
                await conn.stop()
            except Exception as stop_error:
                logging.warning(f"Error stopping connection during cleanup: {stop_error!s}")
            raise

    async def get_all_addrs_current_connections(self, only_direct=False, only_undirected=False):
        """
        Retrieve the addresses of current connections with filtering options.

        Args:
            only_direct (bool, optional): If True, return only directly connected addresses. Defaults to False.
            only_undirected (bool, optional): If True, return only undirected (non-direct) connections. Defaults to False.

        Returns:
            set: A set of connection addresses based on the filtering criteria.
        """
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
        """
        Get the addresses of current connections, optionally including self and filtering by connection type.

        Args:
            only_direct (bool, optional): If True, include only directly connected addresses. Defaults to False.
            only_undirected (bool, optional): If True, include only undirected connections. Defaults to False.
            myself (bool, optional): If True, include this node's own address in the result. Defaults to False.

        Returns:
            set: A set of connection addresses according to the specified filters.
        """
        current_connections = await self.get_all_addrs_current_connections(
            only_direct=only_direct, only_undirected=only_undirected
        )
        current_connections = set(current_connections)
        if myself:
            current_connections.add(self.addr)
        return current_connections

    def get_ready_connections(self):
        return {addr for addr, conn in self.connections.items() if conn.get_ready()}

    def learning_finished(self):
        return self.engine.learning_cycle_finished()

    def __str__(self):
        return f"Connections: {[str(conn) for conn in self.connections.values()]}"

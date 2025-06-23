import asyncio
import logging
import socket
import struct

from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import BeaconRecievedEvent, ChangeLocationEvent
from nebula.core.network.externalconnection.externalconnectionservice import ExternalConnectionService


class NebulaServerProtocol(asyncio.DatagramProtocol):
    BCAST_IP = "239.255.255.250"
    UPNP_PORT = 1900
    DISCOVER_MESSAGE = "TYPE: discover"
    BEACON_MESSAGE = "TYPE: beacon"

    def __init__(self, nebula_service, addr):
        self.nebula_service: NebulaConnectionService = nebula_service
        self.addr = addr
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logging.info("Nebula UPnP server is listening...")

    def datagram_received(self, data, addr):
        msg = data.decode("utf-8")
        if self._is_nebula_message(msg):
            # logging.info("Nebula message received...")
            if self.DISCOVER_MESSAGE in msg:
                logging.info("Discovery request received, responding...")
                asyncio.create_task(self.respond(addr))
            elif self.BEACON_MESSAGE in msg:
                asyncio.create_task(self.handle_beacon_received(msg))

    async def respond(self, addr):
        """
        Send a unicast HTTP-like response message to a given address.

        This method is typically called when a discovery request is received.
        It returns metadata indicating that this node is available for
        participation in a DFL federation.

        Args:
            addr (tuple): The address (IP, port) to send the response to.
        """
        try:
            response = (
                "HTTP/1.1 200 OK\r\n"
                "CACHE-CONTROL: max-age=1800\r\n"
                "ST: urn:nebula-service\r\n"
                "TYPE: response\r\n"
                f"LOCATION: {self.addr}\r\n"
                "\r\n"
            )
            self.transport.sendto(response.encode("ASCII"), addr)
        except Exception as e:
            logging.exception(f"Error responding to client: {e}")

    async def handle_beacon_received(self, msg):
        """
        Process a received beacon message from another node.

        Extracts and parses the beacon content, validates it is not from
        this same node, and then notifies the associated Nebula service
        about the presence of a neighbor.

        Args:
            msg (str): The raw message string received via multicast.
        """
        lines = msg.split("\r\n")
        beacon_data = {}

        for line in lines:
            if ": " in line:
                key, value = line.split(": ", 1)
                beacon_data[key] = value

        # Verify that it is not the beacon itself
        beacon_addr = beacon_data.get("LOCATION")
        if beacon_addr == self.addr:
            return

        latitude = float(beacon_data.get("LATITUDE", 0.0))
        longitude = float(beacon_data.get("LONGITUDE", 0.0))
        await self.nebula_service.notify_beacon_received(beacon_addr, (latitude, longitude))

    def _is_nebula_message(self, msg):
        """
        Determine if a message corresponds to the Nebula discovery protocol.

        Args:
            msg (str): The raw message string to evaluate.

        Returns:
            bool: True if the message follows the Nebula service format, False otherwise.
        """
        return "ST: urn:nebula-service" in msg


class NebulaClientProtocol(asyncio.DatagramProtocol):
    BCAST_IP = "239.255.255.250"
    BCAST_PORT = 1900
    SEARCH_TRIES = 3
    SEARCH_INTERVAL = 3

    def __init__(self, nebula_service):
        self.nebula_service: NebulaConnectionService = nebula_service
        self.transport = None
        self.search_done = asyncio.Event()

    def connection_made(self, transport):
        self.transport = transport
        sock = self.transport.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        asyncio.create_task(self.keep_search())

    async def stop(self):
        """
        Stop the client protocol by setting the search_done event to release any waiting tasks.
        """
        self.search_done.set()

    async def keep_search(self):
        """
        Periodically broadcast search requests to discover other nodes in the federation.

        This loop runs a fixed number of times, each time sending a multicast
        discovery request and waiting for a predefined interval before repeating.

        When the loop completes, a synchronization event (`search_done`) is set
        to indicate that the search phase is finished.
        """
        logging.info("Federation searching loop started")
        for _ in range(self.SEARCH_TRIES):
            await self.search()
            await asyncio.sleep(self.SEARCH_INTERVAL)
        self.search_done.set()

    async def wait_for_search(self):
        """
        Wait for the search phase to complete.

        This coroutine blocks until the `search_done` event is set,
        signaling that the search loop has finished.
        """
        await self.search_done.wait()

    async def search(self):
        """
        Send a multicast discovery message to locate other Nebula nodes.

        Constructs and sends an SSDP-like M-SEARCH request targeted to
        all devices on the local multicast group. This message indicates
        interest in finding other participants in the Nebula DFL federation.

        If an error occurs during sending, it is logged as an exception.
        """
        logging.info("Searching for nodes...")
        try:
            search_request = (
                "M-SEARCH * HTTP/1.1\r\n"
                "HOST: 239.255.255.250:1900\r\n"
                'MAN: "ssdp:discover"\r\n'
                "MX: 1\r\n"
                "ST: urn:nebula-service\r\n"
                "TYPE: discover\r\n"
                "\r\n"
            )
            self.transport.sendto(search_request.encode("ASCII"), (self.BCAST_IP, self.BCAST_PORT))
        except Exception as e:
            logging.exception(f"Error sending search request: {e}")

    def datagram_received(self, data, addr):
        try:
            if "ST: urn:nebula-service" in data.decode("utf-8"):
                # logging.info("Received response from Node server-service")
                self.nebula_service.response_received(data, addr)
        except UnicodeDecodeError:
            logging.warning(f"Received malformed message from {addr}, ignoring.")


class NebulaBeacon:
    def __init__(self, nebula_service, addr, interval=20):
        self.nebula_service: NebulaConnectionService = nebula_service
        self.addr = addr
        self.interval = interval  # Send interval in seconds
        self._latitude = None
        self._longitude = None
        self._running = asyncio.Event()

    async def start(self):
        logging.info("[NebulaBeacon]: Starting sending pressence beacon")
        self._running.set()
        await EventManager.get_instance().subscribe_addonevent(ChangeLocationEvent, self._proces_change_location_event)
        while await self.is_running():
            await asyncio.sleep(self.interval)
            await self.send_beacon()

    async def _proces_change_location_event(self, cle: ChangeLocationEvent):
        lat, long = await cle.get_event_data()
        # logging.info(f"Location changed to: ({lat},{long})")
        self._latitude, self._longitude = lat, long

    async def stop(self):
        logging.info("[NebulaBeacon]: Stop existance beacon")
        self._running.clear()
        logging.info("[NebulaBeacon]: _running event cleared")

    async def is_running(self):
        return self._running.is_set()

    async def modify_beacon_frequency(self, frequency):
        logging.info(f"[NebulaBeacon]: Changing beacon frequency from {self.interval}s to {frequency}s")
        self.interval = frequency

    async def send_beacon(self):
        latitude, longitude = self._latitude, self._longitude
        try:
            message = (
                "NOTIFY * HTTP/1.1\r\n"
                "HOST: 239.255.255.250:1900\r\n"
                "ST: urn:nebula-service\r\n"
                "TYPE: beacon\r\n"
                f"LOCATION: {self.addr}\r\n"
                f"LATITUDE: {latitude}\r\n"
                f"LONGITUDE: {longitude}\r\n"
                "\r\n"
            )
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.sendto(message.encode("ASCII"), ("239.255.255.250", 1900))
            sock.close()
            logging.info("Beacon sent")
        except Exception as e:
            logging.exception(f"Error sending beacon: {e}")


class NebulaConnectionService(ExternalConnectionService):
    def __init__(self, addr):
        self.nodes_found = set()
        self.addr = addr
        self._cm = None
        self.server: NebulaServerProtocol = None
        self.client: NebulaClientProtocol = None
        self.beacon: NebulaBeacon = NebulaBeacon(self, self.addr)
        self._running = asyncio.Event()
        self._beacon_task = None  # Track the beacon task

    @property
    def cm(self):
        if not self._cm:
            from nebula.core.network.communications import CommunicationsManager

            self._cm = CommunicationsManager.get_instance()
            return self._cm
        else:
            return self._cm

    async def start(self):
        self._running.set()
        try:
            loop = asyncio.get_running_loop()
            transport, self.server = await loop.create_datagram_endpoint(
                lambda: NebulaServerProtocol(self, self.addr), local_addr=("0.0.0.0", 1900)
            )
        except Exception as e:
            logging.exception(f"Error starting Nebula Connection Service server: {e}")
            await self.stop()
        try:
            # Advanced socket settings
            sock = transport.get_extra_info("socket")
            if sock is not None:
                group = socket.inet_aton("239.255.255.250")  # Multicast to binary format.
                mreq = struct.pack("4sL", group, socket.INADDR_ANY)  # Join multicast group in every interface available
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)  # SO listen multicast packages
        except Exception as e:
            logging.exception(f"Error starting Nebula Connection Service client: {e}")
            await self.stop()

    async def stop(self):
        logging.info("🔗  Stopping Nebula Connection Service...")
        if self.server:
            if self.server.transport:
                self.server.transport.close()
            self.server = None
        if self.client:
            await self.client.stop()
            if self.client.transport:
                self.client.transport.close()
            self.client = None
        if self.beacon:
            await self.stop_beacon()
            self.beacon = None
        self._running.clear()

    async def start_beacon(self):
        if not self.beacon:
            self.beacon = NebulaBeacon(self, self.addr)
        self._beacon_task = asyncio.create_task(self.beacon.start(), name="NebulaBeacon_start")

    async def stop_beacon(self):
        if self.beacon:
            await self.beacon.stop()
            # Cancel the beacon task
            if self._beacon_task and not self._beacon_task.done():
                logging.info("🛑  Cancelling NebulaBeacon background task...")
                self._beacon_task.cancel()
                try:
                    await self._beacon_task
                except asyncio.CancelledError:
                    pass
                self._beacon_task = None
                logging.info("🛑  NebulaBeacon background task cancelled")

    async def modify_beacon_frequency(self, frequency):
        if self.beacon:
            await self.beacon.modify_beacon_frequency(frequency=frequency)

    async def is_running(self):
        return self._running.is_set()

    async def find_federation(self):
        logging.info(f"Node {self.addr} trying to find federation...")
        loop = asyncio.get_running_loop()
        transport, self.client = await loop.create_datagram_endpoint(
            lambda: NebulaClientProtocol(self), local_addr=("0.0.0.0", 0)
        )  # To listen on all network interfaces
        await self.client.wait_for_search()
        transport.close()
        return self.nodes_found

    def response_received(self, data, addr):
        # logging.info("Parsing response...")
        msg_str = data.decode("utf-8")
        for line in msg_str.splitlines():
            if line.strip().startswith("LOCATION:"):
                addr = line.split(": ")[1].strip()
                if addr != self.addr:
                    if addr not in self.nodes_found:
                        logging.info(f"Device address received: {addr}")
                        self.nodes_found.add(addr)

    async def notify_beacon_received(self, addr, geoloc):
        beacon_event = BeaconRecievedEvent(addr, geoloc)
        asyncio.create_task(EventManager.get_instance().publish_node_event(beacon_event))

import asyncio
import logging
import socket
import struct
from nebula.core.network.externalconnectionservice import ExternalConnectionService
from nebula.core.utils.locker import Locker

class NebulaServerProtocol(asyncio.DatagramProtocol):
    BCAST_IP = '239.255.255.250'
    UPNP_PORT = 1900
    DISCOVER_MESSAGE = "TYPE: discover"
    BEACON_MESSAGE = "TYPE: beacon"

    def __init__(self, nebula_service, addr):
        self.nebula_service : NebulaConnectionService = nebula_service
        self.addr = addr
        self.transport = None
        
    def connection_made(self, transport):
        self.transport = transport
        logging.info("Nebula UPnP server is listening...")
    
    def datagram_received(self, data, addr):
        msg = data.decode('utf-8')
        if self._is_nebula_message(msg):
            logging.info("Nebula message received...")
            if self.DISCOVER_MESSAGE in msg:
                logging.info("Discovery request received, responding...")
                asyncio.create_task(self.respond(addr))
            elif self.BEACON_MESSAGE in msg:
                asyncio.create_task(self.handle_beacon_received(msg, addr))
    
    async def respond(self, addr):
        try:
            response = ("HTTP/1.1 200 OK\r\n"
                        "CACHE-CONTROL: max-age=1800\r\n"
                        "ST: urn:nebula-service\r\n"
                        "TYPE: response\r\n"
                        f"LOCATION: {self.addr}\r\n"
                        "\r\n")
            self.transport.sendto(response.encode('ASCII'), addr)
        except Exception as e:
            logging.error(f"Error responding to client: {e}")
    
    async def handle_beacon_received(self, msg):
        for line in msg.splitlines():
            if line.startswith("LOCATION:"):
                beacon_addr = line.split(": ")[1].strip()
                if beacon_addr != self.addr:
                    logging.info(f"Beacon received from: {beacon_addr}")
                    await self.nebula_service.notify_beacon_received(beacon_addr)
    
    def _is_nebula_message(self, msg):
        return "ST: urn:nebula-service" in msg

class NebulaClientProtocol(asyncio.DatagramProtocol):
    BCAST_IP = '239.255.255.250'
    BCAST_PORT = 1900
    SEARCH_TRIES = 5
    SEARCH_INTERVAL = 3

    def __init__(self, nebula_service):
        self.nebula_service : NebulaConnectionService = nebula_service
        self.transport = None
        self.search_done = asyncio.Event()

    def connection_made(self, transport):
        self.transport = transport
        sock = self.transport.get_extra_info('socket')
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        asyncio.create_task(self.keep_search())
    
    async def keep_search(self):
        logging.info("Federation searching loop started")
        # while True:
        for _ in range(self.SEARCH_TRIES):
            await self.search()
            await asyncio.sleep(self.SEARCH_INTERVAL)
        self.search_done.set()

    async def wait_for_search(self):
        await self.search_done.wait()
    
    async def search(self):
        logging.info("Searching for nodes...")
        try:
            search_request = ("M-SEARCH * HTTP/1.1\r\n"
                              "HOST: 239.255.255.250:1900\r\n"
                              "MAN: \"ssdp:discover\"\r\n"
                              "MX: 1\r\n"
                              "ST: urn:nebula-service\r\n"
                              "TYPE: discover\r\n"
                              "\r\n")
            self.transport.sendto(search_request.encode('ASCII'), (self.BCAST_IP, self.BCAST_PORT))
        except Exception as e:
            logging.error(f"Error sending search request: {e}")
    
    def datagram_received(self, data, addr):
        try:
            if "ST: urn:nebula-service" in data.decode('utf-8'):
                logging.info("Received response from Node server-service")
                self.nebula_service.response_received(data, addr)
        except UnicodeDecodeError:
            logging.warning(f"Received malformed message from {addr}, ignoring.")

class NebulaBeacon:
    def __init__(self, addr, interval=7):
        self.addr = addr
        self.interval = interval  # Intervalo de envío en segundos
        self.running = False

    async def start(self):
        logging.info("[NebulaBeacon]: Starting sending pressence beacon")
        self.running = True
        while self.running:
            await self.send_beacon()
            await asyncio.sleep(self.interval)

    async def stop(self):
        logging.info("[NebulaBeacon]: Stop existance beacon")
        self.running = False
        
    async def modify_beacon_frequency(self, frequency):
        logging.info(f"[NebulaBeacon]: Changing beacon frequency from {self.interval}s to {frequency}s")
        self.interval = frequency    

    async def send_beacon(self):
        try:
            message = ("NOTIFY * HTTP/1.1\r\n"
                       "HOST: 239.255.255.250:1900\r\n"
                       "ST: urn:nebula-service\r\n"
                       "TYPE: beacon\r\n"
                       f"LOCATION: {self.addr}\r\n"
                       "\r\n")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.sendto(message.encode('ASCII'), ('239.255.255.250', 1900))
            sock.close()
            logging.info("Beacon sent")
        except Exception as e:
            logging.error(f"Error sending beacon: {e}")

#TODO si la busqueda no devuelve nada nuevo, dejar de hacerla para eliminar tráfico inutil
class NebulaConnectionService(ExternalConnectionService):
    def __init__(self, addr):
        self.nodes_found = set()
        self.addr = addr
        self.server : NebulaServerProtocol = None
        self.client : NebulaClientProtocol = None
        self.beacon : NebulaBeacon = NebulaBeacon(self.addr)
        self.running = False
        self._beacon_listeners_lock = Locker(name="beacon_listeners_lock", async_lock=True)
        self._beacon_listeners = []

    async def start(self):
        loop = asyncio.get_running_loop()
        transport, self.server = await loop.create_datagram_endpoint(
            lambda: NebulaServerProtocol(self, self.addr),
            local_addr=('0.0.0.0', 1900))
        try:
            # Advanced socket settings
            sock = transport.get_extra_info('socket')
            if sock is not None:
                group = socket.inet_aton('239.255.255.250')                             # Multicast to binary format.
                mreq = struct.pack('4sL', group, socket.INADDR_ANY)                     # Join multicast group in every interface available 
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)      # SO listen multicast packages
        except Exception as e:
            logging.exception(f"{e}")
        self.running = True

    async def stop(self):
        if self.server and self.server.transport:
            self.server.transport.close()
        self.running = False

    async def start_beacon(self):
        if not self.beacon:
            self.beacon = NebulaBeacon(self.addr)
        asyncio.create_task(self.beacon.start())
    
    async def stop_beacon(self):
        if self.beacon:
            await self.beacon.stop()
            #self.beacon = None
    
    async def modify_beacon_frequency(self, frequency):
        if self.beacon:
            await self.beacon.modify_beacon_frequency(frequency=frequency)

    def is_running(self):
        return self.running
    
    async def find_federation(self):
        logging.info(f"Node {self.addr} trying to find federation...")
        loop = asyncio.get_running_loop()
        transport, self.client = await loop.create_datagram_endpoint(
            lambda: NebulaClientProtocol(self),
            local_addr=('0.0.0.0', 0))                  # To listen on all network interfaces
        await self.client.wait_for_search() 
        transport.close() 
        return self.nodes_found

    def response_received(self, data, addr):
        logging.info("Parsing response...")
        msg_str = data.decode('utf-8')
        for line in msg_str.splitlines():
            if line.strip().startswith("LOCATION:"):
                addr = line.split(": ")[1].strip()
                if addr != self.addr:
                    logging.info(f"Device address received: {addr}")
                    self.nodes_found.add(addr)
                    
    async def subscribe_beacon_listener(self, listener : callable):
        await self._beacon_listeners_lock.acquire_async()
        self._beacon_listeners.append(listener)
        await self._beacon_listeners_lock.release_async()
                                       
    async def notify_beacon_received(self, addr):
        await self._beacon_listeners_lock.acquire_async()
        for bec_listener in self._beacon_listeners:
            await bec_listener(addr)
        await self._beacon_listeners_lock.release_async()
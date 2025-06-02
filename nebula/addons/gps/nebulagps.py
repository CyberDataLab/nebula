import asyncio
import logging
import socket

from geopy import distance

from nebula.addons.gps.gpsmodule import GPSModule
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import GPSEvent
from nebula.core.utils.locker import Locker


class NebulaGPS(GPSModule):
    BROADCAST_IP = "255.255.255.255"  # Broadcast IP
    BROADCAST_PORT = 50001  # Port used for GPS
    INTERFACE = "eth2"  # Interface to avoid network conditions

    def __init__(self, config, addr, update_interval: float = 5.0, verbose=False):
        self._config = config
        self._addr = addr
        self.update_interval = update_interval  # Frequency
        self.running = False
        self._node_locations = {}  # Dictionary for storing node locations
        self._broadcast_socket = None
        self._nodes_location_lock = Locker("nodes_location_lock", async_lock=True)
        self._verbose = verbose

    async def start(self):
        """Starts the GPS service, sending and receiving locations."""
        logging.info("Starting NebulaGPS service...")
        self.running = True

        # Create broadcast socket
        self._broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Bind socket on eth2 to also receive data
        self._broadcast_socket.bind(("", self.BROADCAST_PORT))

        # Start sending and receiving tasks
        asyncio.create_task(self._send_location_loop())
        asyncio.create_task(self._receive_location_loop())
        asyncio.create_task(self._notify_geolocs())

    async def stop(self):
        """Stops the GPS service."""
        logging.info("Stopping NebulaGPS service...")
        self.running = False
        if self._broadcast_socket:
            self._broadcast_socket.close()
            self._broadcast_socket = None

    async def is_running(self):
        return self.running

    async def get_geoloc(self):
        latitude = self._config.participant["mobility_args"]["latitude"]
        longitude = self._config.participant["mobility_args"]["longitude"]
        return (latitude, longitude)

    async def calculate_distance(self, self_lat, self_long, other_lat, other_long):
        distance_m = distance.distance((self_lat, self_long), (other_lat, other_long)).m
        return distance_m

    async def _send_location_loop(self):
        """Send the geolocation periodically by broadcast."""
        while self.running:
            latitude, longitude = await self.get_geoloc()  # Obtener ubicación actual
            message = f"GPS-UPDATE {self._addr} {latitude} {longitude}"
            self._broadcast_socket.sendto(message.encode(), (self.BROADCAST_IP, self.BROADCAST_PORT))
            if self._verbose:
                logging.info(f"Sent GPS location: ({latitude}, {longitude})")
            await asyncio.sleep(self.update_interval)

    async def _receive_location_loop(self):
        """Listens to and stores geolocations from other nodes."""
        while self.running:
            try:
                data, addr = await asyncio.get_running_loop().run_in_executor(
                    None, self._broadcast_socket.recvfrom, 1024
                )
                message = data.decode().strip()
                if message.startswith("GPS-UPDATE"):
                    _, sender_addr, lat, lon = message.split()
                    if sender_addr != self._addr:
                        async with self._nodes_location_lock:
                            self._node_locations[sender_addr] = (float(lat), float(lon))
                    if self._verbose:
                        logging.info(f"Received GPS from {addr[0]}: {lat}, {lon}")
            except Exception as e:
                logging.exception(f"Error receiving GPS update: {e}")

    async def _notify_geolocs(self):
        while True:
            await asyncio.sleep(self.update_interval)
            await self._nodes_location_lock.acquire_async()
            geolocs: dict = self._node_locations.copy()
            await self._nodes_location_lock.release_async()
            if geolocs:
                distances = {}
                self_lat, self_long = await self.get_geoloc()
                for addr, (lat, long) in geolocs.items():
                    dist = await self.calculate_distance(self_lat, self_long, lat, long)
                    distances[addr] = (dist, (lat, long))
                
                self._config.update_nodes_distance(distances)
                gpsevent = GPSEvent(distances)
                asyncio.create_task(EventManager.get_instance().publish_addonevent(gpsevent))

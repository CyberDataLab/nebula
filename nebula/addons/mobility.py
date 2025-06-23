import asyncio
import logging
import math
import random
import time
from functools import cached_property

from nebula.addons.functions import print_msg_box
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import ChangeLocationEvent, GPSEvent
from nebula.core.network.communications import CommunicationsManager
from nebula.core.utils.locker import Locker


class Mobility:
    def __init__(self, config, verbose=False):
        """
        Initializes the mobility module with specified configuration and communication manager.

        This method sets up the mobility parameters required for the module, including grace time,
        geographical change interval, mobility type, and other network conditions based on distance.
        It also logs the initialized settings for the mobility system.

        Args:
            config (Config): Configuration object containing mobility parameters and settings.
            cm (CommunicationsManager): An instance of the CommunicationsManager class used for handling
                                         communication-related tasks within the mobility module.

        Attributes:
            grace_time (float): Time allocated for mobility processes to stabilize.
            period (float): Interval at which geographic changes are made.
            mobility (bool): Flag indicating whether mobility is enabled.
            mobility_type (str): Type of mobility strategy to be used (e.g., random, nearest).
            radius_federation (float): Radius for federation in meters.
            scheme_mobility (str): Scheme to be used for managing mobility.
            round_frequency (int): Number of rounds after which mobility changes are applied.
            max_distance_with_direct_connections (float): Maximum distance for direct connections in meters.
            max_movement_random_strategy (float): Maximum movement distance for the random strategy in meters.
            max_movement_nearest_strategy (float): Maximum movement distance for the nearest strategy in meters.
            max_initiate_approximation (float): Maximum distance for initiating approximation calculations.
            network_conditions (dict): A dictionary containing network conditions (bandwidth and delay)
                                       based on distance.
            current_network_conditions (dict): A dictionary mapping addresses to their current network conditions.

        Logs:
            Mobility information upon initialization to provide insights into the current setup.

        Raises:
            KeyError: If the expected mobility configuration keys are not found in the provided config.
        """
        logging.info("Starting mobility module...")
        self.config = config
        self._verbose = verbose
        self._running = asyncio.Event()
        self._nodes_distances = {}
        self._nodes_distances_lock = Locker("nodes_distances_lock", async_lock=True)
        self._mobility_task = None  # Track the background task

        # Mobility configuration
        self.mobility = self.config.participant["mobility_args"]["mobility"]
        self.mobility_type = self.config.participant["mobility_args"]["mobility_type"]
        self.grace_time = self.config.participant["mobility_args"]["grace_time_mobility"]
        self.period = self.config.participant["mobility_args"]["change_geo_interval"]
        # INFO: These values may change according to the needs of the federation
        self.max_distance_with_direct_connections = 150  # meters
        self.max_movement_random_strategy = 50  # meters
        self.max_movement_nearest_strategy = 50  # meters
        self.max_initiate_approximation = self.max_distance_with_direct_connections * 1.2
        self.radius_federation = float(config.participant["mobility_args"]["radius_federation"])
        self.scheme_mobility = config.participant["mobility_args"]["scheme_mobility"]
        self.round_frequency = int(config.participant["mobility_args"]["round_frequency"])
        # Logging box with mobility information
        mobility_msg = f"Mobility: {self.mobility}\nMobility type: {self.mobility_type}\nRadius federation: {self.radius_federation}\nScheme mobility: {self.scheme_mobility}\nEach {self.round_frequency} rounds"
        print_msg_box(msg=mobility_msg, indent=2, title="Mobility information")

    @cached_property
    def cm(self):
        return CommunicationsManager.get_instance()

    # @property
    # def round(self):
    #     """
    #     Gets the current round number from the Communications Manager.

    #     This property retrieves the current round number that is being managed by the
    #     CommunicationsManager instance associated with this module. It provides an
    #     interface to access the ongoing round of the communication process without
    #     directly exposing the underlying method in the CommunicationsManager.

    #     Returns:
    #         int: The current round number managed by the CommunicationsManager.
    #     """
    #     return self.cm.get_round()

    async def start(self):
        """
        Initiates the mobility process by starting the associated task.

        This method creates and schedules an asynchronous task to run the
        `run_mobility` coroutine, which handles the mobility operations
        for the module. It allows the mobility operations to run concurrently
        without blocking the execution of other tasks.

        Returns:
            asyncio.Task: An asyncio Task object representing the scheduled
                           `run_mobility` operation.
        """
        await EventManager.get_instance().subscribe_addonevent(GPSEvent, self.update_nodes_distances)
        await EventManager.get_instance().subscribe_addonevent(GPSEvent, self.update_nodes_distances)
        self._running.set()
        self._mobility_task = asyncio.create_task(self.run_mobility(), name="Mobility_run_mobility")
        return self._mobility_task

    async def stop(self):
        """
        Stops the mobility module.
        """
        logging.info("Stopping Mobility module...")
        self._running.clear()

        # Cancel the background task
        if self._mobility_task and not self._mobility_task.done():
            logging.info("🛑  Cancelling Mobility background task...")
            self._mobility_task.cancel()
            try:
                await self._mobility_task
            except asyncio.CancelledError:
                pass
            self._mobility_task = None
            logging.info("🛑  Mobility background task cancelled")

    async def is_running(self):
        return self._running.is_set()

    async def update_nodes_distances(self, gpsevent: GPSEvent):
        distances = await gpsevent.get_event_data()
        async with self._nodes_distances_lock:
            self._nodes_distances = dict(distances)

    async def run_mobility(self):
        """
        Executes the mobility operations in a continuous loop.

        This coroutine manages the mobility behavior of the module. It first
        checks whether mobility is enabled. If mobility is not enabled, the
        function returns immediately.

        If mobility is enabled, the function will wait for the specified
        grace time before entering an infinite loop where it performs the
        following operations:

        1. Changes the geographical location by calling the `change_geo_location` method.
        2. Adjusts connections based on the current distance by calling
           the `change_connections_based_on_distance` method.
        3. Sleeps for a specified period (`self.period`) before repeating the operations.

        This allows for periodic updates to the module's geographical location
        and network connections as per the defined mobility strategy.

        Raises:
            Exception: May raise exceptions if `change_geo_location` or
                        `change_connections_based_on_distance` encounters errors.
        """
        if not self.mobility:
            return
        # await asyncio.sleep(self.grace_time)
        while await self.is_running():
            await self.change_geo_location()
            await asyncio.sleep(self.period)

    async def change_geo_location_random_strategy(self, latitude, longitude):
        """
        Changes the geographical location of the entity using a random strategy.

        This coroutine modifies the current geographical location by randomly
        selecting a new position within a specified radius around the given
        latitude and longitude. The new location is determined using polar
        coordinates, where a random distance (radius) and angle are calculated.

        Args:
            latitude (float): The current latitude of the entity.
            longitude (float): The current longitude of the entity.

        Raises:
            Exception: May raise exceptions if the `set_geo_location` method encounters errors.

        Notes:
            - The maximum movement distance is determined by `self.max_movement_random_strategy`.
            - The calculated radius is converted from meters to degrees based on an approximate
              conversion factor (1 degree is approximately 111 kilometers).
        """
        if self._verbose:
            logging.info("📍  Changing geo location randomly")
        # radius_in_degrees = self.radius_federation / 111000
        max_radius_in_degrees = self.max_movement_random_strategy / 111000
        radius = random.uniform(0, max_radius_in_degrees)  # noqa: S311
        angle = random.uniform(0, 2 * math.pi)  # noqa: S311
        latitude += radius * math.cos(angle)
        longitude += radius * math.sin(angle)
        await self.set_geo_location(latitude, longitude)

    async def change_geo_location_nearest_neighbor_strategy(
        self, distance, latitude, longitude, neighbor_latitude, neighbor_longitude
    ):
        """
        Changes the geographical location of the entity towards the nearest neighbor.

        This coroutine updates the current geographical location by calculating the direction
        and distance to the nearest neighbor's coordinates. The movement towards the neighbor
        is scaled based on the distance and the maximum movement allowed.

        Args:
            distance (float): The distance to the nearest neighbor.
            latitude (float): The current latitude of the entity.
            longitude (float): The current longitude of the entity.
            neighbor_latitude (float): The latitude of the nearest neighbor.
            neighbor_longitude (float): The longitude of the nearest neighbor.

        Raises:
            Exception: May raise exceptions if the `set_geo_location` method encounters errors.

        Notes:
            - The movement is scaled based on the maximum allowed distance defined by
              `self.max_movement_nearest_strategy`.
            - The angle to the neighbor is calculated using the arctangent of the difference in
              coordinates to determine the direction of movement.
            - The conversion from meters to degrees is based on approximate geographical conversion factors.
        """
        if self._verbose:
            logging.info("📍  Changing geo location towards the nearest neighbor")
        scale_factor = min(1, self.max_movement_nearest_strategy / distance)
        # Calculating angle to the neighbor
        angle = math.atan2(neighbor_longitude - longitude, neighbor_latitude - latitude)
        # Convert maximum movement to angle
        max_lat_change = self.max_movement_nearest_strategy / 111000  # Change degree to latitude
        max_lon_change = self.max_movement_nearest_strategy / (
            111000 * math.cos(math.radians(latitude))
        )  # Change dregree for longitude
        # Scale and direction
        delta_lat = max_lat_change * math.cos(angle) * scale_factor
        delta_lon = max_lon_change * math.sin(angle) * scale_factor
        # Update values
        new_latitude = latitude + delta_lat
        new_longitude = longitude + delta_lon
        await self.set_geo_location(new_latitude, new_longitude)

    async def set_geo_location(self, latitude, longitude):
        """
        Sets the geographical location of the entity to the specified latitude and longitude.

        This coroutine updates the latitude and longitude values in the configuration. If the
        provided coordinates are out of bounds (latitude must be between -90 and 90, and
        longitude must be between -180 and 180), the previous location is retained.

        Args:
            latitude (float): The new latitude to set.
            longitude (float): The new longitude to set.

        Raises:
            None: This function does not raise any exceptions but retains the previous coordinates
                  if the new ones are invalid.

        Notes:
            - The new location is logged for tracking purposes.
            - The coordinates are expected to be in decimal degrees format.
        """

        if latitude < -90 or latitude > 90 or longitude < -180 or longitude > 180:
            # If the new location is out of bounds, we keep the old location
            latitude = self.config.participant["mobility_args"]["latitude"]
            longitude = self.config.participant["mobility_args"]["longitude"]

        self.config.participant["mobility_args"]["latitude"] = latitude
        self.config.participant["mobility_args"]["longitude"] = longitude
        if self._verbose:
            logging.info(f"📍  New geo location: {latitude}, {longitude}")
        cle = ChangeLocationEvent(latitude, longitude)
        asyncio.create_task(EventManager.get_instance().publish_addonevent(cle))

    async def change_geo_location(self):
        """
        Changes the geographical location of the entity based on the current mobility strategy.

        This coroutine checks the mobility type and decides whether to move towards the nearest neighbor
        or change the geo location randomly. It uses the communications manager to obtain the current
        connections and their distances.

        If the number of undirected connections is greater than directed connections, the method will
        attempt to find the nearest neighbor and move towards it if the distance exceeds a certain threshold.
        Otherwise, it will randomly change the geo location.

        Args:
            None: This function does not take any arguments.

        Raises:
            Exception: If the neighbor's location or distance cannot be found.

        Notes:
            - The method expects the mobility type to be either "topology" or "both".
            - It logs actions taken during the execution for tracking and debugging purposes.
        """
        if self.mobility and (self.mobility_type == "topology" or self.mobility_type == "both"):
            random.seed(time.time() + self.config.participant["device_args"]["idx"])
            latitude = float(self.config.participant["mobility_args"]["latitude"])
            longitude = float(self.config.participant["mobility_args"]["longitude"])
            if True:
                # Get neighbor closer to me
                async with self._nodes_distances_lock:
                    sorted_list = sorted(self._nodes_distances.items(), key=lambda item: item[1][0])
                    # Transformamos la lista para obtener solo dirección y coordenadas
                    result = [(addr, dist, coords) for addr, (dist, coords) in sorted_list]

                selected_neighbor = result[0] if result else None
                if selected_neighbor:
                    # logging.info(f"📍  Selected neighbor: {selected_neighbor}")
                    addr, dist, (lat, long) = selected_neighbor
                    if dist > self.max_initiate_approximation:
                        # If the distance is too big, we move towards the neighbor
                        if self._verbose:
                            logging.info(f"Moving towards nearest neighbor: {addr}")
                        await self.change_geo_location_nearest_neighbor_strategy(
                            dist,
                            latitude,
                            longitude,
                            lat,
                            long,
                        )
                    else:
                        await self.change_geo_location_random_strategy(latitude, longitude)
                else:
                    await self.change_geo_location_random_strategy(latitude, longitude)
            else:
                await self.change_geo_location_random_strategy(latitude, longitude)
        else:
            logging.error(f"📍  Mobility type {self.mobility_type} not implemented")
            return

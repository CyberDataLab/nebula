from abc import ABC, abstractmethod


class GPSModule(ABC):
    """
    Abstract base class representing a GPS module interface.

    This class defines the required asynchronous methods that any concrete GPS module implementation must provide.
    These methods allow for lifecycle control (start/stop), status checking, and distance calculation between coordinates.

    Any subclass must implement all the following asynchronous methods:
    - `start()`: Begins GPS tracking or data acquisition.
    - `stop()`: Halts the GPS module's operation.
    - `is_running()`: Checks whether the GPS module is currently active.
    - `calculate_distance()`: Computes the distance between two geographic coordinates (latitude and longitude).

    All implementations should ensure that methods are non-blocking and integrate smoothly with async event loops.
    """

    @abstractmethod
    async def start(self):
        """
        Starts the GPS module operation.

        This may involve initiating hardware tracking, establishing connections, or beginning periodic updates.
        """
        pass

    @abstractmethod
    async def stop(self):
        """
        Stops the GPS module operation.

        Ensures that any background tasks or hardware interactions are properly terminated.
        """
        pass

    @abstractmethod
    async def is_running(self):
        """
        Checks whether the GPS module is currently active.

        Returns:
            bool: True if the module is running, False otherwise.
        """
        pass

    @abstractmethod
    async def calculate_distance(self, self_lat, self_long, other_lat, other_long):
        """
        Calculates the distance between two geographic points.

        Args:
            self_lat (float): Latitude of the source point.
            self_long (float): Longitude of the source point.
            other_lat (float): Latitude of the target point.
            other_long (float): Longitude of the target point.

        Returns:
            float: Distance in meters (or implementation-defined units) between the two coordinates.
        """
        pass


class GPSModuleException(Exception):
    pass


def factory_gpsmodule(gps_module, config, addr, update_interval: float = 5.0, verbose=False) -> GPSModule:
    from nebula.addons.gps.nebulagps import NebulaGPS

    GPS_SERVICES = {
        "nebula": NebulaGPS,
    }

    gps_module = GPS_SERVICES.get(gps_module, NebulaGPS)

    if gps_module:
        return gps_module(config, addr, update_interval, verbose)
    else:
        raise GPSModuleException(f"GPS Module {gps_module} not found")

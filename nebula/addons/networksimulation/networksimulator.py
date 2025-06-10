from abc import ABC, abstractmethod


class NetworkSimulator(ABC):
    """
    Abstract base class representing a network simulator interface.

    This interface defines the required methods for controlling and simulating network conditions between nodes.
    A concrete implementation is expected to manage artificial delays, bandwidth restrictions, packet loss, 
    or other configurable conditions typically used in network emulation or testing.

    Required asynchronous methods:
    - `start()`: Initializes the network simulation module.
    - `stop()`: Shuts down the simulation and cleans up any active conditions.
    - `set_thresholds(thresholds)`: Configures system-wide thresholds (e.g., max/min delay or distance mappings).
    - `set_network_conditions(dest_addr, distance)`: Applies network constraints to a target address based on distance.

    Synchronous method:
    - `clear_network_conditions(interface)`: Clears any simulated network configuration for a given interface.

    All asynchronous methods should be non-blocking to support integration in async systems.
    """

    @abstractmethod
    async def start(self):
        """
        Starts the network simulation module.

        This might involve preparing network interfaces, initializing tools like `tc`, or configuring internal state.
        """
        pass

    @abstractmethod
    async def stop(self):
        """
        Stops the network simulation module.

        Cleans up any modifications made to network interfaces or system configuration.
        """
        pass

    @abstractmethod
    async def set_thresholds(self, thresholds: dict):
        """
        Sets threshold values for simulating conditions.

        Args:
            thresholds (dict): A dictionary specifying condition thresholds,
                               e.g., {'low': 100, 'medium': 200, 'high': 300}, or distance-delay mappings.
        """
        pass

    @abstractmethod
    async def set_network_conditions(self, dest_addr, distance):
        """
        Applies network simulation settings to a given destination based on the computed distance.

        Args:
            dest_addr (str): The address of the destination node (e.g., IP or identifier).
            distance (float): The physical or logical distance used to determine the simulation severity.
        """
        pass

    @abstractmethod
    def clear_network_conditions(self, interface):
        """
        Clears any simulated network conditions applied to the specified network interface.

        Args:
            interface (str): The name of the network interface to restore (e.g., 'eth0').
        """
        pass


class NetworkSimulatorException(Exception):
    pass


def factory_network_simulator(net_sim, changing_interval, interface, verbose) -> NetworkSimulator:
    from nebula.addons.networksimulation.nebulanetworksimulator import NebulaNS

    SIMULATION_SERVICES = {
        "nebula": NebulaNS,
    }

    net_serv = SIMULATION_SERVICES.get(net_sim, NebulaNS)

    if net_serv:
        return net_serv(changing_interval, interface, verbose)
    else:
        raise NetworkSimulatorException(f"Network Simulator {net_sim} not found")

from abc import ABC, abstractmethod


class NetworkSimulator(ABC):
    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def stop(self):
        pass

    @abstractmethod
    async def set_thresholds(self, thresholds: dict):
        pass

    @abstractmethod
    async def set_network_conditions(self, dest_addr, distance):
        pass

    @abstractmethod
    def clear_network_conditions(self, interface):
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

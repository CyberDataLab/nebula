from abc import ABC, abstractmethod


class ExternalConnectionService(ABC):
    """
    Abstract base class for an external connection service in a DFL federation.

    This interface defines the required methods for any service responsible
    for discovering federations and managing beacon signals that announce
    node presence in the network.
    """
    
    @abstractmethod
    async def start(self):
        """
        Start the external connection service.

        This typically involves initializing discovery mechanisms
        and preparing to receive or send messages related to federation discovery.
        """
        pass

    @abstractmethod
    async def stop(self):
        """
        Stop the external connection service.

        This should gracefully shut down any background tasks or sockets
        associated with discovery or beaconing.
        """
        pass

    @abstractmethod
    def is_running(self):
        """
        Check whether the external connection service is currently active.

        Returns:
            bool: True if the service is running, False otherwise.
        """
        pass

    @abstractmethod
    async def find_federation(self):
        """
        Attempt to discover other federations or nodes in the network.

        This method is used by a node to actively search for potential
        neighbors to join a federation or to bootstrap its own.
        """
        pass

    @abstractmethod
    async def start_beacon(self):
        """
        Start periodically sending beacon messages to announce node presence.

        Beacon messages help other nodes detect and identify this node's
        existence and availability on the network.
        """
        pass

    @abstractmethod
    async def stop_beacon(self):
        """
        Stop sending beacon messages.

        This disables periodic presence announcements, making the node
        temporarily invisible to passive discovery.
        """
        pass

    @abstractmethod
    async def modify_beacon_frequency(self, frequency):
        """
        Modify the frequency at which beacon messages are sent.

        Args:
            frequency (float): New beacon interval in seconds.
        """
        pass


class ExternalConnectionServiceException(Exception):
    """
    Exception raised for errors related to external connection services.
    """
    pass


def factory_connection_service(con_serv, addr) -> ExternalConnectionService:
    """
    Factory method to instantiate the appropriate external connection service.

    Args:
        con_serv (str): Identifier of the connection service to use.
        addr (str): Address of the node.

    Returns:
        ExternalConnectionService: An instance of the requested service.

    Raises:
        ExternalConnectionServiceException: If the service identifier is not recognized.
    """
    from nebula.core.network.externalconnection.nebuladiscoveryservice import NebulaConnectionService

    CONNECTION_SERVICES = {
        "nebula": NebulaConnectionService,
    }

    con_serv = CONNECTION_SERVICES.get(con_serv, NebulaConnectionService)

    if con_serv:
        return con_serv(addr)
    else:
        raise ExternalConnectionServiceException(f"Connection Service {con_serv} not found")

from abc import ABC, abstractmethod

from nebula.addons.functions import print_msg_box


class ISADiscovery(ABC):
    """
    Interface for Situational Awareness discovery components.

    Defines methods for initializing discovery, handling late connection processes,
    and retrieving training-related information.
    """
    
    @abstractmethod
    async def init(self, sa_reasoner):
        """
        Initialize the discovery component with a corresponding reasoner.

        Args:
            sa_reasoner (ISAReasoner): The reasoner instance to coordinate with.
        """
        raise NotImplementedError

    @abstractmethod
    async def start_late_connection_process(self, connected=False, msg_type="discover_join", addrs_known=None):
        """
        Begin the late-connection discovery process for situational awareness.

        Args:
            connected (bool, optional): Whether the node is already connected. Defaults to False.
            msg_type (str, optional): Type of discovery message to send. Defaults to "discover_join".
            addrs_known (list, optional): Known addresses to use instead of active discovery.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_trainning_info(self):
        """
        Retrieve information necessary for training initialization.

        Returns:
            Any: Training information produced by the discovery component.
        """
        raise NotImplementedError


class ISAReasoner(ABC):
    """
    Interface for Situational Awareness reasoning components.

    Defines methods for initializing the reasoner, accepting or rejecting connections,
    and querying known nodes and available actions.
    """
    
    @abstractmethod
    async def init(self, sa_discovery):
        """
        Initialize the reasoner with a corresponding discovery component.

        Args:
            sa_discovery (ISADiscovery): The discovery instance to coordinate with.
        """
        raise NotImplementedError

    @abstractmethod
    async def accept_connection(self, source, joining=False):
        """
        Decide whether to accept a connection from a given source node.

        Args:
            source (str): The address or identifier of the requesting node.
            joining (bool, optional): Whether the connection is part of a join process. Defaults to False.
        """
        raise NotImplementedError

    @abstractmethod
    def get_nodes_known(self, neighbors_too=False, neighbors_only=False):
        """
        Get the set of nodes known to the reasoner.

        Args:
            neighbors_too (bool, optional): Include neighbors in the result. Defaults to False.
            neighbors_only (bool, optional): Return only neighbors. Defaults to False.

        Returns:
            set: Identifiers of known nodes based on the provided filters.
        """
        raise NotImplementedError

    @abstractmethod
    def get_actions(self):
        """
        Get the list of situational awareness actions the reasoner can perform in
        response to late connections process.

        Returns:
            list: Available action identifiers.
        """
        raise NotImplementedError


def factory_sa_discovery(sa_discovery, additional, selector, model_handler, engine, verbose) -> ISADiscovery:
    """
    Factory function to create an ISADiscovery implementation.

    Args:
        sa_discovery (str): Identifier of the discovery backend (e.g., "nebula").
        additional (bool): Additional status of the node.
        selector (str): Candidate selector strategy name.
        model_handler (str): Model handler strategy name.
        engine (Engine): Reference to the engine.
        verbose (bool): Enable verbose logging or output.

    Returns:
        ISADiscovery: An instance of the requested discovery implementation.

    Raises:
        Exception: If the specified discovery service identifier is not found.
    """
    from nebula.core.situationalawareness.discovery.federationconnector import FederationConnector

    DISCOVERY = {
        "nebula": FederationConnector,
    }
    sad = DISCOVERY.get(sa_discovery)
    if sad:
        return sad(additional, selector, model_handler, engine, verbose)
    else:
        raise Exception(f"SA Discovery service {sa_discovery} not found.")


def factory_sa_reasoner(sa_reasoner, config) -> ISAReasoner:
    """
    Factory function to create an ISAReasoner implementation.

    Args:
        sa_reasoner (str): Identifier of the reasoner backend (e.g., "nebula").
        config (Config): The configuration object for initializing the reasoner.

    Returns:
        ISAReasoner: An instance of the requested reasoner implementation.

    Raises:
        Exception: If the specified reasoner service identifier is not found.
    """
    from nebula.core.situationalawareness.awareness.sareasoner import SAReasoner

    REASONER = {
        "nebula": SAReasoner,
    }
    sar = REASONER.get(sa_reasoner)
    if sar:
        return sar(config)
    else:
        raise Exception(f"SA Reasoner service {sa_reasoner} not found.")


class SituationalAwareness:
    """
    High-level coordinator for Situational Awareness in the DFL federation.

    Manages discovery and reasoning components, wiring them together
    and exposing simple methods for initialization and late-connection handling.
    """
    
    def __init__(self, config, engine):
        """
        Initialize Situational Awareness module by creating discovery and reasoner instances.

        Args:
            config (Config): Configuration containing situational awareness settings.
            engine (Engine): The core engine of the federation for coordination.
        """
        print_msg_box(
            msg="Starting Situational Awareness module...",
            indent=2,
            title="Situational Awareness module",
        )
        self._config = config
        selector = self._config.participant["situational_awareness"]["sa_discovery"]["candidate_selector"]
        selector = selector.lower()
        model_handler = config.participant["situational_awareness"]["sa_discovery"]["model_handler"]
        self._sad = factory_sa_discovery(
            "nebula",
            self._config.participant["mobility_args"]["additional_node"]["status"],
            selector,
            model_handler,
            engine=engine,
            verbose=config.participant["situational_awareness"]["sa_discovery"]["verbose"],
        )
        self._sareasoner = factory_sa_reasoner(
            "nebula",
            self._config,
        )

    @property
    def sad(self):
        """
        Access the Situational Awareness discovery component.

        Returns:
            ISADiscovery: The discovery instance.
        """
        return self._sad

    @property
    def sar(self):
        """
        Access the Situational Awareness reasoner component.

        Returns:
            ISAReasoner: The reasoner instance.
        """
        return self._sareasoner

    async def init(self):
        """
        Initialize both discovery and reasoner components, linking them together.
        """
        await self.sad.init(self.sar)
        await self.sar.init(self.sad)

    async def start_late_connection_process(self):
        """
        Start the late-connection process via the discovery component.
        """
        await self.sad.start_late_connection_process()

    async def get_trainning_info(self):
        """
        Retrieve training information from the discovery component.

        Returns:
            Any: Information relevant to training decisions.
        """
        return await self.sad.get_trainning_info()

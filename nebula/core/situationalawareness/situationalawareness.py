from abc import ABC, abstractmethod

from nebula.addons.functions import print_msg_box


class ISADiscovery(ABC):
    @abstractmethod
    async def init(self, sa_reasoner):
        raise NotImplementedError

    @abstractmethod
    async def start_late_connection_process(self, connected=False, msg_type="discover_join", addrs_known=None):
        raise NotImplementedError

    @abstractmethod
    async def get_trainning_info(self):
        raise NotImplementedError


class ISAReasoner(ABC):
    @abstractmethod
    async def init(self, sa_discovery):
        raise NotImplementedError

    @abstractmethod
    async def accept_connection(self, source, joining=False):
        raise NotImplementedError

    @abstractmethod
    def get_nodes_known(self, neighbors_too=False, neighbors_only=False):
        raise NotImplementedError

    @abstractmethod
    def get_actions(self):
        raise NotImplementedError


def factory_sa_discovery(sa_discovery, additional, selector, model_handler, engine, verbose) -> ISADiscovery:
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
    def __init__(self, config, engine):
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
        """SA Discovery"""
        return self._sad

    @property
    def sar(self):
        """SA Reasoner"""
        return self._sareasoner

    async def init(self):
        await self.sad.init(self.sar)
        await self.sar.init(self.sad)

    async def start_late_connection_process(self):
        await self.sad.start_late_connection_process()

    async def get_trainning_info(self):
        return await self.sad.get_trainning_info()

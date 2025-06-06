from nebula.core.situationalawareness.discovery.federationconnector import FederationConnector
from nebula.core.situationalawareness.discovery.modelhandlers.modelhandler import ModelHandler
from nebula.core.utils.locker import Locker


class DefaultModelHandler(ModelHandler):
    """
    Provides the initial default model.

    This handler returns the baseline model with default weights, 
    typically used at the start of the federation or when no suitable 
    model offers have been received from peers.

    Inherits from:
        ModelHandler: Provides the base interface for model operations.
    """
    
    def __init__(self):
        self.model = None
        self.rounds = 0
        self.round = 0
        self.epochs = 0
        self.model_lock = Locker(name="model_lock")
        self.params_lock = Locker(name="param_lock")
        self._nm: FederationConnector = None

    def set_config(self, config):
        """
        Args:
            config[0] -> total rounds
            config[1] -> current round
            config[2] -> epochs
            config[3] -> FederationConnector
        """
        self.params_lock.acquire()
        self.rounds = config[0]
        if config[1] > self.round:
            self.round = config[1]
        self.epochs = config[2]
        if not self._nm:
            self._nm = config[3]
        self.params_lock.release()

    def accept_model(self, model):
        return True

    async def get_model(self, model):
        """
        Returns:
            model with default weights
        """
        (sm, _, _) = await self._nm.engine.cm.propagator.get_model_information(None, "initialization", init=True)
        return (sm, self.rounds, self.round, self.epochs)

    def pre_process_model(self):
        """
        no pre-processing defined
        """
        pass

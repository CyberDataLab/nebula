from nebula.core.situationalawareness.discovery.modelhandlers.modelhandler import ModelHandler
from nebula.core.utils.locker import Locker


class STDModelHandler(ModelHandler):
    def __init__(self):
        self.model = None
        self.rounds = 0
        self.round = 0
        self.epochs = 0
        self.model_lock = Locker(name="model_lock")
        self.params_lock = Locker(name="param_lock")

    def set_config(self, config):
        """
        Args:
            config[0] -> total rounds
            config[1] -> current round
            config[2] -> epochs
        """
        self.params_lock.acquire()
        self.rounds = config[0]
        if config[1] > self.round:
            self.round = config[1]
        self.epochs = config[2]
        self.params_lock.release()

    def accept_model(self, model):
        """
        save only first model received to set up own model later
        """
        if not self.model_lock.locked():
            self.model_lock.acquire()
            self.model = model
        return True

    async def get_model(self, model):
        """
        Returns:
            neccesary data to create trainer
        """
        if self.model is not None:
            return (self.model, self.rounds, self.round, self.epochs)
        else:
            return (None, 0, 0, 0)

    def pre_process_model(self):
        """
        no pre-processing defined
        """
        pass

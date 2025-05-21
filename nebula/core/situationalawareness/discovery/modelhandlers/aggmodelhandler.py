from nebula.core.situationalawareness.discovery.modelhandlers.modelhandler import ModelHandler
from nebula.core.utils.locker import Locker


class AGGModelHandler(ModelHandler):
    def __init__(self):
        self.model = None
        self.rounds = 0
        self.round = 0
        self.epochs = 1
        self.model_list = []
        self.models_lock = Locker(name="model_lock")
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
            self.round = config[0]
        self.epochs = config[2]
        self.params_lock.release()

    def accept_model(self, model):
        """
        Save first model receive and collect the rest for pre-processing
        """
        self.models_lock.acquire()
        if self.model is None:
            self.model = model
        else:
            self.model_list.append(model)
        self.models_lock.release()

    def get_model(self, model):
        """
        Returns:
            neccesary data to create trainer after pre-processing
        """
        self.models_lock.acquire()
        self.pre_process_model()
        self.models_lock.release()
        return (self.model, self.rounds, self.round, self.epochs)

    def pre_process_model(self):
        # define pre-processing strategy
        pass

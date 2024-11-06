import logging
import pickle
import traceback

from sklearn.metrics import accuracy_score


class Scikit:
    def __init__(self, model, data, config=None, logger=None):
        self.model = model
        self.data = data
        self.config = config
        self.logger = logger
        self.round = 0
        self.epochs = 1
        self.logger.log_data({"Round": self.round}, step=self.logger.global_step)

    def set_model(self, model):
        self.model = model

    def get_round(self):
        return self.round

    def set_data(self, data):
        self.data = data

    def serialize_model(self, params=None):
        if params is None:
            params = self.model.get_params()
        return pickle.dumps(params)

    def deserialize_model(self, data):
        try:
            params = pickle.loads(data)
            return params
        except:
            raise Exception("Error decoding parameters")

    def set_model_parameters(self, params):
        self.model.set_params(**params)

    def get_model_parameters(self):
        return self.model.get_params()

    def set_epochs(self, epochs):
        self.epochs = epochs

    def fit(self):
        try:
            X_train, y_train = self.data.train_dataloader()
            self.model.fit(X_train, y_train)
        except Exception as e:
            logging.exception(f"Error with scikit-learn fit. {e}")
            logging.exception(traceback.format_exc())

    def interrupt_fit(self):
        pass

    def evaluate(self):
        try:
            X_test, y_test = self.data.test_dataloader()
            y_pred = self.model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            logging.info(f"Accuracy: {accuracy}")
        except Exception as e:
            logging.exception(f"Error with scikit-learn evaluate. {e}")
            logging.exception(traceback.format_exc())
            return None

    def get_train_size(self):
        return (
            len(self.data.train_dataloader()),
            len(self.data.test_dataloader()),
        )

    def finalize_round(self):
        self.round += 1
        if self.logger:
            self.logger.log_data({"Round": self.round})

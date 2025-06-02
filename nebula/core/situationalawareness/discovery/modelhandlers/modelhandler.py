from abc import ABC, abstractmethod


class ModelHandler(ABC):
    @abstractmethod
    def set_config(self, config):
        """
        Configure internal settings for the model handler using the provided configuration.

        Parameters:
            config: A configuration object or dictionary with parameters relevant to model handling.
        """
        pass

    @abstractmethod
    def accept_model(self, model):
        """
        Evaluate and store a received model if it satisfies the required criteria.

        Parameters:
            model: The model object to be processed or stored.

        Returns:
            bool: True if the model is accepted, False otherwise.
        """
        pass

    @abstractmethod
    async def get_model(self, model):
        """
        Asynchronously retrieve or generate the model to be used.

        Parameters:
            model: A reference to the kind of model to be used.

        Returns:
            object: The model instance requested.
        """
        pass

    @abstractmethod
    def pre_process_model(self):
        """
        Perform any necessary preprocessing steps on the model before it is used.

        Returns:
            object: The preprocessed model, ready for further operations.
        """
        pass


def factory_ModelHandler(model_handler) -> ModelHandler:
    from nebula.core.situationalawareness.discovery.modelhandlers.aggmodelhandler import AGGModelHandler
    from nebula.core.situationalawareness.discovery.modelhandlers.defaultmodelhandler import DefaultModelHandler
    from nebula.core.situationalawareness.discovery.modelhandlers.stdmodelhandler import STDModelHandler

    options = {
        "std": STDModelHandler,
        "default": DefaultModelHandler,
        "aggregator": AGGModelHandler,
    }

    cs = options.get(model_handler, STDModelHandler)
    return cs()

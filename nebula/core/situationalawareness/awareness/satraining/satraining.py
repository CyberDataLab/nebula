import asyncio
import logging
from nebula.core.utils.locker import Locker
from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.trainingpolicy import factory_training_policy
from nebula.core.situationalawareness.awareness.sareasoner import SAMComponent
from nebula.addons.functions import print_msg_box
from nebula.core.situationalawareness.awareness.sareasoner import SAReasoner, SAMComponent
from nebula.core.eventmanager import EventManager
    
RESTRUCTURE_COOLDOWN = 5    
    
class SATraining(SAMComponent):
    """
    SATraining is a Situational Awareness (SA) component responsible for enhancing
    the training process in Distributed Federated Learning (DFL) environments
    by leveraging context-awareness and environmental knowledge.

    This component dynamically instantiates a training policy based on the configuration,
    allowing the system to adapt training strategies depending on the local topology,
    node behavior, or environmental constraints.

    Attributes:
        _config (dict): Configuration dictionary containing parameters and references.
        _sar (SAReasoner): Reference to the shared situational reasoner.
        _trainning_policy: Instantiated training policy strategy.
    """
    
    def __init__(self, config):
        """
        Initialize the SATraining component with a given configuration.

        Args:
            config (dict): Configuration dictionary containing:
                - 'addr': Node address.
                - 'verbose': Verbosity flag.
                - 'sar': Reference to the SAReasoner instance.
                - 'training_policy': Training policy name to be used.
        """
        print_msg_box(
            msg=f"Starting Training SA\nTraining policy: {config['training_policy']}",
            indent=2,
            title="Training SA module",
        )
        self._config = config
        self._sar: SAReasoner = self._config["sar"]
        tp_config = {}
        tp_config["addr"] = self._config["addr"]
        tp_config["verbose"] = self._config["verbose"]
        training_policy = self._config["training_policy"]
        self._trainning_policy = factory_training_policy(training_policy, tp_config)

    @property
    def sar(self):
        """
        Returns the current instance of the SAReasoner.
        """
        return self._sar

    @property
    def tp(self):
        """
        Returns the currently active training policy instance.
        """
        return self._trainning_policy    

    async def init(self):
        """
        Initialize the training policy with the current known neighbors from the SAReasoner.
        This setup enables the policy to make informed decisions based on local topology.
        """
        config = {}
        config["nodes"] = set(await self.sar.get_nodes_known(neighbors_only=True)) 
        await self.tp.init(config)

    async def sa_component_actions(self):
        """
        Periodically called action of the SA component to evaluate the current scenario.
        This invokes the evaluation logic defined in the training policy to adapt behavior.
        """
        logging.info("SA Trainng evaluating current scenario")
        asyncio.create_task(self.tp.get_evaluation_results())


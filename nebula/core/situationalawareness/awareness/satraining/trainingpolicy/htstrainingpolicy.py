from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.trainingpolicy import TrainingPolicy
from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.trainingpolicy import factory_training_policy
from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.trainingpolicy import TrainingPolicy
import logging

# "Hybrid Training Strategy"    (HTS)
class HTSTrainingPolicy(TrainingPolicy):
    """
    Implements a Hybrid Training Strategy (HTS) that combines multiple training policies 
    (e.g., QDS, FRTS) to collaboratively decide on the evaluation and potential pruning 
    of neighbors in a decentralized federated learning scenario.
    
    Attributes:
        TRAINING_POLICY (set): Names of training policy classes to instantiate and manage.
    """
    
    TRAINING_POLICY = {
        "Quality-Driven Selection",
        "Fast Reboot Training Strategy",
    }
    
    def __init__(self, config):
        """
        Initializes the HTS policy with the node's address and verbosity level.
        It creates instances of each sub-policy listed in TRAINING_POLICY.

        Args:
            config (dict): Configuration dictionary with keys:
                - 'addr': Node's address
                - 'verbose': Enable verbose logging
        """
        self._addr = config["addr"]
        self._verbose = config["verbose"]
        self._training_policies : set[TrainingPolicy] = set()
        self._training_policies.add([factory_training_policy(x, config) for x in self.TRAINING_POLICY])
        
    def __str__(self):
        return "HTS"    
        
    @property
    def tps(self):
        return self._training_policies  

    async def init(self, config):
        for tp in self.tps:
            await tp.init(config)    

    async def update_neighbors(self, node, remove=False):
        pass
    
    async def get_evaluation_results(self):
        """
        Asynchronously calls the `get_evaluation_results` of each policy,
        and logs the nodes each policy would remove.
        
        Returns:
            None (future version may merge all evaluations).
        """
        nodes_to_remove = dict()
        for tp in self.tps:
            nodes_to_remove[tp] = await tp.get_evaluation_results()
        
        for tp, nodes in nodes_to_remove.items():
            logging.info(f"Training Policy: {tp}, nodes to remove: {nodes}")
            
        return None
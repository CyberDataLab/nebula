from abc import ABC, abstractmethod
from nebula.core.situationalawareness.awareness.sautils.samoduleagent import SAModuleAgent

class TrainingPolicy(SAModuleAgent):
    
    @abstractmethod
    async def init(self, config):
        pass

    @abstractmethod
    async def get_evaluation_results(self):
        pass
    
    
def factory_training_policy(training_policy, config) -> TrainingPolicy:
    from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.bpstrainingpolicy import BPSTrainingPolicy
    from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.qdstrainingpolicy import QDSTrainingPolicy
    from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.htstrainingpolicy import HTSTrainingPolicy
    from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.fastreboot import FastReboot
    
    options = {
        "Broad-Propagation Strategy": BPSTrainingPolicy,   # "Broad-Propagation Strategy"  (BPS) -- default value
        "Quality-Driven Selection": QDSTrainingPolicy,   # "Quality-Driven Selection"    (QDS)
        "Hybrid Training Strategy": HTSTrainingPolicy,   # "Hybrid Training Strategy"    (HTS)
        "Fast Reboot Training Strategy": FastReboot,         # "Fast Reboot Training Strategy" (FRTS)
    } 
    
    cs = options.get(training_policy, BPSTrainingPolicy)
    return cs(config)
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
from nebula.kafka.clients.messages.experiment import ExperimentMessages, MESSAGE_CLASSES_EXPERIMENT

def factory_experiment_message(message: ExperimentMessages, **kwargs) -> KafkaMessage | None:
    cls = MESSAGE_CLASSES_EXPERIMENT.get(message, None)
    if not cls:
        return None
    
    return cls(**kwargs)
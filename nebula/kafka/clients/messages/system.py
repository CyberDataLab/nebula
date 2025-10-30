from enum import Enum
from typing import Dict, Type
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
import json

NEBULA_SYSTEM_TOPIC = "nebula-system-control"

class SystemMessages(Enum):
    AGENT_READY = 1
    EXPERIMENT_FINISH = 2
    
class AgentReadyMessage(KafkaMessage):
    kafka_message: str = SystemMessages.AGENT_READY.name
    
    def __init__(self, data: str):
        self.agent = data
        
    def to_bytes(self) -> bytes:
        """Serialize UpdateMessage to bytes"""
        return json.dumps({
            "kafka-message": self.kafka_message,
            "data": self.agent
        }).encode()

    @classmethod
    def from_bytes(cls, raw_bytes: bytes):
        """Deserialize bytes to UpdateMessage"""
        data = json.loads(raw_bytes.decode())
        return cls(data=data["data"])   
    
class FinishExperimentMessage(KafkaMessage):
    kafka_message: str = SystemMessages.EXPERIMENT_FINISH.name
    
    def __init__(self, data: str):
        self.experiment = data
        
    def to_bytes(self) -> bytes:
        """Serialize UpdateMessage to bytes"""
        return json.dumps({
            "kafka-message": self.kafka_message,
            "data": self.experiment
        }).encode()

    @classmethod
    def from_bytes(cls, raw_bytes: bytes):
        """Deserialize bytes to UpdateMessage"""
        data = json.loads(raw_bytes.decode())
        return cls(data=data["data"])   
    
MESSAGE_CLASSES_SYSTEM: Dict[SystemMessages, Type[KafkaMessage]] = {
    SystemMessages.AGENT_READY: AgentReadyMessage,
    SystemMessages.EXPERIMENT_FINISH: FinishExperimentMessage,
}
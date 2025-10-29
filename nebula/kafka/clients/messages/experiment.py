from enum import Enum
from typing import Dict, Type
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
import json

class ExperimentMessages(Enum):
    UPDATE = 1
    DONE = 2
    METRICS = 3
        
class UpdateMessage(KafkaMessage):
    kafka_message: str = ExperimentMessages.UPDATE.name
    
    def __init__(self, data: dict):
        self.config = data
        
    def to_bytes(self) -> bytes:
        """Serialize UpdateMessage to bytes"""
        return json.dumps({
            "kafka-message": self.kafka_message,
            "data": self.config
        }).encode()

    @classmethod
    def from_bytes(cls, raw_bytes: bytes):
        """Deserialize bytes to UpdateMessage"""
        data = json.loads(raw_bytes.decode())
        return cls(data=data["data"])
    
class DoneMessage(KafkaMessage):
    kafka_message: str = ExperimentMessages.DONE.name
    
    def __init__(self, data: str):
        self.idx = data
        
    def to_bytes(self) -> bytes:
        """Serialize UpdateMessage to bytes"""
        return json.dumps({
            "kafka-message": self.kafka_message,
            "data": self.idx
        }).encode()

    @classmethod
    def from_bytes(cls, raw_bytes: bytes):
        """Deserialize bytes to UpdateMessage"""
        data = json.loads(raw_bytes.decode())
        return cls(data=data["data"])
    
MESSAGE_CLASSES_EXPERIMENT: Dict[ExperimentMessages, Type[KafkaMessage]] = {
    ExperimentMessages.UPDATE: UpdateMessage,
    ExperimentMessages.DONE: DoneMessage,
}
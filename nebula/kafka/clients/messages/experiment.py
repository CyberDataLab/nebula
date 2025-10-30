from enum import Enum
from typing import Dict, Type
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
import json

class ExperimentMessages(Enum):
    INIT = 1
    UPDATE = 2
    DONE = 3
    METRICS = 4 #events.out.tfevents.1758626399.da5deb2691ce.1.0
    
class ExperimentINITMessage(KafkaMessage):
    kafka_message: str = ExperimentMessages.INIT.name
    
    def __init__(self, data: str):
        self.experiment_id = data
        
    def to_bytes(self) -> bytes:
        """Serialize UpdateMessage to bytes"""
        return json.dumps({
            "kafka-message": self.kafka_message,
            "data": self.experiment_id
        }).encode()

    @classmethod
    def from_bytes(cls, raw_bytes: bytes):
        """Deserialize bytes to UpdateMessage"""
        data = json.loads(raw_bytes.decode())
        return cls(data=data["data"])    
        
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
    ExperimentMessages.INIT: ExperimentINITMessage,
    ExperimentMessages.UPDATE: UpdateMessage,
    ExperimentMessages.DONE: DoneMessage,
}
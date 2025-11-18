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

    def __init__(self, experiment_id: str, experiment_type: str, data: dict):
        self.experiment_id = experiment_id
        self.experiment_type = experiment_type
        self.config = data

    def to_bytes(self) -> bytes:
        """Serialize UpdateMessage to bytes"""
        return json.dumps({
            "kafka-message": self.kafka_message,
            "experiment_id": self.experiment_id,
            "experiment_type": self.experiment_type,
            "data": self.config
        }).encode()

    @classmethod
    def from_bytes(cls, raw_bytes: bytes):
        """Deserialize bytes to UpdateMessage"""
        data = json.loads(raw_bytes.decode())
        return cls(experiment_id=data["experiment_id"],  experiment_type=data["experiment_type"], data=data["data"])

class DoneMessage(KafkaMessage):
    kafka_message: str = ExperimentMessages.DONE.name

    def __init__(self, experiment_id: str, experiment_type: str, idx: str):
        self.experiment_id = experiment_id
        self.experiment_type = experiment_type
        self.idx = idx

    def to_bytes(self) -> bytes:
        """Serialize UpdateMessage to bytes"""
        return json.dumps({
            "kafka-message": self.kafka_message,
            "experiment_id": self.experiment_id,
            "experiment_type": self.experiment_type,
            "idx": self.idx
        }).encode()

    @classmethod
    def from_bytes(cls, raw_bytes: bytes):
        """Deserialize bytes to UpdateMessage"""
        data = json.loads(raw_bytes.decode())
        return cls(experiment_id=data["experiment_id"], experiment_type=data["experiment_type"], idx=data["idx"])

class METRICSMessage(KafkaMessage):
    kafka_message: str = ExperimentMessages.METRICS.name

    def __init__(self, experiment_id: str, end_time: float, iteration: int, metrics: dict):
        self.experiment_id = experiment_id
        self.end_time = end_time
        self.iteration = iteration
        self.metrics = metrics

    def to_bytes(self) -> bytes:
        """Serialize metrics message to bytes"""
        return json.dumps({
            "kafka-message": self.kafka_message,
            "experiment_id": self.experiment_id,
            "end_time": self.end_time,
            "iteration": self.iteration,
            "metrics": self.metrics,
        }).encode()

    @classmethod
    def from_bytes(cls, raw_bytes: bytes):
        """Deserialize bytes to message"""
        data = json.loads(raw_bytes.decode())
        return cls(
            experiment_id=data["experiment_id"],
            end_time=data["end_time"],
            iteration=data["iteration"],
            metrics=data["metrics"]
        )

MESSAGE_CLASSES_EXPERIMENT: Dict[ExperimentMessages, Type[KafkaMessage]] = {
    ExperimentMessages.INIT: ExperimentINITMessage,
    ExperimentMessages.UPDATE: UpdateMessage,
    ExperimentMessages.DONE: DoneMessage,
    ExperimentMessages.METRICS: METRICSMessage,
}

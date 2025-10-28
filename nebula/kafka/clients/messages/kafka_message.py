from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class KafkaMessage(ABC):
    kafka_message: str

    @abstractmethod
    def to_bytes(self) -> bytes:
        """Serialize KafkaMessage to bytes"""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_bytes(cls, raw_bytes: bytes):
        """Deserialize bytes to KafkaMessage"""
        raise NotImplementedError
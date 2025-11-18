import json
from typing import Type, Union
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
from nebula.kafka.clients.messages.experiment import ExperimentMessages, MESSAGE_CLASSES_EXPERIMENT
from nebula.kafka.clients.messages.system import SystemMessages, MESSAGE_CLASSES_SYSTEM

_MESSAGE_REGISTRY = {
    ExperimentMessages: MESSAGE_CLASSES_EXPERIMENT,
    SystemMessages: MESSAGE_CLASSES_SYSTEM,
}

def factory_kafka_message(
    message_type: Union[SystemMessages, ExperimentMessages],
    **kwargs
) -> KafkaMessage | None:
    for enum_type, registry in _MESSAGE_REGISTRY.items():
        if isinstance(message_type, enum_type):
            cls: Type[KafkaMessage] = registry.get(message_type)
            if cls:
                return cls(**kwargs)
            return None
    raise ValueError(f"Unknown message type: {message_type}")

def parse_kafka_message(raw_bytes) -> KafkaMessage | None:
    cls = None
    data = json.loads(raw_bytes.decode("utf-8"))
    msg_type_str = data.get("kafka-message", None)
    if not msg_type_str:
        raise ValueError("Missing 'kafka-message' field in payload")

    for enum_type, registry in _MESSAGE_REGISTRY.items():
        if msg_type_str in enum_type.__members__:
            msg_type = enum_type[msg_type_str]
            cls: Type[KafkaMessage] = registry.get(msg_type)
            break
    else:
        raise ValueError(f"Unknown kafka-message type: '{msg_type_str}'")

    if not cls:
        raise ValueError(f"No registered class for message type: '{msg_type_str}'")
    return cls.from_bytes(raw_bytes)

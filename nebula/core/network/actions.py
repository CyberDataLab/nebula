from nebula.core.pb import nebula_pb2
from enum import Enum
import logging


class ConnectionAction(Enum):
    CONNECT = nebula_pb2.ConnectionMessage.Action.CONNECT
    DISCONNECT = nebula_pb2.ConnectionMessage.Action.DISCONNECT

class FederationAction(Enum):
    FEDERATION_START = nebula_pb2.FederationMessage.Action.FEDERATION_START
    REPUTATION = nebula_pb2.FederationMessage.Action.REPUTATION
    FEDERATION_MODELS_INCLUDED = nebula_pb2.FederationMessage.Action.FEDERATION_MODELS_INCLUDED
    FEDERATION_READY = nebula_pb2.FederationMessage.Action.FEDERATION_READY

class DiscoveryAction(Enum):
    DISCOVER = nebula_pb2.DiscoveryMessage.Action.DISCOVER
    REGISTER = nebula_pb2.DiscoveryMessage.Action.REGISTER
    DEREGISTER = nebula_pb2.DiscoveryMessage.Action.DEREGISTER

class ControlAction(Enum):
    ALIVE = nebula_pb2.ControlMessage.Action.ALIVE
    OVERHEAD = nebula_pb2.ControlMessage.Action.OVERHEAD
    MOBILITY = nebula_pb2.ControlMessage.Action.MOBILITY
    RECOVERY = nebula_pb2.ControlMessage.Action.RECOVERY
    WEAK_LINK = nebula_pb2.ControlMessage.Action.WEAK_LINK

ACTION_CLASSES = {
    "connection": ConnectionAction,
    "federation": FederationAction,
    "discovery": DiscoveryAction,
    "control": ControlAction,
}

def get_action_name_from_value(message_type: str, action_value: int) -> str:
    # Obtener el Enum correspondiente al tipo de mensaje
    enum_class = ACTION_CLASSES.get(message_type)
    if not enum_class:
        raise ValueError(f"Unknown message type: {message_type}")

    # Buscar el nombre de la acción a partir del valor
    for action in enum_class:
        if action.value == action_value:
            return action.name.lower()  # Convertimos a lowercase para mantener el formato "late_connect"

    raise ValueError(f"Unknown action value {action_value} for message type {message_type}")

def get_actions_names(message_type: str):
    message_actions = ACTION_CLASSES.get(message_type)
    if not message_actions:
        raise ValueError(f"Invalid message type: {message_type}")

    return [action.name.lower() for action in message_actions]

def factory_message_action(message_type: str, action: str):
    message_actions = ACTION_CLASSES.get(message_type, None)

    if message_actions:
        normalized_action = action.upper()
        enum_action = message_actions[normalized_action]
        #logging.info(f"Message action: {enum_action}, value: {enum_action.value}")
        return enum_action.value
    else:
        return None



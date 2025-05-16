from enum import Enum

from nebula.core.pb import nebula_pb2


class ConnectionAction(Enum):
    CONNECT = nebula_pb2.ConnectionMessage.Action.CONNECT
    DISCONNECT = nebula_pb2.ConnectionMessage.Action.DISCONNECT
    LATE_CONNECT = nebula_pb2.ConnectionMessage.Action.LATE_CONNECT
    RESTRUCTURE = nebula_pb2.ConnectionMessage.Action.RESTRUCTURE


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


class DiscoverAction(Enum):
    DISCOVER_JOIN = nebula_pb2.DiscoverMessage.Action.DISCOVER_JOIN
    DISCOVER_NODES = nebula_pb2.DiscoverMessage.Action.DISCOVER_NODES


class OfferAction(Enum):
    OFFER_MODEL = nebula_pb2.OfferMessage.Action.OFFER_MODEL
    OFFER_METRIC = nebula_pb2.OfferMessage.Action.OFFER_METRIC


class LinkAction(Enum):
    CONNECT_TO = nebula_pb2.LinkMessage.Action.CONNECT_TO
    DISCONNECT_FROM = nebula_pb2.LinkMessage.Action.DISCONNECT_FROM


class ReputationAction(Enum):
    SHARE = nebula_pb2.ReputationMessage.Action.SHARE


ACTION_CLASSES = {
    "connection": ConnectionAction,
    "federation": FederationAction,
    "discovery": DiscoveryAction,
    "control": ControlAction,
    "discover": DiscoverAction,
    "offer": OfferAction,
    "link": LinkAction,
    "reputation": ReputationAction,
}


def get_action_name_from_value(message_type: str, action_value: int) -> str:
    # Get the Enum corresponding to the message type
    enum_class = ACTION_CLASSES.get(message_type)
    if not enum_class:
        raise ValueError(f"Unknown message type: {message_type}")

    # Find the name of the action from the value
    for action in enum_class:
        if action.value == action_value:
            return action.name.lower()  # Convert to lowercase to maintain the format "late_connect"

    raise ValueError(f"Unknown action value {action_value} for message type {message_type}")


def get_actions_names(message_type: str):
    message_actions = ACTION_CLASSES.get(message_type)
    if not message_actions:
        raise ValueError(f"Invalid message type: {message_type}")

    return [action.name.lower() for action in message_actions]


def factory_message_action(message_type: str, action: str):
    message_actions = ACTION_CLASSES.get(message_type)

    if message_actions:
        normalized_action = action.upper()
        enum_action = message_actions[normalized_action]
        # logging.info(f"Message action: {enum_action}, value: {enum_action.value}")
        return enum_action.value
    else:
        return None

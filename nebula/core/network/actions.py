from enum import Enum

from nebula.core.pb import nebula_pb2


class ConnectionAction(Enum):
    """
    Enum for connection-related actions exchanged between nodes in the federation.
    """

    CONNECT = nebula_pb2.ConnectionMessage.Action.CONNECT
    DISCONNECT = nebula_pb2.ConnectionMessage.Action.DISCONNECT
    LATE_CONNECT = nebula_pb2.ConnectionMessage.Action.LATE_CONNECT
    RESTRUCTURE = nebula_pb2.ConnectionMessage.Action.RESTRUCTURE


class FederationAction(Enum):
    """
    Enum for actions related to federation lifecycle and state management.
    """

    FEDERATION_START = nebula_pb2.FederationMessage.Action.FEDERATION_START
    REPUTATION = nebula_pb2.FederationMessage.Action.REPUTATION
    FEDERATION_MODELS_INCLUDED = nebula_pb2.FederationMessage.Action.FEDERATION_MODELS_INCLUDED
    FEDERATION_READY = nebula_pb2.FederationMessage.Action.FEDERATION_READY


class DiscoveryAction(Enum):
    """
    Enum for node discovery and registration events.
    """

    DISCOVER = nebula_pb2.DiscoveryMessage.Action.DISCOVER
    REGISTER = nebula_pb2.DiscoveryMessage.Action.REGISTER
    DEREGISTER = nebula_pb2.DiscoveryMessage.Action.DEREGISTER


class ControlAction(Enum):
    """
    Enum for control signals used to report system status and health.
    """

    ALIVE = nebula_pb2.ControlMessage.Action.ALIVE
    OVERHEAD = nebula_pb2.ControlMessage.Action.OVERHEAD
    MOBILITY = nebula_pb2.ControlMessage.Action.MOBILITY
    RECOVERY = nebula_pb2.ControlMessage.Action.RECOVERY
    WEAK_LINK = nebula_pb2.ControlMessage.Action.WEAK_LINK
    LEADERSHIP_TRANSFER = nebula_pb2.ControlMessage.Action.LEADERSHIP_TRANSFER
    LEADERSHIP_TRANSFER_ACK = nebula_pb2.ControlMessage.Action.LEADERSHIP_TRANSFER_ACK


class DiscoverAction(Enum):
    """
    Enum for extended discovery behaviors in multi-federation scenarios.
    """

    DISCOVER_JOIN = nebula_pb2.DiscoverMessage.Action.DISCOVER_JOIN
    DISCOVER_NODES = nebula_pb2.DiscoverMessage.Action.DISCOVER_NODES


class OfferAction(Enum):
    """
    Enum for offer-related messages, such as model or metric sharing.
    """

    OFFER_MODEL = nebula_pb2.OfferMessage.Action.OFFER_MODEL
    OFFER_METRIC = nebula_pb2.OfferMessage.Action.OFFER_METRIC


class LinkAction(Enum):
    """
    Enum for explicit link manipulation between nodes.
    """

    CONNECT_TO = nebula_pb2.LinkMessage.Action.CONNECT_TO
    DISCONNECT_FROM = nebula_pb2.LinkMessage.Action.DISCONNECT_FROM


class ReputationAction(Enum):
    """
    Enum for reputation exchange messages in the federation.
    """

    SHARE = nebula_pb2.ReputationMessage.Action.SHARE


# Mapping between message type strings and their corresponding Enum classes
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
    """
    Retrieve the string name of an action from its integer value.

    Args:
        message_type (str): The type of the message (e.g., "connection", "control").
        action_value (int): The numeric value of the action.

    Returns:
        str: The name of the action in lowercase format.

    Raises:
        ValueError: If the message type or action value is not recognized.
    """
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
    """
    Get all action names for a given message type.

    Args:
        message_type (str): The type of the message.

    Returns:
        List[str]: List of action names in lowercase.

    Raises:
        ValueError: If the message type is invalid.
    """
    message_actions = ACTION_CLASSES.get(message_type)
    if not message_actions:
        raise ValueError(f"Invalid message type: {message_type}")

    return [action.name.lower() for action in message_actions]


def factory_message_action(message_type: str, action: str):
    """
    Convert a string action name to its corresponding Enum value.

    Args:
        message_type (str): The type of the message (e.g., "offer", "link").
        action (str): The string name of the action.

    Returns:
        int or None: The integer value of the Enum action, or None if the type is unknown.
    """
    message_actions = ACTION_CLASSES.get(message_type)

    if message_actions:
        normalized_action = action.upper()
        enum_action = message_actions[normalized_action]
        # logging.info(f"Message action: {enum_action}, value: {enum_action.value}")
        return enum_action.value
    else:
        return None

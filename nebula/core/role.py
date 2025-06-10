from enum import Enum

class Role(Enum):
    """
    This class defines the participant roles of the platform.
    """

    TRAINER = "trainer"
    AGGREGATOR = "aggregator"
    PROXY = "proxy"
    IDLE = "idle"
    SERVER = "server"
    
def factory_node_role(role: str) -> Role:
    if role == "trainer":
        return Role.TRAINER
    elif role == "aggregator":
        return Role.AGGREGATOR
    elif role == "proxy":
        return Role.PROXY
    elif role == "idle":
        return Role.IDLE
    elif role == "server":
        return Role.SERVER
    else:
        return ""

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
    
def factory_node_role(self, rol: str) -> Role:
    if rol == "trainer":
        return Role.TRAINER
    elif rol == "aggregator":
        return Role.AGGREGATOR
    elif rol == "proxy":
        return Role.PROXY
    elif rol == "idle":
        return Role.IDLE
    elif rol == "server":
        return Role.SERVER
    else:
        return ""

from abc import ABC, abstractmethod

from nebula.core.situationalawareness.awareness.sautils.sacommand import SACommand


class ArbitrationPolicy(ABC):
    """
    Abstract base class defining the arbitration policy for resolving conflicts between SA commands.

    This class establishes the interface for implementing arbitration logic used in the
    Situational Awareness module. It includes initialization and a tie-breaking mechanism
    when two commands have the same priority or conflict.

    Methods:
    - init(config): Initialize the arbitration policy with a configuration object.
    - tie_break(sac1, sac2): Decide which command to keep when two conflict and have equal priority.
    """

    @abstractmethod
    async def init(self, config):
        """
        Initialize the arbitration policy with the provided configuration.

        Parameters:
            config (Any): A configuration object or dictionary to set up internal parameters.
        """
        raise NotImplementedError

    @abstractmethod
    async def tie_break(self, sac1: SACommand, sac2: SACommand) -> bool:
        """
        Resolve a conflict between two commands with equal priority.

        Parameters:
            sac1 (SACommand): First command in conflict.
            sac2 (SACommand): Second command in conflict.

        Returns:
            bool: True if sac1 should be kept over sac2, False if sac2 is preferred.
        """
        raise NotImplementedError


def factory_arbitration_policy(arbitatrion_policy, verbose) -> ArbitrationPolicy:
    from nebula.core.situationalawareness.awareness.arbitrationpolicies.staticarbitrationpolicy import SAP

    options = {
        "sap": SAP,  # "Static Arbitatrion Policy"                   (SAP) -- default value
    }

    cs = options.get(arbitatrion_policy, SAP)
    return cs(verbose)

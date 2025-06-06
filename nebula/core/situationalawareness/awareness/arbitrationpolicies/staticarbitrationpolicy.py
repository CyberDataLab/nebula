import logging

from nebula.core.situationalawareness.awareness.arbitrationpolicies.arbitrationpolicy import ArbitrationPolicy
from nebula.core.situationalawareness.awareness.sautils.sacommand import SACommand


class SAP(ArbitrationPolicy):  # Static Arbitatrion Policy
    """
    Static Arbitration Policy for the Reasoner module.

    This class implements a fixed priority arbitration mechanism for 
    SA (Situational Awareness) components. Each SA component category 
    is assigned a static weight representing its priority level.

    In case of conflicting SA commands, the policy selects the command 
    whose originating component has the highest priority weight.

    Attributes:
        _verbose (bool): Enables verbose logging for debugging and tracing.
        agent_weights (dict): Mapping of SA component categories to static weights.

    Methods:
        init(config): Placeholder for initialization with external configuration.
        tie_break(sac1, sac2): Resolves conflicts between two SA commands by 
            comparing their category weights, returning True if sac1 wins.
    """
    def __init__(self, verbose):
        self._verbose = verbose
        # Define static weights for SA Agents from SA Components
        self.agent_weights = {"SATraining": 1, "SANetwork": 2, "SAReputation": 3}

    async def init(self, config):
        pass

    async def _get_agent_category(self, sa_command: SACommand) -> str:
        """
        Extract agent category name.
        Example: "SATraining_Agent1" → "SATraining"
        """
        full_name = await sa_command.get_owner()
        return full_name.split("_")[0] if "_" in full_name else full_name

    async def tie_break(self, sac1: SACommand, sac2: SACommand) -> bool:
        """
        Tie break conflcited SA Commands
        """
        if self._verbose:
            logging.info(
                f"Tie break between ({await sac1.get_owner()}, {sac1.get_action().value}) & ({await sac2.get_owner()}, {sac2.get_action().value})"
            )

        async def get_weight(cmd):
            category = await self._get_agent_category(cmd)
            return self.agent_weights.get(category, 0)

        if await get_weight(sac1) > await get_weight(sac2):
            if self._verbose:
                logging.info(
                    f"Tie break resolved, SA Command choosen ({await sac1.get_owner()}, {sac1.get_action().value})"
                )
            return True
        else:
            if self._verbose:
                logging.info(
                    f"Tie break resolved, SA Command choosen ({await sac2.get_owner()}, {sac2.get_action().value})"
                )
            return False

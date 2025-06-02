import asyncio
from abc import abstractmethod
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nebula.core.situationalawareness.awareness.sautils.samoduleagent import SAModuleAgent


class SACommandType(Enum):
    CONNECTIVITY = "Connectivity"
    AGGREGATION = "Aggregation"


# TODO make differents parts
class SACommandAction(Enum):
    IDLE = "idle"
    DISCONNECT = "disconnect"
    RECONNECT = "reconnect"
    SEARCH_CONNECTIONS = "search_connections"
    MAINTAIN_CONNECTIONS = "maintain_connections"
    ADJUST_WEIGHT = "adjust_weight"
    DISCARD_UPDATE = "discard_update"


class SACommandPRIO(Enum):
    CRITICAL = 20
    HIGH = 10
    MEDIUM = 5
    LOW = 3
    MAINTENANCE = 1


class SACommandState(Enum):
    PENDING = "pending"
    DISCARDED = "discarded"
    EXECUTED = "executed"

    """                                             ###############################
                                                    #      SA COMMAND CLASS       #
                                                    ###############################
    """


class SACommand:
    """
    Base class for Situational Awareness (SA) module commands.

    This class defines the core structure and behavior of commands that can be
    issued by SA agents. Each command has an associated type, action, target,
    priority, and execution state. Commands may also declare whether they can be
    executed in parallel. Subclasses must implement the actual logic for execution
    and conflict detection.

    Attributes:
        command_type (SACommandType): Type of the command (e.g., parameter update, structural change).
        action (SACommandAction): Specific action the command performs.
        owner (SAModuleAgent): Reference to the module or agent that issued the command.
        target (Any): Target of the command (e.g., node, parameter name).
        priority (SACommandPRIO): Priority level of the command.
        parallelizable (bool): Indicates whether the command can be run concurrently.
        _state (SACommandState): Internal state of the command (e.g., PENDING, DISCARDED).
        _state_future (asyncio.Future): Future that resolves when the command changes state.
    """

    def __init__(
        self,
        command_type: SACommandType,
        action: SACommandAction,
        owner: "SAModuleAgent",
        target,
        priority: SACommandPRIO = SACommandPRIO.MEDIUM,
        parallelizable=False,
    ):
        self._command_type = command_type
        self._action = action
        self._owner = owner
        self._target = target  # Could be a node, parameter, etc.
        self._priority = priority
        self._parallelizable = parallelizable
        self._state = SACommandState.PENDING
        self._state_future = asyncio.get_event_loop().create_future()

    @abstractmethod
    async def execute(self):
        """
        Execute the command's action on the specified target.

        This method must be implemented by subclasses to define the actual logic
        of how the command affects the system. It may involve sending messages,
        modifying local or global state, or interacting with external components.
        """
        raise NotImplementedError

    @abstractmethod
    async def conflicts_with(self, other: "SACommand") -> bool:
        """
        Determine whether this command conflicts with another command.

        This method must be implemented by subclasses to define conflict logic,
        e.g., whether two commands target the same resource in incompatible ways.
        Used during arbitration to resolve simultaneous command suggestions.

        Parameters:
            other (SACommand): Another command instance to check for conflicts.

        Returns:
            bool: True if there is a conflict, False otherwise.
        """
        raise NotImplementedError

    async def discard_command(self):
        await self._update_command_state(SACommandState.DISCARDED)

    def got_higher_priority_than(self, other_prio: SACommandPRIO):
        return self._priority.value > other_prio.value

    def get_prio(self):
        return self._priority

    async def get_owner(self):
        return await self._owner.get_agent()

    def get_action(self) -> SACommandAction:
        return self._action

    async def _update_command_state(self, sacs: SACommandState):
        self._state = sacs
        if not self._state_future.done():
            self._state_future.set_result(sacs)

    def get_state_future(self) -> asyncio.Future:
        return self._state_future

    def is_parallelizable(self):
        return self._parallelizable

    def __repr__(self):
        return (
            f"{self.__class__.__name__}(Type={self._command_type.value}, "
            f"Action={self._action.value}, Target={self._target}, Priority={self._priority.value})"
        )

    """                                             ###############################
                                                    #     SA COMMAND SUBCLASS     #
                                                    ###############################
    """


class ConnectivityCommand(SACommand):
    """Commands related to connectivity."""

    def __init__(
        self,
        action: SACommandAction,
        owner: "SAModuleAgent",
        target: str,
        priority: SACommandPRIO = SACommandPRIO.MEDIUM,
        parallelizable=False,
        action_function=None,
        *args,
    ):
        super().__init__(SACommandType.CONNECTIVITY, action, owner, target, priority, parallelizable)
        self._action_function = action_function
        self._args = args

    async def execute(self):
        """Executes the assigned action function with the given parameters."""
        await self._update_command_state(SACommandState.EXECUTED)
        if self._action_function:
            if asyncio.iscoroutinefunction(self._action_function):
                await self._action_function(*self._args)
            else:
                self._action_function(*self._args)

    async def conflicts_with(self, other: "ConnectivityCommand") -> bool:
        """Determines if two commands conflict with each other."""
        if await self._owner.get_agent() == await other._owner.get_agent():
            return False

        if self._target == other._target:
            conflict_pairs = [
                {SACommandAction.DISCONNECT, SACommandAction.DISCONNECT},
            ]
            return {self._action, other._action} in conflict_pairs
        else:
            conflict_pairs = [
                {SACommandAction.DISCONNECT, SACommandAction.RECONNECT},
                {SACommandAction.DISCONNECT, SACommandAction.MAINTAIN_CONNECTIONS},
                {SACommandAction.DISCONNECT, SACommandAction.SEARCH_CONNECTIONS},
            ]
            return {self._action, other._action} in conflict_pairs


class AggregationCommand(SACommand):
    """Commands related to data aggregation."""

    def __init__(
        self,
        action: SACommandAction,
        owner: "SAModuleAgent",
        target: dict,
        priority: SACommandPRIO = SACommandPRIO.MEDIUM,
        parallelizable=False,
    ):
        super().__init__(SACommandType.CONNECTIVITY, action, owner, target, priority, parallelizable)

    async def execute(self):
        await self._update_command_state(SACommandState.EXECUTED)
        return self._target

    async def conflicts_with(self, other: "AggregationCommand") -> bool:
        """Determines if two commands conflict with each other."""
        topologic_conflict = False
        weight_conflict = False

        if set(self._target.keys()) != set(other._target.keys()):
            topologic_conflict = True

        weight_conflict = any(
            abs(self._target[node][1] - other._target[node][1]) > 0
            for node in self._target.keys()
            if node in other._target.keys()
        )

        return weight_conflict and topologic_conflict

    """                                             ###############################
                                                    #     SA COMMAND FACTORY      #
                                                    ###############################
    """


def factory_sa_command(sacommand_type, *config) -> SACommand:
    options = {
        "connectivity": ConnectivityCommand,
        "aggregation": AggregationCommand,
    }

    cs = options.get(sacommand_type)
    if cs is None:
        raise ValueError(f"Unknown SACommand type: {sacommand_type}")
    return cs(*config)

from abc import ABC, abstractmethod

from nebula.core.situationalawareness.awareness.sautils.sacommand import SACommand


class SAModuleAgent(ABC):
    """
    Abstract base class representing a Situational Awareness (SA) module agent.

    This interface defines the essential methods that any SA agent must implement
    to participate in the suggestion and arbitration pipeline. Agents are responsible
    for registering themselves, suggesting actions in the form of commands, and
    notifying when all suggestions related to an event are complete.

    Methods:
    - get_agent(): Return a unique identifier or name of the agent.
    - register_sa_agent(): Perform initialization or registration steps for the agent.
    - suggest_action(sac): Submit a suggested command (SACommand) for arbitration.
    - notify_all_suggestions_done(event_type): Indicate that all suggestions for a given event are complete.
    """

    @abstractmethod
    async def get_agent(self) -> str:
        """
        Return the unique identifier or name of the agent.

        Returns:
            str: The identifier or label representing this SA agent.
        """
        raise NotImplementedError

    @abstractmethod
    async def register_sa_agent(self):
        """
        Perform initialization logic required to register this SA agent
        within the system (e.g., announcing its presence or preparing state).
        """
        raise NotImplementedError

    @abstractmethod
    async def suggest_action(self, sac: SACommand):
        """
        Submit a suggested action in the form of a SACommand for a given context.

        Parameters:
            sac (SACommand): The command proposed by the agent for execution.
        """
        raise NotImplementedError

    @abstractmethod
    async def notify_all_suggestions_done(self, event_type):
        """
        Notify that this agent has completed all its suggestions for a particular event.

        Parameters:
            event_type (Type[NodeEvent]): The type of the event for which suggestions are now complete.
        """
        raise NotImplementedError

import asyncio
from collections import defaultdict

from nebula.core.nebulaevents import NodeEvent
from nebula.core.situationalawareness.awareness.sautils.sacommand import SACommand
from nebula.core.situationalawareness.awareness.sautils.samoduleagent import SAModuleAgent
from nebula.core.utils.locker import Locker
from nebula.utils import logging


class SuggestionBuffer:
    """
    Singleton class that manages the coordination of suggestions from Situational Awareness (SA) agents.

    The SuggestionBuffer stores, synchronizes, and tracks command suggestions issued by agents in
    response to specific node events. It ensures that all expected agents have submitted their input
    before triggering arbitration. Internally, it maintains buffers for suggestions, synchronization
    locks, and agent-specific notifications to guarantee consistency in distributed settings.

    Main Responsibilities:
    - Register expected agents for an event and track their completion.
    - Store and retrieve suggestions for arbitration.
    - Signal the arbitrator once all expected suggestions have been received.
    - Support safe concurrent access through async-aware locking mechanisms.
    """

    _instance = None
    _lock = Locker("initialize_sb_lock", async_lock=False)

    def __new__(cls, arbitrator_notification, verbose):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        """Obtain SuggestionBuffer instance"""
        if cls._instance is None:
            raise ValueError("SuggestionBuffer has not been initialized yet.")
        return cls._instance

    def __init__(self, arbitrator_notification: asyncio.Event, verbose):
        """Initializes the suggestion buffer with thread-safe synchronization."""
        self._arbitrator_notification = arbitrator_notification
        self._arbitrator_notification_lock = Locker("arbitrator_notification_lock", async_lock=True)
        self._verbose = verbose
        self._buffer: dict[type[NodeEvent], list[tuple[SAModuleAgent, SACommand]]] = defaultdict(list)
        self._suggestion_buffer_lock = Locker("suggestion_buffer_lock", async_lock=True)
        self._expected_agents: dict[type[NodeEvent], list[SAModuleAgent]] = defaultdict(list)
        self._expected_agents_lock = Locker("expected_agents_lock", async_lock=True)
        self._event_notifications: dict[type[NodeEvent], list[tuple[SAModuleAgent, asyncio.Event]]] = defaultdict(list)
        self._event_waited = None

    async def register_event_agents(self, event_type, agent: SAModuleAgent):
        """
        Register a Situational Awareness (SA) agent as an expected participant for a given event type.

        Parameters:
            event_type (Type[NodeEvent]): The type of event being registered.
            agent (SAModuleAgent): The agent expected to submit suggestions for the event.
        """
        async with self._expected_agents_lock:
            if self._verbose:
                logging.info(f"Registering SA Agent: {await agent.get_agent()} for event: {event_type.__name__}")

            if event_type not in self._event_notifications:
                self._event_notifications[event_type] = []

            self._expected_agents[event_type].append(agent)

            existing_agents = {a for a, _ in self._event_notifications[event_type]}
            if agent not in existing_agents:
                self._event_notifications[event_type].append((agent, asyncio.Event()))

    async def register_suggestion(self, event_type, agent: SAModuleAgent, suggestion: SACommand):
        """
        Register a suggestion issued by a specific SA agent for a given event.

        Parameters:
            event_type (Type[NodeEvent]): The event type for which the suggestion is made.
            agent (SAModuleAgent): The agent submitting the suggestion.
            suggestion (SACommand): The command being suggested.
        """
        async with self._suggestion_buffer_lock:
            if self._verbose:
                logging.info(
                    f"Registering Suggestion from SA Agent: {await agent.get_agent()} for event: {event_type.__name__}"
                )
            self._buffer[event_type].append((agent, suggestion))

    async def set_event_waited(self, event_type):
        """
        Set the event type that the SuggestionBuffer will wait for.

        Used to indicate that arbitration should proceed when all suggestions for this event are received.

        Parameters:
            event_type (Type[NodeEvent]): The event type to monitor.
        """
        if not self._event_waited:
            if self._verbose:
                logging.info(
                    f"Set notification when all suggestions have being received for event: {event_type.__name__}"
                )
            self._event_waited = event_type
            await self._notify_arbitrator(event_type)

    async def notify_all_suggestions_done_for_agent(self, saa: SAModuleAgent, event_type):
        """
        Notify that a specific SA agent has completed its suggestion submission for an event.

        Parameters:
            saa (SAModuleAgent): The notifying agent.
            event_type (Type[NodeEvent]): The related event type.
        """
        async with self._expected_agents_lock:
            agent_found = False
            for agent, event in self._event_notifications.get(event_type, []):
                if agent == saa:
                    event.set()
                    agent_found = True
                    if self._verbose:
                        logging.info(
                            f"SA Agent: {await saa.get_agent()} notifies all suggestions registered for event: {event_type.__name__}"
                        )
                    break
            if not agent_found and self._verbose:
                logging.error(
                    f"SAModuleAgent: {await saa.get_agent()} not found on notifications awaited for event {event_type.__name__}"
                )
        await self._notify_arbitrator(event_type)

    async def _notify_arbitrator(self, event_type):
        """
        Check if all expected agents have submitted their suggestions for the current awaited event.

        If so, notifies the arbitrator via the provided asyncio event.
        """
        if event_type != self._event_waited:
            return

        async with self._arbitrator_notification_lock:
            async with self._expected_agents_lock:
                expected_agents = self._expected_agents.get(event_type, [])
                notifications = self._event_notifications.get(event_type, list())

                agent_event_map = {a: e for a, e in notifications}
                all_received = all(
                    agent in agent_event_map and agent_event_map[agent].is_set() for agent in expected_agents
                )

                if all_received:
                    self._arbitrator_notification.set()
                    self._event_waited = None
                    await self._reset_notifications_for_agents(event_type, expected_agents)

    async def _reset_notifications_for_agents(self, event_type, agents):
        """
        Reset all notification events for the given agents tied to a specific event.

        Parameters:
            event_type (Type[NodeEvent]): The event for which to reset agent notifications.
            agents (list[SAModuleAgent]): The list of agents to reset.
        """
        notifications = self._event_notifications.get(event_type, set())
        for agent, event in notifications:
            if agent in agents:
                event.clear()

    async def get_suggestions(self, event_type) -> list[tuple[SAModuleAgent, SACommand]]:
        """
        Retrieve and return all suggestions for a given event type.

        Also clears the buffer after reading.

        Parameters:
            event_type (Type[NodeEvent]): The event whose suggestions are requested.

        Returns:
            list[tuple[SAModuleAgent, SACommand]]: List of (agent, suggestion) pairs.
        """
        async with self._suggestion_buffer_lock:
            async with self._expected_agents_lock:
                suggestions = list(self._buffer.get(event_type, []))
                if self._verbose:
                    logging.info(f"Retrieving all sugestions for event: {event_type.__name__}")
                await self._clear_suggestions(event_type)
                return suggestions

    async def _clear_suggestions(self, event_type):
        """
        Clear the buffer and associated data for a specific event type.

        Parameters:
            event_type (Type[NodeEvent]): The event whose stored suggestions are to be removed.
        """
        self._buffer[event_type].clear()

from __future__ import annotations

import asyncio
import copy
import importlib.util
import logging
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from nebula.addons.functions import print_msg_box
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import AggregationEvent, RoundEndEvent
from nebula.core.network.communications import CommunicationsManager
from nebula.core.situationalawareness.awareness.arbitrationpolicies.arbitrationpolicy import factory_arbitration_policy
from nebula.core.situationalawareness.awareness.sautils.sacommand import SACommand
from nebula.core.situationalawareness.awareness.sautils.sasystemmonitor import SystemMonitor
from nebula.core.situationalawareness.awareness.suggestionbuffer import SuggestionBuffer
from nebula.core.situationalawareness.situationalawareness import ISADiscovery, ISAReasoner
from nebula.core.utils.locker import Locker

if TYPE_CHECKING:
    from nebula.core.situationalawareness.awareness.sanetwork.sanetwork import SANetwork


class SAMComponent(ABC):
    """
    Abstract base class representing a Situational Awareness Module Component (SAMComponent).

    Each SAMComponent is responsible for analyzing specific aspects of the system's state and
    proposing relevant actions. These components act as internal reasoning units within the
    SAReasoner and contribute suggestions to the command arbitration process.

    Methods:
    - init(): Initialize internal state and resources required by the component.
    - sa_component_actions(): Generate and return actions based on local analysis.
    """

    @abstractmethod
    async def init(self):
        """
        Initialize the SAMComponent.

        This method should prepare any internal state, models, or resources required
        before the component starts analyzing and proposing actions.
        """
        raise NotImplementedError

    @abstractmethod
    async def sa_component_actions(self):
        """
        Analyze system state and generate a list of SACommand suggestions.
        It uses the SuggestionBuffer to send a list of SACommands.
        """
        raise NotImplementedError


class SAReasoner(ISAReasoner):
    """
    Core implementation of the Situational Awareness Reasoner (SAReasoner).

    This class coordinates the lifecycle and interactions of all internal components
    in the SA module, including SAMComponents (reasoning units), the suggestion buffer,
    and the arbitration policy. It is responsible for:

    - Initializing and managing all registered SAMComponents.
    - Collecting suggestions from each component in response to events.
    - Registering and notifying the SuggestionBuffer of suggestions.
    - Triggering arbitration when multiple conflicting commands are proposed.
    - Interfacing with the wider system through the ISAReasoner interface.

    This class acts as the central controller for decision-making based on local
    or global awareness in distributed systems.
    """

    MODULE_PATH = "nebula/nebula/core/situationalawareness/awareness"

    def __init__(
        self,
        config,
    ):
        print_msg_box(
            msg="Starting Situational Awareness Reasoner module...",
            indent=2,
            title="SA Reasoner",
        )
        logging.info("🌐  Initializing SAReasoner")
        self._config = copy.deepcopy(config.participant)
        self._addr = config.participant["network_args"]["addr"]
        self._topology = config.participant["mobility_args"]["topology_type"]
        self._situational_awareness_network = None
        self._situational_awareness_training = None
        self._restructure_process_lock = Locker(name="restructure_process_lock")
        self._restructure_cooldown = 0
        self._arbitrator_notification = asyncio.Event()
        self._suggestion_buffer = SuggestionBuffer(self._arbitrator_notification, verbose=True)
        self._communciation_manager = CommunicationsManager.get_instance()
        self._sys_monitor = SystemMonitor()
        arb_pol = config.participant["situational_awareness"]["sa_reasoner"]["arbitration_policy"]
        self._arbitatrion_policy = factory_arbitration_policy(arb_pol, True)
        self._sa_components: dict[str, SAMComponent] = {}
        self._sa_discovery: ISADiscovery = None
        self._verbose = config.participant["situational_awareness"]["sa_reasoner"]["verbose"]

    @property
    def san(self) -> SANetwork:
        """Situational Awareness Network"""
        return self._situational_awareness_network

    @property
    def cm(self):
        """Communicaiton Manager"""
        return self._communciation_manager

    @property
    def sb(self):
        """Suggestion Buffer"""
        return self._suggestion_buffer

    @property
    def ab(self):
        """Arbitatrion Policy"""
        return self._arbitatrion_policy

    @property
    def sad(self) -> ISADiscovery:
        """SA Discovery"""
        return self._sa_discovery

    async def init(self, sa_discovery):
        """
        Initialize the SAReasoner by loading components and subscribing to relevant events.

        Args:
            sa_discovery (ISADiscovery): The discovery component to coordinate with.
        """
        self._sa_discovery: ISADiscovery = sa_discovery
        await self._loading_sa_components()
        await EventManager.get_instance().subscribe_node_event(RoundEndEvent, self._process_round_end_event)
        await EventManager.get_instance().subscribe_node_event(AggregationEvent, self._process_aggregation_event)

    def is_additional_participant(self):
        """
        Determine if this node is configured as an additional (mobile) participant.

        Returns:
            bool: True if the node is marked as an additional participant, False otherwise.
        """
        return self._config["mobility_args"]["additional_node"]["status"]

    """                                                     ###############################
                                                            #    REESTRUCTURE TOPOLOGY    #
                                                            ###############################
    """

    def get_restructure_process_lock(self):
        return self.san.get_restructure_process_lock()

    """                                                     ###############################
                                                            #          SA NETWORK         #
                                                            ###############################
    """

    async def get_nodes_known(self, neighbors_too=False, neighbors_only=False):
        """
        Retrieve the set of nodes known to the situational awareness reasoner.

        This may include additional metadata depending on the flags.

        Args:
            neighbors_too (bool, optional): If True, include neighboring nodes in the result. Defaults to False.
            neighbors_only (bool, optional): If True, return only neighbors. Defaults to False.

        Returns:
            set: Identifiers of known nodes based on the provided filters.
        """
        return await self.san.get_nodes_known(neighbors_too, neighbors_only)

    async def accept_connection(self, source, joining=False):
        """
        Decide whether to accept a connection request from a source node.

        Delegates to the underlying reasoner logic to determine acceptance.

        Args:
            source (str): The identifier or address of the requesting node.
            joining (bool, optional): If True, this connection is part of a join operation. Defaults to False.

        Returns:
            bool: True if the connection should be accepted, False otherwise.
        """
        return await self.san.accept_connection(source, joining)

    async def get_actions(self):
        """
        Retrieve the list of situational awareness actions available to execute.

        Delegates to the underlying reasoner component.

        Returns:
            list: Action identifiers that the reasoner can perform.
        """
        return await self.san.get_actions()

    """                                                     ###############################
                                                            #         ARBITRATION         #
                                                            ###############################
    """

    async def _process_round_end_event(self, ree: RoundEndEvent):
        """
        Handle the end of a federated learning round by gathering situational awareness actions
        and executing arbitration commands.

        1. Trigger each SA component to propose actions asynchronously.
        2. Run arbitration to select valid SACommand instances.
        3. Execute parallelizable commands concurrently and sequential commands one by one.

        Args:
            ree (RoundEndEvent): The event signaling the end of the current training round.
        """
        logging.info("🔄 Arbitration | Round End Event...")
        for sa_comp in self._sa_components.values():
            asyncio.create_task(sa_comp.sa_component_actions())
        valid_commands = await self._arbitatrion_suggestions(RoundEndEvent)

        # Execute SACommand selected
        if self._verbose:
            logging.info(f"Going to execute {len(valid_commands)} SACommands")
        for cmd in valid_commands:
            if cmd.is_parallelizable():
                if self._verbose:
                    logging.info(
                        f"going to execute parallelizable action: {cmd.get_action()} made by: {await cmd.get_owner()}"
                    )
                asyncio.create_task(cmd.execute())
            else:
                if self._verbose:
                    logging.info(f"going to execute action: {cmd.get_action()} made by: {await cmd.get_owner()}")
                await cmd.execute()

    async def _process_aggregation_event(self, age: AggregationEvent):
        """
        Handle an aggregation event by selecting and executing an SACommand to adjust aggregation behavior.

        1. Run arbitration to retrieve suggestions specific to aggregation.
        2. If any commands are returned, pick the first one.
        3. Execute the chosen command and apply its resulting updates to the aggregation event.

        Args:
            age (AggregationEvent): The event containing updates ready for federation aggregation.
        """
        logging.info("🔄 Arbitration | Aggregation Event...")
        aggregation_command = await self._arbitatrion_suggestions(AggregationEvent)
        if len(aggregation_command):
            if self._verbose:
                logging.info(
                    f"Aggregation event resolved. SA Agente that suggest action: {await aggregation_command[0].get_owner}"
                )
            final_updates = await aggregation_command[0].execute()
            age.update_updates(final_updates)

    async def _arbitatrion_suggestions(self, event_type):
        """
        Perform arbitration over a set of agent suggestions for a given event type.

        This method waits for all suggestions to be submitted, detects and resolves
        conflicts based on command priorities and optional tie-breaking, and
        returns a list of valid, non-conflicting commands.

        Parameters:
            event_type: The identifier or type of the event for which suggestions are being arbitrated.

        Returns:
            list[SACommand]: A list of validated and conflict-free commands after arbitration.
        """
        if self._verbose:
            logging.info("Waiting for all suggestions done")
        await self.sb.set_event_waited(event_type)
        await self._arbitrator_notification.wait()
        if self._verbose:
            logging.info("waiting released")
        suggestions = await self.sb.get_suggestions(event_type)
        self._arbitrator_notification.clear()
        if not len(suggestions):
            if self._verbose:
                logging.info("No suggestions for this event | Arbitatrion not required")
            return []

        if self._verbose:
            logging.info(f"Starting arbitatrion | Number of suggestions received: {len(suggestions)}")

        valid_commands: list[SACommand] = []

        for agent, cmd in suggestions:
            has_conflict = False
            to_remove: list[SACommand] = []

            for other in valid_commands:
                if await cmd.conflicts_with(other):
                    if self._verbose:
                        logging.info(
                            f"Conflict detected between -- {await cmd.get_owner()} and {await other.get_owner()} --"
                        )
                    if self._verbose:
                        logging.info(f"Action in conflict ({cmd.get_action()}, {other.get_action()})")
                    if cmd.got_higher_priority_than(other.get_prio()):
                        to_remove.append(other)
                    elif cmd.get_prio() == other.get_prio():
                        if await self.ab.tie_break(cmd, other):
                            to_remove.append(other)
                        else:
                            has_conflict = True
                            break
                    else:
                        has_conflict = True
                        break

            if not has_conflict:
                for r in to_remove:
                    await r.discard_command()
                    valid_commands.remove(r)
                valid_commands.append(cmd)

        logging.info("Arbitatrion finished")
        return valid_commands

    """                                                     ###############################
                                                            #    SA COMPONENT LOADING     #
                                                            ###############################
    """

    def _to_pascal_case(self, name: str) -> str:
        """Converts a snake_case or compact lowercase name into PascalCase with 'SA' prefix."""
        if name.startswith("sa_"):
            name = name[3:]  # remove 'sa_' prefix
        elif name.startswith("sa"):
            name = name[2:]  # remove 'sa' prefix
        parts = name.split("_") if "_" in name else [name]
        return "SA" + "".join(part.capitalize() for part in parts)

    async def _loading_sa_components(self):
        """Dynamically loads the SA Components defined in the JSON configuration."""
        self._load_minimal_requirement_config()
        sa_section = self._config["situational_awareness"]["sa_reasoner"]
        components: dict = sa_section["sar_components"]

        for component_name, is_enabled in components.items():
            if is_enabled:
                component_config = sa_section[component_name]
                component_name = component_name.replace("_", "")
                class_name = self._to_pascal_case(component_name)
                module_path = os.path.join(self.MODULE_PATH, component_name)
                module_file = os.path.join(module_path, f"{component_name}.py")

                if os.path.exists(module_file):
                    module = await self._load_component(class_name, module_file, component_config)
                    if module:
                        self._sa_components[component_name] = module
                else:
                    logging.error(f"⚠️ SA Component {component_name} not found on {module_file}")

        await self._set_minimal_requirements()
        await self._initialize_sa_components()

    async def _load_component(self, class_name, component_file, config):
        """Loads a SA Component dynamically and initializes it with its configuration."""
        spec = importlib.util.spec_from_file_location(class_name, component_file)
        if spec and spec.loader:
            component = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(component)
            if hasattr(component, class_name):  # Verify if class exists
                return getattr(component, class_name)(config)  # Create and instance using component config
            else:
                logging.error(f"⚠️ Cannot create {class_name} SA Component, class not found on {component_file}")
        return None

    async def _initialize_sa_components(self):
        if self._sa_components:
            for sacomp in self._sa_components.values():
                await sacomp.init()

    def _load_minimal_requirement_config(self):
        #self._config["situational_awareness"]["sa_reasoner"]["sa_network"]["addr"] = self._addr
        #self._config["situational_awareness"]["sa_reasoner"]["sa_network"]["sar"] = self
        self._config["situational_awareness"]["sa_reasoner"]["sa_network"]["strict_topology"] = self._config["situational_awareness"]["strict_topology"]
        
        # SA Reasoner instance for all SA Reasoner Components
        sar_components: dict = self._config["situational_awareness"]["sa_reasoner"]["sar_components"]
        for sar_comp in sar_components.keys():
            self._config["situational_awareness"]["sa_reasoner"][sar_comp]["sar"] = self
            self._config["situational_awareness"]["sa_reasoner"][sar_comp]["addr"] = self._addr

    async def _set_minimal_requirements(self):
        """Set minimal requirements to setup the SA Reasoner"""
        if self._sa_components:
            self._situational_awareness_network = self._sa_components["sanetwork"]
        else:
            raise ValueError("SA Network not found")

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from nebula.addons.functions import print_msg_box
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import (
    BeaconRecievedEvent,
    ExperimentFinishEvent,
    NodeFoundEvent,
    RoundEndEvent,
    UpdateNeighborEvent,
)
from nebula.core.network.communications import CommunicationsManager
from nebula.core.situationalawareness.awareness.sanetwork.neighborpolicies.neighborpolicy import factory_NeighborPolicy
from nebula.core.situationalawareness.awareness.sareasoner import SAMComponent
from nebula.core.situationalawareness.awareness.sautils.sacommand import (
    SACommand,
    SACommandAction,
    SACommandPRIO,
    SACommandState,
    factory_sa_command,
)
from nebula.core.situationalawareness.awareness.sautils.samoduleagent import SAModuleAgent
from nebula.core.situationalawareness.awareness.suggestionbuffer import SuggestionBuffer
from nebula.core.utils.locker import Locker

if TYPE_CHECKING:
    from nebula.core.situationalawareness.awareness.sareasoner import SAReasoner

RESTRUCTURE_COOLDOWN = 1  # 5


class SANetwork(SAMComponent):
    """
    Network situational awareness component responsible for monitoring and managing
    the communication context within the federation.

    This component handles:
      - Tracking active and potential peer nodes.
      - Evaluating network conditions for situational awareness decisions.
      - Integrating with discovery and reasoning modules for dynamic topology updates.

    Inherits from SAMComponent to participate in the broader Situational Awareness pipeline.
    """

    NEIGHBOR_VERIFICATION_TIMEOUT = 30

    def __init__(self, config):
        self._neighbor_policy = config["neighbor_policy"]  # topology
        self._neighbor_policy = self._neighbor_policy.lower()
        self._strict_topology = config["strict_topology"]  # strict_topology
        print_msg_box(
            msg=f"Starting Network SA\nNeighbor Policy: {self._neighbor_policy}\nStrict: {self._strict_topology}",
            indent=2,
            title="Network SA module",
        )
        self._sar = config["sar"]  # sar
        self._addr = config["addr"]  # addr
        self._neighbor_policy = factory_NeighborPolicy(self._neighbor_policy)
        self._restructure_process_lock = Locker(name="restructure_process_lock", async_lock=True)
        self._restructure_cooldown = 0
        self._verbose = config["verbose"]  # verbose
        self._cm = CommunicationsManager.get_instance()
        self._sa_network_agent = SANetworkAgent(self)

        # Track verification tasks for proper cleanup during shutdown
        self._verification_tasks = set()
        self._verification_tasks_lock = asyncio.Lock()

    @property
    def sar(self) -> SAReasoner:
        """SA Reasoner"""
        return self._sar

    @property
    def cm(self):
        """Communication Manager"""
        return self._cm

    @property
    def np(self):
        """Neighbor Policy"""
        return self._neighbor_policy

    @property
    def sana(self):
        """SA Network Agent"""
        return self._sa_network_agent

    async def init(self):
        """
        Initialize the SANetwork component by deploying external connection services,
        subscribing to relevant events, starting beaconing, and configuring neighbor policies.

        Actions performed:
        1. If not an additional participant, start and subscribe to beacon and finish events.
        2. Otherwise, initialize ECS without running it.
        3. Build and apply the neighbor policy using current direct and undirected connections.
        4. Subscribe to node discovery and neighbor update events.
        5. Register this agent with the situational awareness network agent.
        """
        if not self.sar.is_additional_participant():
            logging.info("Deploying External Connection Service")
            await self.cm.start_external_connection_service()
            await EventManager.get_instance().subscribe_node_event(BeaconRecievedEvent, self.beacon_received)
            await EventManager.get_instance().subscribe_node_event(ExperimentFinishEvent, self.experiment_finish)
            await self.cm.start_beacon()
        else:
            logging.info("Deploying External Connection Service | No running")
            await self.cm.start_external_connection_service(run_service=False)

        logging.info("Building neighbor policy configuration..")
        await self.np.set_config([
            await self.cm.get_addrs_current_connections(only_direct=True, myself=False),
            await self.cm.get_addrs_current_connections(only_direct=False, only_undirected=False, myself=False),
            self._addr,
            self._strict_topology,
        ])

        await EventManager.get_instance().subscribe_node_event(NodeFoundEvent, self._process_node_found_event)
        await EventManager.get_instance().subscribe_node_event(UpdateNeighborEvent, self._process_update_neighbor_event)
        await self.sana.register_sa_agent()

    async def sa_component_actions(self):
        """
        Perform periodic situational awareness checks for network conditions.

        This method evaluates the external connection service status and analyzes
        the robustness of the current network topology.
        """
        logging.info("SA Network evaluating current scenario")
        await self._check_external_connection_service_status()
        await self._analize_topology_robustness()

    """                                                     ###############################
                                                            #       NEIGHBOR POLICY       #
                                                            ###############################
    """

    async def _process_node_found_event(self, nfe: NodeFoundEvent):
        """
        Handle an event indicating a new node has been discovered.

        Args:
            nfe (NodeFoundEvent): The event containing the discovered node's address.
        """
        node_addr = await nfe.get_event_data()
        await self.np.meet_node(node_addr)

    async def _process_update_neighbor_event(self, une: UpdateNeighborEvent):
        """
        Handle an update to the neighbor set, such as node join or leave.

        Args:
            une (UpdateNeighborEvent): The event containing the neighbor address and removal flag.
        """
        node_addr, removed = await une.get_event_data()
        if self._verbose:
            logging.info(f"Processing Update Neighbor Event, node addr: {node_addr}, remove: {removed}")
        await self.np.update_neighbors(node_addr, removed)

    async def meet_node(self, node):
        """
        Propose a meeting (connection) with a newly discovered node if it is not self.

        Args:
            node (str): The address of the node to meet.
        """
        if node != self._addr:
            await self.np.meet_node(node)

    async def get_nodes_known(self, neighbors_too=False, neighbors_only=False):
        """
        Retrieve the list of known nodes in the network.

        Args:
            neighbors_too (bool, optional): Include neighbors in the result. Defaults to False.
            neighbors_only (bool, optional): Return only neighbors. Defaults to False.

        Returns:
            set: Addresses of known nodes based on the provided filters.
        """
        return await self.np.get_nodes_known(neighbors_too, neighbors_only)

    async def neighbors_left(self):
        """
        Check whether any direct neighbor connections remain.

        Returns:
            bool: True if there are one or more direct neighbor connections, False otherwise.
        """
        return len(await self.cm.get_addrs_current_connections(only_direct=True, myself=False)) > 0

    async def accept_connection(self, source, joining=False):
        """
        Decide whether to accept an incoming connection request from a source node.

        Args:
            source (str): The address of the requesting node.
            joining (bool, optional): True if this is part of a join process. Defaults to False.

        Returns:
            bool: True if the connection should be accepted, False otherwise.
        """
        accepted = await self.np.accept_connection(source, joining)
        return accepted

    async def need_more_neighbors(self):
        """
        Determine if the network requires additional neighbor connections.

        Returns:
            bool: True if more neighbors are needed, False otherwise.
        """
        return await self.np.need_more_neighbors()

    async def get_actions(self):
        """
        Retrieve the set of situational awareness actions applicable to the current network state.

        Returns:
            list: Identifiers of available network actions.
        """
        return await self.np.get_actions()

    """                                                     ###############################
                                                            # EXTERNAL CONNECTION SERVICE #
                                                            ###############################
    """

    async def _check_external_connection_service_status(self):
        """
        Ensure the external connection service is running; if not, initialize and start beaconing.

        This method checks the ECS status, starts it if necessary,
        subscribes to beacon events, and initiates beacon transmission.
        """
        if not await self.cm.is_external_connection_service_running():
            logging.info("🔄 External Service not running | Starting service...")
            await self.cm.init_external_connection_service()
            await EventManager.get_instance().subscribe_node_event(BeaconRecievedEvent, self.beacon_received)
            await self.cm.start_beacon()

    async def experiment_finish(self, efe: ExperimentFinishEvent):
        """
        Handle the completion of an experiment by shutting down the external connection service.

        Args:
            efe (ExperimentFinishEvent): The event indicating the experiment has finished.
        """
        await self.cm.stop_external_connection_service()

    async def beacon_received(self, beacon_recieved_event: BeaconRecievedEvent):
        """
        Process a received beacon event by publishing a NodeFoundEvent for the given address.

        Extracts the address and geolocation from the beacon event and notifies
        the system that a new node has been discovered.

        Args:
            beacon_recieved_event (BeaconRecievedEvent): The event containing beacon data.
        """
        addr, geoloc = await beacon_recieved_event.get_event_data()
        latitude, longitude = geoloc
        nfe = NodeFoundEvent(addr)
        asyncio.create_task(EventManager.get_instance().publish_node_event(nfe))

    """                                                     ###############################
                                                            #    REESTRUCTURE TOPOLOGY    #
                                                            ###############################
    """

    def _update_restructure_cooldown(self):
        """
        Decrement or wrap the restructure cooldown counter.

        Uses modulo arithmetic to ensure the cooldown cycles correctly,
        preventing frequent restructuring operations.
        """
        if self._restructure_cooldown > 0:
            self._restructure_cooldown = (self._restructure_cooldown + 1) % RESTRUCTURE_COOLDOWN

    def _restructure_available(self):
        """
        Check if restructuring is currently allowed based on the cooldown.

        Returns:
            bool: True if cooldown is zero (restructure allowed), False otherwise.
        """
        if self._restructure_cooldown:
            if self._verbose:
                logging.info("Reestructure on cooldown")
        return self._restructure_cooldown == 0

    def get_restructure_process_lock(self):
        """
        Retrieve the asynchronous lock protecting the restructure process.

        Returns:
            asyncio.Lock: Lock to ensure only one restructure operation runs at a time.
        """
        return self._restructure_process_lock

    async def _analize_topology_robustness(self):
        """
        Analyze the current network topology to assess robustness and suggest SA actions.

        Performs the following checks:
        1. If no neighbors remain, suggest reconnection to the federation.
        2. If more neighbors are needed and restructuring is off cooldown, suggest removing or searching for neighbors.
        3. If excess neighbors exist, suggest disconnecting according to policy.
        4. Otherwise, suggest maintaining current connections.
        5. If a restructure is already in progress, suggest idling.

        Uses neighbor policy decisions and cooldown logic to produce situational awareness commands.
        """
        # TODO update the way of checking
        logging.info("🔄 Analizing node network robustness...")
        if not self._restructure_process_lock.locked():
            if not await self.neighbors_left():
                if self._verbose:
                    logging.info("No Neighbors left | reconnecting with Federation")
                await self.sana.create_and_suggest_action(
                    SACommandAction.RECONNECT, self.reconnect_to_federation, False, None
                )
            elif await self.np.need_more_neighbors() and self._restructure_available():
                if self._verbose:
                    logging.info("Suggesting to Remove neighbors according to policy...")
                if await self.np.any_leftovers_neighbors():
                    nodes_to_remove = await self.np.get_neighbors_to_remove()
                    await self.sana.create_and_suggest_action(
                        SACommandAction.DISCONNECT, self.cm.disconnect, True, nodes_to_remove
                    )
                if self._verbose:
                    logging.info("Insufficient Robustness | Upgrading robustness | Searching for more connections")
                self._update_restructure_cooldown()
                possible_neighbors = await self.np.get_posible_neighbors()
                possible_neighbors = await self.cm.apply_restrictions(possible_neighbors)
                if not possible_neighbors:
                    if self._verbose:
                        logging.info("All possible neighbors using nodes known are restricted...")
                else:
                    pass
                await self.sana.create_and_suggest_action(
                    SACommandAction.SEARCH_CONNECTIONS, self.upgrade_connection_robustness, False, possible_neighbors
                )
            elif await self.np.any_leftovers_neighbors():
                nodes_to_remove = await self.np.get_neighbors_to_remove()
                if self._verbose:
                    logging.info(f"Excess neighbors | removing: {list(nodes_to_remove)}")
                await self.sana.create_and_suggest_action(
                    SACommandAction.DISCONNECT, self.cm.disconnect, False, nodes_to_remove
                )
            else:
                if self._verbose:
                    logging.info("Sufficient Robustness | no actions required")
                await self.sana.create_and_suggest_action(
                    SACommandAction.MAINTAIN_CONNECTIONS,
                    self.cm.clear_unused_undirect_connections,
                    more_suggestions=False,
                )
        else:
            if self._verbose:
                logging.info("❗️ Reestructure/Reconnecting process already running...")
            await self.sana.create_and_suggest_action(SACommandAction.IDLE, more_suggestions=False)

    async def reconnect_to_federation(self):
        """
        Clear any connection restrictions and initiate a late‐connection discovery process
        to rejoin the federation.

        Steps:
        1. Acquire the restructure lock.
        2. Clear blacklist and recently disconnected restrictions.
        3. If known node addresses exist, use them for discovery; otherwise, perform a fresh discovery.
        4. Release the restructure lock.
        """
        logging.info("Going to reconnect with federation...")
        await self._restructure_process_lock.acquire_async()
        await self.cm.clear_restrictions()
        # If we got some refs, try to reconnect to them
        if len(await self.np.get_nodes_known()) > 0:
            if self._verbose:
                logging.info("Reconnecting | Addrs availables")
            await self.sar.sad.start_late_connection_process(
                connected=False, msg_type="discover_nodes", addrs_known=await self.np.get_nodes_known()
            )
        else:
            if self._verbose:
                logging.info("Reconnecting | NO Addrs availables")
            await self.sar.sad.start_late_connection_process(connected=False, msg_type="discover_nodes")
        await self._restructure_process_lock.release_async()

    async def upgrade_connection_robustness(self, possible_neighbors):
        """
        Attempt to strengthen network robustness by discovering or reconnecting to additional neighbors.

        Steps:
        1. Acquire the restructure lock.
        2. If possible_neighbors is non‐empty, use them for a targeted late‐connection discovery.
        3. Otherwise, perform a generic discovery of federation nodes.
        4. Release the restructure lock.

        Args:
            possible_neighbors (set): Addresses of candidate nodes for connection enhancement.
        """
        await self._restructure_process_lock.acquire_async()
        # If we got some refs, try to connect to them
        if possible_neighbors and len(possible_neighbors) > 0:
            if self._verbose:
                logging.info(f"Reestructuring | Addrs availables | addr list: {possible_neighbors}")
            await self.sar.sad.start_late_connection_process(
                connected=True, msg_type="discover_nodes", addrs_known=possible_neighbors
            )
        else:
            if self._verbose:
                logging.info("Reestructuring | NO Addrs availables")
            await self.sar.sad.start_late_connection_process(connected=True, msg_type="discover_nodes")
        await self._restructure_process_lock.release_async()

    async def stop_connections_with_federation(self):
        """
        Disconnect from all current federation neighbors after a short delay.

        1. Waits for a predefined sleep period (to allow in‐flight messages to complete).
        2. Blacklists each direct neighbor.
        3. Disconnects from each neighbor without mutual handshake.
        """
        await asyncio.sleep(10)
        logging.info("### DISCONNECTING FROM FEDERATON ###")
        neighbors = await self.np.get_nodes_known(neighbors_only=True)
        for n in neighbors:
            await self.cm.add_to_blacklist(n)
        for n in neighbors:
            await self.cm.disconnect(n, mutual_disconnection=False, forced=True)

    async def verify_neighbors_stablished(self, nodes: set):
        """
        Verify that a set of connection attempts has succeeded within a timeout.

        Args:
            nodes (set): The set of node addresses for which connections were attempted.

        Behavior:
        1. Sleeps for NEIGHBOR_VERIFICATION_TIMEOUT seconds.
        2. Compares the originally requested nodes against the currently known neighbors.
        3. Logs any addresses that failed to establish and instructs the policy to forget them.
        """
        if not nodes:
            return

        await asyncio.sleep(self.NEIGHBOR_VERIFICATION_TIMEOUT)
        logging.info("Verifyng all connections were stablished")
        nodes_to_forget = nodes.copy()
        neighbors = await self.np.get_nodes_known(neighbors_only=True)
        if neighbors:
            nodes_to_forget.difference_update(neighbors)
        logging.info(f"Connections dont stablished: {nodes_to_forget}")
        await self.forget_nodes(nodes_to_forget)

    async def create_verification_task(self, nodes: set):
        """
        Create and track a verification task for neighbor establishment.

        Args:
            nodes (set): The set of node addresses for which connections were attempted.

        Returns:
            asyncio.Task: The created verification task.
        """
        verification_task = asyncio.create_task(self.verify_neighbors_stablished(nodes))

        async with self._verification_tasks_lock:
            self._verification_tasks.add(verification_task)

        return verification_task

    async def forget_nodes(self, nodes_to_forget):
        """
        Instruct the neighbor policy to remove specified nodes from its known set.

        Args:
            nodes_to_forget (set): Addresses of nodes to be purged from policy memory.
        """
        await self.np.forget_nodes(nodes_to_forget)

    async def stop(self):
        """
        Stop the SANetwork component by releasing locks and clearing any pending operations.
        """
        logging.info("🛑  Stopping SANetwork...")

        # Cancel all verification tasks
        async with self._verification_tasks_lock:
            if self._verification_tasks:
                tasks_to_cancel = [task for task in self._verification_tasks if not task.done()]
                logging.info(f"🛑  Cancelling {len(tasks_to_cancel)} verification tasks...")
                for task in tasks_to_cancel:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                self._verification_tasks.clear()
                logging.info("🛑  All verification tasks cancelled")

        # Release any held locks
        try:
            if self._restructure_process_lock.locked():
                self._restructure_process_lock.release()
        except Exception as e:
            logging.warning(f"Error releasing restructure_process_lock: {e}")

        logging.info("✅  SANetwork stopped successfully")

    """                                                     ###############################
                                                            #       SA NETWORK AGENT      #
                                                            ###############################
    """


class SANetworkAgent(SAModuleAgent):
    def __init__(self, sanetwork: SANetwork):
        self._san = sanetwork

    async def get_agent(self) -> str:
        return "SANetwork_MainNetworkAgent"

    async def register_sa_agent(self):
        await SuggestionBuffer.get_instance().register_event_agents(RoundEndEvent, self)

    async def suggest_action(self, sac: SACommand):
        await SuggestionBuffer.get_instance().register_suggestion(RoundEndEvent, self, sac)

    async def notify_all_suggestions_done(self, event_type):
        await SuggestionBuffer.get_instance().notify_all_suggestions_done_for_agent(self, event_type)

    async def create_and_suggest_action(
        self, saca: SACommandAction, function: Callable = None, more_suggestions=False, *args
    ):
        """
        Create a situational awareness command based on the specified action and suggest it for arbitration.

        Depending on the SACommandAction provided, this method:
        - Instantiates the appropriate SACommand via the factory.
        - Submits the command to the arbitration process (`suggest_action`).
        - Optionally finalizes suggestion collection (`notify_all_suggestions_done`).
        - In some cases waits for execution.

        Args:
            saca (SACommandAction): The situational awareness action to suggest (e.g., SEARCH_CONNECTIONS, RECONNECT).
            function (Callable, optional): The function to execute if the command is chosen. Defaults to None.
            more_suggestions (bool, optional): If False, marks the end of suggestion gathering. Defaults to False.
            *args: Additional positional arguments passed to the SACommand constructor to be used as function parameters.
        """
        sac = None
        if saca == SACommandAction.MAINTAIN_CONNECTIONS:
            sac = factory_sa_command(
                "connectivity", SACommandAction.MAINTAIN_CONNECTIONS, self, "", SACommandPRIO.MEDIUM, False, function
            )
            await self.suggest_action(sac)
            await self.notify_all_suggestions_done(RoundEndEvent)
        elif saca == SACommandAction.SEARCH_CONNECTIONS:
            sac = factory_sa_command(
                "connectivity",
                SACommandAction.SEARCH_CONNECTIONS,
                self,
                "",
                SACommandPRIO.MEDIUM,
                True,
                function,
                *args,
            )
            await self.suggest_action(sac)
            if not more_suggestions:
                await self.notify_all_suggestions_done(RoundEndEvent)
            sa_command_state = await sac.get_state_future()  # By using 'await' we get future.set_result()
            if sa_command_state == SACommandState.EXECUTED:
                (nodes_to_forget,) = args
                await self._san.create_verification_task(nodes_to_forget)
        elif saca == SACommandAction.RECONNECT:
            sac = factory_sa_command(
                "connectivity", SACommandAction.RECONNECT, self, "", SACommandPRIO.HIGH, True, function
            )
            await self.suggest_action(sac)
            if not more_suggestions:
                await self.notify_all_suggestions_done(RoundEndEvent)
        elif saca == SACommandAction.DISCONNECT:
            nodes = args[0] if isinstance(args[0], set) else set(args)
            for node in nodes:
                sac = factory_sa_command(
                    "connectivity",
                    SACommandAction.DISCONNECT,
                    self,
                    node,
                    SACommandPRIO.HIGH,
                    True,
                    function,
                    node,
                    True,
                )
                # TODO Check executed state to ensure node is removed
                await self.suggest_action(sac)
            if not more_suggestions:
                await self.notify_all_suggestions_done(RoundEndEvent)
        elif saca == SACommandAction.IDLE:
            sac = factory_sa_command(
                "connectivity", SACommandAction.IDLE, self, "", SACommandPRIO.LOW, False, function, None
            )
            await self.suggest_action(sac)
            if not more_suggestions:
                await self.notify_all_suggestions_done(RoundEndEvent)

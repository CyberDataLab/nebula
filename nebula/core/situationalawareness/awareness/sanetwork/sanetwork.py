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
        self._restructure_process_lock = Locker(name="restructure_process_lock")
        self._restructure_cooldown = 0
        self._verbose = config["verbose"]  # verbose
        self._cm = CommunicationsManager.get_instance()
        self._sa_network_agent = SANetworkAgent(self)

    @property
    def sar(self) -> SAReasoner:
        """SA Reasoner"""
        return self._sar

    @property
    def cm(self):
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
        logging.info("SA Network evaluating current scenario")
        await self._check_external_connection_service_status()
        await self._analize_topology_robustness()

    """                                                     ###############################
                                                            #       NEIGHBOR POLICY       #
                                                            ###############################
    """

    async def _process_node_found_event(self, nfe: NodeFoundEvent):
        node_addr = await nfe.get_event_data()
        await self.np.meet_node(node_addr)

    async def _process_update_neighbor_event(self, une: UpdateNeighborEvent):
        node_addr, removed = await une.get_event_data()
        if self._verbose:
            logging.info(f"Processing Update Neighbor Event, node addr: {node_addr}, remove: {removed}")
        await self.np.update_neighbors(node_addr, removed)

    async def meet_node(self, node):
        if node != self._addr:
            await self.np.meet_node(node)

    async def get_nodes_known(self, neighbors_too=False, neighbors_only=False):
        return await self.np.get_nodes_known(neighbors_too, neighbors_only)

    async def neighbors_left(self):
        return len(await self.cm.get_addrs_current_connections(only_direct=True, myself=False)) > 0

    async def accept_connection(self, source, joining=False):
        accepted = await self.np.accept_connection(source, joining)
        return accepted

    async def need_more_neighbors(self):
        return await self.np.need_more_neighbors()

    async def get_actions(self):
        return await self.np.get_actions()

    """                                                     ###############################
                                                            # EXTERNAL CONNECTION SERVICE #
                                                            ###############################
    """

    async def _check_external_connection_service_status(self):
        if not await self.cm.is_external_connection_service_running():
            logging.info("🔄 External Service not running | Starting service...")
            await self.cm.init_external_connection_service()
            await EventManager.get_instance().subscribe_node_event(BeaconRecievedEvent, self.beacon_received)
            await self.cm.start_beacon()

    async def experiment_finish(self):
        await self.cm.stop_external_connection_service()

    async def beacon_received(self, beacon_recieved_event: BeaconRecievedEvent):
        addr, geoloc = await beacon_recieved_event.get_event_data()
        latitude, longitude = geoloc
        nfe = NodeFoundEvent(addr)
        asyncio.create_task(EventManager.get_instance().publish_node_event(nfe))

    """                                                     ###############################
                                                            #    REESTRUCTURE TOPOLOGY    #
                                                            ###############################
    """

    def _update_restructure_cooldown(self):
        if self._restructure_cooldown > 0:
            self._restructure_cooldown = (self._restructure_cooldown + 1) % RESTRUCTURE_COOLDOWN

    def _restructure_available(self):
        if self._restructure_cooldown:
            if self._verbose:
                logging.info("Reestructure on cooldown")
        return self._restructure_cooldown == 0

    def get_restructure_process_lock(self):
        return self._restructure_process_lock

    async def _analize_topology_robustness(self):
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
        logging.info("Going to reconnect with federation...")
        self._restructure_process_lock.acquire()
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
        self._restructure_process_lock.release()

    async def upgrade_connection_robustness(self, possible_neighbors):
        self._restructure_process_lock.acquire()
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
        self._restructure_process_lock.release()

    async def stop_connections_with_federation(self):
        await asyncio.sleep(10)
        logging.info("### DISCONNECTING FROM FEDERATON ###")
        neighbors = await self.np.get_nodes_known(neighbors_only=True)
        for n in neighbors:
            await self.cm.add_to_blacklist(n)
        for n in neighbors:
            await self.cm.disconnect(n, mutual_disconnection=False, forced=True)

    async def verify_neighbors_stablished(self, nodes: set):
        if not nodes:
            return

        await asyncio.sleep(self.NEIGHBOR_VERIFICATION_TIMEOUT)
        logging.info("Verifyng all connections were stablished")
        nodes_to_forget = nodes.copy()
        neighbors = await self.np.get_nodes_known(neighbors_only=True)
        if neighbors:
            nodes_to_forget.difference_update(neighbors)
        logging.info(f"Connections dont stablished: {nodes_to_forget}")
        self.forget_nodes(nodes_to_forget)

    async def forget_nodes(self, nodes_to_forget):
        await self.np.forget_nodes(nodes_to_forget)

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
                asyncio.create_task(self._san.verify_neighbors_stablished(nodes_to_forget))
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

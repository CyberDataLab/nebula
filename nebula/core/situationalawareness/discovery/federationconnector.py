import asyncio
import logging
from typing import TYPE_CHECKING

from nebula.addons.functions import print_msg_box
from nebula.core.situationalawareness.discovery.candidateselection.candidateselector import factory_CandidateSelector
from nebula.core.situationalawareness.discovery.modelhandlers.modelhandler import factory_ModelHandler
from nebula.core.situationalawareness.situationalawareness import ISADiscovery, ISAReasoner
from nebula.core.utils.locker import Locker
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateNeighborEvent, NodeFoundEvent
from nebula.core.network.communications import CommunicationsManager
from functools import cached_property

if TYPE_CHECKING:
    from nebula.core.engine import Engine

RESTRUCTURE_COOLDOWN = 5
OFFER_TIMEOUT = 5

class FederationConnector(ISADiscovery):
    """
    Responsible for the discovery and operational management of the federation within the Situational Awareness module.

    The FederationConnector implements the ISADiscovery interface and coordinates both the discovery 
    of participants in the federation and the operational steps required to integrate them into the 
    Situational Awareness (SA) workflow. Its responsibilities include:

    - Initiating the discovery process using the configured CandidateSelector and ModelHandler.
    - Managing neighbor evaluation and model exchange.
    - Interfacing with the SAReasoner to accept connections and ask for actions to do in response.
    - Applying neighbor policies and orchestrating topology changes.
    - Acting as the operational core of the SA module by executing workflows and ensuring coordination.

    This class bridges the discovery logic with situational response capabilities in decentralized or federated systems.
    """
    def __init__(
        self,
        aditional_participant,
        selector,
        model_handler,
        engine: "Engine",
        verbose=False
    ):
        self._aditional_participant = aditional_participant
        self._selector = selector
        print_msg_box(
            msg=f"Starting FederationConnector module...", indent=2, title="FederationConnector module"
        )
        logging.info("🌐  Initializing Federation Connector")
        self._engine = engine
        self._cm = None
        self.config = engine.get_config()
        logging.info("Initializing Candidate Selector")
        self._candidate_selector = factory_CandidateSelector(self._selector)
        logging.info("Initializing Model Handler")
        self._model_handler = factory_ModelHandler(model_handler)
        self._update_neighbors_lock = Locker(name="_update_neighbors_lock", async_lock=True)
        self.late_connection_process_lock = Locker(name="late_connection_process_lock")
        self.pending_confirmation_from_nodes = set()
        self.pending_confirmation_from_nodes_lock = Locker(name="pending_confirmation_from_nodes_lock", async_lock=True)
        self.accept_candidates_lock = Locker(name="accept_candidates_lock")
        self.recieve_offer_timer = OFFER_TIMEOUT
        self.discarded_offers_addr_lock = Locker(name="discarded_offers_addr_lock", async_lock=True)
        self.discarded_offers_addr = []
        
        self._sa_reasoner: ISAReasoner = None
        self._verbose = verbose

    @property
    def engine(self):
        return self._engine
    
    @cached_property
    def cm(self):
        return CommunicationsManager.get_instance()

    @property
    def candidate_selector(self):
        return self._candidate_selector

    @property
    def model_handler(self):
        return self._model_handler

    @property
    def sar(self):
        """Situational Awareness Reasoner"""
        return self._sa_reasoner

    async def init(self, sa_reasoner):
        """
        model_handler config:
            - self total rounds
            - self current round
            - self epochs

        candidate_selector config:
            - self model loss
            - self weight distance
            - self weight hetereogeneity
        """
        logging.info("Building Federation Connector configurations...")
        self._sa_reasoner: ISAReasoner = sa_reasoner
        await self._register_message_events_callbacks()
        await EventManager.get_instance().subscribe_node_event(UpdateNeighborEvent, self._update_neighbors)
        await EventManager.get_instance().subscribe(("model", "update"), self._model_update_callback)
        
        logging.info("Building candidate selector configuration..")
        self.candidate_selector.set_config([0, 0.5, 0.5])
        # self.engine.trainer.get_loss(), self.config.participant["molibity_args"]["weight_distance"], self.config.participant["molibity_args"]["weight_het"]
             
    """
                ##############################
                #        CONNECTIONS         #
                ##############################
    """
    
    def _accept_connection(self, source, joining=False):
        return self.sar.accept_connection(source, joining)
    
    def _still_waiting_for_candidates(self):
        return not self.accept_candidates_lock.locked() and self.late_connection_process_lock.locked()

    async def _add_pending_connection_confirmation(self, addr):
        async with self._update_neighbors_lock:
            async with self.pending_confirmation_from_nodes_lock:
                if addr not in self.sar.get_nodes_known(neighbors_only=True):
                    logging.info(f"Addition | pending connection confirmation from: {addr}")
                    self.pending_confirmation_from_nodes.add(addr)

    async def _remove_pending_confirmation_from(self, addr):
        async with self.pending_confirmation_from_nodes_lock:
            self.pending_confirmation_from_nodes.discard(addr)

    async def _clear_pending_confirmations(self):
        async with self.pending_confirmation_from_nodes_lock:
            self.pending_confirmation_from_nodes.clear()

    async def _waiting_confirmation_from(self, addr):
        async with self.pending_confirmation_from_nodes_lock:
            found = addr in self.pending_confirmation_from_nodes
        return found

    async def _confirmation_received(self, addr, joining=False):
        logging.info(f" Update | connection confirmation received from: {addr} | joining federation: {joining}")
        await self.cm.connect(addr, direct=True)
        await self._remove_pending_confirmation_from(addr)
        une = UpdateNeighborEvent(addr, joining=joining)
        await EventManager.get_instance().publish_node_event(une)
            
    async def _add_to_discarded_offers(self, addr_discarded):
        async with self.discarded_offers_addr_lock:
            self.discarded_offers_addr.append(addr_discarded)

    def _get_actions(self):
        return self.sar.get_actions()

    async def _register_late_neighbor(self, addr, joinning_federation=False):
        if self._verbose: logging.info(f"Registering | late neighbor: {addr}, joining: {joinning_federation}")
        une = UpdateNeighborEvent(addr, joining=joinning_federation)
        await EventManager.get_instance().publish_node_event(une)

    async def _update_neighbors(self, une : UpdateNeighborEvent):
        node, remove = await une.get_event_data()
        await self._update_neighbors_lock.acquire_async()
        if not remove:
            await self._meet_node(node)
        await self._remove_pending_confirmation_from(node)
        await self._update_neighbors_lock.release_async()

    async def _meet_node(self, node):
        nfe = NodeFoundEvent(node)
        await EventManager.get_instance().publish_node_event(nfe)

    def accept_model_offer(self, source, decoded_model, rounds, round, epochs, n_neighbors, loss):
        """
        Evaluate and possibly accept a model offer from a remote source.

        Parameters:
            source (str): Identifier of the node sending the model.
            decoded_model (object): The model received and decoded from the sender.
            rounds (int): Total number of training rounds in the current session.
            round (int): Current round.
            epochs (int): Number of epochs assigned for local training.
            n_neighbors (int): Number of neighbors of the sender.
            loss (float): Loss value associated with the proposed model.

        Returns:
            bool: True if the model is accepted and the sender added as a candidate, False otherwise.
        """
        if not self.accept_candidates_lock.locked():
            if self._verbose: logging.info(f"🔄 Processing offer from {source}...")
            model_accepted = self.model_handler.accept_model(decoded_model)
            self.model_handler.set_config(config=(rounds, round, epochs, self))
            if model_accepted:
                self.candidate_selector.add_candidate((source, n_neighbors, loss))
                return True
        else:
            return False

    async def get_trainning_info(self):
        return await self.model_handler.get_model(None)

    def _add_candidate(self, source, n_neighbors, loss):
        if not self.accept_candidates_lock.locked():
            self.candidate_selector.add_candidate((source, n_neighbors, loss))

    async def _stop_not_selected_connections(self, rejected: set = {}):
        """
        Asynchronously stop connections that were not selected after a waiting period.

        Parameters:
            rejected (set): A set of node addresses that were explicitly rejected 
                            and should be marked for disconnection.
        """
        await asyncio.sleep(5)
        for r in rejected:
            await self._add_to_discarded_offers(r)
            
        try:
            async with self.discarded_offers_addr_lock:
                if len(self.discarded_offers_addr) > 0:
                    self.discarded_offers_addr = set(
                        self.discarded_offers_addr
                    ) - await self.cm.get_addrs_current_connections(only_direct=True, myself=False)
                    if self._verbose: logging.info(
                        f"Interrupting connections | discarded offers | nodes discarded: {self.discarded_offers_addr}"
                    )
                    for addr in self.discarded_offers_addr:
                        await self.cm.disconnect(addr, mutual_disconnection=True)
                        await asyncio.sleep(1)
                    self.discarded_offers_addr = []
        except asyncio.CancelledError:
            pass

    async def start_late_connection_process(self, connected=False, msg_type="discover_join", addrs_known=None):
        """
        This function represents the process of discovering the federation and stablish the first
        connections with it. The first step is to send the DISCOVER_JOIN/NODES message to look for nodes,
        the ones that receive that message will send back a OFFER_MODEL/METRIC message. It contains info to do
        a selection process among candidates to later on connect to the best ones.
        The process will repeat until at least one candidate is found and the process will be locked
        to avoid concurrency.
        """
        logging.info("🌐  Initializing late connection process..")

        self.late_connection_process_lock.acquire()
        best_candidates = []
        self.candidate_selector.remove_candidates()
        await self._clear_pending_confirmations()

        # find federation and send discover
        discovers_sent, connections_stablished = await self.cm.stablish_connection_to_federation(msg_type, addrs_known)

        # wait offer
        if self._verbose: logging.info(f"Discover messages sent after finding federation: {discovers_sent}")
        if discovers_sent:
            if self._verbose: logging.info(f"Waiting: {self.recieve_offer_timer}s to receive offers from federation")
            await asyncio.sleep(self.recieve_offer_timer)

        # acquire lock to not accept late candidates
        self.accept_candidates_lock.acquire()

        if self.candidate_selector.any_candidate():
            if self._verbose: logging.info("Candidates found to connect to...")
            # create message to send to candidates selected
            if not connected:
                msg = self.cm.create_message("connection", "late_connect")
            else:
                msg = self.cm.create_message("connection", "restructure")

            best_candidates, rejected_candidates = self.candidate_selector.select_candidates()
            if self._verbose: logging.info(f"Candidates | {[addr for addr, _, _ in best_candidates]}")
            try:
                for addr, _, _ in best_candidates:
                    await self._add_pending_connection_confirmation(addr)
                    await self.cm.send_message(addr, msg)
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                # upe = UpdateNeighborEvent(addr, removed=True)
                # asyncio.create_task(EventManager.get_instance().publish_node_event(upe))
                if self._verbose: logging.info("Error during stablishment")
                
            asyncio.create_task(self._stop_not_selected_connections({rc[0]for rc in rejected_candidates}))
            self.accept_candidates_lock.release()
            self.late_connection_process_lock.release()
            self.candidate_selector.remove_candidates()
            logging.info("🌐  Ending late connection process..")
        # if no candidates, repeat process
        else:
            if self._verbose: logging.info("❗️  No Candidates found...")
            if connected:
                asyncio.create_task(self._stop_not_selected_connections(connections_stablished))
            self.accept_candidates_lock.release()
            self.late_connection_process_lock.release()
            if not connected:
                if self._verbose: logging.info("❗️  repeating process...")
                await self.start_late_connection_process(connected, msg_type, addrs_known)


    """                                                     ##############################
                                                            #     Mobility callbacks     #
                                                            ##############################
    """

    async def _register_message_events_callbacks(self):
        me_dict = self.cm.get_messages_events()
        message_events = [
            (message_name, message_action)
            for (message_name, message_actions) in me_dict.items()
            for message_action in message_actions
        ]
        for event_type, action in message_events:
            callback_name = f"_{event_type}_{action}_callback"
            method = getattr(self, callback_name, None)

            if callable(method):
                await EventManager.get_instance().subscribe((event_type, action), method)
                
    async def _connection_disconnect_callback(self, source, message):
        if await self._waiting_confirmation_from(source):
            await self._confirmation_received(source, confirmation=False)

    async def _model_update_callback(self, source, message):
        if await self._waiting_confirmation_from(source):
            await self._confirmation_received(source, confirmation=False)

    async def _connection_late_connect_callback(self, source, message):
        logging.info(f"🔗  handle_connection_message | Trigger | Received late connect message from {source}")
        # Verify if it's a confirmation message from a previous late connection message sent to source
        if await self._waiting_confirmation_from(source):
            await self._confirmation_received(source, joining=False)
            return

        if not self.engine.get_initialization_status():
            logging.info("❗️ Connection refused | Device not initialized yet...")
            return

        if self._accept_connection(source, joining=True):
            logging.info(f"🔗  handle_connection_message | Late connection accepted | source: {source}")
            await self.cm.connect(source, direct=True)

            # Verify conenction is accepted
            conf_msg = self.cm.create_message("connection", "late_connect")
            await self.cm.send_message(source, conf_msg)

            ct_actions, df_actions = self._get_actions()
            logging.info("voy a mostrar acciones en respuesta a late connect")
            if len(ct_actions):
                logging.info("1 acciones")
                logging.info(f"{ct_actions}")
                cnt_msg = self.cm.create_message("link", "connect_to", addrs=ct_actions)
                await self.cm.send_message(source, cnt_msg)

            if len(df_actions):
                logging.info("2 acciones")
                logging.info(f"{df_actions}")
                for addr in df_actions.split():
                    await self.cm.disconnect(addr, mutual_disconnection=True)
                # df_msg = self.cm.create_message("link", "disconnect_from", addrs=df_actions)
                # await self.cm.send_message(source, df_msg)

            await self._register_late_neighbor(source, joinning_federation=True)

        else:
            logging.info(f"❗️  Late connection NOT accepted | source: {source}")

    async def _connection_restructure_callback(self, source, message):
        logging.info(f"🔗  handle_connection_message | Trigger | Received restructure message from {source}")
        # Verify if it's a confirmation message from a previous restructure connection message sent to source
        if await self._waiting_confirmation_from(source):
            await self._confirmation_received(source)
            return

        if not self.engine.get_initialization_status():
            logging.info("❗️ Connection refused | Device not initialized yet...")
            return

        if self._accept_connection(source, joining=False):
            logging.info(f"🔗  handle_connection_message | Trigger | restructure connection accepted from {source}")
            await self.cm.connect(source, direct=True)

            conf_msg = self.cm.create_message("connection", "restructure")
            await self.cm.send_message(source, conf_msg)

            ct_actions, df_actions = self._get_actions()
            if len(ct_actions):
                cnt_msg = self.cm.create_message("link", "connect_to", addrs=ct_actions)
                await self.cm.send_message(source, cnt_msg)
                
            if len(df_actions):
                for addr in df_actions.split():
                    await self.cm.disconnect(addr, mutual_disconnection=True)
                # df_msg = self.cm.create_message("link", "disconnect_from", addrs=df_actions)
                # await self.cm.send_message(source, df_msg)
            
            await self._register_late_neighbor(source, joinning_federation=False)
        else:
            logging.info(f"❗️  handle_connection_message | Trigger | restructure connection denied from {source}")

    async def _discover_discover_join_callback(self, source, message):
        logging.info(f"🔍  handle_discover_message | Trigger | Received discover_join message from {source} ")
        if len(await self.engine.get_federation_nodes()) > 0:
            await self.engine.trainning_in_progress_lock.acquire_async()
            model, rounds, round = (
                await self.cm.propagator.get_model_information(source, "stable")
                if self.engine.get_round() > 0
                else await self.cm.propagator.get_model_information(source, "initialization")
            )
            await self.engine.trainning_in_progress_lock.release_async()
            if round != -1:
                epochs = self.config.participant["training_args"]["epochs"]
                msg = self.cm.create_message(
                    "offer",
                    "offer_model",
                    len(await self.engine.get_federation_nodes()),
                    0,
                    parameters=model,
                    rounds=rounds,
                    round=round,
                    epochs=epochs,
                )
                logging.info(f"Sending offer model to {source}")
                await self.cm.send_message(source, msg, is_compressed=True)
            else:
                logging.info("Discover join received before federation is running..")
                # starter node is going to send info to the new node
        else:
            logging.info(f"🔗  Dissmissing discover join from {source} | no active connections at the moment")

    async def _discover_discover_nodes_callback(self, source, message):
        logging.info(f"🔍  handle_discover_message | Trigger | Received discover_node message from {source} ")
        if len(await self.engine.get_federation_nodes()) > 0:
            if self._accept_connection(source, joining=False):
                msg = self.cm.create_message(
                    "offer",
                    "offer_metric",
                    n_neighbors=len(await self.engine.get_federation_nodes()),
                    loss=0 #self.engine.trainer.get_current_loss(),
                )
                logging.info(f"Sending offer metric to {source}")
                await self.cm.send_message(source, msg)
        else:
            logging.info(f"🔗  Dissmissing discover nodes from {source} | no active connections at the moment")

    async def _offer_offer_model_callback(self, source, message):
        logging.info(f"🔍  handle_offer_message | Trigger | Received offer_model message from {source}")
        await self._meet_node(source)
        if self._still_waiting_for_candidates():
            try:
                model_compressed = message.parameters
                if self.accept_model_offer(
                    source,
                    model_compressed,
                    message.rounds,
                    message.round,
                    message.epochs,
                    message.n_neighbors,
                    message.loss,
                ):
                    logging.info(f"🔧 Model accepted from offer | source: {source}")
                else:
                    logging.info(f"❗️ Model offer discarded | source: {source}")
                    await self._add_to_discarded_offers(source)
            except RuntimeError:
                logging.info(f"❗️ Error proccesing offer model from {source}")
        else:
            logging.info(
                f"❗️ handfle_offer_message | NOT accepting offers | waiting candidates: {self._still_waiting_for_candidates()}"
            )
            await self._add_to_discarded_offers(source)

    async def _offer_offer_metric_callback(self, source, message):
        logging.info(f"🔍  handle_offer_message | Trigger | Received offer_metric message from {source}")
        await self._meet_node(source)
        if self._still_waiting_for_candidates():
            n_neighbors = message.n_neighbors
            loss = message.loss
            self._add_candidate(source, n_neighbors, loss)

    async def _link_connect_to_callback(self, source, message):
        logging.info(f"🔗  handle_link_message | Trigger | Received connect_to message from {source}")
        addrs = message.addrs
        for addr in addrs.split():
            await self._meet_node(addr)

    async def _link_disconnect_from_callback(self, source, message):
        logging.info(f"🔗  handle_link_message | Trigger | Received disconnect_from message from {source}")
        addrs = message.addrs
        for addr in addrs.split():
            await asyncio.create_task(self.cm.disconnect(addr, mutual_disconnection=False))
                



from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.trainingpolicy import TrainingPolicy
import asyncio
from nebula.core.utils.helper import cosine_metric
from nebula.core.utils.locker import Locker
from collections import deque
import logging
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import AggregationEvent, UpdateNeighborEvent, RoundEndEvent
from nebula.core.situationalawareness.awareness.suggestionbuffer import SuggestionBuffer
from nebula.core.situationalawareness.awareness.sautils.sacommand import SACommand, SACommandAction, SACommandPRIO, factory_sa_command
from nebula.core.network.communications import CommunicationsManager
import math

# "Quality-Driven Selection"    (QDS)
class QDSTrainingPolicy(TrainingPolicy):
    """
    Implements a Quality-Driven Selection (QDS) strategy for training in DFL.
    
    This policy tracks the cosine similarity of neighbor model updates over time,
    and detects nodes that are inactive or provide redundant updates.
    Based on these evaluations, the policy suggests disconnecting such nodes
    to promote better model convergence and network efficiency.
    """
    
    MAX_HISTORIC_SIZE = 10
    SIMILARITY_THRESHOLD = 0.73
    INACTIVE_THRESHOLD = 3
    GRACE_ROUNDS = 0
    CHECK_COOLDOWN = 10000

    def __init__(self, config : dict):
        """
        Initializes the QDS training policy.
        
        Args:
            config (dict): Configuration dictionary with keys:
                - "addr": Local node address.
                - "verbose": Boolean flag for logging verbosity.
        """
        self._addr = config["addr"]
        self._verbose = config["verbose"]
        self._nodes : dict[str, tuple[deque, int]] = {}
        self._nodes_lock = Locker(name="nodes_lock", async_lock=True)
        self._round_missing_nodes = set()
        self._grace_rounds = self.GRACE_ROUNDS
        self._last_check = 0
        self._check_done = False
        self._evaluation_results = set()
        
    def __str__(self):
        return "QDS"

    async def init(self, config):
        """
        Initializes the internal state and subscribes to necessary events.

        Args:
            config (dict): Must contain a 'nodes' set representing known neighbors.
        """
        async with self._nodes_lock:
            nodes = config["nodes"]
            self._nodes : dict[str, tuple[deque, int]] = {node_id: (deque(maxlen=self.MAX_HISTORIC_SIZE), 0) for node_id in nodes}
        await EventManager.get_instance().subscribe_node_event(AggregationEvent, self._process_aggregation_event)
        await EventManager.get_instance().subscribe_node_event(UpdateNeighborEvent, self._update_neighbors)
        await self.register_sa_agent()

    async def _update_neighbors(self, une: UpdateNeighborEvent):
        """
        Updates the internal list of neighbors based on topology changes.

        Args:
            une (UpdateNeighborEvent): Event containing added/removed neighbor information.
        """
        node, remove = await une.get_event_data()
        async with self._nodes_lock:
            if remove:
                self._nodes.pop(node, None)
            else:
                if not node in self._nodes:
                    self._nodes.update({node : (deque(maxlen=self.MAX_HISTORIC_SIZE), 0)})

    async def _process_aggregation_event(self, agg_ev : AggregationEvent):
        """
        Processes an AggregationEvent and updates similarity/inactivity metrics.

        Args:
            agg_ev (AggregationEvent): Aggregation event with model updates and missing nodes.
        """
        if self._verbose: logging.info("Processing aggregation event")
        (updates, expected_nodes, missing_nodes) = await agg_ev.get_event_data()
        self._round_missing_nodes = missing_nodes
        self_updt = updates[self._addr]
        async with self._nodes_lock:
            for addr, updt in updates.items():
                if addr == self._addr: continue
                if not addr in self._nodes.keys(): continue
                
                deque_history, missed_count = self._nodes[addr]
                if addr in missing_nodes:
                    if self._verbose: logging.info(f"Node inactivity counter increased for: {addr}")
                    self._nodes[addr] = (deque_history, missed_count + 1)   # Inactive rounds counter +1
                else:
                    self._nodes[addr] = (deque_history, 0)                  # Reset inactive counter
                    
                #TODO Do it for the ones not using the last update received cause they are missing this round                      
                (model,_) = updt
                (self_model, _) = self_updt 
                cos_sim = cosine_metric(self_model, model, similarity=True)
                self._nodes[addr][0].append(cos_sim)
        self._evaluation_results = await self.evaluate()
        
    async def _get_nodes(self):
        """
        Safely returns a copy of the current node tracking dictionary.

        Returns:
            dict: A copy of the internal node state.
        """
        async with self._nodes_lock:
            nodes = self._nodes.copy()
        return nodes    
    
    async def evaluate(self):
        """
        Evaluates the current neighbor set to determine inactive or redundant nodes.

        Returns:
            set: A set of node addresses suggested for disconnection.
        """
        if self._grace_rounds:  # Grace rounds
            self._grace_rounds -= 1
            if self._verbose: logging.info("Grace time hasnt finished...")
            return None
        
        if self._verbose: logging.info("Evaluation in process")
    
        result = set()     
        if self._last_check == 0:
            self._check_done = True
            nodes = await self._get_nodes()
            redundant_nodes = set()
            inactive_nodes = set()
            for node in nodes:
                if nodes[node][0]:
                    last_sim = nodes[node][0][-1]
                    inactivity_counter =  nodes[node][1]
                    if inactivity_counter >= self.INACTIVE_THRESHOLD:
                        inactive_nodes.add(node)
                        if self._verbose: logging.info(f"Node: {node} hadn't participated in any of the last {self.INACTIVE_THRESHOLD} rounds")
                    else:
                        if self._verbose: logging.info(f"Node: {node} inactivity counter: {inactivity_counter}")
                        
                    if node not in self._round_missing_nodes:
                        if last_sim < self.SIMILARITY_THRESHOLD:
                            if self._verbose: logging.info(f"Node: {node} got a similarity value of: {last_sim} under threshold: {self.SIMILARITY_THRESHOLD}")
                        else:
                            if self._verbose: logging.info(f"Node: {node} got a redundant model, cossine simmilarity: {last_sim} over threshold: {self.SIMILARITY_THRESHOLD}")
                            redundant_nodes.add((node, last_sim))
                        
            if self._verbose: logging.info(f"Inactive nodes on aggregations: {inactive_nodes}")
            if self._verbose: logging.info(f"Redundant nodes on aggregations: {redundant_nodes}")
            if inactive_nodes:
                result = result.union(inactive_nodes)    
            if len(redundant_nodes):
                sorted_redundant_nodes = sorted(redundant_nodes, key=lambda x: x[1])
                n_discarded = math.ceil((len(redundant_nodes)/2))
                discard_nodes = sorted_redundant_nodes[:n_discarded]
                discard_nodes = [node for (node,_) in discard_nodes]
                if self._verbose: logging.info(f"Discarded redundant nodes: {discard_nodes}")
                result = result.union(discard_nodes)
        else:
            if self._verbose: logging.info(f"Evaluation is on cooldown... | {self.CHECK_COOLDOWN - self._last_check} rounds remaining")
            self._check_done = False
            
        self._last_check = (self._last_check + 1)  % self.CHECK_COOLDOWN
                             
        return result
    
    async def get_evaluation_results(self):
        """
        Triggers suggested actions based on last evaluation results.

        Suggests disconnection from nodes marked as inactive or redundant.
        """
        if self._check_done:
            for node_discarded in self._evaluation_results:
                args = (node_discarded, False, True)
                sac = factory_sa_command(
                    "connectivity",                        
                    SACommandAction.DISCONNECT,
                    self,           
                    node_discarded,                       
                    SACommandPRIO.MEDIUM,                 
                    False,                                
                    CommunicationsManager.get_instance().disconnect,  
                    *args                                  
                )
                await self.suggest_action(sac)
            await self.notify_all_suggestions_done(RoundEndEvent)

    async def get_agent(self) -> str:
        return "SATraining_QDSTP"

    async def register_sa_agent(self):
        await SuggestionBuffer.get_instance().register_event_agents(RoundEndEvent, self)
    
    async def suggest_action(self, sac : SACommand):
        await SuggestionBuffer.get_instance().register_suggestion(RoundEndEvent, self, sac)
    
    async def notify_all_suggestions_done(self, event_type):
        await SuggestionBuffer.get_instance().notify_all_suggestions_done_for_agent(self, event_type)
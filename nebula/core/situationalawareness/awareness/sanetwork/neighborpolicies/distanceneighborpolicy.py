from nebula.core.situationalawareness.awareness.sanetwork.neighborpolicies.neighborpolicy import NeighborPolicy
from nebula.core.utils.locker import Locker
import logging
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import GPSEvent

class DistanceNeighborPolicy(NeighborPolicy):
    MAX_DISTANCE_THRESHOLD = 100

    def __init__(self):
        self.max_neighbors = None
        self.nodes_known = set()
        self.neighbors = set()
        self.addr = None
        self.neighbors_lock = Locker(name="neighbors_lock", async_lock=True)
        self.nodes_known_lock = Locker(name="nodes_known_lock", async_lock=True)
        self.nodes_distances: dict[str, tuple[float, tuple[float, float]]] = None
        self.nodes_distances_lock = Locker("nodes_distances_lock", async_lock=True)

    async def set_config(self, config):
        """
        Args:
            config[0] -> list of self neighbors
            config[1] -> list of nodes known on federation
            config[2] -> self addr
            config[3] -> stricted_topology
        """
        logging.info("Initializing Random Topology Neighbor Policy")
        async with self.neighbors_lock:
            self.neighbors = config[0] 
        for addr in config[1]:
                self.nodes_known.add(addr)
        self.addr

        await EventManager.get_instance().subscribe_addonevent(GPSEvent, self._udpate_distances)

    async def _udpate_distances(self, gpsevent: GPSEvent):
        async with self.nodes_distances_lock:
            distances = await gpsevent.get_event_data()
            self.nodes_distances = distances   

    async def need_more_neighbors(self):
        async with self.neighbors_lock:
            async with self.nodes_distances_lock:
                if not self.nodes_distances:
                    return False
                
                closest_nodes: set[str] = {
                    nodo_id
                    for nodo_id, (distancia, _) in self.nodes_distances.items()
                    if distancia < self.MAX_DISTANCE_THRESHOLD
                }
                available_nodes = closest_nodes.difference(self.neighbors)
                logging.info(f"Available neighbors based on distance: {available_nodes}")
                return len(available_nodes) > 0
          
    async def accept_connection(self, source, joining=False):
        """
            return true if connection is accepted
        """
        async with self.neighbors_lock:
            ac = (not source in self.neighbors)
        return ac
    
    async def meet_node(self, node):
        """
            Update the list of nodes known on federation
        """
        async with self.nodes_known_lock:
            if node != self.addr:
                if not node in self.nodes_known: logging.info(f"Update nodes known | addr: {node}")
                self.nodes_known.add(node)
        
    async def get_nodes_known(self, neighbors_too=False, neighbors_only=False):     
        if neighbors_only:
            async with self.neighbors_lock:
                no = self.neighbors.copy()
                return no
        
        async with self.nodes_known_lock:
            nk = self.nodes_known.copy()
            if not neighbors_too:
                async with self.neighbors_lock:
                    nk = self.nodes_known - self.neighbors
        return nk     
    
    async def forget_nodes(self, nodes, forget_all=False):
        async with self.nodes_known_lock:
            if forget_all:
                self.nodes_known.clear()
            else:
                for node in nodes:
                    self.nodes_known.discard(node)
        
    async def get_actions(self): 
        """
            return list of actions to do in response to connection
                - First list represents addrs argument to LinkMessage to connect to
                - Second one represents the same but for disconnect from LinkMessage
        """ 
        return [await self._connect_to(), await self._disconnect_from()]
            
    async def _disconnect_from(self):
        return ""
    
    async def _connect_to(self):
        ct = ""
        async with self.neighbors_lock:
            ct = " ".join(self.neighbors)
        return ct
    
    async def update_neighbors(self, node, remove=False):
        if node == self.addr:
            return
        async with self.neighbors_lock:
            if remove:
                try:
                    self.neighbors.remove(node)
                    logging.info(f"Remove neighbor | addr: {node}")
                except KeyError:
                    pass    
            else:
                self.neighbors.add(node)
                logging.info(f"Add neighbor | addr: {node}")

    async def get_posible_neighbors(self):
        """Return set of posible neighbors to connect to."""
        async with self.neighbors_lock:
            async with self.nodes_distances_lock:
                closest_nodes: set[str] = {
                    nodo_id
                    for nodo_id, (distancia, _) in self.nodes_distances.items()
                    if distancia < self.MAX_DISTANCE_THRESHOLD-20
                }
                logging.info(f"Closest nodes: {closest_nodes}, neighbors: {self.neighbors}")
                available_nodes = closest_nodes.difference(self.neighbors)
                logging.info(f"Available neighbors based on distance: {available_nodes}")
                return available_nodes

    async def any_leftovers_neighbors(self):
        distant_nodes = set()
        async with self.neighbors_lock:
            async with self.nodes_distances_lock:
                if not self.nodes_distances:
                    return False
                
                distant_nodes: set[str] = {
                    nodo_id
                    for nodo_id, (distancia, _) in self.nodes_distances.items()
                    if distancia > self.MAX_DISTANCE_THRESHOLD
                }
                distant_nodes = self.neighbors.intersection(distant_nodes)
                logging.info(f"Distant neighbors based on distance: {distant_nodes}")
        return len(distant_nodes) > 0

    async def get_neighbors_to_remove(self):
        distant_nodes = set()
        async with self.neighbors_lock:
            async with self.nodes_distances_lock:
                distant_nodes: set[str] = {
                    nodo_id
                    for nodo_id, (distancia, _) in self.nodes_distances.items()
                    if distancia > self.MAX_DISTANCE_THRESHOLD
                }
                distant_nodes = self.neighbors.intersection(distant_nodes)
                logging.info(f"Remove neighbors based on distance: {distant_nodes}")
        return distant_nodes

    def stricted_topology_status(stricted_topology: bool):
        pass
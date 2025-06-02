import logging

from nebula.core.situationalawareness.awareness.sanetwork.neighborpolicies.neighborpolicy import NeighborPolicy
from nebula.core.utils.locker import Locker


class STARNeighborPolicy(NeighborPolicy):
    def __init__(self):
        self.max_neighbors = 1
        self.nodes_known = set()
        self.neighbors = set()
        self.neighbors_lock = Locker(name="neighbors_lock")
        self.nodes_known_lock = Locker(name="nodes_known_lock")
        self.addr = ""
        self._verbose = False

    async def need_more_neighbors(self):
        self.neighbors_lock.acquire()
        need_more = len(self.neighbors) < self.max_neighbors
        self.neighbors_lock.release()
        return need_more

    async def set_config(self, config):
        """
        Args:
            config[0] -> list of self neighbors, in this case, the star point
            config[1] -> list of nodes known on federation
            config[2] -> self.addr
            config[3] -> stricted_topology
        """
        self.neighbors_lock.acquire()
        self.neighbors = config[0]
        self.neighbors_lock.release()
        for addr in config[1]:
            self.nodes_known.add(addr)
        self.addr = config[2]

    async def accept_connection(self, source, joining=False):
        """
        return true if connection is accepted
        """
        ac = joining
        return ac

    async def meet_node(self, node):
        self.nodes_known_lock.acquire()
        if node != self.addr:
            if node not in self.nodes_known:
                logging.info(f"Update nodes known | addr: {node}")
            self.nodes_known.add(node)
        self.nodes_known_lock.release()

    async def forget_nodes(self, nodes, forget_all=False):
        self.nodes_known_lock.acquire()
        if forget_all:
            self.nodes_known.clear()
        else:
            for node in nodes:
                self.nodes_known.discard(node)
        self.nodes_known_lock.release()

    async def get_nodes_known(self, neighbors_too=False, neighbors_only=False):
        self.nodes_known_lock.acquire()
        nk = self.nodes_known.copy()
        if not neighbors_too:
            self.neighbors_lock.acquire()
            nk = self.nodes_known - self.neighbors
            self.neighbors_lock.release()
        self.nodes_known_lock.release()
        return nk

    async def get_actions(self):
        """
        return list of actions to do in response to connection
            - First list represents addrs argument to LinkMessage to connect to
            - Second one represents the same but for disconnect from LinkMessage
        """
        self.neighbors_lock.acquire()
        ct_actions = []
        df_actions = []
        if len(self.neighbors) < self.max_neighbors:
            ct_actions.append(self.neighbors[0])  # connect to star point
            df_actions.append(self.addr)  # disconnect from me
        self.neighbors_lock.release()
        return [ct_actions, df_actions]

    async def update_neighbors(self, node, remove=False):
        pass

    async def stricted_topology_status(stricted_topology: bool):
        pass

    async def get_posible_neighbors(self):
        """Return set of posible neighbors to connect to."""
        return await self.get_nodes_known(neighbors_too=False)

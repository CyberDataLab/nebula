import logging

from nebula.core.situationalawareness.awareness.sanetwork.neighborpolicies.neighborpolicy import NeighborPolicy
from nebula.core.utils.locker import Locker


class FCNeighborPolicy(NeighborPolicy):
    def __init__(self):
        self.max_neighbors = None
        self.nodes_known = set()
        self.neighbors = set()
        self.addr = None
        self.neighbors_lock = Locker(name="neighbors_lock")
        self.nodes_known_lock = Locker(name="nodes_known_lock")
        self._verbose = False

    async def need_more_neighbors(self):
        """
        Fully connected network requires to be connected to all devices, therefore,
        if there are more nodes known that self.neighbors, more neighbors are required
        """
        self.neighbors_lock.acquire()
        need_more = len(self.neighbors) < len(self.nodes_known)
        self.neighbors_lock.release()
        return need_more

    async def set_config(self, config):
        """
        Args:
            config[0] -> list of self neighbors
            config[1] -> list of nodes known on federation
            config[2] -> self addr
            config[3] -> stricted_topology
        """
        logging.info("Initializing Fully-Connected Topology Neighbor Policy")
        self.neighbors_lock.acquire()
        self.neighbors = config[0]
        self.neighbors_lock.release()
        for addr in config[1]:
            self.nodes_known.add(addr)
        self.addr

    async def accept_connection(self, source, joining=False):
        """
        return true if connection is accepted
        """
        self.neighbors_lock.acquire()
        ac = source not in self.neighbors
        self.neighbors_lock.release()
        return ac

    async def meet_node(self, node):
        """
        Update the list of nodes known on federation
        """
        self.nodes_known_lock.acquire()
        if node != self.addr:
            if node not in self.nodes_known:
                logging.info(f"Update nodes known | addr: {node}")
            self.nodes_known.add(node)
        self.nodes_known_lock.release()

    async def get_nodes_known(self, neighbors_too=False, neighbors_only=False):
        if neighbors_only:
            self.neighbors_lock.acquire()
            no = self.neighbors.copy()
            self.neighbors_lock.release()
            return no

        self.nodes_known_lock.acquire()
        nk = self.nodes_known.copy()
        if not neighbors_too:
            self.neighbors_lock.acquire()
            nk = self.nodes_known - self.neighbors
            self.neighbors_lock.release()
        self.nodes_known_lock.release()
        return nk

    async def forget_nodes(self, nodes, forget_all=False):
        self.nodes_known_lock.acquire()
        if forget_all:
            self.nodes_known.clear()
        else:
            for node in nodes:
                self.nodes_known.discard(node)
        self.nodes_known_lock.release()

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
        self.neighbors_lock.acquire()
        ct = " ".join(self.neighbors)
        self.neighbors_lock.release()
        return ct

    async def update_neighbors(self, node, remove=False):
        if node == self.addr:
            return
        self.neighbors_lock.acquire()
        if remove:
            try:
                self.neighbors.remove(node)
                if self._verbose:
                    logging.info(f"Remove neighbor | addr: {node}")
            except KeyError:
                pass
        else:
            self.neighbors.add(node)
            if self._verbose:
                logging.info(f"Add neighbor | addr: {node}")
        self.neighbors_lock.release()

    async def any_leftovers_neighbors(self):
        return False

    async def get_neighbors_to_remove(self):
        return set()

    async def get_posible_neighbors(self):
        """Return set of posible neighbors to connect to."""
        return await self.get_nodes_known(neighbors_too=False)

    async def stricted_topology_status(stricted_topology: bool):
        pass

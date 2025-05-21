import asyncio
import logging
import random

from nebula.core.situationalawareness.awareness.sanetwork.neighborpolicies.neighborpolicy import NeighborPolicy
from nebula.core.utils.locker import Locker


class RINGNeighborPolicy(NeighborPolicy):
    RECENTLY_REMOVED_BAN_TIME = 20

    def __init__(self):
        self.max_neighbors = 2
        self.nodes_known = set()
        self.neighbors = set()
        self.neighbors_lock = Locker(name="neighbors_lock")
        self.nodes_known_lock = Locker(name="nodes_known_lock")
        self.addr = ""
        self._excess_neighbors_removed = set()
        self._excess_neighbors_removed_lock = Locker("excess_neighbors_removed_lock", async_lock=True)
        self._verbose = False

    async def need_more_neighbors(self):
        self.neighbors_lock.acquire()
        need_more = len(self.neighbors) < self.max_neighbors
        self.neighbors_lock.release()
        return need_more

    async def set_config(self, config):
        """
        Args:
            config[0] -> list of self neighbors
            config[1] -> list of nodes known on federation
            config[2] -> self.addr
            config[3] -> stricted_topology
        """
        logging.info("Initializing Ring Topology Neighbor Policy")
        self.neighbors_lock.acquire()
        if self._verbose:
            logging.info(f"neighbors: {config[0]}")
        self.neighbors = config[0]
        self.neighbors_lock.release()
        for addr in config[1]:
            self.nodes_known.add(addr)
        self.addr = config[2]

    async def accept_connection(self, source, joining=False):
        """
        return true if connection is accepted
        """
        ac = False
        if await self._is_recently_removed(source):
            return ac

        with self.neighbors_lock:
            if joining:
                ac = source not in self.neighbors
            else:
                ac = not len(self.neighbors) >= self.max_neighbors
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

    async def get_actions(self):
        """
        return list of actions to do in response to connection
            - First list represents addrs argument to LinkMessage to connect to
            - Second one represents the same but for disconnect from LinkMessage
        """
        self.neighbors_lock.acquire()
        ct_actions = ""
        df_actions = ""
        if len(self.neighbors) == self.max_neighbors:
            list_neighbors = list(self.neighbors)
            index = random.randint(0, len(list_neighbors) - 1)
            node = list_neighbors[index]
            ct_actions = node  # connect to
            df_actions = node  # disconnect from
        self.neighbors_lock.release()
        return [ct_actions, df_actions]

    async def update_neighbors(self, node, remove=False):
        self.neighbors_lock.acquire()
        if remove:
            if node in self.neighbors:
                self.neighbors.remove(node)
        else:
            self.neighbors.add(node)
        self.neighbors_lock.release()

    async def get_posible_neighbors(self):
        """Return set of posible neighbors to connect to."""
        return await self.get_nodes_known(neighbors_too=False)

    async def any_leftovers_neighbors(self):
        self.neighbors_lock.acquire()
        aln = len(self.neighbors) > self.max_neighbors
        self.neighbors_lock.release()
        return aln

    async def get_neighbors_to_remove(self):
        neighbors = list()
        self.neighbors_lock.acquire()
        if self.neighbors:
            neighbors = set(self.neighbors)
            neighbors_to_remove = len(self.neighbors) - self.max_neighbors
            neighbors = set(random.sample(list(neighbors), neighbors_to_remove))
            self.neighbors_lock.release()
        await self._add_removed_ban(neighbors)
        return neighbors

    async def stricted_topology_status(stricted_topology: bool):
        pass

    async def _is_recently_removed(self, source):
        async with self._excess_neighbors_removed_lock:
            return source in self._excess_neighbors_removed

    async def _add_removed_ban(self, sources):
        async with self._excess_neighbors_removed_lock:
            for source in sources:
                self._excess_neighbors_removed.add(source)
                asyncio.create_task(self._clear_ban(source))

    async def _clear_ban(self, source):
        asyncio.sleep(self.RECENTLY_REMOVED_BAN_TIME)
        async with self._excess_neighbors_removed_lock:
            self._excess_neighbors_removed.discard(source)

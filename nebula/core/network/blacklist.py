import asyncio
import logging
import time

from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import NodeBlacklistedEvent
from nebula.core.utils.locker import Locker

BLACKLIST_EXPIRATION_TIME = 240
RECENTLY_DISCONNECTED_EXPIRE_TIME = 60


class BlackList:
    """
    Manages a dynamic blacklist and a list of recently disconnected nodes in a distributed system.

    The blacklist tracks nodes that are temporarily excluded from communication or interaction due to malicious behavior
    or disconnection events. Nodes remain blacklisted for a fixed period defined by `max_time_listed`.

    The recently disconnected list tracks peers that were recently disconnected and may need to be temporarily avoided.

    Key features:
    - Asynchronous locks for concurrent safety.
    - Periodic cleaning of the blacklist via a background coroutine.
    - Integration with an event manager to publish changes.
    """

    def __init__(self, max_time_listed=BLACKLIST_EXPIRATION_TIME):
        """
        Initialize the BlackList with the specified expiration time.

        Args:
            max_time_listed (int): Maximum time in seconds for nodes to remain blacklisted.
        """
        self._max_time_listed = max_time_listed
        self._blacklisted_nodes = {}
        self._recently_disconnected = set()
        self._blacklisted_nodes_lock = Locker("blacklisted_nodes_lock", async_lock=True)
        self._recently_disconnected_lock = Locker("recently_disconnected_lock", async_lock=True)
        self._running = asyncio.Event()
        self._background_tasks = []  # Track background tasks

    async def apply_restrictions(self, nodes) -> set | None:
        """
        Applies both blacklist and recently disconnected restrictions to a given set of nodes.

        Args:
            nodes (set): Set of peer node addresses.

        Returns:
            set | None: Filtered set excluding blacklisted and recently disconnected nodes, or None if input is empty.
        """
        nodes_allowed = await self.verify_allowed_nodes(nodes)
        # logging.info(f"nodes allowed after appliying blacklist restricttions: {nodes_allowed}")
        if nodes_allowed:
            nodes_allowed = await self.verify_not_recently_disc(nodes_allowed)
            # logging.info(f"nodes allowed after seen recently disconnection restrictions: {nodes_allowed}")
        return nodes_allowed

    async def clear_restrictions(self):
        """
        Clears both the blacklist and the recently disconnected list.
        """
        await self.clear_blacklist()
        await self.clear_recently_disconected()

    """                                                     ##############################
                                                            #          BLACKLIST         #
                                                            ##############################
    """

    async def add_to_blacklist(self, addr):
        """
        Adds a node to the blacklist and starts the cleaner task if not already running.

        Args:
            addr (str): Address of the node to blacklist.
        """
        logging.info(f"Update blackList | addr listed: {addr}")
        await self._blacklisted_nodes_lock.acquire_async()
        expiration_time = time.time()
        self._blacklisted_nodes[addr] = expiration_time
        if not self._running.is_set():
            self._running.set()
            asyncio.create_task(self._start_blacklist_cleaner())
        await self._blacklisted_nodes_lock.release_async()
        nbe = NodeBlacklistedEvent(addr, blacklisted=True)
        event_manager = EventManager.get_instance()
        if event_manager is not None:
            asyncio.create_task(event_manager.publish_node_event(nbe))

    async def get_blacklist(self) -> set:
        """
        Adds a node to the blacklist and starts the cleaner task if not already running.

        Args:
            addr (str): Address of the node to blacklist.
        """
        bl = None
        await self._blacklisted_nodes_lock.acquire_async()
        if self._blacklisted_nodes:
            bl = set(self._blacklisted_nodes.keys())
        await self._blacklisted_nodes_lock.release_async()
        return bl or set()

    async def clear_blacklist(self):
        """
        Clears the blacklist entirely.
        """
        await self._blacklisted_nodes_lock.acquire_async()
        logging.info("🧹 Removing nodes from blacklist")
        self._blacklisted_nodes.clear()
        await self._blacklisted_nodes_lock.release_async()

    async def _start_blacklist_cleaner(self):
        """
        Background task that periodically removes expired entries from the blacklist.
        """
        while self._running.is_set():
            await self._blacklist_clean()
            await self._blacklist_cleaner_wait()

    async def _blacklist_clean(self):
        """
        Removes nodes from the blacklist whose expiration time has passed.
        """
        await self._blacklisted_nodes_lock.acquire_async()
        logging.info("BlackList cleaner has waken up")
        now = time.time()
        new_bl = {}

        for addr, timer in self._blacklisted_nodes.items():
            if timer + self._max_time_listed >= now:
                new_bl[addr] = timer
            else:
                logging.info(f"Removing addr{addr} from blacklisted nodes...")

        self._blacklisted_nodes = new_bl
        if not new_bl:
            self._running.clear()
        await self._blacklisted_nodes_lock.release_async()

    async def _blacklist_cleaner_wait(self):
        """
        Waits for the blacklist cleaner delay duration.
        """
        try:
            await asyncio.sleep(self._max_time_listed)
        except TimeoutError:
            pass

    async def node_in_blacklist(self, addr):
        """
        Checks whether a given address is currently blacklisted.

        Args:
            addr (str): Node address.

        Returns:
            bool: True if the node is blacklisted, False otherwise.
        """
        blacklisted = False
        await self._blacklisted_nodes_lock.acquire_async()
        if self._blacklisted_nodes:
            blacklisted = addr in self._blacklisted_nodes.keys()
        await self._blacklisted_nodes_lock.release_async()
        return blacklisted

    async def verify_allowed_nodes(self, nodes: set) -> set | None:
        """
        Filters out blacklisted nodes from the given set.

        Args:
            nodes (set): Set of node addresses to check.

        Returns:
            set | None: Nodes not in the blacklist, or None if input is empty.
        """
        if not nodes:
            return None
        nodes_not_listed = nodes
        await self._blacklisted_nodes_lock.acquire_async()
        blacklist = self._blacklisted_nodes
        if blacklist:
            nodes_not_listed = nodes.difference(blacklist)
        await self._blacklisted_nodes_lock.release_async()
        return nodes_not_listed

    """                                                     ##############################
                                                            #    RECENTLY DISCONNECTED   #
                                                            ##############################
    """

    async def add_recently_disconnected(self, addr):
        """
        Marks a node as recently disconnected and schedules its expiration.

        Args:
            addr (str): Address of the disconnected node.
        """
        logging.info(f"Recently disconnected from: {addr}")
        await self._recently_disconnected_lock.acquire_async()
        self._recently_disconnected.add(addr)
        await self._recently_disconnected_lock.release_async()
        task = asyncio.create_task(self._remove_recently_disc(addr), name=f"BlackList_remove_recently_{addr}")
        self._background_tasks.append(task)
        nbe = NodeBlacklistedEvent(addr)
        event_manager = EventManager.get_instance()
        if event_manager is not None:
            asyncio.create_task(event_manager.publish_node_event(nbe))

    async def clear_recently_disconected(self):
        """
        Clears the list of recently disconnected nodes.
        """
        await self._recently_disconnected_lock.acquire_async()
        logging.info("🧹 Removing nodes from Recently Disconencted list")
        self._recently_disconnected.clear()
        await self._recently_disconnected_lock.release_async()

    async def get_recently_disconnected(self):
        """
        Retrieves a copy of the recently disconnected nodes.

        Returns:
            set: Addresses of recently disconnected nodes.
        """
        rd = None
        await self._recently_disconnected_lock.acquire_async()
        rd = self._recently_disconnected.copy()
        await self._recently_disconnected_lock.release_async()
        return rd

    async def _remove_recently_disc(self, addr):
        """
        Waits for the expiration time and then removes the node from the recently disconnected list.

        Args:
            addr (str): Address to remove after expiration.
        """
        await asyncio.sleep(RECENTLY_DISCONNECTED_EXPIRE_TIME)
        await self._recently_disconnected_lock.acquire_async()
        self._recently_disconnected.discard(addr)
        logging.info(f"Recently disconnection timeout expired for souce: {addr}")
        await self._recently_disconnected_lock.release_async()

    async def verify_not_recently_disc(self, nodes: set) -> set | None:
        """
        Filters out recently disconnected nodes from the given set.

        Args:
            nodes (set): Set of node addresses to filter.

        Returns:
            set | None: Set of nodes not recently disconnected, or None if input is empty.
        """
        if not nodes:
            return None
        nodes_not_listed = nodes
        await self._recently_disconnected_lock.acquire_async()
        rec_disc = self._recently_disconnected
        # logging.info(f"recently disconencted nodes: {rec_disc}")
        if rec_disc:
            nodes_not_listed = nodes.difference(rec_disc)
        await self._recently_disconnected_lock.release_async()
        return nodes_not_listed

    async def stop(self):
        """
        Stop the BlackList by clearing all data and stopping background tasks.
        """
        logging.info("🛑  Stopping BlackList...")

        # Stop the background cleaner
        self._running.clear()

        # Cancel all background tasks
        if self._background_tasks:
            logging.info(f"🛑  Cancelling {len(self._background_tasks)} background tasks...")
            for task in self._background_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            self._background_tasks.clear()
            logging.info("🛑  All background tasks cancelled")

        # Clear all data
        try:
            async with self._blacklisted_nodes_lock:
                self._blacklisted_nodes.clear()
        except Exception as e:
            logging.warning(f"Error clearing blacklist: {e}")

        try:
            async with self._recently_disconnected_lock:
                self._recently_disconnected.clear()
        except Exception as e:
            logging.warning(f"Error clearing recently disconnected: {e}")

        logging.info("✅  BlackList stopped successfully")

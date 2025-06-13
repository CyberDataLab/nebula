import logging
import time
from collections import deque
from typing import TYPE_CHECKING

from nebula.core.aggregation.updatehandlers.updatehandler import UpdateHandler
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateNeighborEvent, UpdateReceivedEvent
from nebula.core.utils.locker import Locker

if TYPE_CHECKING:
    from nebula.core.aggregation.aggregator import Aggregator


class Update:
    """
    Represents a model update received from a node in a specific training round.
    
    Attributes:
        model (object): The model object or weights received.
        weight (float): The weight or importance of the update.
        source (str): Identifier of the node that sent the update.
        round (int): Training round this update belongs to.
        time_received (float): Timestamp when the update was received.
    """
    def __init__(self, model, weight, source, round, time_received):
        self.model = model
        self.weight = weight
        self.source = source
        self.round = round
        self.time_received = time_received

    def __eq__(self, other):
        """
        Checks if two updates belong to the same round.
        """
        return self.round == other.round


MAX_UPDATE_BUFFER_SIZE = 1


class CFLUpdateHandler(UpdateHandler):
    """
    Handles updates received in a cross-silo/federated learning setup,
    managing synchronization and aggregation across distributed nodes.

    Attributes:
        _aggregator (Aggregator): Reference to the aggregator managing the global model.
        _addr (str): Local address of the node.
        _buffersize (int): Max number of updates to store per node.
        _updates_storage (dict): Stores received updates per source node.
        _sources_expected (set): Set of nodes expected to send updates this round.
        _sources_received (set): Set of nodes that have sent updates this round.
        _missing_ones (set): Tracks nodes whose updates are missing.
        _role (str): Role of this node (e.g., trainer or server).
    """
    
    def __init__(self, aggregator, addr, buffersize=MAX_UPDATE_BUFFER_SIZE):
        self._addr = addr
        self._aggregator: Aggregator = aggregator
        self._buffersize = buffersize
        self._updates_storage: dict[str, deque[Update]] = {}
        self._updates_storage_lock = Locker(name="updates_storage_lock", async_lock=True)
        self._sources_expected = set()
        self._sources_received = set()
        self._round_updates_lock = Locker(
            name="round_updates_lock", async_lock=True
        )  # se coge cuando se empieza a comprobar si estan todas las updates
        self._update_federation_lock = Locker(name="update_federation_lock", async_lock=True)
        self._notification_sent_lock = Locker(name="notification_sent_lock", async_lock=True)
        self._notification = False
        self._missing_ones = set()
        self._role = ""

    @property
    def us(self):
        """Returns the internal updates storage dictionary."""
        return self._updates_storage

    @property
    def agg(self):
        """Returns the aggregator instance."""
        return self._aggregator

    async def init(self, config):
        """
        Initializes the handler with the participant configuration,
        and subscribes to relevant node events.
        """
        self._role = config
        await EventManager.get_instance().subscribe_node_event(UpdateNeighborEvent, self.notify_federation_update)
        await EventManager.get_instance().subscribe_node_event(UpdateReceivedEvent, self.storage_update)

    async def round_expected_updates(self, federation_nodes: set):
        """
        Sets the expected nodes for the current training round and updates storage.

        Args:
            federation_nodes (set): Nodes expected to send updates this round.
        """
        await self._update_federation_lock.acquire_async()
        await self._updates_storage_lock.acquire_async()
        self._sources_expected = federation_nodes.copy()
        self._sources_received.clear()

        # Initialize new nodes
        for fn in federation_nodes:
            if fn not in self.us:
                self.us[fn] = deque(maxlen=self._buffersize)

        # Clear removed nodes
        removed_nodes = [node for node in self._updates_storage.keys() if node not in federation_nodes]
        for rn in removed_nodes:
            del self._updates_storage[rn]

        await self._updates_storage_lock.release_async()
        await self._update_federation_lock.release_async()

        # Lock to check if all updates received
        if self._round_updates_lock.locked():
            self._round_updates_lock.release_async()

        self._notification = False

    async def storage_update(self, updt_received_event: UpdateReceivedEvent):
        """
        Stores a received update if it comes from an expected source.

        Args:
            updt_received_event (UpdateReceivedEvent): The event containing the update.
        """
        time_received = time.time()
        (model, weight, source, round, _) = await updt_received_event.get_event_data()

        if source in self._sources_expected:
            updt = Update(model, weight, source, round, time_received)
            await self._updates_storage_lock.acquire_async()
            if updt in self.us[source]:
                logging.info(f"Discard | Alerady received update from source: {source} for round: {round}")
            else:
                self.us[source].append(updt)
                logging.info(
                    f"Storage Update | source={source} | round={round} | weight={weight} | federation nodes: {self._sources_expected}"
                )

                self._sources_received.add(source)
                updates_left = self._sources_expected.difference(self._sources_received)
                logging.info(
                    f"Updates received ({len(self._sources_received)}/{len(self._sources_expected)}) | Missing nodes: {updates_left}"
                )
                if self._round_updates_lock.locked() and not updates_left:
                    all_rec = await self._all_updates_received()
                    if all_rec:
                        await self._notify()
            await self._updates_storage_lock.release_async()
        else:
            if source not in self._sources_received:
                logging.info(f"Discard update | source: {source} not in expected updates for this Round")

    async def get_round_updates(self) -> dict[str, tuple[object, float]]:
        """
        Retrieves the latest updates received this round.

        Returns:
            dict: Mapping of source to (model, weight) tuples.
        """
        await self._updates_storage_lock.acquire_async()
        updates_missing = self._sources_expected.difference(self._sources_received)
        if updates_missing:
            self._missing_ones = updates_missing
            logging.info(f"Missing updates from sources: {updates_missing}")
        updates = {}
        for sr in self._sources_received:
            if (
                self._role == "trainer" and len(self._sources_received) > 1
            ):  # if trainer node ignore self updt if has received udpate from server
                if sr == self._addr:
                    continue
            source_historic = self.us[sr]
            updt: Update = None
            updt = source_historic[-1]  # Get last update received
            updates[sr] = (updt.model, updt.weight)
        await self._updates_storage_lock.release_async()
        return updates

    async def notify_federation_update(self, updt_nei_event: UpdateNeighborEvent):
        """
        Reacts to neighbor updates (e.g., join or leave).

        Args:
            updt_nei_event (UpdateNeighborEvent): The neighbor update event.
        """
        source, remove = await updt_nei_event.get_event_data()
        if not remove:
            if self._round_updates_lock.locked():
                logging.info(f"Source: {source} will be count next round")
            else:
                await self._update_source(source, remove)
        else:
            if source not in self._sources_received:  # Not received update from this source yet
                await self._update_source(source, remove=True)
                await self._all_updates_received()  # Verify if discarding node aggregation could be done
            else:
                logging.info(f"Already received update from: {source}, it will be discarded next round")

    async def _update_source(self, source, remove=False):
        """
        Updates internal tracking for a specific source node.

        Args:
            source (str): Source node ID.
            remove (bool): Whether the source should be removed.
        """
        logging.info(f"🔄 Update | remove: {remove} | source: {source}")
        await self._updates_storage_lock.acquire_async()
        if remove:
            self._sources_expected.discard(source)
        else:
            self.us[source] = deque(maxlen=self._buffersize)
            self._sources_expected.add(source)
        logging.info(f"federation nodes expected this round: {self._sources_expected}")
        await self._updates_storage_lock.release_async()

    async def get_round_missing_nodes(self):
        """
        Returns nodes whose updates were expected but not received.
        """
        return self._missing_ones

    async def notify_if_all_updates_received(self):
        """
        Acquires a lock to notify the aggregator if all updates have been received.
        """
        logging.info("Set notification when all expected updates received")
        await self._round_updates_lock.acquire_async()
        await self._updates_storage_lock.acquire_async()
        all_received = await self._all_updates_received()
        await self._updates_storage_lock.release_async()
        if all_received:
            await self._notify()

    async def stop_notifying_updates(self):
        """
        Stops waiting for updates and releases the notification lock if held.
        """
        if self._round_updates_lock.locked():
            logging.info("Stop notification updates")
            await self._round_updates_lock.release_async()

    async def _notify(self):
        """
        Notifies the aggregator that all updates have been received.
        """
        await self._notification_sent_lock.acquire_async()
        if self._notification:
            await self._notification_sent_lock.release_async()
            return
        self._notification = True
        await self.stop_notifying_updates()
        await self._notification_sent_lock.release_async()
        logging.info("🔄 Notifying aggregator to release aggregation")
        await self.agg.notify_all_updates_received()

    async def _all_updates_received(self):
        """
        Checks if updates from all expected nodes have been received.

        Returns:
            bool: True if all updates are received, False otherwise.
        """
        updates_left = self._sources_expected.difference(self._sources_received)
        all_received = False
        if len(updates_left) == 0:
            logging.info("All updates have been received this round")
            await self._round_updates_lock.release_async()
            all_received = True
        return all_received

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
    def __init__(self, model, weight, source, round, time_received):
        self.model = model
        self.weight = weight
        self.source = source
        self.round = round
        self.time_received = time_received

    def __eq__(self, other):
        return self.round == other.round


MAX_UPDATE_BUFFER_SIZE = 1  # Modify to create an historic


class DFLUpdateHandler(UpdateHandler):
    def __init__(self, aggregator, addr, buffersize=MAX_UPDATE_BUFFER_SIZE):
        self._addr = addr
        self._aggregator: Aggregator = aggregator
        self._buffersize = buffersize
        self._updates_storage: dict[str, tuple[Update, deque[Update]]] = {}
        self._updates_storage_lock = Locker(name="updates_storage_lock", async_lock=True)
        self._sources_expected = set()
        self._sources_received = set()
        self._round_updates_lock = Locker(
            name="round_updates_lock", async_lock=True
        )  # It is taken when you start to check if all the updates are available.
        self._update_federation_lock = Locker(name="update_federation_lock", async_lock=True)
        self._notification_sent_lock = Locker(name="notification_sent_lock", async_lock=True)
        self._notification = False
        self._missing_ones = set()
        self._nodes_using_historic = set()

    @property
    def us(self):
        return self._updates_storage

    @property
    def agg(self):
        return self._aggregator

    async def init(self, config=None):
        await EventManager.get_instance().subscribe_node_event(UpdateNeighborEvent, self.notify_federation_update)
        await EventManager.get_instance().subscribe_node_event(UpdateReceivedEvent, self.storage_update)

    async def round_expected_updates(self, federation_nodes: set):
        await self._update_federation_lock.acquire_async()
        await self._updates_storage_lock.acquire_async()
        self._sources_expected = federation_nodes.copy()
        self._sources_received.clear()

        # Initialize new nodes
        for fn in federation_nodes:
            if fn not in self.us:
                self.us[fn] = (None, deque(maxlen=self._buffersize))

        # Clear removed nodes
        removed_nodes = [node for node in self._updates_storage if node not in federation_nodes]
        for rn in removed_nodes:
            del self._updates_storage[rn]

        # Check already received updates
        await self._check_updates_already_received()

        await self._updates_storage_lock.release_async()
        await self._update_federation_lock.release_async()

        # Lock to check if all updates received
        if self._round_updates_lock.locked():
            self._round_updates_lock.release_async()

        self._notification = False

    async def _check_updates_already_received(self):
        for se in self._sources_expected:
            (last_updt, node_storage) = self._updates_storage[se]
            if len(node_storage) and last_updt != node_storage[-1]:
                    logging.info(
                        f"Update already received from source: {se} | ({len(self._sources_received)}/{len(self._sources_expected)}) Updates received"
                    )
                    self._sources_received.add(se)

    async def storage_update(self, updt_received_event: UpdateReceivedEvent):
        time_received = time.time()
        (model, weight, source, round, _) = await updt_received_event.get_event_data()

        if source in self._sources_expected:
            updt = Update(model, weight, source, round, time_received)
            await self._updates_storage_lock.acquire_async()
            if updt in self.us[source][1]:
                logging.info(f"Discard | Alerady received update from source: {source} for round: {round}")
            else:
                last_update_used = self.us[source][0]
                self.us[source][1].append(updt)
                self.us[source] = (last_update_used, self.us[source][1])
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

    async def get_round_updates(self):
        await self._updates_storage_lock.acquire_async()
        updates_missing = self._sources_expected.difference(self._sources_received)
        if updates_missing:
            self._missing_ones = updates_missing
            logging.info(f"Missing updates from sources: {updates_missing}")
        else:
            self._missing_ones.clear()
        self._nodes_using_historic.clear()
        updates = {}
        for sr in self._sources_received:
            source_historic = self.us[sr][1]
            last_updt_received = self.us[sr][0]
            updt: Update = None
            updt = source_historic[-1]  # Get last update received
            if last_updt_received and last_updt_received == updt:
                logging.info(f"Missing update from source: {sr}, using last update received..")
                self._nodes_using_historic.add(sr)
            else:
                last_updt_received = updt
                self.us[sr] = (last_updt_received, source_historic)  # Update storage with new last update used
            updates[sr] = (updt.model, updt.weight)

        await self._updates_storage_lock.release_async()
        return updates

    async def notify_federation_update(self, updt_nei_event: UpdateNeighborEvent):
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
        logging.info(f"🔄 Update | remove: {remove} | source: {source}")
        await self._updates_storage_lock.acquire_async()
        if remove:
            self._sources_expected.discard(source)
        else:
            self.us[source] = (None, deque(maxlen=self._buffersize))
            self._sources_expected.add(source)
        logging.info(f"federation nodes expected this round: {self._sources_expected}")
        await self._updates_storage_lock.release_async()

    async def get_round_missing_nodes(self):
        return self._missing_ones

    async def notify_if_all_updates_received(self):
        logging.info("Set notification when all expected updates received")
        await self._round_updates_lock.acquire_async()
        await self._updates_storage_lock.acquire_async()
        all_received = await self._all_updates_received()
        await self._updates_storage_lock.release_async()
        if all_received:
            await self._notify()

    async def stop_notifying_updates(self):
        if self._round_updates_lock.locked():
            logging.info("Stop notification updates")
            await self._round_updates_lock.release_async()

    async def _notify(self):
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
        updates_left = self._sources_expected.difference(self._sources_received)
        all_received = False
        if len(updates_left) == 0:
            logging.info("All updates have been received this round")
            await self._round_updates_lock.release_async()
            all_received = True
        return all_received

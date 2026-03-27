import asyncio
import time
import logging
from typing import TYPE_CHECKING, Any

from nebula.core.aggregation.updatehandlers.updatehandler import UpdateHandler
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateNeighborEvent, UpdateReceivedEvent
from nebula.core.utils.locker import Locker

if TYPE_CHECKING:
    from nebula.core.aggregation.aggregator import Aggregator


class Update:
    """
    Holds a single model update along with metadata.

    Attributes:
        model (object): The serialized model or weights.
        weight (float): The importance weight of the update.
        source (str): Identifier of the sending node.
        round (int): Training round number of this update.
        time_received (float): Timestamp when update arrived.
    """
    def __init__(self, model, weight, source, round, time_received):
        self.model = model
        self.weight = weight
        self.source = source
        self.round = round
        self.time_received = time_received


class CAFFUpdateHandler(UpdateHandler):
    """
    CAFF: Cache-based Aggregation with Fairness and Filterin Update Handler.

    Manages peer updates asynchronously, applies a staleness filter,
    and triggers aggregation once a dynamic threshold K_node is met.
    """
    def __init__(self, aggregator: "Aggregator", addr: str):
        """
        Initialize handler state and async locks.

        Args:
            aggregator (Aggregator): The federation aggregator instance.
            addr (str): This node's unique address.
        """
        self._addr = addr
        self._aggregator = aggregator

        self._update_cache: dict[str, Update] = {}
        self._sources_expected: set[str] = set()

        self._cache_lock = Locker(name="caff_cache_lock", async_lock=True)

        self._fallback_task = None
        self._notification_sent = False

        self._aggregation_fraction = 1.0
        self._staleness_threshold = 1

        self._local_round = 0
        self._K_node = 1

        self._local_training_done = False

        ### TEST FOR CAFF - Send model updates only to last contributors
        self._last_contributors: list[str] = []
        ### TEST FOR CAFF - Send model updates only to last contributors


    @property
    def us(self):
        """Returns the internal update cache mapping source -> Update."""
        return self._update_cache

    @property
    def agg(self):
        """Returns the linked aggregator."""
        return self._aggregator

    @property
    def last_contributors(self) -> list[str]:
        """
        The list of peer-addresses who actually contributed in the previous round.
        """
        return self._last_contributors

    def _recalc_K_node(self):
        """
        Recalculate K_node based on current expected peers and fraction.

        Ensures at least one external peer and includes local update.
        """
        # when only local node is still active and all others finished training
        if len(self._sources_expected) == 1:
            self._K_node = 1
        else:
            # count only “external” peers
            external = len(self._sources_expected - {self._addr})
            # round() to nearest int, Account for local update also stored with + 1
            self._K_node = max(1 + 1, round(self._aggregation_fraction * external) + 1)

    async def init(self, _role_name):
        """
        Subscribe to federation events and load config args.

        Args:
            _role_name (str): Unused placeholder for role.
        """
        cfg = self._aggregator.config

        self._aggregation_fraction = cfg.participant["caff_args"]["aggregation_fraction"]
        self._staleness_threshold   = cfg.participant["caff_args"]["staleness_threshold"]

        await EventManager.get_instance().subscribe_node_event(UpdateNeighborEvent, self.notify_federation_update)
        await EventManager.get_instance().subscribe_node_event(UpdateReceivedEvent, self.storage_update)

    async def round_expected_updates(self, federation_nodes: set):
        """
        Reset round state when a new round starts.

        Args:
            federation_nodes (set[str]): IDs of peers expected this round.
        """
        self._sources_expected = federation_nodes.copy()
        self._update_cache.clear()
        self._notification_sent = False
        self._local_round = await self._aggregator.engine.get_round()

        # compute initial K_node
        self._recalc_K_node()

        self._local_training_done = False

    async def storage_update(self, updt_received_event: UpdateReceivedEvent):
        """
        Handle an incoming model update event.

        Args:
            updt_received_event (UpdateReceivedEvent): Carries model, weight, source, and round.
        """
        time_received = time.time()
        model, weight, source, round_received, _ = await updt_received_event.get_event_data()
        await self._cache_lock.acquire_async()

        # reject any update not in expected set
        if source not in self._sources_expected:
            logging.info(
                f"[CAFF] Discard update | source: {source} not in expected updates for round {self._local_round}"
            )
            await self._cache_lock.release_async()
            return

        # store local update
        if self._addr == source:
            update = Update(model, weight, source, round_received, time_received)
            self._update_cache[source] = update
            self._local_training_done = True
            logging.info(f"[CAFF] Received own update from {source} (local training done)")
            logging.info(
            f"[CAFF] Round {self._local_round} aggregation check: {len(self._update_cache)} / {self._K_node} (local ready: {self._local_training_done})"
            )
            await self._cache_lock.release_async()
            await self._maybe_aggregate(force_check=True)
            return

        # replace or discard update from peer already in cache
        if source in self._update_cache:
            cached_update = self._update_cache[source]
            if round_received > cached_update.round:
                self._update_cache[source] = Update(model, weight, source, round_received, time_received)
                logging.info(f"[CAFF] Replaced cached update from {source} with newer round {round_received}")
            else:
                logging.info(f"[CAFF] Discarded stale update from {source} (round {round_received})")
            await self._cache_lock.release_async()
            if self._local_training_done:
                await self._maybe_aggregate()
            return

        # staleness filter for new peer update
        if self._local_round - round_received <= self._staleness_threshold:
            self._update_cache[source] = Update(model, weight, source, round_received, time_received)
            logging.info(f"[CAFF] Cached new update from {source} (round {round_received})")
        else:
            logging.info(f"[CAFF] Discarded stale update from {source} (round {round_received})")

        peer_count = len(self._update_cache)
        has_local = self._local_training_done

        logging.info(
            f"[CAFF] Round {self._local_round} aggregation check: {peer_count} / {self._K_node} (local ready: {has_local})"
        )

        await self._cache_lock.release_async()
        if self._local_training_done:
            await self._maybe_aggregate()

    async def get_round_updates(self):
        """
        Return all cached updates for aggregation.

        Returns:
            dict[str, tuple]: Mapping of node -> (model, weight) pairs.
        """
        await self._cache_lock.acquire_async()
        updates = {peer: (u.model, u.weight) for peer, u in self._update_cache.items()}
        await self._cache_lock.release_async()
        logging.info(f"[CAFF] Aggregating with {len(self._update_cache)} updates (incl. local)")

        ### TEST FOR CAFF - Send model updates only to last contributors
        # Snapshot the peers who actually contributed this round
        self._last_contributors = list(set(self._update_cache.keys()).difference({self._addr}))
        ### TEST FOR CAFF - Send model updates only to last contributors

        return updates

    async def notify_federation_update(self, updt_nei_event: UpdateNeighborEvent):
        """
        Handle peers joining or leaving mid-round.

        When a peer leaves, remove it from expected set and recalc K_node.
        """
        source, remove = await updt_nei_event.get_event_data()

        if remove:
            # peer left / finished
            if source in self._sources_expected:
                self._sources_expected.discard(source)
                logging.info(f"[CAFF] Peer {source} removed → now expecting {self._sources_expected}")
                # recompute threshold
                self._recalc_K_node()
                logging.info(f"[CAFF] Recomputed K_node={self._K_node}")
                # maybe we can now aggregate earlier
                await self._maybe_aggregate()
        else:
            # peer joined mid-round
            self._sources_expected.add(source)
            logging.info(f"[CAFF] Peer {source} joined → now expecting {self._sources_expected}")
            self._recalc_K_node()
            logging.info(f"[CAFF] Recomputed K_node={self._K_node}")

    async def get_round_missing_nodes(self):
        """
        List peers whose updates have not yet arrived.

        Returns:
            set[str]: IDs of missing peers.
        """
        return self._sources_expected.difference(self._update_cache.keys())

    async def notify_if_all_updates_received(self):
        """
        Trigger aggregation check immediately when all conditions may be met.
        """
        logging.info("[CAFF] Timer started and waiting for updates to reach threshold K_node")
        await self._maybe_aggregate()

    async def stop_notifying_updates(self):
        """
        Cancel any pending fallback notification timers.
        """
        if self._fallback_task:
            self._fallback_task.cancel()
            self._fallback_task = None

    async def _maybe_aggregate(self, force_check=False):
        """
        Check if K_node threshold and local training are satisfied; if so, notify aggregator.
        """
        await self._cache_lock.acquire_async()

        # if aggregation already started leave function
        if self._notification_sent and not force_check:
            await self._cache_lock.release_async()
            return

        peer_count = len(self._update_cache)
        has_local = self._local_training_done

        # wait for local model
        if not has_local:
            logging.debug("[CAFF] Waiting for local training to finish before aggregation.")
            await self._cache_lock.release_async()
            return

        # if enough peers ready, start aggregation
        if has_local and peer_count >= self._K_node:
            logging.info(f"[CAFF] K_node threshold reached and local training finished: Starting aggregation process..")
            self._notification_sent = True
            await self._cache_lock.release_async()
            logging.info("[CAFF] 🔄 Notifying aggregator to release aggregation")
            await self.agg.notify_all_updates_received()
            return

        await self._cache_lock.release_async()

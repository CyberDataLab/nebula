import logging
from nebula.core.utils.locker import Locker
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import AggregationEvent, UpdateNeighborEvent
from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.trainingpolicy import TrainingPolicy
from nebula.core.situationalawareness.awareness.suggestionbuffer import SuggestionBuffer
from nebula.core.situationalawareness.awareness.sautils.sacommand import SACommand, SACommandAction, SACommandPRIO, factory_sa_command

VANILLA_LEARNING_RATE = 1e-3
FR_LEARNING_RATE = 1e-3
MAX_ROUNDS = 20
DEFAULT_WEIGHT_MODIFIER = 3


class FastReboot(TrainingPolicy):
    def __init__(
        self,
        config
    ):
        logging.info("🌐  Initializing FastReboot")
        self._max_rounds = MAX_ROUNDS                           # Max rounds to be applied FastReboot
        self._weight_mod_value = DEFAULT_WEIGHT_MODIFIER
        self._default_lr = VANILLA_LEARNING_RATE                # Stable value for learning rate
        self._upgrade_lr = FR_LEARNING_RATE                     # Increased value for learning rate
        self._current_lr = VANILLA_LEARNING_RATE
        self._verbose = config["verbose"]
        
        self._learning_rate_lock = Locker(name="learning_rate_lock", async_lock=True)
        self._weight_modifier = {}
        self._weight_modifier_lock = Locker(name="weight_modifier_lock", async_lock=True)

        self._fr_in_progress = False
        
    async def init(self, config):
        #await EventManager.get_instance().subscribe_node_event(UpdateNeighborEvent)
        #await EventManager.get_instance().subscribe_node_event(AggregationEvent)
        pass

    async def get_evaluation_results(self):
        pass

    def __str__(self):
        return "FRTS"

    async def _get_current_learning_rate(self):
        await self._learning_rate_lock.acquire_async()
        lr = self._current_lr
        await self._learning_rate_lock.release_async()
        return lr

    async def discard_fastreboot_for(self, addr):
        await self._weight_modifier_lock.acquire_async()
        try:
            del self._weight_modifier[addr]
        except KeyError:
            pass
        await self._weight_modifier_lock.release_async()

    async def _set_learning_rate(self, lr):
        await self._learning_rate_lock.acquire_async()
        self._current_lr = lr
        await self._learning_rate_lock.release_async()

    async def add_fastReboot_addr(self, addr):
        await self._weight_modifier_lock.acquire_async()
        if addr not in self._weight_modifier:
            self._fr_in_progress = True
            wm = self._weight_mod_value
            logging.info(
                f"📝 Registering | FastReboot registered for source {addr} | round application: {self._max_rounds} | multiplier value: {wm}"
            )
            self._weight_modifier[addr] = (wm, 1)
            await self._set_learning_rate(self._upgrade_lr)
            current_lr = await self._get_current_learning_rate()
            #TODO modify learning rate suggestion await self.nm.update_learning_rate(current_lr)
        await self._weight_modifier_lock.release_async()

    async def _remove_weight_modifier(self, addr):
        logging.info(f"📝 Removing | FastReboot removed for source {addr}")
        del self._weight_modifier[addr]

    async def _weight_modifiers_empty(self):
        await self._weight_modifier_lock.acquire_async()
        empty = False if self._weight_modifier else True
        await self._weight_modifier_lock.release_async()
        return empty

    async def apply_weight_strategy(self, updates: dict):
        if await self._weight_modifiers_empty():
            if self._fr_in_progress:
                await self._end_fastreboot()
            return
        logging.info("🔄  Applying FastReboot Strategy...")
        for addr, update in updates.items():
            weightmodifier, rounds = await self._get_weight_modifier(addr)
            if weightmodifier != 1:
                logging.info(
                    f"📝 Appliying FastReboot strategy | addr: {addr} | multiplier value: {weightmodifier}, rounds applied: {rounds}"
                )
                model, weight = update
                updates.update({addr: (model, weight * weightmodifier)})
        await self._update_weight_modifiers()

    async def _update_weight_modifiers(self):
        await self._weight_modifier_lock.acquire_async()
        if self._weight_modifier:
            logging.info("🔄  Update | weights being updated")
            remove_addrs = []
            for addr, (weight, rounds) in self._weight_modifier.items():
                new_weight = weight - 1 / (rounds**2)
                rounds = rounds + 1
                if new_weight > 1 and rounds <= self._max_rounds:
                    self._weight_modifier[addr] = (new_weight, rounds)
                else:
                    remove_addrs.append(addr)
            for a in remove_addrs:
                await self._remove_weight_modifier(a)
        await self._weight_modifier_lock.release_async()

    async def _end_fastreboot(self):
        await self._weight_modifier_lock.acquire_async()
        if not self._weight_modifier and await self._is_lr_modified():
            logging.info("🔄  Finishing | FastReboot is completed")
            self._fr_in_progress = False
            await self._set_learning_rate(self._default_lr)
            #TODO modify learning rate suggestion await self.nm.update_learning_rate(self._default_lr)
        await self._weight_modifier_lock.release_async()

    async def _get_weight_modifier(self, addr):
        await self._weight_modifier_lock.acquire_async()
        wm = self._weight_modifier.get(addr, (1, 0))
        await self._weight_modifier_lock.release_async()
        return wm

    async def _is_lr_modified(self):
        await self._learning_rate_lock.acquire_async()
        mod = self._current_lr == self._upgrade_lr
        await self._learning_rate_lock.release_async()
        return mod

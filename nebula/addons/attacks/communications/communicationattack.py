import logging
import random
import random
import types
from abc import abstractmethod

from nebula.addons.attacks.attacks import Attack
from nebula.core.network.communications import CommunicationsManager


class CommunicationAttack(Attack):
    def __init__(
        self,
        engine,
        target_class,
        target_method,
        round_start_attack,
        round_stop_attack,
        attack_interval,
        decorator_args=None,
        selectivity_percentage: int = 100,
        selection_interval: int = None,
    ):
        super().__init__()
        self.engine = engine
        self.target_class = target_class
        self.target_method = target_method
        self.decorator_args = decorator_args
        self.round_start_attack = round_start_attack
        self.round_stop_attack = round_stop_attack
        self.attack_interval = attack_interval
        self.original_method = getattr(target_class, target_method, None)
        self.selectivity_percentage = selectivity_percentage
        self.selection_interval = selection_interval
        self.last_selection_round = 0
        self.targets = set()

        if not self.original_method:
            raise AttributeError(f"Method {target_method} not found in class {target_class}")

    @abstractmethod
    def decorator(self, *args):
        """Decorator that adds malicious behavior to the execution of the original method."""
        pass

    async def select_targets(self):
        if self.selectivity_percentage != 100:
            if self.selection_interval:
                if self.last_selection_round % self.selection_interval == 0:
                    logging.info("Recalculating targets...")
                    all_nodes = await CommunicationsManager.get_instance().get_addrs_current_connections(only_direct=True)
                    num_targets = max(1, int(len(all_nodes) * (self.selectivity_percentage / 100)))
                    self.targets = set(random.sample(list(all_nodes), num_targets))
            elif not self.targets:
                logging.info("Calculating targets...")
                all_nodes = await CommunicationsManager.get_instance().get_addrs_current_connections(only_direct=True)
                num_targets = max(1, int(len(all_nodes) * (self.selectivity_percentage / 100)))
                self.targets = set(random.sample(list(all_nodes), num_targets))
        else:
            logging.info("All neighbors selected as targets")
            self.targets = await CommunicationsManager.get_instance().get_addrs_current_connections(only_direct=True)

        logging.info(f"Selected {self.selectivity_percentage}% targets from neighbors: {self.targets}")
        self.last_selection_round += 1

        self.last_selection_round += 1

    async def _inject_malicious_behaviour(self):
        """Inject malicious behavior into the target method."""
        decorated_method = self.decorator(self.decorator_args)(self.original_method)

        setattr(
            self.target_class,
            self.target_method,
            types.MethodType(decorated_method, self.target_class),
        )

    async def _restore_original_behaviour(self):
        """Restore the original behavior of the target method."""
        setattr(self.target_class, self.target_method, self.original_method)

    async def attack(self):
        """Perform the attack logic based on the current round."""
        if self.engine.round not in range(self.round_start_attack, self.round_stop_attack + 1):
            pass
        elif self.engine.round == self.round_stop_attack:
            logging.info(f"[{self.__class__.__name__}] Stoping attack")
            await self._restore_original_behaviour()
        elif (self.engine.round == self.round_start_attack) or (
            (self.engine.round - self.round_start_attack) % self.attack_interval == 0
        ):
            await self.select_targets()
            logging.info(f"[{self.__class__.__name__}] Performing attack")
            await self._inject_malicious_behaviour()
        else:
            await self._restore_original_behaviour()

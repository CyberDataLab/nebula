import logging
import types
from abc import abstractmethod
from functools import wraps

from nebula.addons.attacks.attacks import Attack


class ModelAttack(Attack):
    """
    Base class for implementing model attacks, which modify the behavior of
    model aggregation methods.

    This class defines a decorator for introducing malicious behavior into the
    aggregation process and requires subclasses to implement the model-specific
    attack logic.

    Args:
        engine (object): The engine object that manages the aggregator for
                         model aggregation.
    """

    def __init__(self, engine, round_start_attack, round_stop_attack, attack_interval):
        """
        Initializes the ModelAttack with the specified engine.

        Args:
            engine (object): The engine object that includes the aggregator.
        """
        super().__init__()
        self.engine = engine
        self.aggregator = engine._aggregator
        self.original_aggregation = engine.aggregator.run_aggregation
        self.round_start_attack = round_start_attack
        self.round_stop_attack = round_stop_attack
        self.attack_interval = attack_interval

    def aggregator_decorator(self):
        """
        Decorator that adds a delay to the execution of the original method.

        Args:
            delay (int or float): The time in seconds to delay the method execution.

        Returns:
            function: A decorator function that wraps the target method with
                      the delay logic and potentially modifies the aggregation
                      behavior to inject malicious changes.
        """

        # The actual decorator function that will be applied to the target method
        def decorator(func):
            @wraps(func)  # Preserves the metadata of the original function
            def wrapper(*args):
                _, *new_args = args  # Exclude self argument
                accum = func(*new_args)
                logging.info(f"malicious_aggregate | original aggregation result={accum}")

                if new_args is not None:
                    accum = self.model_attack(accum)
                    logging.info(f"malicious_aggregate | attack aggregation result={accum}")
                return accum

            return wrapper

        return decorator

    @abstractmethod
    def model_attack(self, received_weights):
        """
        Abstract method that applies the specific model attack logic.

        This method should be implemented in subclasses to define the attack
        logic on the received model weights.

        Args:
            received_weights (any): The aggregated model weights to be modified.

        Returns:
            any: The modified model weights after applying the attack.
        """
        raise NotImplementedError

    async def _inject_malicious_behaviour(self):
        """
        Modifies the `propagate` method of the aggregator to include the delay
        introduced by the decorator.

        This method wraps the original aggregation method with the malicious
        decorator to inject the attack behavior into the aggregation process.
        """
        decorated_aggregation = self.aggregator_decorator()(self.aggregator.run_aggregation)
        self.aggregator.run_aggregation = types.MethodType(decorated_aggregation, self.aggregator)

    async def _restore_original_behaviour(self):
        """
        Restores the original behaviour of the `run_aggregation` method.
        """
        self.aggregator.run_aggregation = self.original_aggregation

    async def attack(self):
        """
        Initiates the malicious attack by injecting the malicious behavior
        into the aggregation process.

        This method logs the attack and calls the method to modify the aggregator.
        """
        if self.engine.round not in range(self.round_start_attack, self.round_stop_attack + 1):
            pass
        elif self.engine.round == self.round_stop_attack:
            logging.info(f"[{self.__class__.__name__}] Stopping attack")
            await self._restore_original_behaviour()
        elif (self.engine.round == self.round_start_attack) or (
            (self.engine.round - self.round_start_attack) % self.attack_interval == 0
        ):
            logging.info(f"[{self.__class__.__name__}] Performing attack")
            await self._inject_malicious_behaviour()
        else:
            await self._restore_original_behaviour()

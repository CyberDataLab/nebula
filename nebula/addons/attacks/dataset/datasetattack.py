import logging
from abc import abstractmethod

from nebula.addons.attacks.attacks import Attack


class DatasetAttack(Attack):
    """
    Implements an attack that replaces the training dataset with a malicious version
    during specific rounds of the engine's execution.

    This attack modifies the dataset used by the engine's trainer to introduce malicious
    data, potentially impacting the model's training process.
    """

    def __init__(self, engine, round_start_attack, round_stop_attack, attack_interval):
        """
        Initializes the DatasetAttack with the given engine.

        Args:
            engine: The engine managing the attack context.
        """
        self.engine = engine
        self.round_start_attack = round_start_attack
        self.round_stop_attack = round_stop_attack
        self.attack_interval = attack_interval

    async def attack(self):
        """
        Performs the attack by replacing the training dataset with a malicious version.

        During the specified rounds of the attack, the engine's trainer is provided
        with a malicious dataset. The attack is stopped when the engine reaches the
        designated stop round.
        """
        if self.engine.round not in range(self.round_start_attack, self.round_stop_attack + 1):
            pass
        elif self.engine.round == self.round_stop_attack:
            logging.info(f"[{self.__class__.__name__}] Stopping attack")
        elif self.engine.round >= self.round_start_attack and (
            (self.engine.round - self.round_start_attack) % self.attack_interval == 0
        ):
            logging.info(f"[{self.__class__.__name__}] Performing attack")
            self.engine.trainer.datamodule.train_set = self.get_malicious_dataset()

    async def _inject_malicious_behaviour(self, target_function, *args, **kwargs):
        """
        Abstract method for injecting malicious behavior into a target function.

        This method is not implemented in this class and must be overridden by subclasses
        if additional malicious behavior is required.

        Args:
            target_function (callable): The function to inject the malicious behavior into.
            *args: Positional arguments for the malicious behavior.
            **kwargs: Keyword arguments for the malicious behavior.

        Raises:
            NotImplementedError: This method is not implemented in this class.
        """
        pass

    @abstractmethod
    def get_malicious_dataset(self):
        """
        Abstract method to retrieve the malicious dataset.

        Subclasses must implement this method to define how the malicious dataset
        is created or retrieved.

        Raises:
            NotImplementedError: If the method is not implemented in a subclass.
        """
        raise NotImplementedError

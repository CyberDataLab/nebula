import logging
from nebula.addons.attacks.attacks import create_attack
from nebula.config.config import Config
from nebula.core.engine import Engine
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateReceivedEvent
from nebula.core.training.lightning import Lightning

from enum import Enum

class MaliciousNode(Engine):
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )
        self.attack = create_attack(self)
        self.aggregator_bening = self._aggregator

    async def _extended_learning_cycle(self):
        try:
            await self.attack.attack()
        except Exception:
            attack_name = self.config.participant["adversarial_args"]["attack_params"]["attacks"]
            logging.exception(f"Attack {attack_name} failed")

        if self.role.value == "aggregator":
            await AggregatorNode._extended_learning_cycle(self)
        if self.role.value == "trainer":
            await TrainerNode._extended_learning_cycle(self)
        if self.role.value == "server":
            await ServerNode._extended_learning_cycle(self)


class AggregatorNode(Engine):
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )

    async def _extended_learning_cycle(self):
        # Define the functionality of the aggregator node
        await self.trainer.test()
        await self.trainning_in_progress_lock.acquire_async()
        await self.trainer.train()
        await self.trainning_in_progress_lock.release_async()

        self_update_event = UpdateReceivedEvent(
            self.trainer.get_model_parameters(), self.trainer.get_model_weight(), self.addr, self.round
        )
        await EventManager.get_instance().publish_node_event(self_update_event)

        await self.cm.propagator.propagate("stable")
        await self._waiting_model_updates()


class ServerNode(Engine):
    from datetime import datetime
    
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )
        self._start_time = ServerNode.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    async def _extended_learning_cycle(self):
        # Define the functionality of the server node
        await self.trainer.test()

        self_update_event = UpdateReceivedEvent(
            self.trainer.get_model_parameters(), self.trainer.BYPASS_MODEL_WEIGHT, self.addr, self.round
        )
        await EventManager.get_instance().publish_node_event(self_update_event)

        await self._waiting_model_updates()
        await self.cm.propagator.propagate("stable")


class TrainerNode(Engine):
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )

    async def _extended_learning_cycle(self):
        # Define the functionality of the trainer node
        logging.info("Waiting global update | Assign _waiting_global_update = True")

        await self.trainer.test()
        await self.trainer.train()

        self_update_event = UpdateReceivedEvent(
            self.trainer.get_model_parameters(), self.trainer.get_model_weight(), self.addr, self.round, local=True
        )
        await EventManager.get_instance().publish_node_event(self_update_event)

        await self.cm.propagator.propagate("stable")
        await self._waiting_model_updates()


class IdleNode(Engine):
    def __init__(
        self,
        model,
        datamodule,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )

    async def _extended_learning_cycle(self):
        # Define the functionality of the idle node
        logging.info("Waiting global update | Assign _waiting_global_update = True")
        await self._waiting_model_updates()
from __future__ import annotations
import logging
import asyncio
from nebula.addons.attacks.attacks import create_attack
from nebula.addons.functions import print_msg_box
from nebula.config.config import Config
from nebula.core.utils.locker import Locker
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateReceivedEvent, ModelPropagationEvent
from enum import Enum
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from nebula.core.engine import Engine

#TODO ensure attacks works properly

"""                                                         ##############################
                                                            #        ROLE BEHAVIORS      #
                                                            ##############################
"""

class Role(Enum):
    """
    This class defines the participant roles of the platform.
    """
    TRAINER = "trainer"
    AGGREGATOR = "aggregator"
    TRAINER_AGGREGATOR = "trainer_aggregator"
    PROXY = "proxy"
    IDLE = "idle"
    SERVER = "server"
    MALICIOUS = "malicious"

def factory_node_role(role: str) -> Role:
    if role == "trainer":
        return Role.TRAINER
    elif role == "aggregator":
        return Role.AGGREGATOR
    elif role =="trainer_aggregator":
        return Role.TRAINER_AGGREGATOR
    elif role == "proxy":
        return Role.PROXY
    elif role == "idle":
        return Role.IDLE
    elif role == "server":
        return Role.SERVER
    elif role == "malicious":
        return Role.MALICIOUS
    else:
        return ""

class RoleBehavior(ABC):
    """
    Abstract base class for defining the role-specific behavior of a node in CFL, DFL, or SDFL systems.

    Each subclass encapsulates the logic needed for a particular node role (e.g., trainer, aggregator),
    providing custom implementations for role-related operations such as training cycles,
    update aggregation, and recovery strategies.

    Attributes:
        _next_role (Role): The role to which the node is expected to transition.
        _next_role_locker (Locker): An asynchronous lock to protect access to _next_role.
        _source_to_notificate (Optional[Any]): The source node to notify once a role change is applied.
    """
    def __init__(self):
        self._next_role: Role = None
        self._next_role_locker = Locker("next_role_locker", async_lock=True)
        self._source_to_notificate = None

    @abstractmethod
    def get_role(self):
        """
        Returns the Role enum value representing the current role of the node.
        """
        raise NotImplementedError

    @abstractmethod
    def get_role_name(self, effective=False):
        """
        Returns a string representation of the current role.

        Args:
            effective (bool): Whether to return the name of the current effective role when going as malicious.

        Returns:
            str: Name of the role.
        """
        raise NotImplementedError

    @abstractmethod
    async def extended_learning_cycle(self):
        """
        Performs the main learning or aggregation cycle associated with the current role.

        This method encapsulates all the logic tied to the behavior of the node in its current role,
        including training, aggregating updates, and coordinating with neighbors.
        """
        raise NotImplementedError

    @abstractmethod
    async def select_nodes_to_wait(self):
        """
        Determines which neighbors the node should wait for during the current cycle.

        This logic varies depending on whether the node is an aggregator, trainer, or other role.

        Returns:
            Set[Any]: A set of neighbor node identifiers to wait for.
        """
        raise NotImplementedError

    @abstractmethod
    async def resolve_missing_updates(self):
        """
        Defines the fallback strategy when expected model updates are not received.

        For example, an aggregator might default to a fresh model, while a trainer might proceed
        with its own local model.

        Returns:
            Any: The resolution outcome depending on the role's specific logic.
        """
        raise NotImplementedError

    async def set_next_role(self, role: Role, source_to_notificate = None):
        """
        Schedules a role change and optionally stores the source to notify upon completion.

        Args:
            role (Role): The new role to transition to.
            source_to_notificate (Optional[Any]): Identifier of the node that triggered the change.
        """
        async with self._next_role_locker:
            self._next_role = role
            self._source_to_notificate = source_to_notificate

    async def get_next_role(self) -> Role:
        """
        Retrieves and clears the next role value.

        Returns:
            Role: The next role to transition into.
        """
        async with self._next_role_locker:
            next_role = self._next_role
            self._next_role = None
        return next_role

    async def get_source_to_notificate(self):
        """
        Retrieves and clears the stored source to notify after a role change.

        Returns:
            Any: The source node identifier, or None if not set.
        """
        async with self._next_role_locker:
            source_to_notificate = self._source_to_notificate
            self._source_to_notificate = None
        return source_to_notificate

    async def update_role_needed(self):
        """
        Checks whether a role update is scheduled.

        Returns:
            bool: True if a role update is pending, False otherwise.
        """
        async with self._next_role_locker:
            updt_needed = self._next_role != None
        return updt_needed

    async def before_round_start(self):
        """Hook for role-specific work before a round starts."""
        return None

"""                                                         ##############################
                                                            #     MALICIOUS BEHAVIOR     #
                                                            ##############################
"""

class MaliciousRoleBehavior(RoleBehavior):
    def __init__(self, engine: Engine, config: Config):
        super().__init__()
        print_msg_box(
            msg=f"Role Behavior Malicious initialization",
            indent=2,
            title="Role initialization",
        )
        self._engine = engine
        self._config = config
        logging.info("Creating attack behavior...")
        self.attack = create_attack(self._engine)
        logging.info("Attack behavior created")
        self.aggregator_bening = self._engine._aggregator
        benign_role = self._config.participant["adversarial_args"]["fake_behavior"]
        self._fake_role_behavior = factory_role_behavior(benign_role, self._engine, self._config)
        self._role = factory_node_role("malicious")

    def get_role(self):
        return self._role

    def get_role_name(self, effective=False):
        if effective:
            return self._fake_role_behavior.get_role_name()
        return f"{self._role.value} as {self._fake_role_behavior.get_role_name()}"

    async def extended_learning_cycle(self):
        try:
            await self.attack.attack()
        except Exception:
            attack_name = self._config.participant["adversarial_args"]["attacks"]
            logging.exception(f"Attack {attack_name} failed")

        await self._fake_role_behavior.extended_learning_cycle()

    async def before_round_start(self):
        await self._fake_role_behavior.before_round_start()

    async def select_nodes_to_wait(self):
        nodes = await self._fake_role_behavior.select_nodes_to_wait()
        return nodes

    async def resolve_missing_updates(self):
        return await self._fake_role_behavior.resolve_missing_updates()

"""                                                         ###############################
                                                            # TRAINER AGGREGATOR BEHAVIOR #
                                                            ###############################
"""

class TrainerAggregatorRoleBehavior(RoleBehavior):
    def __init__(self, engine: Engine, config: Config):
        super().__init__()
        self._engine = engine
        self._config = config
        self._role = factory_node_role("trainer_aggregator")

    def get_role(self):
        return self._role

    def get_role_name(self, effective=False):
        return self._role.value

    async def extended_learning_cycle(self):
        await self._engine.trainer.test()
        await self._engine.trainning_in_progress_lock.acquire_async()
        await self._engine.trainer.train()
        await self._engine.trainning_in_progress_lock.release_async()

        self_update_event = UpdateReceivedEvent(
            self._engine.trainer.get_model_parameters(), self._engine.trainer.get_model_weight(), self._engine.addr, self._engine.round
        )
        await EventManager.get_instance().publish_node_event(self_update_event)

        mpe = ModelPropagationEvent(await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False), "stable")
        await EventManager.get_instance().publish_node_event(mpe)

        await self._engine._waiting_model_updates()

    async def select_nodes_to_wait(self):
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=True)
        return nodes

    async def resolve_missing_updates(self):
        return {}

"""                                                         ##############################
                                                            #    AGGREGATOR BEHAVIOR     #
                                                            ##############################
"""

class AggregatorRoleBehavior(RoleBehavior):
    def __init__(self, engine: Engine, config: Config):
        super().__init__()
        self._engine = engine
        self._config = config
        self._role = factory_node_role("aggregator")
        self._transfer_send = False

    def get_role(self):
        return self._role

    def get_role_name(self, effective=False):
        return self._role.value

    async def extended_learning_cycle(self):
        await self._engine.trainer.test()

        await self._engine._waiting_model_updates()

        mpe = ModelPropagationEvent(await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False), "stable")
        await EventManager.get_instance().publish_node_event(mpe)

        await self._transfer_leadership()

    async def _transfer_leadership(self):
        if self._engine.round >= self._engine.total_rounds - 1:
            logging.info(
                f"Skipping leadership transfer in final round {self._engine.round} "
                f"of {self._engine.total_rounds - 1}"
            )
            return

        neighbors = await self._engine.cm.get_addrs_current_connections(myself=False)
        if len(neighbors) and not self._transfer_send:
            successor = await self._engine.select_leadership_successor(neighbors)
            if successor is None:
                return
            lt_message = self._engine.cm.create_message("control", "leadership_transfer")
            logging.info(f"Sending transfer leadership to: {successor}")
            await self._before_leadership_transfer(successor)
            asyncio.create_task(self._engine.cm.send_message(successor, lt_message))
            await self._engine.register_leadership_transfer(successor)
            self._transfer_send = True

    async def _before_leadership_transfer(self, successor):
        return None

    async def select_nodes_to_wait(self):
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return nodes

    async def resolve_missing_updates(self):
        return (self._engine.trainer.get_model_parameters(), self._engine.trainer.BYPASS_MODEL_WEIGHT)


class SDFLRoleMixin:
    async def _send_reputation_model_update(self):
        # SDFL reputation evaluates direct neighbors from the latest local model update.
        model_params = self._engine.trainer.get_model_parameters()
        serialized_model = (
            model_params
            if isinstance(model_params, bytes)
            else self._engine.trainer.serialize_model(model_params)
        )

        message = self._engine.cm.create_message(
            "model",
            round=self._engine.round,
            parameters=serialized_model,
            weight=self._engine.trainer.get_model_weight(),
        )

        neighbors = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        if not neighbors:
            logging.info("SDFL reputation | No direct neighbors to send model/update")
            return

        # Reputation model updates use the regular model channel and stay one-hop local.
        logging.info(f"SDFL reputation | Broadcasting model/update to direct neighbors: {neighbors}")
        await asyncio.gather(
            *[
                asyncio.create_task(self._engine.cm.send_message(neighbor, message, "model"))
                for neighbor in neighbors
            ]
        )


class SDFLAggregatorRoleBehavior(SDFLRoleMixin, AggregatorRoleBehavior):
    async def before_round_start(self):
        # Leadership transfer must be acknowledged before the new aggregator starts a round.
        await self._engine.wait_pending_leadership_ack()

    async def extended_learning_cycle(self):
        # SDFL aggregators collect trainer updates, publish the global model, then rotate leadership.
        await self._engine.trainer.test()
        await self._send_reputation_model_update()
        await self._engine._waiting_model_updates()
        await self._send_global_model()
        await self._transfer_leadership()

    async def _before_leadership_transfer(self, successor):
        await self._engine.mark_leadership_transfer_pending(successor)

    async def select_nodes_to_wait(self):
        # The aggregator waits for all expected trainers, not just currently direct neighbors.
        nodes = self._engine.get_sdfl_expected_trainers()
        if nodes:
            return nodes
        return await super().select_nodes_to_wait()

    async def _send_global_model(self) -> None:
        # Send the aggregated model through the SDFL forwarding channel.
        model_params = self._engine.trainer.get_model_parameters()
        serialized_model = (
            model_params
            if isinstance(model_params, bytes)
            else self._engine.trainer.serialize_model(model_params)
        )

        message = self._engine.cm.create_message(
            "sdflmodel",
            "global_model",
            target="trainer",
            parameters=serialized_model,
            weight=self._engine.trainer.get_model_weight(),
            round=self._engine.round,
            node_id=self._engine.addr,
        )

        neighbors = await self._engine.cm.get_addrs_current_connections(
            only_direct=True,
            myself=False,
        )

        logging.info(f"SDFL aggregator | Broadcasting GLOBAL_MODEL to neighbors: {neighbors}")

        tasks = [
            asyncio.create_task(
                self._engine.cm.send_message(
                    neighbor,
                    message,
                    "sdflmodel",
                    allow_after_learning_finished=True,
                )
            )
            for neighbor in neighbors
        ]

        if tasks:
            await asyncio.gather(*tasks)
        else:
            logging.warning("SDFL aggregator | No neighbors available to send GLOBAL_MODEL")

"""                                                         ##############################
                                                            #       SERVER BEHAVIOR      #
                                                            ##############################
"""

class ServerRoleBehavior(RoleBehavior):
    from datetime import datetime

    def __init__(self, engine: Engine, config: Config):
        super().__init__()
        self._engine = engine
        self._config = config
        self._start_time = ServerRoleBehavior.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self._role = factory_node_role("server")

    def get_role(self):
        return self._role

    def get_role_name(self, effective=False):
        return self._role.value

    async def extended_learning_cycle(self):
        await self._engine.trainer.test()

        await self._engine._waiting_model_updates()

        mpe = ModelPropagationEvent(await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False), "stable")
        await EventManager.get_instance().publish_node_event(mpe)

    async def select_nodes_to_wait(self):
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return nodes

    async def resolve_missing_updates(self):
        return (self._engine.trainer.get_model_parameters(), self._engine.trainer.BYPASS_MODEL_WEIGHT)

"""                                                         ##############################
                                                            #      TRAINER BEHAVIOR      #
                                                            ##############################
"""

class TrainerRoleBehavior(RoleBehavior):
    def __init__(self, engine: Engine, config: Config):
        super().__init__()
        self._engine = engine
        self._config = config
        self._role = factory_node_role("trainer")

    def get_role(self):
        return self._role

    def get_role_name(self, effective=False):
        return self._role.value

    async def extended_learning_cycle(self):
        logging.info("Waiting global update | Assign _waiting_global_update = True")

        await self._engine.trainer.test()
        await self._engine.trainning_in_progress_lock.acquire_async()
        try:
            await self._engine.trainer.train()
        finally:
            await self._engine.trainning_in_progress_lock.release_async()

        mpe = ModelPropagationEvent(await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False), "stable")
        await EventManager.get_instance().publish_node_event(mpe)

        await self._engine._waiting_model_updates()

    async def select_nodes_to_wait(self):
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return nodes

    async def resolve_missing_updates(self):
        return (self._engine.trainer.get_model_parameters(), self._engine.trainer.get_model_weight())


class SDFLTrainerRoleBehavior(SDFLRoleMixin, TrainerRoleBehavior):
    async def extended_learning_cycle(self):
        logging.info("Waiting global update | Assign _waiting_global_update = True")

        await self._engine.trainer.test()
        self._prepare_waiting_global_model()
        # Trainers train locally, exchange reputation evidence, send their update, then wait for aggregation.
        await self._engine.trainning_in_progress_lock.acquire_async()
        try:
            await self._engine.trainer.train()
        finally:
            await self._engine.trainning_in_progress_lock.release_async()

        if self._engine._reputation is not None:
            # Process reputation model updates that arrived before the local table is computed.
            await self._engine._reputation.process_pending_sdfl_reputation_updates(self._engine.round)

        await self._send_reputation_model_update()
        await self._calculate_and_send_reputation_table()
        await self._send_trainer_update()
        await self._waiting_global_model()

    def _prepare_waiting_global_model(self):
        # Reset the per-round event used by trainers to block until a GLOBAL_MODEL arrives.
        self._engine._global_model_source = None
        self._engine._global_model_received.clear()

    async def _calculate_and_send_reputation_table(self):
        # Trainers publish direct-neighbor reputation tables for the aggregator to combine.
        if self._engine._reputation is None:
            return

        expected_reputation_neighbors = await self._engine.cm.get_addrs_current_connections(
            only_direct=True,
            myself=False,
        )
        reputation_timeout = float(
            self._config.participant["defense_args"]
            .get("reputation", {})
            .get(
                "model_update_timeout",
                self._config.participant["defense_args"]
                .get("reputation", {})
                .get("table_aggregation_timeout", 30),
            )
        )
        await self._engine._reputation.wait_sdfl_reputation_updates(
            expected_reputation_neighbors,
            self._engine.round,
            reputation_timeout,
        )
        await self._engine._reputation.calculate_and_send_sdfl_reputation_table()

    async def _send_trainer_update(self):
        # Broadcast the local trainer update; forwarding delivers it to the current aggregator.
        model_params = self._engine.trainer.get_model_parameters()
        serialized_model = (
            model_params
            if isinstance(model_params, bytes)
            else self._engine.trainer.serialize_model(model_params)
        )

        message = self._engine.cm.create_message(
            "sdflmodel",
            "trainer_update",
            target="aggregator",
            parameters=serialized_model,
            weight=self._engine.trainer.get_model_weight(),
            round=self._engine.round,
            node_id=self._engine.addr,
        )

        neighbors = await self._engine.cm.get_addrs_current_connections(
            only_direct=True,
            myself=False,
        )

        logging.info(f"SDFL trainer | Broadcasting TRAINER_UPDATE to neighbors: {neighbors}")

        tasks = [
            asyncio.create_task(
                self._engine.cm.send_message(
                    neighbor,
                    message,
                    "sdflmodel",
                )
            )
            for neighbor in neighbors
        ]

        if tasks:
            await asyncio.gather(*tasks)
        else:
            logging.warning("SDFL trainer | No neighbors available to send TRAINER_UPDATE")

    async def _waiting_global_model(self):
        # A trainer continues only after the aggregator's GLOBAL_MODEL is received or times out.
        timeout = self._config.participant["aggregator_args"]["aggregation_timeout"]
        logging.info(f"💤  Waiting global SDFL model in round {self._engine.round}.")
        try:
            await asyncio.wait_for(self._engine._global_model_received.wait(), timeout=timeout)
            logging.info(
                f"🤖  SDFL trainer | Global model received from "
                f"{self._engine._global_model_source} in round {self._engine.round}"
            )
        except TimeoutError:
            logging.error(f"🤖  SDFL trainer | Timeout waiting global model in round {self._engine.round}")

"""                                                         ##############################
                                                            #       IDLE BEHAVIOR        #
                                                            ##############################
"""

class IdleRoleBehavior(RoleBehavior):
    def __init__(self, engine: Engine, config: Config):
        super().__init__()
        self._engine = engine
        self._config = config
        self._role = factory_node_role("idle")

    def get_role(self):
        return self._role

    def get_role_name(self, effective=False):
        return self._role.value

    async def extended_learning_cycle(self):
        logging.info("Waiting global update | Assign _waiting_global_update = True")
        await self._engine._waiting_model_updates()

    async def select_nodes_to_wait(self):
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return nodes

    async def resolve_missing_updates(self):
        raise NotImplementedError

"""                                                         ##############################
                                                            #       PROXY BEHAVIOR       #
                                                            ##############################
"""

class ProxyRoleBehavior(RoleBehavior):
    def __init__(self, engine: Engine, config: Config):
        super().__init__()
        self._engine = engine
        self._config = config
        self._role = factory_node_role("proxy")

    def get_role(self):
        return self._role

    def get_role_name(self, effective=False):
        return self._role.value

    async def extended_learning_cycle(self):
        logging.info("Waiting global update | Assign _waiting_global_update = True")
        await self._engine._waiting_model_updates()

    async def select_nodes_to_wait(self):
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return nodes

    async def resolve_missing_updates(self):
        raise NotImplementedError

"""                                                         ##############################
                                                            #    UTILS ROLE BEHAVIORS    #
                                                            ##############################
"""

class roleBehaviorException(Exception):
    pass

def factory_role_behavior(role: str, engine: Engine, config: Config) -> RoleBehavior | None:
    federation = config.participant["scenario_args"].get("federation")
    if federation == "SDFL":
        sdfl_role_behaviors = {
            "trainer": SDFLTrainerRoleBehavior,
            "aggregator": SDFLAggregatorRoleBehavior,
        }
        node_role = sdfl_role_behaviors.get(role)
        if node_role:
            return node_role(engine, config)

    role_behaviors = {
        "malicious": MaliciousRoleBehavior,
        "trainer": TrainerRoleBehavior,
        "aggregator": AggregatorRoleBehavior,
        "server": ServerRoleBehavior,
        "trainer_aggregator": TrainerAggregatorRoleBehavior,
        "proxy": ProxyRoleBehavior,
        "idle": IdleRoleBehavior,
    }

    node_role = role_behaviors.get(role, None)

    if node_role:
        return node_role(engine, config)
    else:
        raise roleBehaviorException(f"Node Role Behavior {role} not found")

def change_role_behavior(old_role: RoleBehavior, new_role: Role, *parameters) -> RoleBehavior:
    engine, config = parameters
    if not isinstance(old_role, MaliciousRoleBehavior):
        return factory_role_behavior(new_role.value, engine, config)
    else:
        fake_behavior = factory_role_behavior(new_role.value, engine, config)
        old_role._fake_role_behavior = fake_behavior
        return old_role

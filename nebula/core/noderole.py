from __future__ import annotations
import logging
import asyncio
from nebula.addons.attacks.attacks import create_attack
from nebula.addons.functions import print_msg_box
from nebula.config.config import Config
from nebula.core.utils.locker import Locker
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateReceivedEvent, ModelPropagationEvent
import random
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
    def __init__(self):
        self._next_role: Role = None
        self._next_role_locker = Locker("next_role_locker", async_lock=True)
        self._source_to_notificate = None
        
    @abstractmethod
    def get_role(self):
        raise NotImplementedError
    
    @abstractmethod
    def get_role_name(self, effective=False):
        raise NotImplementedError
    
    @abstractmethod
    async def extended_learning_cycle(self):
        raise NotImplementedError
    
    @abstractmethod
    async def select_nodes_to_wait(self):
        raise NotImplementedError
    
    async def set_next_role(self, role: Role, source_to_notificate = None):
        async with self._next_role_locker:
            self._next_role = role
            self._source_to_notificate = source_to_notificate
        
    async def get_next_role(self) -> Role:
        async with self._next_role_locker:
            next_role = self._next_role
            self._next_role = None
        return next_role
    
    async def get_source_to_notificate(self):
        async with self._next_role_locker:
            source_to_notificate = self._source_to_notificate
            self._source_to_notificate = None
        return source_to_notificate
        
    async def update_role_needed(self):
        async with self._next_role_locker:
            updt_needed = self._next_role != None
        return updt_needed
    
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
        
    async def select_nodes_to_wait(self):
        nodes = await self._fake_role_behavior.select_nodes_to_wait()
        return nodes

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
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return nodes

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
            
        # self_update_event = UpdateReceivedEvent(
        #     self._engine.trainer.get_model_parameters(), self._engine.trainer.BYPASS_MODEL_WEIGHT, self._engine.addr, self._engine.round
        # )
        # await EventManager.get_instance().publish_node_event(self_update_event)

        await self._engine._waiting_model_updates()
        
        mpe = ModelPropagationEvent(await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False), "stable")
        await EventManager.get_instance().publish_node_event(mpe)
        
        # Transfer leadership
        neighbors = await self._engine.cm.get_addrs_current_connections(myself=False)
        if len(neighbors) and not self._transfer_send:
            random_neighbor = random.choice(list(neighbors))
            lt_message = self._engine.cm.create_message("control", "leadership_transfer")
            logging.info(f"Sending transfer leadership to: {random_neighbor}")
            asyncio.create_task(self._engine.cm.send_message(random_neighbor, lt_message))
            self._transfer_send = True
        
    async def select_nodes_to_wait(self):
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return nodes
        
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

        # self_update_event = UpdateReceivedEvent(
        #     self._engine.trainer.get_model_parameters(), self._engine.trainer.BYPASS_MODEL_WEIGHT, self._engine.addr, self._engine.round
        # )
        # await EventManager.get_instance().publish_node_event(self_update_event)

        await self._engine._waiting_model_updates()
        
        mpe = ModelPropagationEvent(await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False), "stable")
        await EventManager.get_instance().publish_node_event(mpe)
        
    async def select_nodes_to_wait(self):
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return nodes 

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
        await self._engine.trainer.train()

        # self_update_event = UpdateReceivedEvent(
        #     self._engine.trainer.get_model_parameters(), self._engine.trainer.get_model_weight(), self._engine.addr, self._engine.round, local=True
        # )
        # await EventManager.get_instance().publish_node_event(self_update_event)

        mpe = ModelPropagationEvent(await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False), "stable")
        await EventManager.get_instance().publish_node_event(mpe)
        
        await self._engine._waiting_model_updates()
        
    async def select_nodes_to_wait(self):
        nodes = await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return nodes

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

"""                                                         ##############################
                                                            #    UTILS ROLE BEHAVIORS    #
                                                            ##############################
"""
          
class roleBehaviorException(Exception):
    pass

def factory_role_behavior(role: str, engine: Engine, config: Config) -> RoleBehavior | None: 
     
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
            


        

import logging
import asyncio
from typing import Dict
from nebula.controller.federation.federation_controller import FederationController, EXPERIMENT_TYPES 
from nebula.controller.federation.factory_federation_controller import federation_controller_factory
from nebula.controller.federation.schemas.errors import BAD_CONTROLLER
from nebula.controller.federation.utils.api_utils import raise_error
from nebula.kafka.clients.agent_client import NebulaKafkaAgent
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
from nebula.kafka.clients.messages.experiment import (
    ExperimentINITMessage,
    UpdateMessage,
    DoneMessage,
)
from nebula.kafka.clients.messages.system import (
    AgentReadyMessage,
)

class FederationBroker():
    def __init__(self, hub_url: str, logger: logging.Logger):
        self._hub_url = hub_url
        self._logger = logger
        self._fed_controllers: Dict[str, FederationController] = {}
        self._kafka_client = None
        
    @property
    def log(self):
        return self._logger
    
    def _initialize_federation_controllers(self):
        for exp_type in EXPERIMENT_TYPES:
            self._fed_controllers[exp_type] = federation_controller_factory(exp_type, self._hub_url, self._logger)
            self.log.info(f"{exp_type} Federation controller created.")
             
    def _get_controller(self, experiment_type):
        controller = self._fed_controllers.get(experiment_type, None)
        if controller:
            return controller
        else:
            raise_error(BAD_CONTROLLER)
               
    """                                             ###############################
                                                    #           API REST          #
                                                    ###############################
    """
    
    async def run_scenario(self, experiment_type: str, federation_id: str, scenario_data: Dict, user: str):
        controller = self._get_controller(experiment_type)
        return await controller.run_scenario(federation_id, scenario_data, user)
    
    async def stop_scenario(self, experiment_type: str, federation_id: str):
        controller = self._get_controller(experiment_type)
        return await controller.stop_scenario(federation_id)

    async def remove_scenario(self, experiment_type: str, federation_id: str, user: str, scenario_name: str):
        controller = self._get_controller(experiment_type)
        return await controller.remove_scenario(federation_id, experiment_type, user, scenario_name)
    
    """                                             ###############################
                                                    #         KAFKA SERVICE       #
                                                    ###############################
    """
    
    async def initialize_control_system(self, broker: str, user: str, password: str):
        self._kafka_client = NebulaKafkaAgent(
            broker=broker, 
            user=user, 
            password=password,
            client_id="N-Controller",
            logger=self._logger
        )
        await self._kafka_client.init()
        await self._kafka_client.register_listener(self._handle_kafka_messages)
        
    async def _handle_kafka_messages(self, message: KafkaMessage):
        try:

            # Experiment Messages
            if isinstance(message, UpdateMessage):
                self.log.info(f"Update received for experiment {message.experiment_id}")
                controller = self._get_controller(message.experiment_type)
                try:
                    await controller.update_nodes(message.experiment_id, message.config)
                except Exception as e:
                    self.log.error(f"[ERROR]: {e}")

            elif isinstance(message, DoneMessage):
                self.log.info(f"Done received for experiment {message.idx}")
                controller = self._get_controller(message.experiment_type)
                try:
                    await controller.node_done(message.experiment_id, message.idx, "", "")
                except Exception as e:
                    self.log.error(f"[ERROR]: {e}")

             # System Messages
            elif isinstance(message, AgentReadyMessage):
                self.log.info(f"Agent ready received: {message.agent}")
                pass
            else:
                self.log.warning(f"⚠️ Unhandled Kafka message type: {type(message).__name__}")

        except Exception as e:
            self.log.exception(f"❌ Error handling Kafka message {type(message).__name__}: {e}")
        
       
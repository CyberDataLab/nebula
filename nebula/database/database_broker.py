import base64
import logging
import asyncio
from typing import Dict
from nebula.database.database_adapter_factory import factory_database_adapter
from nebula.kafka.clients.agent_client import NebulaKafkaAgent
from nebula.kafka.clients.messages.message_handler import KafkaMessageHandler, generate_handler
from nebula.kafka.clients.messages.experiment import (
    ExperimentINITMessage,
    UpdateMessage,
)
from nebula.kafka.clients.messages.system import (
    CompletedExperimentMessage,
)

class DatabaseBroker():
    def __init__(self, database_adapter: str, logger: logging.Logger):
        self._database_adapter = factory_database_adapter(database_adapter)
        self._logger = logger
        self._kafka_client: NebulaKafkaAgent = None


    @property
    def db(self):
        return self._database_adapter

    @property
    def log(self):
        return self._logger
    
    async def init(self, broker: str, user: str, password: str):
        await self.db._init_db_pool()
        self.log.info(f"{broker} -- {user} -- {password}")
        await asyncio.sleep(60)
        await self._initialize_kafka_service(broker, user, password)

    async def shutdown(self):
        await self._kafka_client.shutdown()
        await self.db._close_db_pool()

    """                                             ###############################
                                                    #           API REST          #
                                                    ###############################
    """

    # Scenarios
    async def save_scenario(self, federation_id: str, **kwargs):
        return await self.db._save_scenario(
            federation_id = federation_id,
            **kwargs
        )

    async def stop_scenario(self, federation_id: str, **kwargs):
        return await self.db._finish_scenario(federation_id, **kwargs)

    async def remove_scenario(self, federation_id: str):
        return await self.db._remove_scenario_by_federation_id(federation_id)

    async def get_scenarios(self, **kwargs):
        return await self.db._get_scenarios(**kwargs)

    async def set_scenario_status_to_finished(self, federation_id: str, **kwargs):
        return await self.db._finish_scenario(federation_id, **kwargs)

    async def get_running_scenario(self, **kwargs):
        return await self.db._get_running_scenario(**kwargs)

    async def check_scenario(self, **kwargs):
        return await self.db._check_scenario_with_role(**kwargs)

    async def get_scenario_by_name(self, federation_id: str):
        return await self.db._get_scenario_by_federation_id(federation_id)

    # Nodes
    async def list_nodes_by_federation_id(self, federation_id: str):
        return await self.db._list_nodes_by_federation_id(federation_id)

    async def remove_nodes_by_federation_id(self, federation_id: str):
        return await self.db._remove_nodes_by_federation_id(federation_id)

    # Notes
    async def get_notes_by_federation_id(self, federation_id: str):
        return await self.db._get_notes(federation_id)

    async def update_notes_by_scenario_name(self, federation_id: str, **kwargs):
        return await self.db._save_notes(federation_id , **kwargs)

    async def remove_notes_by_federation_id(self, federation_id: str):
        return await self.db._remove_note(federation_id)

    """                                             ###############################
                                                    #         KAFKA SERVICE       #
                                                    ###############################
    """

    async def _initialize_kafka_service(self, broker: str, user: str, password: str):
        callbacks = [
            (UpdateMessage, self._handle_update_message),
            (CompletedExperimentMessage, self._handle_finish_experiment_message)
        ]
        message_handler = generate_handler(self._logger, callbacks)

        self._kafka_client = NebulaKafkaAgent(
            broker=broker,
            user=user,
            password=password,
            client_id=user,
            logger=self._logger,
            handler=message_handler,
        )
        
        await self._kafka_client.init(producer=True)
        
    async def _handle_update_message(self, message: UpdateMessage):
        await self.db._update_node_record(
            message.config["device_args"]["uid"],
            message.config["device_args"]["idx"],
            message.config["network_args"]["ip"],
            message.config["network_args"]["port"],
            message.config["device_args"]["role"],
            message.config["network_args"]["neighbors"],
            message.config["timestamp"],
            message.config["scenario_args"]["federation"],
            message.config["federation_args"]["round"],
            message.config["scenario_args"]["federation_id"],
            message.config["device_args"]["malicious"],
        )

    async def _handle_finish_experiment_message(self, message: CompletedExperimentMessage):
        await self.db._(message.experiment)

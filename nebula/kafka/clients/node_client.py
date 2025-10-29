from aiokafka import AIOKafkaProducer
from kafka.errors import KafkaError
from nebula.kafka.clients.messages.experiment import ExperimentMessages
from nebula.kafka.clients.messages.utils.utils import factory_experiment_message
import logging

class NebulaKafkaNode:
    def __init__(self, broker: str, experiment_topic: str, user: str, password: str, idx: str, logger: logging.Logger):
        self._broker = broker
        self._experiment_topic = experiment_topic
        self._username = user
        self._password = password
        self._logger = logger
        self._producer = AIOKafkaProducer(
            bootstrap_servers=broker,
            client_id=f"node-{idx}-{self._experiment_topic}",
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username=self._username,
            sasl_plain_password=self._password,
        )
             
    @property
    def log(self):
        return self._logger
    
    async def init(self):
        await self._producer.start()
        
    async def produce(self, message_type: ExperimentMessages, data):
        message = factory_experiment_message(message_type, data=data)
        if message is None:
            self.log.info(f"Cannot create message type '{message_type}'")
            return
        
        try:
            await self._producer.send_and_wait(self._experiment_topic, message.to_bytes())
        except KafkaError as e:
            self.log.error(f"Kafka error sending {message_type}: {e}")
        except Exception as e:
            self.log.info(f"Unexpected error sending message: {e}")

    async def shutdown(self):
        try:
            await self._producer.stop()
            self.log.info("Kafka producer stopped successfully.")
        except Exception as e:
            self.log.info(f"Error stopping Kafka producer: {e}")
           

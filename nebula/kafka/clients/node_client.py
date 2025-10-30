from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError, KafkaTimeoutError, KafkaError
from nebula.kafka.clients.messages.experiment import ExperimentMessages
from nebula.kafka.clients.messages.utils.utils import factory_kafka_message
from nebula.kafka.clients.errors import KafkaInitializationError
import logging
import asyncio

class NebulaKafkaNode:
    def __init__(self, broker: str, experiment_topic: str, user: str, password: str, idx: str, logger: logging.Logger):
        self._broker = broker
        self._experiment_topic = experiment_topic
        self._username = user
        self._password = password
        self._logger = logger
        self._client_id = f"node-{idx}-{self._experiment_topic}"
        self._producer = AIOKafkaProducer(
            bootstrap_servers=broker,
            client_id=self._client_id,
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username=self._username,
            sasl_plain_password=self._password,
        )
             
    @property
    def log(self):
        return self._logger
    
    async def init(self, max_retries=3, delay=2):
        for attempt in range(1, max_retries + 1):
            try:
                self.log.info(f"[Kafka] Attempting to start producer (attempt {attempt}/{max_retries})...")
                await self._producer.start()
                self.log.info(f"[Kafka] Producer started successfully with client_id='{self._client_id}'")
                return True
            except (KafkaConnectionError, KafkaTimeoutError) as e:
                self.log.warning(f"[Kafka] Connection issue on attempt {attempt}: {e}")
            except Exception as e:
                self.log.exception(f"[Kafka] Unexpected error starting producer (attempt {attempt}): {e}")

            if attempt < max_retries:
                self.log.info(f"[Kafka] Retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                self.log.error(f"[Kafka] Failed to start producer after {max_retries} attempts")
                raise KafkaInitializationError("Unable to start Kafka producer after multiple attempts.")
            
        
    async def produce(self, message_type: ExperimentMessages, data):
        message = factory_kafka_message(message_type, data=data)
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
           

from typing import Awaitable, Callable
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError, KafkaTimeoutError, KafkaError as AioKafkaError
from kafka.errors import KafkaError
from nebula.kafka.clients.messages.message_handler import KafkaMessageHandler
from nebula.kafka.clients.messages.system import SystemMessages
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
from nebula.kafka.clients.messages.utils.utils import factory_kafka_message, parse_kafka_message
from nebula.kafka.clients.messages.system import NEBULA_SYSTEM_TOPIC
from nebula.kafka.clients.errors import KafkaInitializationError, KafkaTopicSubscriptionError, KafkaConsumerLoopError, KafkaProducerError, KafkaMessageHandlerNotDefined
from nebula.core.utils.locker import Locker
import logging
import asyncio
    
class NebulaKafkaAgent:
    def __init__(self, broker: str, user: str, password: str, client_id: str, logger: logging.Logger, handler: KafkaMessageHandler = None):
        self._broker = broker
        self._username = user
        self._password = password
        self._client_id = client_id
        self._logger = logger
        self._producer = AIOKafkaProducer(
            bootstrap_servers=broker,
            client_id=self._client_id,
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username=self._username,
            sasl_plain_password=self._password,
        )
        self._consumer = None
        self._consumer_stop = asyncio.Event()
        self._consumer_loop_task = None
        self._handler = handler
         
    @property
    def log(self):
        return self._logger
     
    async def init(self, producer=True, subscribe_all=True, max_retries=3, retry_delay=2):
        try:
            if producer:
                for attempt in range(1, max_retries + 1):
                    try:
                        self.log.info(f"[Kafka] Starting producer (attempt {attempt}/{max_retries})")
                        await self._producer.start()
                        self.log.info(f"[Kafka] Producer started successfully with client_id='{self._client_id}'")
                        break
                    except (KafkaTimeoutError, KafkaConnectionError) as e:
                        self.log.info(f"[Kafka] Producer connection issue: {e}")
                    except KafkaError as e:
                        self.log.info(f"[Kafka] KafkaError starting producer: {e}")
                    except Exception as e:
                        self.log.info(f"[Kafka] Unexpected error starting producer: {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay)
                    else:
                        raise KafkaInitializationError("Failed to start Kafka producer after multiple attempts on NebulaKafkaAgent.")

            self._consumer = AIOKafkaConsumer(
                bootstrap_servers=self._broker,
                client_id=self._client_id,
                group_id=f"g-{self._client_id}",
                security_protocol="SASL_PLAINTEXT",
                sasl_mechanism="SCRAM-SHA-256",
                sasl_plain_username=self._username,
                sasl_plain_password=self._password,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
            )
            await self._consumer.start()

            if subscribe_all:
                await self.subscribe_topics(pattern="^experiment-.*|^nebula-system-control$")
            else:
                await self.subscribe_topics(topics=[NEBULA_SYSTEM_TOPIC])

            sent = await self.produce(SystemMessages.AGENT_READY, data=self._client_id)
            if not sent:
                raise KafkaProducerError("Failed to produce AGENT_READY message")
            
            self._consumer_loop_task = asyncio.create_task(self._consume_loop())
            self.log.info(f"[SUCCESS]: Kafka initialization process")
        except Exception as e:
            self.log.info(f"[Kafka] Initialization failed: {e}")
            await self.shutdown()
            raise KafkaInitializationError(f"Unable to start Kafka-Agent: {e}") from e
        
    async def produce(self, message_type: SystemMessages, data) -> bool:
        message = factory_kafka_message(message_type, data=data)
        if message is None:
            self.log.info(f"Cannot create message type '{message_type}'")
            return False
        
        try:
            self.log.info(f"[Kafka] Sending message {message_type.name} -> {NEBULA_SYSTEM_TOPIC}")
            await self._producer.client.force_metadata_update()
            self.log.info(f"[Kafka] Producer metadata state: {self._producer._metadata.topics()}")
            await asyncio.sleep(2)
            await self._producer.send_and_wait(NEBULA_SYSTEM_TOPIC, message.to_bytes())
            self.log.info(f"[Kafka] ✅ Message {message_type.name} sent successfully.")
            return True
        except AioKafkaError as e:
            self.log.info(f"Kafka error sending {message_type}: {e}")
            return False
        except Exception as e:
            self.log.info(f"Unexpected error sending message: {e}")
            return False
                
    async def subscribe_topics(self, topics: list = [], pattern = ""):
        try:
            if topics:
                self._consumer.subscribe(topics)
                self.log.info(f"[SUCCESS] Topic subscribed'{topics}'")
            elif pattern:
                self._consumer.subscribe(pattern=pattern)
                self.log.info(f"[SUCCESS] Topic subscribed using pattern: '{pattern}'")
            else:
                self.log.info(f"[ERROR] no topics or pattern")
                raise KafkaTopicSubscriptionError(f"[ERROR] no topics or pattern")
        except AioKafkaError as e:
            self.log.info(f"[ERROR]: {e}")
            raise KafkaTopicSubscriptionError(f"[ERROR]: {e}")
       
    async def set_handler(self, handler: KafkaMessageHandler):
        self._handler = handler      
                      
    async def _consume_loop(self):
        # queue + workers if high concurrency
        await asyncio.sleep(1) 
        self.log.info(f"Consumer loop started..") 
        try:
            async for msg in self._consumer:
                if self._consumer_stop.is_set():
                    self.log.info("Consumer stop requested")
                    break

                try:
                    kafka_message = parse_kafka_message(msg.value)
                    if kafka_message is None:
                        self.log.info(f"Failed to parse message from topic {msg.topic}")
                        continue

                    # Trigger event
                    self.log.info(f"Message received '{kafka_message}'")
                    if not self._handler:
                        raise KafkaMessageHandlerNotDefined("[ERROR]: Kafka Message Handler is not defined")
                    
                    asyncio.create_task(self._handler.handle(kafka_message))

                except Exception as e:
                    self.log.info(f"Error processing message from topic {msg.topic}: {e}")

        except asyncio.CancelledError as ce:
            self.log.info("Consumer loop cancelled")
            raise KafkaConsumerLoopError(f"[ERROR]: {ce}") from ce
        except Exception as e:
            self.log.info(f"Unexpected error in consumer loop: {e}")
            raise KafkaConsumerLoopError(f"[ERROR]: {e}") from e
        finally:
            await self._consumer.stop()
           
    async def shutdown(self):
        await self._shutdown_consumer()
        await self._shutdown_producer()
                
    async def _shutdown_consumer(self):
        self._consumer_stop.set()            

    async def _shutdown_producer(self):
        try:
            await self._producer.stop()
            self.log.info("Kafka producer stopped successfully.")
        except Exception as e:
            self.log.info(f"Error stopping Kafka producer: {e}")
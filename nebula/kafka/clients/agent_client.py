from typing import Awaitable, Callable
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError, KafkaTimeoutError, KafkaError as AioKafkaError
from kafka.errors import KafkaError
from nebula.kafka.clients.messages.system import SystemMessages
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
from nebula.kafka.clients.messages.utils.utils import factory_kafka_message, parse_kafka_message
from nebula.kafka.clients.messages.system import NEBULA_SYSTEM_TOPIC
from nebula.kafka.clients.errors import KafkaInitializationError
from nebula.core.utils.locker import Locker
import logging
import asyncio
    
class NebulaKafkaAgent:
    def __init__(self, broker: str, user: str, password: str, client_id: str, logger: logging.Logger):
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
        self._listeners: list[Callable[[KafkaMessage], Awaitable[None]]] = []
        self._listeners_lock = Locker("listeners_lock", async_lock=True)
         
    @property
    def log(self):
        return self._logger
     
    async def init(self, subscribe_all=True, max_retries=3, retry_delay=2):
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    self.log.info(f"[Kafka] Starting producer (attempt {attempt}/{max_retries})")
                    await self._producer.start()
                    break
                except (KafkaTimeoutError, KafkaConnectionError) as e:
                    self.log.warning(f"[Kafka] Producer connection issue: {e}")
                except KafkaError as e:
                    self.log.error(f"[Kafka] KafkaError starting producer: {e}")
                except Exception as e:
                    self.log.exception(f"[Kafka] Unexpected error starting producer: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
                else:
                    raise KafkaInitializationError("Failed to start Kafka producer after multiple attempts")

            self._consumer = AIOKafkaConsumer(
                bootstrap_servers=self._broker,
                client_id=self._client_id,
                security_protocol="SASL_PLAINTEXT",
                sasl_mechanism="SCRAM-SHA-256",
                sasl_plain_username=self._username,
                sasl_plain_password=self._password,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
            )
            await self._consumer.start()

            if subscribe_all:
                success = await self.subscribe_topics(pattern="^experiment-.*|^nebula-system-control$")
            else:
                success = await self.subscribe_topics(topics=[NEBULA_SYSTEM_TOPIC])

            if not success:
                raise KafkaInitializationError("Failed to subscribe to topics")

            sent = await self.produce(SystemMessages.AGENT_READY, self._client_id)
            if not sent:
                raise KafkaInitializationError("Failed to produce AGENT_READY message")

        except Exception as e:
            self.log.exception(f"[Kafka] Initialization failed: {e}")
            await self.shutdown()
            raise KafkaInitializationError(f"Unable to start Kafka-Agent: {e}")
        
    async def produce(self, message_type: SystemMessages, data):
        message = factory_kafka_message(message_type, data=data)
        if message is None:
            self.log.info(f"Cannot create message type '{message_type}'")
            return
    
        try:
            await self._producer.send_and_wait(NEBULA_SYSTEM_TOPIC, message.to_bytes())
        except AioKafkaError as e:
            self.log.error(f"Kafka error sending {message_type}: {e}")
        except Exception as e:
            self.log.error(f"Unexpected error sending message: {e}")
                
    async def subscribe_topics(self, topics: list = [], pattern = ""):
        try:
            if topics:
                self._consumer.subscribe(topics)
                self.log.info(f"[SUCCESS] Topic subscribed'{topics}'")
            elif pattern:
                self._consumer.subscribe(pattern=pattern)
                self.log.info(f"[SUCCESS] Topic subscribed using pattern: '{pattern}'")
            else:
                self.log.error(f"[ERROR] no topics or pattern")
        except AioKafkaError as e:
            self.log.error(f"[ERROR]: {e}")
            
    async def register_listener(self, callback: Callable[[KafkaMessage], Awaitable[None]]):
        async with self._listeners_lock:
            self._listeners.append(callback)
            
    async def _handle_message(self, message: KafkaMessage):
        for listener in self._listeners:
            try:
                await listener(message)
            except Exception as e:
                self.log.exception(f"Error in listener: {e}")        
            
    async def _consume_loop(self):
        # queue + workers if high concurrency
        await asyncio.sleep(1)  
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
                    asyncio.create_task(self._handle_message(kafka_message))

                except Exception as e:
                    self.log.exception(f"Error processing message from topic {msg.topic}: {e}")

        except asyncio.CancelledError:
            self.log.info("Consumer loop cancelled")
        except Exception as e:
            self.log.exception(f"Unexpected error in consumer loop: {e}")
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
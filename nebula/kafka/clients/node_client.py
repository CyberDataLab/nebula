from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from kafka.errors import KafkaError
from nebula.kafka.clients.messages.experiment import ExperimentMessages
from nebula.kafka.clients.messages.utils.utils import factory_experiment_message
from nebula.core.utils.locker import Locker
import logging
import asyncio

class NebulaKafkaNode:
    def __init__(self, broker: str, experiment_topic: str, user: str, password: str, logger: logging.Logger):
        self._broker = broker
        self._experiment_topic = experiment_topic
        self._username = user
        self._password = password
        
        self._consumer_stop = asyncio.Event()
        self._consumer = None
        self._consumer_started = False
        self._consumer_lock = Locker("consumer_lock", async_lock=True)
        self._consumer_loop_task = None
        
        self._logger = logger
        self._producer = AIOKafkaProducer(bootstrap_servers=broker)
            
    
    @property
    def log(self):
        return self._logger
    
    async def init(self):
        await self._producer.start()
        await self._producer.send_and_wait(self._experiment_topic, b"init-message")
        await self._producer.stop()
        
    async def produce(self, message_type: ExperimentMessages, data):
        message = factory_experiment_message(message_type, data=data)
        if message is None:
            self.log.info(f"Cannot create message type '{message_type}'")
            return
        
        try:
            await self._producer.send_and_wait(self._experiment_topic, message.to_bytes())
        except Exception as e:
            self.log.info(f"Error sending message: {e}")

    async def shoutdown(self):
        self._consumer_stop.set()
    
    async def _init_consumer(self):
        async with self._consumer_lock:
            if not self._consumer:
                self._consumer = AIOKafkaConsumer(
                    bootstrap_servers= self._broker,
                    group_id="hub",
                    auto_offset_reset="earliest",
                    enable_auto_commit=True,
                )
            if not self._consumer_started:
                await self._consumer.start()
                self._consumer_started = True

    async def _shutdown_consumer(self):
        async with self._consumer_lock:
            if self._consumer and self._consumer_started:
                await self._consumer.stop()
                self._consumer_started = False
                
    async def subscribe_topics(self, topics: list = [], pattern = ""):
        try:
            if topics:
                self._consumer.subscribe(topics)
                self.log.info(f"[SUCCESS] Topic subscribed'{topics}'")
            elif pattern:
                self._consumer.subscribe(pattern=pattern)
                self.log.info(f"[SUCCESS] Topic subscribed using pattern: '{pattern}'")
            else:
                self.log.info(f"ERROR no topics or pattern")
        except KafkaError as e:
            self.log.info(f"[ERROR]: {e}")
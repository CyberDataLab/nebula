from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from kafka.errors import KafkaError, TopicAlreadyExistsError
import asyncio
from nebula.core.utils.locker import Locker
import logging

# --- Datos de conexión ---
BROKER_9094 = "dev_dev_alejandro_nebula-kafka:9094"
BROKER_9092 = "dev_dev_alejandro_nebula-kafka:9092"

class HUBKafkaClient:
    def __init__(self, logger: logging.Logger):
        self._username = "hub_admin"
        self._password = "hub_admin_password"
        self._consumer_stop = asyncio.Event()
        self._consumer = None
        self._consumer_started = False
        self._consumer_lock = Locker("consumer_lock", async_lock=True)
        self._client = None
        self._system_control_topic = "nebula-system-control"
        self._consumer_loop_task = None
        self._logger = logger

    @property
    def log(self):
        return self._logger

    async def init(self):
        self._client = AIOKafkaAdminClient(
            bootstrap_servers=BROKER_9092
        )
        await self._client.start()
        msg = await self.create_topic(self._system_control_topic)
        await self._init_consumer()
        await asyncio.sleep(1)
        await self.subscribe_topics(pattern="^experiment-.*|^nebula-system-control$")
        self._consumer_loop_task = asyncio.create_task(self._consume_loop())
        return msg
    
    async def _init_consumer(self):
        async with self._consumer_lock:
            if not self._consumer:
                self._consumer = AIOKafkaConsumer(
                    bootstrap_servers=BROKER_9092,
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

    async def create_topic(self, topic_name: str):
        topic_status = ""
        topic = NewTopic(
            name=topic_name,
            num_partitions=1,
            replication_factor=1
        )
        try:
            await self._client.create_topics([topic])
            topic_status = f"[SUCCESS] Topic '{topic_name}' created"
        except KafkaError as e:
            if "TopicAlreadyExists" in str(e):
                topic_status = f"[INFO] Topic '{topic_name}' already exists"
            else:
                self.log.info(f"[ERROR] Cannot create topic: {e}")
        await asyncio.sleep(1)
        try:
            producer = AIOKafkaProducer(bootstrap_servers=BROKER_9092)
            await producer.start()
            await producer.send_and_wait(topic_name, b"init-message")
            await producer.stop()
            message_status = f"[SUCCESS] First message sent to '{topic_name}'"
        except KafkaError as e:
            message_status = f"[ERROR] Cannot send first message: {e}"

        self.log.info(f"{topic_status} | {message_status}")
            
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

    async def _consume_loop(self):
        await asyncio.sleep(1)
        try:
            async for msg in self._consumer:
                topic = msg.topic
                message = msg.value.decode("utf-8")

                if topic == self._system_control_topic:
                    await self.handle_system_message(message)
                else:
                    await self.handle_experiment_message(topic, message)

                if self._consumer_stop.is_set():
                    break
        finally:
            await self._shutdown_consumer()
            self.log.info("[CONSUMER] Stopped.")

    async def handle_system_message(self, message: str):
        self.log.info(f"[CONTROL] {message}")
        if message.strip().lower() == "stop":
            self.log.info("[CONTROL] Stop command received.")
            self._consumer_stop.set()

    async def handle_experiment_message(self, topic: str, message: str):
        self.log.info(f"[EXPERIMENT] ({topic}): {message}")

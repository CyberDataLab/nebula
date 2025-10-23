from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from kafka.errors import KafkaError, TopicAlreadyExistsError
import asyncio

# --- Datos de conexión ---
BROKER_9094 = "dev_dev_alejandro_nebula-kafka:9094"
BROKER_9092 = "dev_dev_alejandro_nebula-kafka:9092"

class HUBKafkaClient:
    def __init__(self):
        self._username = "hub_admin"
        self._password = "hub_admin_password"
        self._consumer_stop = asyncio.Event()
        self._consumer = None
        self._client = None
        self._system_control_topic = "nebula-system-control"
        self._consumer_loop_task = None

    @property
    def com(self):
        """Kafka_consumer"""
        return self._consumer
    
    async def init(self):
        self._client = AIOKafkaAdminClient(
            bootstrap_servers=BROKER_9092
        )
        await self._client.start()

        self._consumer = AIOKafkaConsumer(
            bootstrap_servers=BROKER_9092,
            group_id="hub",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        await self.com.start()
        
        await self.create_topic(self._system_control_topic)
        await self.com.subscribe(pattern="^experiment-.*|^nebula-system-control$")
        self._consumer_loop_task = asyncio.create_task(self._consume_loop())

    async def create_topic(self, topic_name: str):
        topic = NewTopic(
            name=topic_name,
            num_partitions=1,
            replication_factor=1
        )
        try:
            await self._client.create_topics([topic])
            print(f"[SUCCESS] Topic '{topic_name}' created")
        except KafkaError as e:
            if "TopicAlreadyExists" in str(e):
                print(f"[INFO] Topic '{topic_name}' already exists")
            else:
                print(f"[ERROR] Cannot create topic: {e}")
        
    async def _consume_loop(self):
        try:
            async for msg in self.com:
                topic = msg.topic
                message = msg.value.decode("utf-8")

                if topic == self._system_control_topic:
                    await self.handle_system_message(message)
                else:
                    await self.handle_experiment_message(topic, message)

                if self._consumer_stop.is_set():
                    break
        finally:
            await self.com.stop()
            print("[CONSUMER] Stopped.")

    async def handle_system_message(self, message: str):
        print(f"[CONTROL] {message}")
        if message.strip().lower() == "stop":
            print("[CONTROL] Stop command received.")
            self._consumer_stop.set()

    async def handle_experiment_message(self, topic: str, message: str):
        print(f"[EXPERIMENT] ({topic}): {message}")

# def create_topic_9094(username, password, topic_name):
#     try:
#         admin_client = KafkaAdminClient(
#             bootstrap_servers=BROKER_9094,
#             security_protocol="SASL_PLAINTEXT",
#             sasl_mechanism="SCRAM-SHA-512",
#             sasl_plain_username=username,
#             sasl_plain_password=password,
#         )

#         topic = NewTopic(
#             name=topic_name,
#             num_partitions=1,
#             replication_factor=1
#         )

#         admin_client.create_topics([topic])
#         return f"[SUCCESS] Topic '{topic_name}' creado por {username}"
#     except TopicAlreadyExistsError:
#         return f"[INFO] Topic '{topic_name}' ya existe"
#     except KafkaError as e:
#         return f"[ERROR] {username} no puede crear el topic: {e}"
    

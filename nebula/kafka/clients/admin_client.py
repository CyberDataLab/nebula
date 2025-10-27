from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from kafka.errors import KafkaError, TopicAlreadyExistsError
import asyncio
from nebula.core.utils.locker import Locker
import logging
from confluent_kafka.admin import (
    AdminClient,
    UserScramCredentialUpsertion,
    UserScramCredentialDeletion,
    ScramCredentialInfo,
    ScramMechanism,
)
from kafka.admin import KafkaAdminClient, ACL, ACLOperation, ACLPermissionType, ResourcePattern, ResourceType, ACLFilter, ResourcePatternFilter, ACLResourcePatternType
from confluent_kafka import KafkaException

# --- Datos de conexión ---
BROKER_9094 = "dev_dev_alejandro_nebula-kafka:9094"
BROKER_9092 = "dev_dev_alejandro_nebula-kafka:9092"

class NebulaKafkaAdmin:
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
        self._acl_admin_client = KafkaAdminClient(
            bootstrap_servers=BROKER_9094,
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username=self._username,
            sasl_plain_password=self._password,
        )

    @property
    def log(self):
        return self._logger

    async def test_connection(self, broker: str = BROKER_9094) -> bool:
        try:
            producer = AIOKafkaProducer(
                bootstrap_servers=BROKER_9094,
                security_protocol="SASL_PLAINTEXT",
                sasl_mechanism="SCRAM-SHA-256",
                sasl_plain_username="hub_admin",
                sasl_plain_password="hub_admin_password",
            )
            await producer.start()
            await producer.stop()
            self.log.info(f"[SUCCESS] Conexión a broker {broker} OK")
            return True
        except KafkaError as e:
            self.log.info(f"[ERROR] Conexión a broker {broker} falló: {e}")
            return False
        
    async def create_user(self, user: str, password: str):
        try:
            admin = AdminClient({
                "bootstrap.servers": BROKER_9094,
                "security.protocol": "SASL_PLAINTEXT",
                "sasl.mechanism": "SCRAM-SHA-256",
                "sasl.username": "hub_admin",
                "sasl.password": "hub_admin_password",
            })

            cred_info = ScramCredentialInfo(ScramMechanism.SCRAM_SHA_256, 4096)
            password_bytes = password.encode("utf-8")
            op = UserScramCredentialUpsertion(
                user,
                cred_info,
                password=password_bytes
            )

            # Send operation
            fs = admin.alter_user_scram_credentials([op])

            # fs is a dictionary {username: future}
            f = fs[user]

            try:
                f.result()  # waiting result (sync)
                self.log.info(f"✅ User '{user}' Created/Updated successfully.")
                return True
            except KafkaException as e:
                self.log.error(f"⚠️ Error creating user '{user}': {e}")
                return False

        except Exception as e:
            self.log.error(f"❌ Unexpected error creating user '{user}': {e}")
            return False

    async def delete_user(self, user: str) -> bool:
        try:
            admin = AdminClient({
                "bootstrap.servers": BROKER_9094,
                "security.protocol": "SASL_PLAINTEXT",
                "sasl.mechanism": "SCRAM-SHA-256",
                "sasl.username": "hub_admin",
                "sasl.password": "hub_admin_password",
            })

            op = UserScramCredentialDeletion(user, ScramMechanism.SCRAM_SHA_256)
            fs = admin.alter_user_scram_credentials([op])
            f = fs[user]

            try:
                f.result()
                self.log.info(f"✅ User '{user}' deleted successfully.")
                return True
            except KafkaException as e:
                self.log.error(f"⚠️ Error deleting user '{user}': {e}")
                return False

        except Exception as e:
            self.log.error(f"❌ Unexpected error deleting user '{user}': {e}")
            return False
        
    async def create_acl_for_user_topic(self, user: str, topic_name: str, operation: str) -> bool:
        op_map = {
            "read": [ACLOperation.READ],
            "write": [ACLOperation.WRITE],
            "all": [ACLOperation.READ, ACLOperation.WRITE]
        }

        if operation not in op_map:
            self.log.error(f"❌ ACL operation no permitida: '{operation}'")
            return False

        acl_list = [
            ACL(
                principal=f"User:{user}",
                host="*",
                operation=op,
                permission_type=ACLPermissionType.ALLOW,
                resource_pattern=ResourcePattern(ResourceType.TOPIC, topic_name)
            )
            for op in op_map[operation]
        ]

        try:
            results = self._acl_admin_client.create_acls(acl_list)
            self.log.info(f"{results}")
            self.log.info(f"✅ ACL(s) '{operation}' creada(s) para '{user}' en '{topic_name}'")
            return True
        except Exception as e:
            self.log.error(f"❌ Error creando ACL(s) para '{user}' en '{topic_name}': {e}")
            return False
        
    async def delete_all_acls_for_user(self, user: str) -> bool:
        #TODO loop for all ACLOperations
        try:
            acl_filter = ACLFilter(
                principal=f"User:{user}",
                host=None,
                operation=ACLOperation.READ,
                permission_type=ACLPermissionType.ALLOW,
                resource_pattern=ResourcePatternFilter(
                    resource_type=ResourceType.ANY,
                    resource_name=None,
                    pattern_type=ACLResourcePatternType.ANY
                )
            )

            # delete_acls acepta una lista de ACLFilter
            results = self._acl_admin_client.delete_acls([acl_filter])

            # results es una lista de tuplas: (ACLFilter, list_of_matching_acls, error)
            for acl_filter, matching_acls, error in results:
                if error is not None:
                    self.log.error(f"⚠️ Error eliminando ACLs para '{user}': {error}")
            self.log.info(f"✅ Todas las ACLs para '{user}' eliminadas")
            return True

        except Exception as e:
            self.log.error(f"❌ Error eliminando ACLs para '{user}': {e}")
            return False

    async def init(self):
        # --- Testing ---
        if await self.test_connection():
            self.log.info("SUCCESS test connection")
        else:
            self.log.info("FAILED test connection")
            
        await self.create_user(user="new_user", password="new_pass")
        await self.create_acl_for_user_topic(user="new_user", topic_name="nebula-system-control", operation="read")
        await self.delete_all_acls_for_user(user="new_user")
        await self.delete_user(user="new_user")
        # --- Finish Testing ---

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
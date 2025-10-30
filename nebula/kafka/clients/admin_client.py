# Types and utilities
from typing import Awaitable, Callable, Union
import asyncio
import logging

# AIoKafka
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import KafkaConnectionError, KafkaTimeoutError, KafkaError as AioKafkaError

# Kafka-python
from kafka.errors import KafkaError, NoError, TopicAlreadyExistsError
from kafka.admin import (
    KafkaAdminClient,
    ACL,
    ACLOperation,
    ACLPermissionType,
    ResourcePattern,
    ResourceType,
    ACLFilter,
    ResourcePatternFilter,
    ACLResourcePatternType,
)

# Confluent-Kafka
from confluent_kafka.admin import (
    AdminClient,
    UserScramCredentialUpsertion,
    UserScramCredentialDeletion,
    ScramCredentialInfo,
    ScramMechanism,
)
from confluent_kafka import KafkaError as ConfluentKafkaError

# Project utils
from nebula.core.utils.locker import Locker
from nebula.kafka.clients.messages.system import SystemMessages, NEBULA_SYSTEM_TOPIC
from nebula.kafka.clients.messages.experiment import ExperimentMessages
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
from nebula.kafka.clients.messages.utils.utils import factory_kafka_message, parse_kafka_message
from nebula.kafka.clients.errors import KafkaInitializationError

# --- Datos de conexión ---
BROKER_9094 = "dev_dev_alejandro_nebula-kafka:9094"
BROKER_9092 = "dev_dev_alejandro_nebula-kafka:9092"
# self._username = "hub_admin"
# self._password = "hub_admin_password"

class NebulaKafkaAdmin:
    def __init__(self, user: str, password: str, broker: str, client_id: str, logger: logging.Logger):
        self._client_id = client_id
        self._username = user
        self._password = password
        self._broker = broker
        
        self._admin_user_client = None  # User creation/deletion    ->  confluent-kafka
        self._acl_admin_client = None   # ACLs creation/deletion    ->  kafka-python
        self._topic_admin_client = None # Topics creation           ->  aiokafka
        self._producer = None           # Topics producer           ->  aiokafka
        self._consumer = None           # Topics consumer           ->  aiokafka
        
        self._consumer_stop = asyncio.Event()

        self._consumer_started = False
        self._consumer_lock = Locker("consumer_lock", async_lock=True)
        self._admin_client = None
        self._system_control_topic = "nebula-system-control"
        self._consumer_loop_task = None
        self._logger = logger
        
        
        # Event listeners
        self._listeners: list[Callable[[KafkaMessage], Awaitable[None]]] = []
        self._listeners_lock = Locker("listeners_lock", async_lock=True)

    @property
    def log(self):
        return self._logger

    async def _testing_func(self):
        # --- Testing ---
        if await self._test_connection():
            self.log.info("SUCCESS test connection")
        else:
            self.log.info("FAILED test connection")
            
        await self.create_user(user="new_user", password="new_pass")
        await self.create_acl_for_user_topic(user="new_user", topic_name="nebula-system-control", operation="read")
        #await self.delete_all_acls_for_user(user="new_user")
        #await self.delete_user(user="new_user")
        # --- Finish Testing ---

    async def _test_connection(self, broker: str = BROKER_9094) -> bool:
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

    """                                             ###############################
                                                    #        INITIALIZATION       #
                                                    ###############################
    """
    
    async def init(self):
        #TODO robustness
        #await self._testing_func()
        try:
            # Initialize user-admin-client
            await self._init_user_admin_client()
            
            # Initialize acl-admin-client
            await self._init_acl_admin_client()
            
            # Initialize topic-admin-client
            await self._init_topic_admin_client()
            
            # Initialize producer
            await self._init_producer()
            
            # Initialize consumer
            await self._init_consumer()

            # Initialize system-topic
            created = await self._create_topic(NEBULA_SYSTEM_TOPIC)
            if not created:
                raise KafkaInitializationError(f"Failed to create {NEBULA_SYSTEM_TOPIC} topic")
            
            system_topic_initialized = await self.produce(NEBULA_SYSTEM_TOPIC, SystemMessages.AGENT_READY, data=self._client_id)
            if not system_topic_initialized:
                raise KafkaInitializationError(f"Failed to initialize {NEBULA_SYSTEM_TOPIC} topic")
            
            await asyncio.sleep(1)
            subscribed = await self._subscribe_topics(pattern="^experiment-.*|^nebula-system-control$")
            if not subscribed:
                raise KafkaInitializationError(f"Failed to subscribe to topics: '^experiment-.*|^nebula-system-control$'")
            
            self._consumer_loop_task = asyncio.create_task(self._consume_loop())
        except Exception as e:
            self.log.exception(f"Kafka node initialization failed: {e}")
            await self.shutdown()  
            raise KafkaInitializationError(f"{e}")
    
    async def _init_user_admin_client(self):
        self._admin_user_client = AdminClient({
                "bootstrap.servers": self._broker,
                "client.id": self._client_id,
                "security.protocol": "SASL_PLAINTEXT",
                "sasl.mechanism": "SCRAM-SHA-256",
                "sasl.username": self._username,
                "sasl.password": self._password,
            })
    
    async def _init_acl_admin_client(self):
        self._acl_admin_client = KafkaAdminClient(
            bootstrap_servers=self._broker,
            client_id=self._client_id,
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username=self._username,
            sasl_plain_password=self._password,
        )

    async def _init_topic_admin_client(self):
        self._topic_admin_client = AIOKafkaAdminClient(
            bootstrap_servers=self._broker,
            client_id=self._client_id,
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username=self._username,
            sasl_plain_password=self._password
        )
        await self._topic_admin_client.start()

    async def _init_producer(self):
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._broker,
            client_id=self._client_id,
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username=self._username,
            sasl_plain_password=self._password,
        )
        await self._producer.start()

    async def _init_consumer(self):
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

    """                                             ###############################
                                                    #       USERS MANAGEMENT      #
                                                    ###############################
    """
        
    async def create_user(self, user: str, password: str) -> bool:
        try:
            cred_info = ScramCredentialInfo(ScramMechanism.SCRAM_SHA_256, 4096)
            password_bytes = password.encode("utf-8")
            op = UserScramCredentialUpsertion(
                user,
                cred_info,
                password=password_bytes
            )

            # Send operation
            fs = self._admin_user_client.alter_user_scram_credentials([op])

            # fs is a dictionary {username: future}
            f = fs[user]

            try:
                f.result()  # waiting result (sync)
                self.log.info(f"✅ User '{user}' Created/Updated successfully.")
                return True
            except ConfluentKafkaError as e:
                self.log.error(f"⚠️ Error creating user '{user}': {e}")
                return False

        except Exception as e:
            self.log.error(f"❌ Unexpected error creating user '{user}': {e}")
            return False

    async def delete_user(self, user: str) -> bool:
        try:
            op = UserScramCredentialDeletion(user, ScramMechanism.SCRAM_SHA_256)
            fs = self._admin_user_client.alter_user_scram_credentials([op])
            f = fs[user]

            try:
                f.result()
                self.log.info(f"✅ User '{user}' deleted successfully.")
                return True
            except ConfluentKafkaError as e:
                self.log.error(f"⚠️ Error deleting user '{user}': {e}")
                return False

        except Exception as e:
            self.log.error(f"❌ Unexpected error deleting user '{user}': {e}")
            return False
 
    """                                             ###############################
                                                    #       ACLs MANAGEMENT       #
                                                    ###############################
    """
        
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
            succeeded = results.get("succeeded", [])
            failed = results.get("failed", [])

            if succeeded:
                self.log.info(f"✅ ACL(s) '{operation}' created for '{user}' on '{topic_name}':")
                for acl in succeeded:
                    self.log.info(f"   ↳ {acl}")

            if failed:
                self.log.error(f"⚠️ Errors creating ACL(s):")
                for acl in failed:
                    self.log.error(f"   ↳ {acl}")

            return len(failed) == 0
        except Exception as e:
            self.log.error(f"❌ Error creating ACL(s) for '{user}' on '{topic_name}': {e}")
            return False
        
    async def delete_all_acls_for_user(self, user: str) -> bool:
        #TODO loop for all ACLOperations
        try:
            acl_filter = ACLFilter(
                principal=f"User:{user}",
                host=None,
                operation=ACLOperation.WRITE,
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
                if error is not None and not isinstance(error, NoError):
                    self.log.error(f"⚠️ Error removing ACLs for '{user}': {error}")
                else:
                    self.log.info(f"✅ ACLs removed successfully: {matching_acls}")
            self.log.info(f"✅ All ACLs for '{user}' removed")
            return True
        
        except Exception as e:
            self.log.error(f"❌ Error removing ACLs for '{user}': {e}")
            return False

    """                                             ###############################
                                                    #       TOPICS MANAGEMENT     #
                                                    ###############################
    """
    async def initialize_experiment(self, experiment_name) -> bool:
        # Create topic
        topic_name = f"experiment-{experiment_name}"
        topic_created = await self._create_topic(topic_name)
        if not topic_created: 
            return False
        
        await asyncio.sleep(1)
        
        # Produce init message
        message_produced = await self.produce(topic_name, ExperimentMessages.INIT, data=experiment_name)
        
        #TODO create experiment-user
        #TODO create experiment-user ACL
        return message_produced
    
    async def _create_topic(self, topic_name: str):
        topic = NewTopic(
            name=topic_name,
            num_partitions=1,
            replication_factor=1
        )
        try:
            await self._topic_admin_client.create_topics([topic])
            topic_status = f"[SUCCESS] Topic '{topic_name}' created"
            self.log.info(f"{topic_status}")
            return True
            
        except KafkaError as e:
            if "TopicAlreadyExists" in str(e):
                topic_status = f"[INFO] Topic '{topic_name}' already exists"
                self.log.info(f"{topic_status}")
                return True
            else:
                self.log.info(f"[ERROR] Cannot create topic: {e}")
                return False
       
    async def _subscribe_topics(self, topics: list = [], pattern = ""):
        try:
            if topics:
                self._consumer.subscribe(topics)
                self.log.info(f"[SUCCESS] Topic subscribed'{topics}'")
                return True
            elif pattern:
                self._consumer.subscribe(pattern=pattern)
                self.log.info(f"[SUCCESS] Topic subscribed using pattern: '{pattern}'")
                return True
            else:
                self.log.info(f"ERROR no topics or pattern")
                return False
        except AioKafkaError as e:
            self.log.info(f"[ERROR]: {e}")
            return False
            
    """                                             ###############################
                                                    #      MESSAGE PRODUCTION     #
                                                    ###############################
    """
    
    async def produce(self, topic_name: str, message_type: Union[SystemMessages, ExperimentMessages], data) -> bool:
        message = factory_kafka_message(message_type, data=data)
        if message is None:
            self.log.info(f"Cannot create message type '{message_type}'")
            return
    
        try:
            await self._producer.send_and_wait(topic_name, message.to_bytes())
            return True
        except AioKafkaError as e:
            self.log.error(f"Kafka error sending {message_type}: {e}")
            return False
        except Exception as e:
            self.log.error(f"Unexpected error sending message: {e}")
            return False

    """                                             ###############################
                                                    #       MESSAGE HANDLING      #
                                                    ###############################
    """

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

    """                                             ###############################
                                                    #       SHUTDOWN PROTOCOL     #
                                                    ###############################
    """

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
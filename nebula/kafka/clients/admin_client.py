# Types and utilities
from typing import Any, Awaitable, Callable, Tuple, Union
import base64
import yaml
from pathlib import Path
import secrets
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
from nebula.kafka.clients.messages.message_handler import KafkaMessageHandler
from nebula.kafka.clients.messages.system import SystemMessages, NEBULA_SYSTEM_TOPIC
from nebula.kafka.clients.messages.experiment import ExperimentMessages
from nebula.kafka.clients.messages.kafka_message import KafkaMessage
from nebula.kafka.clients.messages.utils.utils import factory_kafka_message, parse_kafka_message
from nebula.kafka.clients.errors import (
    KafkaInitializationError, 
    KafkaUserCreationError,
    KafkaUserDeletionError,
    KafkaACLCreationError,
    KafkaACLDeletionError,
    KafkaExperimentInitializationError,
    KafkaProducerInitializationError,
    KafkaProducerError,
    KafkaConsumerLoopError,
    KafkaLoadingConfigurationError,
    KafkaConfigurationError,
    KafkaTopicSubscriptionError,
    KafkaMessageHandlerNotDefined,
)

#TODO modify config_parameters.py to obtain from env
BROKER_9094 = "dev_dev_alejandro_nebula-kafka:9094"
BROKER_9092 = "dev_dev_alejandro_nebula-kafka:9092"
# self._username = "hub_admin"
# self._password = "hub_admin_password"

class NebulaKafkaAdmin:
    def __init__(self, user: str, password: str, broker: str, client_id: str, logger: logging.Logger, handler: KafkaMessageHandler = None):
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
        self._consumer_loop_task = None
        self._logger = logger     
        self._handler = handler

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
            
            # Send frist message on system topic
            system_topic_initialized = await self.produce(NEBULA_SYSTEM_TOPIC, SystemMessages.AGENT_READY, data=self._client_id)
            if not system_topic_initialized:
                raise KafkaProducerError(f"Failed to send first message on '{NEBULA_SYSTEM_TOPIC}' topic")
            
            await asyncio.sleep(1)
        
            # Subscribe to system topic
            subscribed = await self._subscribe_topics(pattern="^experiment-.*|^nebula-system-control$")
            if not subscribed:
                raise KafkaTopicSubscriptionError(f"Failed to subscribe to topics: '^experiment-.*|^nebula-system-control$'")
            
            # Users creation & ACLs
            results = await self._bootstrap_users()
            errors = results.get("errors")

            # Critical error - All agents must be configurated
            if errors:
                err_lines = []
                for usr, usr_errors in errors.items():
                    err_lines.append(f"User '{usr}' - Errors:")
                    for err in usr_errors:
                        err_lines.append(f"   ↳ {err}")

                # Unir todas las líneas en un solo string
                err_msg = "\n".join(err_lines)
                raise KafkaConfigurationError(f"[ERROR]:\n{err_msg}")
            
            self._consumer_loop_task = asyncio.create_task(self._consume_loop())
            self.log.info(f"[SUCCESS]: Kafka initialization process")
        except Exception as e:
            self.log.exception(f"Kafka node initialization failed: {e}")
            await self.shutdown()  
            raise KafkaInitializationError(f"[ERROR]: initializing service") from e
    
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

    async def _init_producer(self, max_retries=5, delay=2):
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._broker,
            client_id=self._client_id,
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username=self._username,
            sasl_plain_password=self._password,
        )
        for attempt in range(1, max_retries + 1):
            try:
                self.log.info(f"[Kafka] Attempting to start producer (attempt {attempt}/{max_retries})...")
                await self._producer.start()
                self.log.info(f"[Kafka] Producer started successfully with client_id='{self._client_id}'")
                break
            except (KafkaConnectionError, KafkaTimeoutError) as e:
                self.log.warning(f"[Kafka] Connection issue on attempt {attempt}: {e}")
            except Exception as e:
                self.log.exception(f"[Kafka] Unexpected error starting producer (attempt {attempt}): {e}")

            if attempt < max_retries:
                self.log.info(f"[Kafka] Retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                self.log.error(f"[Kafka] Failed to start producer after {max_retries} attempts")
                raise KafkaProducerInitializationError("Unable to start Kafka producer after multiple attempts on NebulaKafkaAdmin.")

    async def _init_consumer(self):
        self._consumer = AIOKafkaConsumer(
                    bootstrap_servers=self._broker,
                    client_id=self._client_id,
                    group_id="g-hub",
                    security_protocol="SASL_PLAINTEXT",
                    sasl_mechanism="SCRAM-SHA-256",
                    sasl_plain_username=self._username,
                    sasl_plain_password=self._password,
                    auto_offset_reset="earliest",
                    enable_auto_commit=True,
        )
        await self._consumer.start()

    async def _load_config(self, config_path: str | Path) -> dict:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Kafka users config file not found: {config_path}")

        with open(path, "r") as f:
            config = yaml.safe_load(f)

        users = config.get("users", {})
        for username, info in users.items():
            try:
                password_b64 = info["password"]
                decoded_pass = base64.b64decode(password_b64).decode()
                users[username]["password"] = decoded_pass
            except Exception as e:
                self._logger.error(f"Error decoding password for {username}: {e}")
                raise KafkaLoadingConfigurationError(f"[ERROR]: decoding password for {username}: {e}") from e

        return users

    async def _bootstrap_users(self, config_path="/nebula/nebula/kafka/config/kafka_users.yaml") -> dict[str, dict]:
        results = {
            "success": [],
            "errors": {}
        }

        users = await self._load_config(config_path)

        for username, info in users.items():
            user_errors = []
            password = info["password"]
            topics = info.get("topics", [])

            # User creation
            try:
                self.log.info(f"👤 Creating user '{username}'...")
                await self.create_user(username, password)
            except KafkaUserCreationError as e:
                msg = f"❌ Failed to create user '{username}': {e}"
                self.log.error(msg)
                user_errors.append(msg)
            except Exception as e:
                msg = f"Unexpected error creating user '{username}': {e}"
                self.log.exception(msg)
                user_errors.append(msg)

            # ACLs creation if user was created previously
            if not user_errors:
                for topic_cfg in topics:
                    topic_name = topic_cfg["name"]
                    for op in topic_cfg["operations"]:
                        try:
                            await self.create_acl_for_user_topic(username, topic_name, op)
                        except KafkaACLCreationError as e:
                            msg = f"⚠️ Failed to create ACL ({op}) for '{username}' on '{topic_name}': {e}"
                            self.log.error(msg)
                            user_errors.append(msg)
                        except Exception as e:
                            msg = f"Unexpected ACL error for '{username}' on '{topic_name}': {e}"
                            self.log.exception(msg)
                            user_errors.append(msg)

            if user_errors:
                results["errors"][username] = user_errors
            else:
                results["success"].append(username)

        return results


    """                                             ###############################
                                                    #       USERS MANAGEMENT      #
                                                    ###############################
    """
        
    async def create_user(self, user: str, password: str) -> None:
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
                await asyncio.to_thread(f.result)
                self.log.info(f"✅ User '{user}' Created/Updated successfully.")
            except ConfluentKafkaError as e:
                self.log.error(f"⚠️ Error creating user '{user}': {e}")
                raise KafkaUserCreationError(f"[ERROR]: {e}")

        except Exception as e:
            self.log.error(f"❌ Unexpected error creating user '{user}': {e}")
            raise KafkaUserCreationError(f"[ERROR]: {e}")

    async def delete_user(self, user: str) -> None:
        try:
            op = UserScramCredentialDeletion(user, ScramMechanism.SCRAM_SHA_256)
            fs = self._admin_user_client.alter_user_scram_credentials([op])
            f = fs[user]

            try:
                f.result()
                self.log.info(f"✅ User '{user}' deleted successfully.")
            except ConfluentKafkaError as e:
                self.log.error(f"⚠️ Error deleting user '{user}': {e}")
                raise KafkaUserDeletionError(f"[ERROR]: {e}")

        except Exception as e:
            self.log.error(f"❌ Unexpected error deleting user '{user}': {e}")
            raise KafkaUserDeletionError(f"[ERROR]: {e}")
 
    """                                             ###############################
                                                    #       ACLs MANAGEMENT       #
                                                    ###############################
    """
        
    async def create_acl_for_user_topic(self, user: str, topic_name: str, operation: str):
        op_map = {
            "read": [ACLOperation.READ],
            "write": [ACLOperation.WRITE],
            "all": [ACLOperation.READ, ACLOperation.WRITE]
        }

        if operation not in op_map:
            self.log.error(f"❌ ACL operation not allowed: '{operation}'")
            raise ValueError(f"ACL operation not allowed: {operation}")

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
                raise KafkaACLCreationError(f"[ERROR]: Cannot create ACLs - {failed}")

        except Exception as e:
            self.log.error(f"❌ Error creating ACL(s) for '{user}' on '{topic_name}': {e}")
            raise KafkaACLCreationError(f"[ERROR]: {e}")
        
    async def delete_all_acls_for_user(self, user: str) -> list:
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
            return results
        
        except Exception as e:
            self.log.error(f"❌ Error removing ACLs for '{user}': {e}")
            raise KafkaACLDeletionError(f"[ERROR]: {e}")

    """                                             ###############################
                                                    #       TOPICS MANAGEMENT     #
                                                    ###############################
    """
    
    def _generate_experiment_topic_credentials(self, experiment_name: str) -> Tuple[str, str]:
        user = f"user-{experiment_name}"
        password = secrets.token_urlsafe(12)
        return user, password
        
    async def initialize_experiment(self, experiment_name):
        try:
            # Create topic
            topic_name = f"experiment-{experiment_name}"
            topic_created = await self._create_topic(topic_name)
            if not topic_created: 
                raise KafkaExperimentInitializationError("[ERROR]: Cannot create experiment topic name.")
            
            await asyncio.sleep(1)
            
            # Produce init message - not critical
            message_produced = await self.produce(topic_name, ExperimentMessages.INIT, data=experiment_name)
            if not message_produced:
                self.log.info(f"[ERROR]: cannot create INIT message on topic '{experiment_name}'")
            
            # Create experiment-user
            user, password = self._generate_experiment_topic_credentials(experiment_name)
            await self.create_user(user, password)
            
            # Create experiment-user ACL
            await self.create_acl_for_user_topic(user, topic_name, "write")
            
        except Exception as e:
            raise KafkaExperimentInitializationError(f"[ERROR]: initializing experiment {e}") from e
           
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
            self.log.info(f"Message '{message_type.name}' sent on topic '{topic_name}'")
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
    
    async def set_handler(self, handler: KafkaMessageHandler):
        self._handler = handler
    
    async def _consume_loop(self):
        # queue + workers if high concurrency
        self.log.info(f"Consumer loop started..")
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
                    self.log.info(f"Message received '{kafka_message}'")
                    if not self._handler:
                        raise KafkaMessageHandlerNotDefined("[ERROR]: Kafka Message Handler is not defined")
                    
                    asyncio.create_task(self._handler.handle(kafka_message))

                except Exception as e:
                    self.log.exception(f"Error processing message from topic {msg.topic}: {e}")

        except asyncio.CancelledError as ce:
            self.log.info("Consumer loop cancelled")
            raise KafkaConsumerLoopError(f"[ERROR]: {ce}") from ce
        except Exception as e:
            self.log.exception(f"Unexpected error in consumer loop: {e}")
            raise KafkaConsumerLoopError(f"[ERROR]: {e}") from e
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
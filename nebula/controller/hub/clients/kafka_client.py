from kafka import KafkaAdminClient
from kafka.admin import NewTopic
from kafka.errors import KafkaError, TopicAlreadyExistsError

# --- Datos de conexión ---
BROKER_9094 = "dev_dev_alejandro_nebula-kafka:9094"
BROKER_9092 = "dev_dev_alejandro_nebula-kafka:9092"

# Usuarios
USERS = {
    "hub_admin": "hub_admin_password",   # superusuario
    "normal_user": "normal_password"     # usuario sin privilegios
}

def create_topic_9094(username, password, topic_name):
    try:
        admin_client = KafkaAdminClient(
            bootstrap_servers=BROKER_9094,
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-512",
            sasl_plain_username=username,
            sasl_plain_password=password,
        )

        topic = NewTopic(
            name=topic_name,
            num_partitions=1,
            replication_factor=1
        )

        admin_client.create_topics([topic])
        return f"[SUCCESS] Topic '{topic_name}' creado por {username}"
    except TopicAlreadyExistsError:
        return f"[INFO] Topic '{topic_name}' ya existe"
    except KafkaError as e:
        return f"[ERROR] {username} no puede crear el topic: {e}"
    
def create_topic_9092(username, password, topic_name):
    """
    Crea un topic usando el puerto PLAINTEXT (9092).
    No requiere autenticación SASL.
    """
    try:
        admin_client = KafkaAdminClient(
            bootstrap_servers=BROKER_9092,
            client_id="admin_client_9092"
        )

        topic = NewTopic(
            name=topic_name,
            num_partitions=1,
            replication_factor=1
        )

        admin_client.create_topics([topic])
        return f"[SUCCESS] Topic '{topic_name}' creado en {BROKER_9092}"
    except TopicAlreadyExistsError:
        return f"[INFO] Topic '{topic_name}' ya existe"
    except KafkaError as e:
        return f"[ERROR] No se pudo crear el topic: {e}"
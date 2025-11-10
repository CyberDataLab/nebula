#!/bin/bash
set -e

echo "🧠 Starting Nebula Kafka broker..."

# === server.properties ===
cat > /home/kafka/server.properties <<EOF
############################
# KRaft Configuration
############################
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@localhost:9093
controller.listener.names=CONTROLLER

############################
# Listeners
############################
listeners=${KAFKA_LISTENERS}
listener.security.protocol.map=${KAFKA_LISTENER_SECURITY_PROTOCOL_MAP}
advertised.listeners=${KAFKA_ADVERTISED_LISTENERS}

############################
# Security and ACLs
############################
#security.inter.broker.protocol=${KAFKA_INTER_BROKER_LISTENER_NAME}
inter.broker.listener.name=PLAINTEXT

# SASL/SCRAM
sasl.enabled.mechanisms=SCRAM-SHA-256
listener.name.sasl_plaintext.scram-sha-256.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required;

# Authorizer
authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer

# 👇 ESTA ES LA CLAVE: permitir al broker anónimo registrarse
super.users=User:${KAFKA_SUPER_USER_NAME};User:ANONYMOUS

############################
# Topics and Logs
############################
auto.create.topics.enable=true
offsets.topic.replication.factor=1
log.dirs=${KAFKA_LOG_DIR}

############################
# Debug
############################
log4j.logger.org.apache.kafka.common.security=DEBUG
log4j.logger.kafka.authorizer.logger=DEBUG
EOF

# === kafka_server_jaas.conf ===
cat > /home/kafka/kafka_server_jaas.conf <<EOF
KafkaServer {
    org.apache.kafka.common.security.scram.ScramLoginModule required
    user_${KAFKA_SUPER_USER_NAME}=${KAFKA_SUPER_USER_PASS}
};
EOF

# === kafka_client_jaas.conf ===
cat > /home/kafka/kafka_client_jaas.conf <<EOF
KafkaClient {
    org.apache.kafka.common.security.scram.ScramLoginModule required
    username=${KAFKA_SUPER_USER_NAME}
    password=${KAFKA_SUPER_USER_PASS};
};
EOF

# Exportar la variable para que Kafka lea el JAAS
export KAFKA_OPTS="-Djava.security.auth.login.config=/home/kafka/kafka_server_jaas.conf"

# Inicializar cluster si no existe
if [ ! -f "${KAFKA_LOG_DIR}/meta.properties" ]; then
    CLUSTER_ID=$(/opt/kafka/bin/kafka-storage.sh random-uuid)
    echo "🔧 Initializing KRaft metadata with CLUSTER_ID=$CLUSTER_ID"
    /opt/kafka/bin/kafka-storage.sh format --cluster-id $CLUSTER_ID --config /home/kafka/server.properties
fi

echo "⏳ Waiting for Kafka to be ready..."

# Iniciar el broker en primer plano
/opt/kafka/bin/kafka-server-start.sh /home/kafka/server.properties &
KAFKA_PID=$!

# Esperar a que el broker esté escuchando en PLAINTEXT
until nc -z localhost 9092 && nc -z localhost 9094; do
  sleep 5
done
echo "✅ Kafka broker is ready."

echo "🚀 Nebula Kafka initialized and ready."


# === Crear superusuario SASL/SCRAM si no existe ===
echo "🔐 Checking SASL/SCRAM superuser..."
EXISTS=$(/opt/kafka/bin/kafka-configs.sh --bootstrap-server localhost:9092 \
    --entity-type users --describe 2>/dev/null | grep -c "user='${KAFKA_SUPER_USER_NAME}'" || true)

if [ "$EXISTS" -eq 0 ]; then
    echo "👤 Creating superuser '${KAFKA_SUPER_USER_NAME}'..."
    /opt/kafka/bin/kafka-configs.sh --bootstrap-server localhost:9092 \
        --alter --add-config "SCRAM-SHA-256=[password=${KAFKA_SUPER_USER_PASS}]" \
        --entity-type users --entity-name "${KAFKA_SUPER_USER_NAME}"
    echo "✅ Superuser '${KAFKA_SUPER_USER_NAME}' created."
else
    echo "ℹ️ Superuser '${KAFKA_SUPER_USER_NAME}' already exists."
fi

# Mantener el proceso principal en primer plano
wait $KAFKA_PID

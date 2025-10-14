#!/bin/bash
set -e

echo "🧠 Starting Nebula Kafka broker..."

# === server.properties ===
cat > /home/kafka/server.properties <<EOF
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@localhost:9093

# Listeners
listeners=PLAINTEXT://:9092,SASL_PLAINTEXT://:9094,CONTROLLER://:9093
listener.security.protocol.map=PLAINTEXT:PLAINTEXT,SASL_PLAINTEXT:SASL_PLAINTEXT,CONTROLLER:PLAINTEXT
advertised.listeners=PLAINTEXT://dev_dev_alejandro_nebula-kafka:9092,SASL_PLAINTEXT://dev_dev_alejandro_nebula-kafka:9094

# Comunicación interna entre brokers
security.inter.broker.protocol=PLAINTEXT
controller.listener.names=CONTROLLER

# SASL / SCRAM
sasl.enabled.mechanisms=SCRAM-SHA-512
sasl.mechanism.inter.broker.protocol=PLAINTEXT

# Superusuarios
super.users=User:hub_admin,User:controller

# Data directory
log.dirs=${KAFKA_LOG_DIR}

# Opcional: control de autenticación solo para SASL_PLAINTEXT
listener.name.sasl_plaintext.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required;
EOF

# === kafka_server_jaas.conf ===
cat > /home/kafka/kafka_server_jaas.conf <<EOF
KafkaServer {
    org.apache.kafka.common.security.scram.ScramLoginModule required
    user_hub_admin="hub_admin_password";
};
EOF

# === kafka_client_jaas.conf ===
cat > /home/kafka/kafka_client_jaas.conf <<EOF
KafkaClient {
    org.apache.kafka.common.security.scram.ScramLoginModule required
    username="hub_admin"
    password="hub_admin_password";
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
until nc -z localhost 9092; do
  sleep 5
done
echo "✅ Kafka broker is ready."

echo "🚀 Nebula Kafka initialized and ready."

# Mantener el proceso principal en primer plano
wait $KAFKA_PID
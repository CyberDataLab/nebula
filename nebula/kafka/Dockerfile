FROM apache/kafka:4.0.1

USER root

ENV KAFKA_LOG_DIR=/home/kafka/kafka-data

RUN mkdir -p $KAFKA_LOG_DIR && chown -R 1001:1001 $KAFKA_LOG_DIR

COPY nebula-kafka-entrypoint.sh /home/kafka/
WORKDIR /home/kafka

ENTRYPOINT ["/bin/bash", "/home/kafka/nebula-kafka-entrypoint.sh"]
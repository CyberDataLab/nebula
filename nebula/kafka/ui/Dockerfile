FROM ghcr.io/kafbat/kafka-ui:latest

# Copiar configuración personalizada
COPY config.yml /config.yml

# Asegurar formato y permisos
#RUN dos2unix /etc/kafkaui/dynamic_config.yaml && chmod 644 /etc/kafkaui/dynamic_config.yaml

# Exponer el puerto del panel
#EXPOSE 8080

# Usamos el entrypoint original del contenedor base

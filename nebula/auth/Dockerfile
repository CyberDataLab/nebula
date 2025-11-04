# syntax=docker/dockerfile:1
FROM quay.io/keycloak/keycloak:26.4

# Enable lightweight health and metrics endpoints by default. Runtime
# deployment can override these variables if needed.
ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_TRANSACTION_XA_ENABLED=false

# Copy default realm export so Keycloak imports it on first startup
COPY nebula-realm.json /opt/keycloak/data/import/nebula-realm.json

# # Start Keycloak and import the realm configuration
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--import-realm"]

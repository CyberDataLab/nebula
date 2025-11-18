import os
from pathlib import Path

# === Kafka ===
BROKER = os.getenv("KAFKA_BROKER")

# === Paths ===
KAFKA_USERS_CONFIG = os.getenv("KAFKA_USERS_FILE")

# === Credenciales principales ===
KAFKA_SUPERUSER = os.getenv("KAFKA_SUPERUSER")
KAFKA_SUPERPASS = os.getenv("KAFKA_SUPERPASS")

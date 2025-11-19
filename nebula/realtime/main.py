import asyncio
import json
import logging
import os

# Ensure we can import nebula package
import sys
import threading
import time

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from kafka import KafkaConsumer

sys.path.append("/nebula")

from nebula.auth.keycloak.authenticator import KeycloakAuthenticator
from nebula.realtime.manager import RealTimeManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
KAFKA_TOPICS = ["nebula.federation.nodes", "nebula.metrics", "nebula.tensorboard"]
DATA_DIR = os.environ.get("DATA_DIR", "/nebula/realtime/data")
KEYCLOAK_SERVER_URL = os.environ.get("NEBULA_KEYCLOAK_SERVER", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("NEBULA_KEYCLOAK_REALM", "nebula")
KEYCLOAK_AUDIENCE = os.environ.get("NEBULA_KEYCLOAK_AUDIENCE", "nebula-hub")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)


# Global state for WebSocket connections

manager = RealTimeManager(logging.getLogger("RealTimeManager"))

# Auth
authenticator = None


def get_authenticator():
    global authenticator
    if authenticator is None:
        authenticator = KeycloakAuthenticator(
            server_url=KEYCLOAK_SERVER_URL,
            realm=KEYCLOAK_REALM,
            audience=KEYCLOAK_AUDIENCE,
        )
    return authenticator


async def get_current_user(token: str):
    auth = get_authenticator()
    try:
        user = await auth.authenticate(token)
        return user
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Kafka Consumer
def kafka_consumer_loop():
    logger.info(f"Starting Kafka consumer for topics: {KAFKA_TOPICS}")
    try:
        consumer = KafkaConsumer(
            *KAFKA_TOPICS,
            bootstrap_servers=KAFKA_BROKER,
            value_deserializer=lambda x: x.decode("utf-8"),
            auto_offset_reset="latest",
            enable_auto_commit=True,
            # Add SASL config if needed, reading from env
            # security_protocol="SASL_PLAINTEXT",
            # sasl_mechanism="SCRAM-SHA-256",
            # sasl_plain_username=...,
            # sasl_plain_password=...,
        )
    except Exception as e:
        logger.error(f"Failed to start Kafka consumer: {e}")
        return

    for message in consumer:
        try:
            topic = message.topic
            value = message.value
            logger.debug(f"Received message from {topic}: {value[:100]}...")

            # Persist TensorBoard data
            if topic == "nebula.tensorboard":
                # Assuming value contains filename/path info or we just append to a file
                # For now, let's assume it's a JSON with 'filename' and 'content' or similar
                # Or just write raw events.
                # Simple implementation: write to a file named after the topic/partition
                file_path = os.path.join(DATA_DIR, f"{topic}.log")
                with open(file_path, "a") as f:
                    f.write(value + "\n")

            # Broadcast to WebSockets
            # We broadcast everything for now, client can filter
            payload = json.dumps({"topic": topic, "data": value})

            # Broadcast needs to be scheduled in the event loop
            # Since this is a thread, we need to use run_coroutine_threadsafe if we had the loop
            # Or simpler: use a queue or just fire and forget if possible?
            # FastAPI/Uvicorn runs in asyncio.
            # We can use asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)

            # But we need reference to the loop.
            pass

        except Exception as e:
            logger.error(f"Error processing message: {e}")


# We need to bridge the sync Kafka thread and async WebSocket broadcast
# Better approach: Use aiokafka or run consumer in async task with run_in_executor
# But sticking to kafka-python as requested/approved.

# Let's use a queue to pass messages from thread to async task
message_queue = asyncio.Queue()


def kafka_consumer_thread(loop):
    logger.info("Starting Kafka consumer thread...")
    # SASL Config
    sasl_username = os.environ.get("KAFKA_USER_NAME")
    sasl_password = os.environ.get("KAFKA_USER_PASS")
    security_protocol = "PLAINTEXT"
    sasl_mechanism = None

    if sasl_username and sasl_password:
        security_protocol = "SASL_PLAINTEXT"
        sasl_mechanism = "SCRAM-SHA-256"

    if sasl_username and sasl_password:
        security_protocol = "SASL_PLAINTEXT"
        sasl_mechanism = "SCRAM-SHA-256"

    consumer = None
    retries = 0
    max_retries = 30

    while retries < max_retries:
        try:
            consumer = KafkaConsumer(
                *KAFKA_TOPICS,
                bootstrap_servers=KAFKA_BROKER,
                value_deserializer=lambda x: x.decode("utf-8", errors="ignore"),
                auto_offset_reset="latest",
                enable_auto_commit=True,
                security_protocol=security_protocol,
                sasl_mechanism=sasl_mechanism,
                sasl_plain_username=sasl_username,
                sasl_plain_password=sasl_password,
                request_timeout_ms=10000,
                session_timeout_ms=30000,
                api_version=(2, 6, 0),
            )
            logger.info("✅ Connected to Kafka")
            break
        except Exception as e:
            logger.warning(f"Failed to connect to Kafka (attempt {retries + 1}/{max_retries}): {e}")
            retries += 1
            time.sleep(2)

    if not consumer:
        logger.error("❌ Could not connect to Kafka after multiple attempts. Consumer thread exiting.")
        return

    # Wait for topics to exist with timeout
    logger.info("⏳ Waiting for topics to be created (timeout 60s)...")
    start_time = time.time()
    timeout = 60

    while True:
        try:
            existing_topics = consumer.topics()
            missing_topics = [t for t in KAFKA_TOPICS if t not in existing_topics]

            if not missing_topics:
                logger.info("✅ All required topics found.")
                break

            if time.time() - start_time > timeout:
                logger.warning(f"⚠️ Timeout waiting for topics: {missing_topics}. Proceeding anyway...")
                break

            logger.info(f"Waiting for topics: {missing_topics}")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Error checking topics: {e}")
            time.sleep(2)

    logger.info("🚀 Starting consumption loop...")

    for message in consumer:
        try:
            topic = message.topic
            value = message.value
            logger.info(f"📥 Received message from {topic}: {value[:100]}...")

            # Persist
            if topic == "nebula.tensorboard":
                try:
                    # Expecting JSON with 'filename' and 'data' (base64)
                    event_data = json.loads(value)
                    filename = event_data.get("filename")
                    b64_data = event_data.get("data")

                    if filename and b64_data:
                        # Validate filename to prevent directory traversal or weird names
                        # Simple check: must start with events.out.tfevents
                        if not filename.startswith("events.out.tfevents"):
                            logger.warning(f"⚠️ Invalid TensorBoard filename: {filename}")
                            continue

                        file_path = os.path.join(DATA_DIR, filename)

                        # Decode base64
                        import base64

                        binary_data = base64.b64decode(b64_data)

                        with open(file_path, "ab") as f:
                            f.write(binary_data)

                        logger.info(f"💾 Appended {len(binary_data)} bytes to {filename}")
                    else:
                        logger.warning(f"⚠️ Received TensorBoard message without filename or data: {value[:100]}")

                except json.JSONDecodeError:
                    logger.error(f"❌ Failed to parse TensorBoard message as JSON: {value[:100]}")
                except Exception as e:
                    logger.exception(f"❌ Error processing TensorBoard event: {e}")

            else:
                # Handle other topics if needed, or just log
                pass

            # Queue for broadcast
            # For TensorBoard, we might want to broadcast the original JSON or a processed version
            # Sending the original value (which is JSON string) is fine
            # But if we modified it, we should re-serialize.
            # The value received is a string (decoded from utf-8 in consumer init)

            # If it was TensorBoard, 'value' is the JSON string.
            # If it was others, 'value' is whatever string.

            payload = json.dumps({"topic": topic, "data": value})
            asyncio.run_coroutine_threadsafe(message_queue.put(payload), loop)

        except Exception as e:
            logger.error(f"Error in consumer loop: {e}")


async def broadcast_worker():
    while True:
        message = await message_queue.get()
        # RealTimeManager expects a dict, and the message is a JSON string
        try:
            data = json.loads(message)
            await manager.push_message("global", data)
        except Exception:
            logger.exception("Error broadcasting message")
        message_queue.task_done()


@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_event_loop()
    t = threading.Thread(target=kafka_consumer_thread, args=(loop,), daemon=True)
    t.start()
    asyncio.create_task(broadcast_worker())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info(f"WebSocket connection attempt from {client_host}")

    # Verify token
    if not token:
        logger.warning(f"WebSocket connection rejected: Missing token (client: {client_host})")
        await websocket.accept()
        await websocket.send_text("Error: Missing bearer token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        user = await get_current_user(token)
        logger.info(f"WebSocket authentication successful for user: {user.username} (client: {client_host})")
    except HTTPException as e:
        logger.warning(
            f"WebSocket connection rejected: Authentication failed for client {client_host}. Reason: {e.detail}"
        )
        await websocket.accept()
        await websocket.send_text(f"Error: {e.detail}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    except Exception:
        logger.exception(f"WebSocket connection rejected: Unexpected error during auth for client {client_host}")
        await websocket.accept()
        await websocket.send_text("Error: Internal server error during authentication")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    await manager.open_real_time_client(websocket, "global")
    logger.info(f"WebSocket connection closed for user: {user.username}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

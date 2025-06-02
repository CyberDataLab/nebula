import asyncio
import bz2
import json
import logging
import lzma
import time
import uuid
import zlib
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import lz4.frame

from nebula.core.utils.locker import Locker

if TYPE_CHECKING:
    pass


class ConnectionPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class MessageChunk:
    __slots__ = ["index", "data", "is_last"]
    index: int
    data: bytes
    is_last: bool


MAX_INCOMPLETED_RECONNECTIONS = 3


class Connection:
    DEFAULT_FEDERATED_ROUND = -1
    INACTIVITY_TIMER = 30
    INACTIVITY_DAEMON_SLEEP_TIME = 20

    def __init__(
        self,
        reader,
        writer,
        id,
        host,
        port,
        direct=True,
        active=True,
        compression="zlib",
        config=None,
        prio="medium",
    ):
        self.reader = reader
        self.writer = writer
        self.id = str(id)
        self.host = host
        self.port = port
        self.addr = f"{host}:{port}"
        self.direct = direct
        self.active = active
        self.last_active = time.time()
        self.compression = compression
        self.config = config
        self._cm = None

        self.federated_round = Connection.DEFAULT_FEDERATED_ROUND
        self.loop = asyncio.get_event_loop()
        self.read_task = None
        self.process_task = None
        self.pending_messages_queue = asyncio.Queue(maxsize=100)
        self.message_buffers: dict[bytes, dict[int, MessageChunk]] = {}
        self._prio: ConnectionPriority = ConnectionPriority(prio)
        self._inactivity = False
        self._last_activity = time.time()
        self._activity_lock = Locker(name="activity_lock", async_lock=True)

        self.EOT_CHAR = b"\x00\x00\x00\x04"
        self.COMPRESSION_CHAR = b"\x00\x00\x00\x01"
        self.DATA_TYPE_PREFIXES = {
            "pb": b"\x01\x00\x00\x00",
            "string": b"\x02\x00\x00\x00",
            "json": b"\x03\x00\x00\x00",
            "bytes": b"\x04\x00\x00\x00",
        }
        self.HEADER_SIZE = 21
        self.MAX_CHUNK_SIZE = 1024  # 1 KB
        self.BUFFER_SIZE = 1024  # 1 KB

        self.incompleted_reconnections = 0
        self.forced_disconnection = False

        logging.info(
            f"Connection [established]: {self.addr} (id: {self.id}) (active: {self.active}) (direct: {self.direct})"
        )

    def __str__(self):
        return f"Connection to {self.addr} (id: {self.id}) (active: {self.active}) (last active: {self.last_active}) (direct: {self.direct}) (priority: {self._prio.value})"

    def __repr__(self):
        return self.__str__()

    async def __del__(self):
        await self.stop()

    @property
    def cm(self):
        if not self._cm:
            from nebula.core.network.communications import CommunicationsManager

            self._cm = CommunicationsManager.get_instance()
            return self._cm
        else:
            return self._cm

    def get_addr(self):
        return self.addr

    def get_prio(self):
        return self._prio

    async def is_inactive(self):
        async with self._activity_lock:
            return self._inactivity

    async def _update_activity(self):
        async with self._activity_lock:
            self._last_activity = time.time()
            self._inactivity = False

    async def _monitor_inactivity(self):
        while True:
            if self.direct:
                break
            await asyncio.sleep(self.INACTIVITY_DAEMON_SLEEP_TIME)
            async with self._activity_lock:
                time_since_last = time.time() - self._last_activity
                if time_since_last > self.INACTIVITY_TIMER:
                    if not self._inactivity:
                        self._inactivity = True
                        logging.warning(f"[{self}] Connection marked as inactive.")
                else:
                    if self._inactivity:
                        self._inactivity = False

    def get_federated_round(self):
        return self.federated_round

    def get_tunnel_status(self):
        return not (self.reader is None or self.writer is None)

    def update_round(self, federated_round):
        self.federated_round = federated_round

    def get_ready(self):
        return self.federated_round != Connection.DEFAULT_FEDERATED_ROUND

    def get_direct(self):
        return self.direct

    def set_direct(self, direct):
        # config.participant["network_args"]["neighbors"] only contains direct neighbors (frotend purposes)
        if direct:
            self.config.add_neighbor_from_config(self.addr)
        else:
            self.config.remove_neighbor_from_config(self.addr)
        self.last_active = time.time()
        self.direct = direct

    def set_active(self, active):
        self.active = active
        self.last_active = time.time()

    def is_active(self):
        return self.active

    def get_last_active(self):
        return self.last_active

    async def start(self):
        self.read_task = asyncio.create_task(self.handle_incoming_message(), name=f"Connection {self.addr} reader")
        self.process_task = asyncio.create_task(self.process_message_queue(), name=f"Connection {self.addr} processor")
        asyncio.create_task(self._monitor_inactivity())

    async def stop(self):
        logging.info(f"❗️  Connection [stopped]: {self.addr} (id: {self.id})")
        self.forced_disconnection = True
        tasks = [self.read_task, self.process_task]
        for task in tasks:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logging.exception(f"❗️  {self} cancelled...")

        if self.writer is not None:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                logging.exception(f"❗️  Error ocurred when closing pipe: {e}")

    async def reconnect(self, max_retries: int = 5, delay: int = 5) -> None:
        if self.forced_disconnection or not self.direct:
            return

        self.incompleted_reconnections += 1
        if self.incompleted_reconnections == MAX_INCOMPLETED_RECONNECTIONS:
            logging.info(f"Reconnection with {self.addr} failed...")
            self.forced_disconnection = True
            await self.cm.terminate_failed_reconnection(self)
            return

        for attempt in range(max_retries):
            try:
                logging.info(f"Attempting to reconnect to {self.addr} (attempt {attempt + 1}/{max_retries})")
                await self.cm.connect(self.addr)
                await asyncio.sleep(1)

                self.read_task = asyncio.create_task(
                    self.handle_incoming_message(),
                    name=f"Connection {self.addr} reader",
                )
                self.process_task = asyncio.create_task(
                    self.process_message_queue(),
                    name=f"Connection {self.addr} processor",
                )
                if not self.forced_disconnection:
                    logging.info(f"Reconnected to {self.addr}")
                return
            except Exception as e:
                logging.exception(f"Reconnection attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(delay)
        logging.error(f"Failed to reconnect to {self.addr} after {max_retries} attempts. Stopping connection...")
        # await self.stop()
        await self.cm.terminate_failed_reconnection(self)

    async def send(
        self,
        data: Any,
        pb: bool = True,
        encoding_type: str = "utf-8",
        is_compressed: bool = False,
    ) -> None:
        if self.writer is None:
            logging.error("Cannot send data, writer is None")
            return

        try:
            message_id = uuid.uuid4().bytes
            data_prefix, encoded_data = self._prepare_data(data, pb, encoding_type)

            if is_compressed:
                encoded_data = await asyncio.to_thread(self._compress, encoded_data, self.compression)
                if encoded_data is None:
                    return
                data_to_send = data_prefix + encoded_data + self.COMPRESSION_CHAR
            else:
                data_to_send = data_prefix + encoded_data

            await self._update_activity()
            await self._send_chunks(message_id, data_to_send)
        except Exception as e:
            logging.exception(f"Error sending data: {e}")
            if self.direct:
                await self.reconnect()

    def _prepare_data(self, data: Any, pb: bool, encoding_type: str) -> tuple[bytes, bytes]:
        if pb:
            return self.DATA_TYPE_PREFIXES["pb"], data
        elif isinstance(data, str):
            return self.DATA_TYPE_PREFIXES["string"], data.encode(encoding_type)
        elif isinstance(data, dict):
            return self.DATA_TYPE_PREFIXES["json"], json.dumps(data).encode(encoding_type)
        elif isinstance(data, bytes):
            return self.DATA_TYPE_PREFIXES["bytes"], data
        else:
            raise ValueError(f"Unknown data type to send: {type(data)}")

    def _compress(self, data: bytes, compression: str) -> bytes | None:
        if compression == "lz4":
            return lz4.frame.compress(data)
        elif compression == "zlib":
            return zlib.compress(data)
        elif compression == "bz2":
            return bz2.compress(data)
        elif compression == "lzma":
            return lzma.compress(data)
        else:
            logging.error(f"Unsupported compression method: {compression}")
            return None

    async def _send_chunks(self, message_id: bytes, data: bytes) -> None:
        chunk_size = self._calculate_chunk_size(len(data))
        num_chunks = (len(data) + chunk_size - 1) // chunk_size

        for chunk_index in range(num_chunks):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(data))
            chunk = data[start:end]
            is_last_chunk = chunk_index == num_chunks - 1

            header = message_id + chunk_index.to_bytes(4, "big") + (b"\x01" if is_last_chunk else b"\x00")
            chunk_size_bytes = len(chunk).to_bytes(4, "big")
            chunk_with_header = header + chunk_size_bytes + chunk + self.EOT_CHAR

            self.writer.write(chunk_with_header)
            await self.writer.drain()

            # logging.debug(f"Sent message {message_id.hex()} | chunk {chunk_index+1}/{num_chunks} | size: {len(chunk)} bytes")

    def _calculate_chunk_size(self, data_size: int) -> int:
        return self.BUFFER_SIZE

    async def handle_incoming_message(self) -> None:
        reusable_buffer = bytearray(self.MAX_CHUNK_SIZE)
        try:
            while True:
                if self.pending_messages_queue.full():
                    await asyncio.sleep(0.1)  # Wait a bit if the queue is full to create backpressure
                    continue
                header = await self._read_exactly(self.HEADER_SIZE)
                message_id, chunk_index, is_last_chunk = self._parse_header(header)

                chunk_data = await self._read_chunk(reusable_buffer)
                await self._update_activity()
                self._store_chunk(message_id, chunk_index, chunk_data, is_last_chunk)
                # logging.debug(f"Received chunk {chunk_index} of message {message_id.hex()} | size: {len(chunk_data)} bytes")
                # Active connection without fails
                self.incompleted_reconnections = 0
                if is_last_chunk:
                    await self._process_complete_message(message_id)
        except asyncio.CancelledError as e:
            logging.exception(f"Message handling cancelled: {e}")
        except ConnectionError as e:
            logging.exception(f"Connection closed while reading: {e}")
        except Exception as e:
            logging.exception(f"Error handling incoming message: {e}")
        except BrokenPipeError:
            logging.exception(f"Error handling incoming message: {e}")
        finally:
            if self.direct or self._prio == ConnectionPriority.HIGH:
                await self.reconnect()

    async def _read_exactly(self, num_bytes: int, max_retries: int = 3) -> bytes:
        data = b""
        remaining = num_bytes
        for _ in range(max_retries):
            try:
                while remaining > 0:
                    chunk = await self.reader.read(min(remaining, self.BUFFER_SIZE))
                    if not chunk and not self.cm.learning_finished():
                        raise ConnectionError("Connection closed while reading")
                    data += chunk
                    remaining -= len(chunk)
                return data
            except asyncio.IncompleteReadError as e:
                if _ == max_retries - 1:
                    raise
                logging.warning(f"Retrying read after IncompleteReadError: {e}")
            except BrokenPipeError as e:
                if not self.forced_disconnection:
                    logging.exception(f"Broken PIPE while reading: {e}")
        raise RuntimeError("Max retries reached in _read_exactly")

    def _parse_header(self, header: bytes) -> tuple[bytes, int, bool]:
        message_id = header[:16]
        chunk_index = int.from_bytes(header[16:20], "big")
        is_last_chunk = header[20] == 1
        return message_id, chunk_index, is_last_chunk

    async def _read_chunk(self, buffer: bytearray = None) -> bytes:
        if buffer is None:
            buffer = bytearray(self.MAX_CHUNK_SIZE)

        chunk_size_bytes = await self._read_exactly(4)
        chunk_size = int.from_bytes(chunk_size_bytes, "big")

        if chunk_size > self.MAX_CHUNK_SIZE:
            raise ValueError(f"Chunk size {chunk_size} exceeds MAX_CHUNK_SIZE {self.MAX_CHUNK_SIZE}")

        chunk = await self._read_exactly(chunk_size)
        buffer[:chunk_size] = chunk
        eot = await self._read_exactly(len(self.EOT_CHAR))

        if eot != self.EOT_CHAR:
            raise ValueError("Invalid EOT character")

        return memoryview(buffer)[:chunk_size]

    def _store_chunk(self, message_id: bytes, chunk_index: int, buffer: memoryview, is_last: bool) -> None:
        if message_id not in self.message_buffers:
            self.message_buffers[message_id] = {}
        try:
            self.message_buffers[message_id][chunk_index] = MessageChunk(chunk_index, buffer.tobytes(), is_last)
            # logging.debug(f"Stored chunk {chunk_index} of message {message_id.hex()} | size: {len(data)} bytes")
        except Exception as e:
            if message_id in self.message_buffers:
                del self.message_buffers[message_id]
            logging.exception(f"Error storing chunk {chunk_index} for message {message_id.hex()}: {e}")

    async def _process_complete_message(self, message_id: bytes) -> None:
        chunks = sorted(self.message_buffers[message_id].values(), key=lambda x: x.index)
        complete_message = b"".join(chunk.data for chunk in chunks)
        del self.message_buffers[message_id]

        data_type_prefix = complete_message[:4]
        message_content = complete_message[4:]

        if message_content.endswith(self.COMPRESSION_CHAR):
            message_content = await asyncio.to_thread(
                self._decompress,
                message_content[: -len(self.COMPRESSION_CHAR)],
                self.compression,
            )
            if message_content is None:
                return

        await self.pending_messages_queue.put((data_type_prefix, memoryview(message_content)))
        # logging.debug(f"Processed complete message {message_id.hex()} | total size: {len(complete_message)} bytes")

    def _decompress(self, data: bytes, compression: str) -> bytes | None:
        if compression == "zlib":
            return zlib.decompress(data)
        elif compression == "bz2":
            return bz2.decompress(data)
        elif compression == "lzma":
            return lzma.decompress(data)
        elif compression == "lz4":
            return lz4.frame.decompress(data)
        else:
            logging.error(f"Unsupported compression method: {compression}")
            return None

    async def process_message_queue(self) -> None:
        while True:
            try:
                if self.pending_messages_queue is None:
                    logging.error("Pending messages queue is not initialized")
                    return
                data_type_prefix, message = await self.pending_messages_queue.get()
                await self._handle_message(data_type_prefix, message)
                self.pending_messages_queue.task_done()
            except Exception as e:
                logging.exception(f"Error processing message queue: {e}")
            finally:
                await asyncio.sleep(0)

    async def _handle_message(self, data_type_prefix: bytes, message: bytes) -> None:
        if data_type_prefix == self.DATA_TYPE_PREFIXES["pb"]:
            # logging.debug("Received a protobuf message")
            asyncio.create_task(
                self.cm.handle_incoming_message(message, self.addr),
                name=f"Connection {self.addr} message handler",
            )
        elif data_type_prefix == self.DATA_TYPE_PREFIXES["string"]:
            logging.debug(f"Received string message: {message.decode('utf-8')}")
        elif data_type_prefix == self.DATA_TYPE_PREFIXES["json"]:
            logging.debug(f"Received JSON message: {json.loads(message.decode('utf-8'))}")
        elif data_type_prefix == self.DATA_TYPE_PREFIXES["bytes"]:
            logging.debug(f"Received bytes message of length: {len(message)}")
        else:
            logging.error(f"Unknown data type prefix: {data_type_prefix}")

import json
from typing import Dict, Set
from nebula.core.utils.locker import Locker
import logging
import websockets
from fastapi import WebSocket
import asyncio

class RealTimeManager():
    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._channels: Dict[str, Set[WebSocket]] = {}
        self._channels_lock = Locker("channels_lock", async_lock=True)

    @property
    def log(self):
        return self._logger
    
    async def _register_client(self, websocket: WebSocket, channel_id: str):
        """Asocia un cliente a un canal"""
        async with self._channels_lock:
            if channel_id not in self._channels:
                raise ValueError("Channel not found")
            self._channels[channel_id].add(websocket)

    async def _unregister_client(self, websocket: WebSocket, channel_id: str):
        async with self._channels_lock:
            if channel_id in self._channels:
                self._channels[channel_id].discard(websocket)
    
    async def generate_communication_channel(self, federation_id: str):
        async with self._channels_lock:
            if federation_id not in self._channels:
                self._channels[federation_id] = set()
                return True
            else:
                return False
            
    async def 

    async def push_message(self, channel_id: str, message: dict):
        """Envía un mensaje a todos los clientes de un canal"""
        async with self._channels_lock:
            clients = self._channels.get(channel_id, set())
        if clients:
            msg_str = json.dumps(message)
            await asyncio.gather(*[ws.send(msg_str) for ws in clients], return_exceptions=True)

    

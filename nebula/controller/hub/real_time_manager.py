import json
from typing import Dict, Set
from nebula.core.utils.locker import Locker
import logging
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
    
    """                                                     ###############################
                                                            #      CLIENTS MANAGEMENT     #
                                                            ###############################
    """
    
    async def _register_client(self, websocket: WebSocket, channel_id: str):
        """Asocia un cliente a un canal"""
        async with self._channels_lock:
            if channel_id not in self._channels:
                raise ValueError("Channel not found")
            self._channels[channel_id].add(websocket)
            self.log.info(f"Client registered in channel {channel_id}")

    async def _unregister_client(self, websocket: WebSocket, channel_id: str):
        async with self._channels_lock:
            if channel_id in self._channels:
                self._channels[channel_id].discard(websocket)
                self.log.info(f"Client unregistered from channel {channel_id}")
            if not self._channels[channel_id]:
                    # Si el canal queda vacío, lo eliminamos
                    del self._channels[channel_id]
                    self.log.info(f"Channel {channel_id} removed (empty)")
       
    """                                                     ###############################
                                                            #      CHANNEL MANAGEMENT     #
                                                            ###############################
    """       
            
    async def generate_communication_channel(self, federation_id: str):
        async with self._channels_lock:
            if federation_id not in self._channels:
                self._channels[federation_id] = set()
                return True
            else:
                return False
            
    async def close_channel(self, channel_id: str, reason: str = "Channel closed by HUB"):
        async with self._channels_lock:
            clients = self._channels.pop(channel_id, None)

        if not clients:
            self.log.info(f"Channel {channel_id} not found or already empty.")
            return

        self.log.info(f"Closing channel {channel_id} ({len(clients)} clients)...")

        async def _close_client(ws: WebSocket):
            try:
                await ws.close(code=4000, reason=reason)
            except Exception as e:
                self.log.info(f"Error closing WS in channel {channel_id}: {e}")

        # Cierres concurrentes sin bloquear
        asyncio.create_task(asyncio.gather(*[_close_client(ws) for ws in clients]))

    """                                                     ###############################
                                                            #      CLIENTS CONNECTION     #
                                                            ###############################
    """   
            
    async def open_real_time_client(self, websocket: WebSocket, channel_id: str):
        try:
            await websocket.accept()
            await self._register_client(websocket, channel_id)
        except Exception as e:
            self.log.info(f"Client failed to connect or crashed early: {e}")
        finally:
            await self._unregister_client(websocket, channel_id)
                 
    async def push_message(self, channel_id: str, message: dict):
        async with self._channels_lock:
            clients = list(self._channels.get(channel_id, set()))
        if not clients:
            return

        msg_str = json.dumps(message)
        to_remove = []

        async def _send(ws: WebSocket):
            try:
                await ws.send_text(msg_str)
            except Exception:
                to_remove.append(ws)

        await asyncio.gather(*[_send(ws) for ws in clients])

        # Clean failled clients
        if to_remove:
            async with self._channels_lock:
                for ws in to_remove:
                    self._channels[channel_id].discard(ws)
            self.log.info(f"Cleaned {len(to_remove)} disconnected clients from {channel_id}")

    

import asyncio
import logging
import time

from nebula.addons.functions import print_msg_box


class Health:
    def __init__(self, addr, config):
        print_msg_box(msg="Starting health module...", indent=2, title="Health module")
        self.addr = addr
        self.config = config
        self._cm = None
        self.period = self.config.participant["health_args"]["health_interval"]
        self.alive_interval = self.config.participant["health_args"]["send_alive_interval"]
        self.check_alive_interval = self.config.participant["health_args"]["check_alive_interval"]
        self.timeout = self.config.participant["health_args"]["alive_timeout"]
        self._running = asyncio.Event()

    @property
    def cm(self):
        if not self._cm:
            from nebula.core.network.communications import CommunicationsManager

            self._cm = CommunicationsManager.get_instance()
            return self._cm
        else:
            return self._cm

    async def start(self):
        asyncio.create_task(self.run_send_alive())
        asyncio.create_task(self.run_check_alive())

    async def run_send_alive(self):
        await asyncio.sleep(self.config.participant["health_args"]["grace_time_health"])
        # Set all connections to active at the beginning of the health module
        for conn in self.cm.connections.values():
            conn.set_active(True)
        while await self.is_running():
            if len(self.cm.connections) > 0:
                message = self.cm.create_message("control", "alive", log="Alive message")
                current_connections = list(self.cm.connections.values())
                for conn in current_connections:
                    if conn.get_direct():
                        try:
                            logging.info(f"🕒  Sending alive message to {conn.get_addr()}...")
                            await conn.send(data=message)
                        except Exception as e:
                            logging.exception(f"❗️  Cannot send alive message to {conn.get_addr()}. Error: {e!s}")
                    await asyncio.sleep(self.alive_interval)
            await asyncio.sleep(self.period)

    async def run_check_alive(self):
        await asyncio.sleep(self.config.participant["health_args"]["grace_time_health"] + self.check_alive_interval)
        while await self.is_running():
            if len(self.cm.connections) > 0:
                current_connections = list(self.cm.connections.values())
                for conn in current_connections:
                    if conn.get_direct() and time.time() - conn.get_last_active() > self.timeout:
                        logging.error(f"⬅️ 🕒  Heartbeat timeout for {conn.get_addr()}...")
                        await self.cm.disconnect(conn.get_addr(), mutual_disconnection=False)
            await asyncio.sleep(self.check_alive_interval)

    async def alive(self, source):
        current_time = time.time()
        if source not in self.cm.connections:
            logging.error(f"❗️  Connection {source} not found in connections...")
            return
        conn = self.cm.connections[source]
        if conn.get_last_active() < current_time:
            logging.debug(f"🕒  Updating last active time for {source}")
            conn.set_active(True)

    async def is_running(self):
        return self._running.is_set()

    async def stop(self):
        self._running.clear()

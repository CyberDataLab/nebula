import asyncio
import logging

from nebula.addons.functions import print_msg_box


class Discoverer:
    def __init__(self, addr, config):
        print_msg_box(msg="Starting discoverer module...", indent=2, title="Discoverer module")
        self.addr = addr
        self.config = config
        self._cm = None
        self.grace_time = self.config.participant["discoverer_args"]["grace_time_discovery"]
        self.period = self.config.participant["discoverer_args"]["discovery_frequency"]
        self.interval = self.config.participant["discoverer_args"]["discovery_interval"]
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
        self._running.set()
        asyncio.create_task(self.run_discover())

    async def run_discover(self):
        if self.config.participant["scenario_args"]["federation"] == "CFL":
            logging.info("🔍  Federation is CFL. Discoverer is disabled...")
            return
        await asyncio.sleep(self.grace_time)
        while await self.is_running():
            if len(self.cm.connections) > 0:
                latitude = self.config.participant["mobility_args"]["latitude"]
                longitude = self.config.participant["mobility_args"]["longitude"]
                message = self.cm.create_message("discovery", "discover", latitude=latitude, longitude=longitude)
                try:
                    logging.debug("🔍  Sending discovery message to neighbors...")
                    current_connections = await self.cm.get_addrs_current_connections(only_direct=True)
                    await self.cm.send_message_to_neighbors(message, current_connections, self.interval)
                except Exception as e:
                    logging.exception(f"🔍  Cannot send discovery message to neighbors. Error: {e!s}")
            await asyncio.sleep(self.period)

    async def stop(self):
        self._running.clear()
        logging.info("🔍  Stopping Discoverer module...")

    async def is_running(self):
        return self._running.is_set()

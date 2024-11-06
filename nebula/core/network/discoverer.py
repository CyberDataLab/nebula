import asyncio
import logging
from typing import TYPE_CHECKING

from nebula.addons.functions import print_msg_box
from nebula.core.pb import nebula_pb2

if TYPE_CHECKING:
    from nebula.core.network.communications import CommunicationsManager


class Discoverer:
    def __init__(self, addr, config, cm: "CommunicationsManager"):
        print_msg_box(msg="Starting discoverer module...", indent=2, title="Discoverer module")
        self.addr = addr
        self.config = config
        self.cm = cm
        self.grace_time = self.config.participant["discoverer_args"]["grace_time_discovery"]
        self.period = self.config.participant["discoverer_args"]["discovery_frequency"]
        self.interval = self.config.participant["discoverer_args"]["discovery_interval"]

    async def start(self):
        asyncio.create_task(self.run_discover())

    async def run_discover(self):
        if self.config.participant["scenario_args"]["federation"] == "CFL":
            logging.info("🔍  Federation is CFL. Discoverer is disabled...")
            return
        await asyncio.sleep(self.grace_time)
        while True:
            if len(self.cm.connections) > 0:
                latitude = self.config.participant["mobility_args"]["latitude"]
                longitude = self.config.participant["mobility_args"]["longitude"]
                message = self.cm.mm.generate_discovery_message(
                    action=nebula_pb2.DiscoveryMessage.Action.DISCOVER,
                    latitude=latitude,
                    longitude=longitude,
                )
                try:
                    logging.debug("🔍  Sending discovery message to neighbors...")
                    current_connections = await self.cm.get_addrs_current_connections(only_direct=True)
                    await self.cm.send_message_to_neighbors(message, current_connections, self.interval)
                except Exception as e:
                    logging.exception(f"🔍  Cannot send discovery message to neighbors. Error: {e!s}")
            await asyncio.sleep(self.period)

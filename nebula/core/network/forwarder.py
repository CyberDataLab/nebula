import asyncio
import logging
import time

from nebula.addons.functions import print_msg_box
from nebula.core.utils.locker import Locker


class Forwarder:
    def __init__(self, config):
        print_msg_box(msg="Starting forwarder module...", indent=2, title="Forwarder module")
        self.config = config
        self._cm = None
        self.pending_messages = asyncio.Queue()
        self.pending_messages_lock = Locker("pending_messages_lock", verbose=False, async_lock=True)

        self.interval = self.config.participant["forwarder_args"]["forwarder_interval"]
        self.number_forwarded_messages = self.config.participant["forwarder_args"]["number_forwarded_messages"]
        self.messages_interval = self.config.participant["forwarder_args"]["forward_messages_interval"]

    @property
    def cm(self):
        if not self._cm:
            from nebula.core.network.communications import CommunicationsManager

            self._cm = CommunicationsManager.get_instance()
            return self._cm
        else:
            return self._cm

    async def start(self):
        asyncio.create_task(self.run_forwarder())

    async def run_forwarder(self):
        if self.config.participant["scenario_args"]["federation"] == "CFL":
            logging.info("🔁  Federation is CFL. Forwarder is disabled...")
            return
        while True:
            # logging.debug(f"🔁  Pending messages: {self.pending_messages.qsize()}")
            start_time = time.time()
            await self.pending_messages_lock.acquire_async()
            await self.process_pending_messages(messages_left=self.number_forwarded_messages)
            await self.pending_messages_lock.release_async()
            sleep_time = max(0, self.interval - (time.time() - start_time))
            await asyncio.sleep(sleep_time)

    async def process_pending_messages(self, messages_left):
        while messages_left > 0 and not self.pending_messages.empty():
            msg, neighbors = await self.pending_messages.get()
            for neighbor in neighbors[:messages_left]:
                if neighbor not in self.cm.connections:
                    continue
                try:
                    logging.debug(f"🔁  Sending message (forwarding) --> to {neighbor}")
                    await self.cm.send_message(neighbor, msg)
                except Exception as e:
                    logging.exception(f"🔁  Error forwarding message to {neighbor}. Error: {e!s}")
                    pass
                await asyncio.sleep(self.messages_interval)
            messages_left -= len(neighbors)
            if len(neighbors) > messages_left:
                logging.debug("🔁  Putting message back in queue for forwarding to the remaining neighbors")
                await self.pending_messages.put((msg, neighbors[messages_left:]))

    async def forward(self, msg, addr_from):
        if self.config.participant["scenario_args"]["federation"] == "CFL":
            logging.info("🔁  Federation is CFL. Forwarder is disabled...")
            return
        try:
            await self.pending_messages_lock.acquire_async()
            current_connections = await self.cm.get_addrs_current_connections(only_direct=True)
            pending_nodes_to_send = [n for n in current_connections if n != addr_from]
            logging.debug(f"🔁  Puting message in queue for forwarding to {pending_nodes_to_send}")
            await self.pending_messages.put((msg, pending_nodes_to_send))
        except Exception as e:
            logging.exception(f"🔁  Error forwarding message. Error: {e!s}")
        finally:
            await self.pending_messages_lock.release_async()

import asyncio
import logging
import time

from nebula.addons.functions import print_msg_box
from nebula.core.utils.locker import Locker


class Forwarder:
    """
    Component responsible for forwarding incoming messages to appropriate peer nodes.

    The Forwarder handles:
      - Relaying messages received from one node to others in the federation.
      - Applying any forwarding policies (e.g., proxy mode, rate limiting).
      - Ensuring duplicate messages are not resent.
      - Integrating with the CommunicationsManager to obtain current connections.

    This class is designed to run asynchronously, leveraging the existing connection pool
    and message routing logic to propagate messages reliably across the network.
    """

    def __init__(self, config):
        """
        Initialize the Forwarder module.

        Args:
            config (dict): The global configuration, including forwarder parameters:
                - forwarder_interval: Time between forwarding cycles.
                - number_forwarded_messages: Max messages to forward per cycle.
                - forward_messages_interval: Delay between individual message sends.
        """
        print_msg_box(msg="Starting forwarder module...", indent=2, title="Forwarder module")
        self.config = config
        self._cm = None
        self.pending_messages = asyncio.Queue()
        self.pending_messages_lock = Locker("pending_messages_lock", verbose=False, async_lock=True)
        self._forwarder_task = None  # Track the background task

        self.interval = self.config.participant["forwarder_args"]["forwarder_interval"]
        self.number_forwarded_messages = self.config.participant["forwarder_args"]["number_forwarded_messages"]
        self.messages_interval = self.config.participant["forwarder_args"]["forward_messages_interval"]
        self._running = asyncio.Event()

    @property
    def cm(self):
        """
        Lazy-load and return the CommunicationsManager instance for sending messages.

        Returns:
            CommunicationsManager: The singleton communications manager.
        """
        if not self._cm:
            from nebula.core.network.communications import CommunicationsManager

            self._cm = CommunicationsManager.get_instance()
            return self._cm
        else:
            return self._cm

    async def start(self):
        """
        Start the forwarder by scheduling the forwarding loop as a background task.
        """
        self._running.set()
        self._forwarder_task = asyncio.create_task(self.run_forwarder(), name="Forwarder_run_forwarder")

    async def run_forwarder(self):
        """
        Periodically process and dispatch pending messages.

        Runs indefinitely (unless in CFL mode), acquiring a lock to safely
        dequeue up to `number_forwarded_messages` and send them with appropriate timing.
        """
        if self.config.participant["scenario_args"]["federation"] == "CFL":
            logging.info("🔁  Federation is CFL. Forwarder is disabled...")
            return
        try:
            while await self.is_running():
                start_time = time.time()
                await self.pending_messages_lock.acquire_async()
                await self.process_pending_messages(messages_left=self.number_forwarded_messages)
                await self.pending_messages_lock.release_async()
                sleep_time = max(0, self.interval - (time.time() - start_time))
                await asyncio.sleep(sleep_time)
        except asyncio.CancelledError:
            logging.info("run_forwarder cancelled during shutdown.")
            return

    async def stop(self):
        self._running.clear()
        logging.info("🔁  Stopping Forwarder module...")

        # Cancel the background task
        if self._forwarder_task and not self._forwarder_task.done():
            logging.info("🛑  Cancelling Forwarder background task...")
            self._forwarder_task.cancel()
            try:
                await self._forwarder_task
            except asyncio.CancelledError:
                pass
            self._forwarder_task = None
            logging.info("🛑  Forwarder background task cancelled")

    async def is_running(self):
        return self._running.is_set()

    async def process_pending_messages(self, messages_left):
        """
        Send up to `messages_left` messages from the pending queue to their target neighbors.

        Args:
            messages_left (int): The maximum number of messages to forward in this batch.
        """
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
        """
        Enqueue a received message for forwarding to all other direct neighbors.

        Excludes the original sender and acquires a lock to safely add to the queue.

        Args:
            msg (bytes): The serialized message to forward.
            addr_from (str): The address of the node that originally sent the message.
        """
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

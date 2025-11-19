import asyncio
import importlib
import json
import logging
import os
import sys
from nebula.config.config import Config
from nebula.kafka.clients.node_client import NebulaKafkaNode
from nebula.kafka.clients.messages.experiment import ExperimentMessages
from nebula.core.utils.locker import Locker
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateNeighborEvent, RoundEndEvent, ExperimentFinishEvent, ChangeLocationEvent
from nebula.addons.reporting.resource_monitor import ResourceMonitor

class Reporter:
    def __init__(self, config: Config, verbose=False):
        self._config = config
        self._kafka_client = NebulaKafkaNode(
            broker=config.participant["kafka_args"]["broker"],
            experiment_topic=config.participant["kafka_args"]["topic"],
            user=config.participant["kafka_args"]["user"],
            password=config.participant["kafka_args"]["password"],
            idx=config.participant["device_args"]["idx"],
            logger=logging.getLogger()
        )
        self._updare_required = asyncio.Event()
        self._report_locker = Locker(name="report_locker", async_lock=True)
        self._resource_monitor = ResourceMonitor(config=config)
        self._verbose = verbose

    async def start(self):
        await EventManager.get_instance().subscribe_addonevent(ChangeLocationEvent, self._update_required_addon_event)
        await EventManager.get_instance().subscribe_node_event(UpdateNeighborEvent, self._update_required_node_event)
        await EventManager.get_instance().subscribe_node_event(RoundEndEvent, self._round_end)
        await EventManager.get_instance().subscribe_node_event(ExperimentFinishEvent, self._finish_experiment_notification)
        await self._kafka_client.init()

    async def stop(self):
        logging.info("🔍  Stopping reporter module...")
        stopped = await self._kafka_client.shutdown()
        if stopped:
            logging.info("🛑  Reporter cancelled")

    async def _update_required_addon_event(self, event: ChangeLocationEvent):
        self._updare_required.set()
        update_payload = await self._config.get_update_info()
        sent = await self._report_data(ExperimentMessages.UPDATE, **update_payload)
        if self._verbose:
            logging.info(f"Data report successfully: {sent}")

    async def _update_required_node_event(self, event: UpdateNeighborEvent):
        self._updare_required.set()
        update_payload = await self._config.get_update_info()
        sent = await self._report_data(ExperimentMessages.UPDATE, **update_payload)
        if self._verbose:
            logging.info(f"Data report successfully: {sent}")

    async def _round_end(self, event: RoundEndEvent):
        # At round end send UPDATE and METRIC
        # Send UPDATE
        await self._update_required_node_event(event)

        # Send METRICS
        experiment_id = await self._config.get_experiment_id()
        end_time, iteration, model_metrics = await event.get_event_data()
        resources_metrics = await self._resource_monitor.get_resources_metrics()
        metrics = {
            "model": model_metrics,
            "resources": resources_metrics,
        }
        sent = await self._report_data(ExperimentMessages.METRICS, experiment_id=experiment_id, end_time=end_time, iteration=iteration, metrics=metrics)
        if self._verbose:
            logging.info(f"Data report successfully: {sent}")

    async def _finish_experiment_notification(self, event: ExperimentFinishEvent):
        done_payload = await self._config.get_done_info()
        sent = await self._report_data(ExperimentMessages.DONE, **done_payload)
        if self._verbose:
            logging.info(f"Data report successfully: {sent}")

    async def _report_data(self, message_type: ExperimentMessages, **kwargs) -> bool:
        sent = False
        async with self._report_locker:
            if message_type == ExperimentMessages.UPDATE:
                if self._updare_required.is_set():
                    sent = await self._kafka_client.produce(message_type, **kwargs)
                    self._updare_required.clear()
            else:
                sent = await self._kafka_client.produce(message_type, **kwargs)
        return sent

    async def report_scenario_finished(self):
        """
        Reports scenario completion to the controller via Kafka.

        This method sends a DONE message through Kafka to notify that the
        participant has finished the federated learning scenario.

        Returns:
            bool: True if message sent successfully, False otherwise.
        """
        done_payload = await self._config.get_done_info()
        sent = await self._report_data(ExperimentMessages.DONE, **done_payload)
        if sent:
            logging.info(f"Participant {self._config.participant['device_args']['idx']} reported scenario finished via Kafka")
        else:
            logging.error("Failed to report scenario finished via Kafka")
        return sent

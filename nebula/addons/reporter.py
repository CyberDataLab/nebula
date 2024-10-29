import asyncio
import importlib
import json
import logging
import aiohttp
import sys
import psutil
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nebula.core.network.communications import CommunicationsManager


class Reporter:
    def __init__(self, config, trainer, cm: "CommunicationsManager"):
        logging.info(f"Starting reporter module")
        self.config = config
        self.trainer = trainer
        self.cm = cm
        self.frequency = self.config.participant["reporter_args"]["report_frequency"]
        self.grace_time = self.config.participant["reporter_args"]["grace_time_reporter"]
        self.data_queue = asyncio.Queue()
        self.url = f'http://{self.config.participant["scenario_args"]["controller"]}/nebula/dashboard/{self.config.participant["scenario_args"]["name"]}/node/update'
        self.counter = 0
        
        self.first_net_metrics = True
        self.prev_bytes_sent = 0
        self.prev_bytes_recv = 0
        self.prev_packets_sent = 0
        self.prev_packets_recv = 0
        
        self.acc_bytes_sent = 0
        self.acc_bytes_recv = 0
        self.acc_packets_sent = 0
        self.acc_packets_recv = 0

    async def enqueue_data(self, name, value):
        await self.data_queue.put((name, value))

    async def start(self):
        await asyncio.sleep(self.grace_time)
        asyncio.create_task(self.run_reporter())

    async def run_reporter(self):
        while True:
            # NOTE: currently disabled
            if self.config.participant["scenario_args"]["controller"] != "nebula-test":
                 await self.__report_status_to_controller()
            await self.__report_data_queue()
            await self.__report_resources()
            self.counter += 1
            if self.counter % 50 == 0:
                logging.info(f"Reloading config file...")
                self.cm.engine.config.reload_config_file()
            await asyncio.sleep(self.frequency)

    async def report_scenario_finished(self):
        url = f'http://{self.config.participant["scenario_args"]["controller"]}/nebula/dashboard/{self.config.participant["scenario_args"]["name"]}/node/done'
        data = json.dumps({"idx": self.config.participant["device_args"]["idx"]})
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f'NEBULA Participant {self.config.participant["device_args"]["idx"]}',
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, headers=headers) as response:
                    if response.status != 200:
                        logging.error(f"Error received from controller: {response.status} (probably there is overhead in the controller, trying again in the next round)")
                        text = await response.text()
                        logging.debug(text)
                    else:
                        logging.info(f"Participant {self.config.participant['device_args']['idx']} reported scenario finished")
                        return True
        except aiohttp.ClientError as e:
            logging.error(f"Error connecting to the controller at {url}: {e}")
        return False

    async def __report_data_queue(self):
        while not self.data_queue.empty():
            name, value = await self.data_queue.get()
            await self.trainer.logger.log_data({name: value})  # Assuming log_data can be made async
            self.data_queue.task_done()

    async def __report_status_to_controller(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    data=json.dumps(self.config.participant),
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": f'NEBULA Participant {self.config.participant["device_args"]["idx"]}',
                    },
                ) as response:
                    if response.status != 200:
                        logging.error(f"Error received from controller: {response.status} (probably there is overhead in the controller, trying again in the next round)")
                        text = await response.text()
                        logging.debug(text)
        except aiohttp.ClientError as e:
            logging.error(f"Error connecting to the controller at {self.url}: {e}")
        except Exception as e:
            logging.error(f"Error sending status to controller, will try again in a few seconds: {e}")
            await asyncio.sleep(5)

    async def __report_resources(self):
        cpu_percent = psutil.cpu_percent()
        cpu_temp = 0
        try:
            if sys.platform == "linux":
                sensors = await asyncio.to_thread(psutil.sensors_temperatures)
                cpu_temp = sensors.get("coretemp")[0].current if sensors.get("coretemp") else 0
        except Exception as e:
            pass

        pid = os.getpid()
        cpu_percent_process = await asyncio.to_thread(psutil.Process(pid).cpu_percent, interval=1)

        process = psutil.Process(pid)
        memory_process = await asyncio.to_thread(lambda: process.memory_info().rss / (1024**2))
        memory_percent_process = process.memory_percent()
        memory_info = await asyncio.to_thread(psutil.virtual_memory)
        memory_percent = memory_info.percent
        memory_used = memory_info.used / (1024**2)

        disk_percent = psutil.disk_usage("/").percent

        net_io_counters = await asyncio.to_thread(psutil.net_io_counters)
        bytes_sent = net_io_counters.bytes_sent
        bytes_recv = net_io_counters.bytes_recv
        packets_sent = net_io_counters.packets_sent
        packets_recv = net_io_counters.packets_recv
        
        if self.first_net_metrics:
            bytes_sent_diff = 0
            bytes_recv_diff = 0
            packets_sent_diff = 0
            packets_recv_diff = 0
            self.first_net_metrics = False
        else:
            bytes_sent_diff = bytes_sent - self.prev_bytes_sent
            bytes_recv_diff = bytes_recv - self.prev_bytes_recv
            packets_sent_diff = packets_sent - self.prev_packets_sent
            packets_recv_diff = packets_recv - self.prev_packets_recv

        self.prev_bytes_sent = bytes_sent
        self.prev_bytes_recv = bytes_recv
        self.prev_packets_sent = packets_sent
        self.prev_packets_recv = packets_recv
        
        self.acc_bytes_sent += bytes_sent_diff
        self.acc_bytes_recv += bytes_recv_diff
        self.acc_packets_sent += packets_sent_diff
        self.acc_packets_recv += packets_recv_diff

        current_connections = await self.cm.get_addrs_current_connections(only_direct=True)

        resources = {
            "CPU/CPU global (%)": cpu_percent,
            "CPU/CPU process (%)": cpu_percent_process,
            "CPU/CPU temperature (°)": cpu_temp,
            "RAM/RAM global (%)": memory_percent,
            "RAM/RAM global (MB)": memory_used,
            "RAM/RAM process (%)": memory_percent_process,
            "RAM/RAM process (MB)": memory_process,
            "Disk/Disk (%)": disk_percent,
            "Network/Network (bytes sent)": round(self.acc_bytes_sent / (1024 ** 2), 3),
            "Network/Network (bytes received)": round(self.acc_bytes_recv / (1024 ** 2), 3),
            "Network/Network (packets sent)": self.acc_packets_sent,
            "Network/Network (packets received)": self.acc_packets_recv,
            "Network/Connections": len(current_connections),
        }
        self.trainer.logger.log_data(resources)

        if importlib.util.find_spec("pynvml") is not None:
            try:
                import pynvml

                await asyncio.to_thread(pynvml.nvmlInit)
                devices = await asyncio.to_thread(pynvml.nvmlDeviceGetCount)
                for i in range(devices):
                    handle = await asyncio.to_thread(pynvml.nvmlDeviceGetHandleByIndex, i)
                    gpu_percent = (await asyncio.to_thread(pynvml.nvmlDeviceGetUtilizationRates, handle)).gpu
                    gpu_temp = await asyncio.to_thread(pynvml.nvmlDeviceGetTemperature, handle, pynvml.NVML_TEMPERATURE_GPU)
                    gpu_mem = await asyncio.to_thread(pynvml.nvmlDeviceGetMemoryInfo, handle)
                    gpu_mem_percent = round(gpu_mem.used / gpu_mem.total * 100, 3)
                    gpu_power = await asyncio.to_thread(pynvml.nvmlDeviceGetPowerUsage, handle) / 1000.0
                    gpu_clocks = await asyncio.to_thread(pynvml.nvmlDeviceGetClockInfo, handle, pynvml.NVML_CLOCK_SM)
                    gpu_memory_clocks = await asyncio.to_thread(pynvml.nvmlDeviceGetClockInfo, handle, pynvml.NVML_CLOCK_MEM)
                    gpu_fan_speed = await asyncio.to_thread(pynvml.nvmlDeviceGetFanSpeed, handle)
                    gpu_info = {
                        f"GPU/GPU{i} (%)": gpu_percent,
                        f"GPU/GPU{i} temperature (°)": gpu_temp,
                        f"GPU/GPU{i} memory (%)": gpu_mem_percent,
                        f"GPU/GPU{i} power": gpu_power,
                        f"GPU/GPU{i} clocks": gpu_clocks,
                        f"GPU/GPU{i} memory clocks": gpu_memory_clocks,
                        f"GPU/GPU{i} fan speed": gpu_fan_speed,
                    }
                    self.trainer.logger.log_data(gpu_info)
            except Exception:
                pass

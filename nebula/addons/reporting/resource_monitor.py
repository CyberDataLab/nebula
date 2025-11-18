import asyncio
import importlib
import os
import sys
import psutil
from nebula.config.config import Config
from typing import Dict


class ResourceMonitor():
    def __init__(self, config: Config):
        self._config = config
        self.first_net_metrics = True
        self.prev_bytes_sent = 0
        self.prev_bytes_recv = 0
        self.prev_packets_sent = 0
        self.prev_packets_recv = 0

        self.acc_bytes_sent = 0
        self.acc_bytes_recv = 0
        self.acc_packets_sent = 0
        self.acc_packets_recv = 0

    async def get_resources_metrics(self) -> Dict:
        """
        Reports system resource usage metrics.

        This asynchronous function gathers and logs CPU usage data for the participant's device,
        and attempts to retrieve the CPU temperature (Linux systems only). Additionally, it measures
        CPU usage specifically for the current process.

        Functionality:
            - Gathers total CPU usage (percentage) and attempts to retrieve CPU temperature.
            - Uses `psutil` for non-blocking access to system data on Linux.
            - Records CPU usage of the current process for finer monitoring.

        Parameters:
            - None

        Notes:
            - On non-Linux platforms, CPU temperature will default to 0.
            - Uses `asyncio.to_thread` to call CPU and sensor readings without blocking the event loop.
        """
        cpu_percent = psutil.cpu_percent()
        cpu_temp = 0
        try:
            if sys.platform == "linux":
                sensors = await asyncio.to_thread(psutil.sensors_temperatures)
                cpu_temp = sensors.get("coretemp")[0].current if sensors.get("coretemp") else 0
        except Exception:  # noqa: S110
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

        current_connections = len(await self._config.get_current_neighbors())

        resources = {
            "W-CPU/CPU global (%)": cpu_percent,
            "W-CPU/CPU process (%)": cpu_percent_process,
            "W-CPU/CPU temperature (°)": cpu_temp,
            "Z-RAM/RAM global (%)": memory_percent,
            "Z-RAM/RAM global (MB)": memory_used,
            "Z-RAM/RAM process (%)": memory_percent_process,
            "Z-RAM/RAM process (MB)": memory_process,
            "Y-Disk/Disk (%)": disk_percent,
            "X-Network/Network (MB sent)": round(self.acc_bytes_sent / (1024**2), 3),
            "X-Network/Network (MB received)": round(self.acc_bytes_recv / (1024**2), 3),
            "X-Network/Network (packets sent)": self.acc_packets_sent,
            "X-Network/Network (packets received)": self.acc_packets_recv,
            "X-Network/Connections": len(current_connections),
        }

        if importlib.util.find_spec("pynvml") is not None:
            try:
                import pynvml

                await asyncio.to_thread(pynvml.nvmlInit)
                devices = await asyncio.to_thread(pynvml.nvmlDeviceGetCount)
                devices_info: Dict[int, Dict] = {}
                for i in range(devices):
                    handle = await asyncio.to_thread(pynvml.nvmlDeviceGetHandleByIndex, i)
                    gpu_percent = (await asyncio.to_thread(pynvml.nvmlDeviceGetUtilizationRates, handle)).gpu
                    gpu_temp = await asyncio.to_thread(
                        pynvml.nvmlDeviceGetTemperature,
                        handle,
                        pynvml.NVML_TEMPERATURE_GPU,
                    )
                    gpu_mem = await asyncio.to_thread(pynvml.nvmlDeviceGetMemoryInfo, handle)
                    gpu_mem_percent = round(gpu_mem.used / gpu_mem.total * 100, 3)
                    gpu_power = await asyncio.to_thread(pynvml.nvmlDeviceGetPowerUsage, handle) / 1000.0
                    gpu_clocks = await asyncio.to_thread(pynvml.nvmlDeviceGetClockInfo, handle, pynvml.NVML_CLOCK_SM)
                    gpu_memory_clocks = await asyncio.to_thread(
                        pynvml.nvmlDeviceGetClockInfo, handle, pynvml.NVML_CLOCK_MEM
                    )
                    gpu_fan_speed = await asyncio.to_thread(pynvml.nvmlDeviceGetFanSpeed, handle)
                    gpu_info = {
                        f"W-GPU/GPU{i} (%)": gpu_percent,
                        f"W-GPU/GPU{i} temperature (°)": gpu_temp,
                        f"W-GPU/GPU{i} memory (%)": gpu_mem_percent,
                        f"W-GPU/GPU{i} power": gpu_power,
                        f"W-GPU/GPU{i} clocks": gpu_clocks,
                        f"W-GPU/GPU{i} memory clocks": gpu_memory_clocks,
                        f"W-GPU/GPU{i} fan speed": gpu_fan_speed,
                    }
                    devices_info[i] = gpu_info
                resources["V-GPU"] = devices_info
            except Exception:  # noqa: S110
                pass

        return resources

import asyncio
import platform

import psutil
from pynvml import (
    nvmlDeviceGetCount,
    nvmlDeviceGetHandleByIndex,
    nvmlDeviceGetMemoryInfo,
    nvmlDeviceGetUtilizationRates,
    nvmlInit,
    nvmlShutdown,
)

from nebula.core.utils.locker import Locker


class SystemMonitor:
    _instance = None
    _lock = Locker("communications_manager_lock", async_lock=False)

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        """Obtain SystemMonitor instance"""
        if cls._instance is None:
            raise ValueError("SystemMonitor has not been initialized yet.")
        return cls._instance

    def __init__(self):
        """Initialize the system monitor and check for GPU availability."""
        if not hasattr(self, "_initialized"):  # To avoid reinitialization on subsequent calls
            # Try to initialize NVIDIA library if available
            try:
                nvmlInit()
                self.gpu_available = True  # Flag to check if GPU is available
            except Exception:
                self.gpu_available = False  # If not, set GPU availability to False
            self._initialized = True

    async def get_cpu_usage(self):
        """Returns the CPU usage percentage."""
        return psutil.cpu_percent(interval=1)

    async def get_cpu_per_core_usage(self):
        """Returns the CPU usage percentage per core."""
        return psutil.cpu_percent(interval=1, percpu=True)

    async def get_memory_usage(self):
        """Returns the percentage of used RAM memory."""
        memory_info = psutil.virtual_memory()
        return memory_info.percent

    async def get_swap_memory_usage(self):
        """Returns the percentage of used swap memory."""
        swap_info = psutil.swap_memory()
        return swap_info.percent

    async def get_network_usage(self, interval=5):
        """Measures network usage over a time interval and returns bandwidth percentage usage."""
        os_name = platform.system()

        # Get max bandwidth (only implemented for Linux)
        if os_name == "Linux":
            max_bandwidth = self._get_max_bandwidth_linux()
        else:
            max_bandwidth = None

        # Take first measurement
        net_io_start = psutil.net_io_counters()
        bytes_sent_start = net_io_start.bytes_sent
        bytes_recv_start = net_io_start.bytes_recv

        # Wait for the interval
        await asyncio.sleep(interval)

        # Take second measurement
        net_io_end = psutil.net_io_counters()
        bytes_sent_end = net_io_end.bytes_sent
        bytes_recv_end = net_io_end.bytes_recv

        # Calculate bytes transferred during interval
        bytes_sent = bytes_sent_end - bytes_sent_start
        bytes_recv = bytes_recv_end - bytes_recv_start
        total_bytes = bytes_sent + bytes_recv

        # Calculate bandwidth usage percentage
        bandwidth_used_percent = self._calculate_bandwidth_usage(total_bytes, max_bandwidth, interval)

        return {
            "interval": interval,
            "bytes_sent": bytes_sent,
            "bytes_recv": bytes_recv,
            "bandwidth_used_percent": bandwidth_used_percent,
            "bandwidth_max": max_bandwidth,
        }

    # TODO catched speed to avoid reading file
    def _get_max_bandwidth_linux(self, interface="eth0"):
        """Reads max bandwidth from /sys/class/net/{iface}/speed (Linux only)."""
        try:
            with open(f"/sys/class/net/{interface}/speed") as f:
                speed = int(f.read().strip())  # In Mbps
                return speed
        except Exception as e:
            print(f"Could not read max bandwidth: {e}")
            return None

    def _calculate_bandwidth_usage(self, bytes_transferred, max_bandwidth_mbps, interval):
        """Calculates bandwidth usage percentage over the given interval."""
        if max_bandwidth_mbps is None or interval <= 0:
            return None

        try:
            # Convert bytes to megabits
            megabits_transferred = (bytes_transferred * 8) / (1024 * 1024)
            # Calculate usage in Mbps
            current_usage_mbps = megabits_transferred / interval
            # Percentage of max bandwidth
            usage_percentage = (current_usage_mbps / max_bandwidth_mbps) * 100
            return usage_percentage
        except Exception as e:
            print(f"Error calculating bandwidth usage: {e}")
            return None

    async def get_gpu_usage(self):
        """Returns GPU usage stats if available, otherwise returns None."""
        if not self.gpu_available:
            return None  # No GPU available, return None

        # If GPU is available, get the usage using pynvml
        device_count = nvmlDeviceGetCount()
        gpu_usage = []
        for i in range(device_count):
            handle = nvmlDeviceGetHandleByIndex(i)
            memory_info = nvmlDeviceGetMemoryInfo(handle)
            utilization = nvmlDeviceGetUtilizationRates(handle)
            gpu_usage.append({
                "gpu": i,
                "memory_used": memory_info.used / 1024**2,  # MB
                "memory_total": memory_info.total / 1024**2,  # MB
                "gpu_usage": utilization.gpu,
            })
        return gpu_usage

    async def get_system_resources(self):
        """Returns a dictionary with all system resource usage statistics."""
        resources = {
            "cpu_usage": await self.get_cpu_usage(),
            "cpu_per_core_usage": await self.get_cpu_per_core_usage(),
            "memory_usage": await self.get_memory_usage(),
            "swap_memory_usage": await self.get_swap_memory_usage(),
            "network_usage": await self.get_network_usage(),
            "gpu_usage": await self.get_gpu_usage(),  # Includes GPU usage or None if no GPU
        }
        return resources

    async def close(self):
        """Closes the initialization of the NVIDIA library (if used)."""
        if self.gpu_available:
            nvmlShutdown()

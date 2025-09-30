import asyncio
import importlib
from collections.abc import Callable
from typing import Dict, List
import logging 
import psutil
from nebula.core.utils.locker import Locker
import inspect
import random
from abc import ABC, abstractmethod

"""                                             ###############################
                                                #       RESOURCE EVENTS       #
                                                ###############################
"""

class ResourceEvent(ABC):
    """
    Abstract base class for all resource-related events in the system.
    """
    
    @abstractmethod
    async def get_event_data(self):
        """
        Retrieve the data associated with the event.

        Returns:
            Any: The event-specific data payload.
        """
        pass

class ReleaseDevicesEvent(ResourceEvent):
    def __init__(self, federation_id):
        self._federation_id = federation_id

    async def get_event_data(self):
        return self._federation_id
    
class RAMOverusedEvent(ResourceEvent):
    def __init__(self):
        pass
    async def get_event_data(self):
        pass
    
"""                                             ###############################
                                                #    RESOURCE MANAGER CLASS   #
                                                ###############################
"""

class ResourceManager:
    _instance = None
    _lock = Locker("event_manager")

    def __new__(cls, *args, **kwargs):
        """Singleton implementation"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize(*args, **kwargs)
        return cls._instance

    def _initialize(self, logger, verbose=False):
        """Single initialization"""
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._logger: logging.Logger = logger
        self._subscribers: dict[type, list] = {}
        self._resources_events_lock = Locker("resources_events_lock", async_lock=True)
        self._devices: List = []
        self._available_devices: List = []
        self._available_devices_lock = Locker("_avaialble_devices_lock", async_lock=True)
        self._currently_used_devices: Dict[str, str] = {}
        self._currently_used_devices_lock = Locker("currently_used_devices_lock", async_lock=True)
        self._max_devices_per_user = 0
        self._monitor_cooldown = 10
        self._max_ram = None
        self._monitor_task = None
        self._verbose = verbose
        
    @staticmethod
    def get_instance(logger=None, verbose=False):
        """Static method to obtain EventManager instance"""
        if ResourceManager._instance is None:
            ResourceManager(logger=logger,verbose=verbose)
        return ResourceManager._instance
    
    @property
    def cud(self):
        """
        Currently used devices Dictionary
        [Federation ID, Devices]
        """
        return self._currently_used_devices
    
    """                                             ###############################
                                                    #  RESOURCE EVENTS MANAGEMENT #
                                                    ###############################
    """
    
    async def subscribe_resource_event(self, resource_event: type[ResourceEvent], callback: Callable):
        """Register a callback for a specific type of ResouceEvent."""
        async with self._resources_events_lock:
            if resource_event not in self._subscribers:
                self._subscribers[resource_event] = []
            self._subscribers[resource_event].append(callback)

    async def publish_recource_event(self, resource_event: ResourceEvent):
        """Trigger all callbacks registered for a specific type of ResourceEvent."""
        async with self._resources_events_lock:
            event_type = type(resource_event)
            callbacks = self._subscribers.get(event_type, [])

        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback) or inspect.iscoroutine(callback):
                    await callback(resource_event)
                else:
                    callback(resource_event)
            except Exception as e:
                raise Exception(f"{e}")

    """                                             ###############################
                                                    #       FUNCTIONALITIES       #
                                                    ###############################
    """

    async def init(self):
        await self._get_available_gpu()
        await self.subscribe_resource_event(ReleaseDevicesEvent, self._release_device_used)
        if self._max_ram:
            self._monitor_task = asyncio.create_task(self._monitor_resources())

    async def _get_available_gpu(self):
        if importlib.util.find_spec("pynvml") is not None:
            try:
                import pynvml
                await asyncio.to_thread(pynvml.nvmlInit)
                devices = await asyncio.to_thread(pynvml.nvmlDeviceGetCount)
                self._devices = devices
                self._max_devices_per_user = len(devices)
                await self._update_available_devices(self._devices)
            except Exception: 
                pass

    def _verify_valid_devices(self, devices: List):
        return all(d in self._devices for d in devices)
    
    def _devices_allowed_for_permissions(self, permissions: str):
        if permissions == "admin":
            return self._max_devices_per_user
        else:
            return 1

    async def _remove_available_devices(self, devices: List):
        async with self._available_devices_lock:
            self._available_devices.remove(devices)
            if self._verbose:
                self._logger.info(f"[ResourceManager] -  REMOVE available devices: {devices}")

    async def _update_available_devices(self, devices: List):
        async with self._available_devices_lock:
            self._available_devices.extend(devices)
            if self._verbose:
                self._logger.info(f"[ResourceManager] -  UPDATE available devices: {devices}")

    async def _get_devices(self, n: int):
        async with self._available_devices_lock:
            n_devices = min(n, len(self._available_devices))
            if n_devices > 0:
                devices = random.sample(self._available_devices, n_devices)
                self._available_devices.remove(devices)
            else:
                devices = []
        return devices

    async def assign_device_to_federation(self, federation_id: str, permissions: str):
        n_devices = self._devices_allowed_for_permissions(permissions=permissions)
        devices = await self._get_devices(n_devices)
        async with self._currently_used_devices_lock:
            self.cud[federation_id] = devices
            if self._verbose:
                self._logger.info(f"[ResourceManager] -  ALLOCATED federation ID: {federation_id}, devices: {devices}")
        return devices

    async def _release_device_used(self, rde: ReleaseDevicesEvent):
        federation_id = await rde.get_event_data()
        async with self._currently_used_devices_lock:
            devices = self.cud.pop(federation_id, None)
        if devices:
            await self._update_available_devices(devices)
        else:
            raise Exception(f"Not found devices for federation ID: ({federation_id})")
        
    """                                             ###############################
                                                    #       RESOURCES MONITOR     #
                                                    ###############################
    """
        
    async def _monitor_resources(self):
        while True:
            await asyncio.sleep(self._monitor_cooldown)
            memory_info = await asyncio.to_thread(psutil.virtual_memory)
            if memory_info.percent > self._max_ram:
                asyncio.create_task(self.publish_recource_event(RAMOverusedEvent()))
                if self._verbose:
                    self._logger.info(f"[ResourceManager] -  MONITOR RAM overused detected")

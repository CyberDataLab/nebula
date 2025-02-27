import asyncio
from abc import ABC, abstractmethod
from nebula.core.eventmanager import AddonEvent

class GPSModule(ABC):

    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def stop(self):
        pass
    
    @abstractmethod
    async def is_running(self):
        pass
    
    @abstractmethod
    async def calculate_distance(self, self_lat, self_long, other_lat, other_long):
        pass
   
class GPSEvent(AddonEvent):
    def __init__(self, distances : dict):
        self.distances = distances
    
    def __str__(self):
        return "GPSEvent"    
        
    async def get_event_data(self) -> dict:
        return self.distances.copy()

class GPSModuleException(Exception):
    pass

def factory_gpsmodule(gps_module, config, event_manager, addr, update_interval: float = 5.0, verbose=False) -> GPSModule:
    from nebula.addons.GPS.nebulagps import NebulaGPS
    
    GPS_SERVICES = {
        "nebula": NebulaGPS,
    }
    
    gps_module = GPS_SERVICES.get(gps_module, NebulaGPS)
    
    if gps_module:
        return gps_module(config, event_manager, addr, update_interval, verbose)
    else:
         raise GPSModuleException(f"GPS Module {gps_module} not found")
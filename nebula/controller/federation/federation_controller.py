from abc import ABC, abstractmethod
from typing import Any, Dict
import logging 

EXPERIMENT_TYPES = ["docker", "process"]

class NebulaFederation(ABC):
    pass

class FederationController(ABC):
    
    def __init__(self, hub_url, logger):
        self._logger: logging.Logger = logger
        self._hub_url = hub_url

    @property
    def logger(self):
        return self._logger 

    @abstractmethod
    async def run_scenario(self, federation_id: str, scenario_data: Dict, user: str):
        pass

    @abstractmethod
    async def stop_scenario(self, federation_id: str):
        pass

    @abstractmethod
    async def update_nodes(self, federation_id: str, config: Dict[str, Any]):
        pass
    
    abstractmethod
    async def node_done(self, federation_id: str, idx: int, deployment: str, name: str) -> bool:
        pass
    
    abstractmethod
    async def remove_scenario(self, federation_id: str, experiment_type: str, user: str, scenario_name: str):
        pass
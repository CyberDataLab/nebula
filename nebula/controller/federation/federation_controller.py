from abc import ABC, abstractmethod
from fastapi import Request
from typing import Dict
from nebula.controller.federation.scenario_builder import ScenarioBuilder
import logging 

class FederationController(ABC):
    
    def __init__(self, wa_controller_url, logger):
        self._logger: logging.Logger = logger
        self._wa_url = wa_controller_url
        self._scenario_builder = ScenarioBuilder()
        
    @property
    def sb(self):
        return self._scenario_builder
    
    @property
    def logger(self):
        return self._logger 

    @abstractmethod
    async def run_scenario(self, scenario_data: Dict, role: str, user: str):
        pass

    @abstractmethod
    async def stop_scenario(self, scenario_name: str, username: str, all: bool):
        pass

    @abstractmethod
    async def remove_scenario(self, scenario_name: str):
        pass

    @abstractmethod
    async def update_nodes(self, scenario_name: str, request: Request):
        pass

def federation_controller_factory(mode: str, wa_controller_url: str, logger) -> FederationController:
    from nebula.controller.federation.docker_federation_controller import DockerFederationController
    from nebula.controller.federation.processes_federation_controller import ProcessesFederationController
    from nebula.controller.federation.physicall_federation_controller import PhysicalFederationController
    
    if mode == "docker":
        return DockerFederationController(wa_controller_url, logger)
    elif mode == "physical":
        return PhysicalFederationController(wa_controller_url, logger)
    elif mode == "processes":
        return ProcessesFederationController(wa_controller_url, logger)
    else:
        raise ValueError("Unknown federation mode")
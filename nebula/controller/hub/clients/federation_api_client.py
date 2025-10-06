from pydantic import BaseModel
import nebula.controller.federation.schemas.requests as FedReq
from nebula.controller.federation.schemas.responses import (
    RunScenarioResponse,
    StopScenarioResponse,
    RemoveScenarioResponse,
    ErrorResponse,
)
from nebula.utils import APIUtils
import logging
from typing import Any, Dict, Type

class FederationAPIClient():
    _fed_controller_port = 0
    _fed_controller_host = ""
    _fed_api_url = ""

    def __init__(self, fed_controller_port , fed_controller_host , logger: logging.Logger):
        self._fed_controller_port = fed_controller_port
        self._fed_controller_host = fed_controller_host
        self._fed_api_url = f"http://{fed_controller_host}:{fed_controller_port}"
        self._logger = logger
        
    @property
    def log(self):
        return self._logger
        
    async def _handle_response(self, response: dict, expected_model: Type[BaseModel]):
        """
        Converts JSON response into Pydantic model.
        """
        if "error" in response: 
            return ErrorResponse.model_validate(response)
        else:
            return expected_model.model_validate(response) 
        
    def _parse_error_info(self, err: ErrorResponse):
        return f"Error code: {err.internal_code}\n Error type: {err.error}\n additional info: {err.message}"
    
    async def _post_request(self, endpoint: str, request: BaseModel, expected_model: Type[BaseModel]):
        request_url = self._fed_api_url + endpoint
        try:
            response = await APIUtils.post(request_url, request.model_dump())
        except Exception as e:
            self.log.exception(f"Connection error to {request_url}: {e}")
            return None

        parsed_response = await self._handle_response(response, expected_model)
        if isinstance(parsed_response, ErrorResponse):
            # Just logging but doing nothing on response
            self.log.warning(self._parse_error_info(parsed_response))
            return None

        self.log.info(f"[FederationClient] Received OK from endpoint:{endpoint}")
        return parsed_response.model_dump()   
    
    async def run_scenario(self, user: str, federation_id: str, scenario_data: Dict[str, Any]):
        request = FedReq.RunScenarioRequest(scenario_data=scenario_data, user=user, federation_id=federation_id)
        return await self._post_request(FedReq.factory_requests("run"), request, RunScenarioResponse)
    
    async def stop_scenario(self, experiment_type: str, federation_id: str):
        request = FedReq.StopScenarioRequest(experiment_type=experiment_type, federation_id=federation_id)
        return await self._post_request(FedReq.factory_requests("stop", federation_id=federation_id), request, StopScenarioResponse)

    async def remove_scenario(self, federation_id: str, experiment_type: str, user: str, scenario_name: str):
        request = FedReq.RemoveScenarioRequest(experiment_type=experiment_type, user=user, scenario_name=scenario_name)
        return await self._post_request(FedReq.factory_requests("remove", federation_id=federation_id), request, RemoveScenarioResponse)


    

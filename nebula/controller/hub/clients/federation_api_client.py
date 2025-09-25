import nebula.controller.federation.utils_requests as FedReq
from nebula.utils import APIUtils
import logging
from typing import Any, Dict

class FederationAPIClient():
    _fed_controller_port = 0
    _fed_controller_host = ""
    _fed_api_url = ""

    def __init__(self, fed_controller_port , fed_controller_host , logger: logging.Logger):
        self._fed_controller_port = fed_controller_port
        self._fed_controller_host = fed_controller_host
        self._fed_api_url = f"http://{fed_controller_host}:{fed_controller_port}"
        self._logger = logger

    async def run_scenario(self, user: str, federation_id: str, scenario_data: Dict[str, Any]):
        request_url = self._fed_api_url + FedReq.factory_requests_path("run")
        request = FedReq.RunScenarioRequest(scenario_data=scenario_data, user=user, federation_id=federation_id)
        response = None
        try:
            response = await APIUtils.post(request_url, request.model_dump())
        except Exception as e:
            logging.info(e)
        return response

    async def stop_scenario(self, experiment_type: str, federation_id: str):
        request_url = self._fed_api_url + FedReq.factory_requests_path("stop")
        request = FedReq.StopScenarioRequest(experiment_type=experiment_type, federation_id=federation_id)
        response = None
        try:
            response = await APIUtils.post(request_url, request.model_dump())
        except Exception as e:
            logging.info(e)
        return response

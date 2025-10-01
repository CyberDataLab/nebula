from typing import Type
from nebula.controller.hub.utils_requests import *
from nebula.utils import APIUtils
from nebula.core.utils.locker import Locker
from abc import ABC, abstractmethod

class NebulaObserver(ABC):
    @abstractmethod
    async def node_update_event():
        raise NotImplementedError
    
    @abstractmethod
    async def node_done_event():
        raise NotImplementedError
    
    @abstractmethod
    async def finish_scenario_event():
        raise NotImplementedError

class NebulaClient:
    def __init__(self, hub_url: str):
        self._hub_url = hub_url.rstrip("/")
        self._observers: List[NebulaObserver] = None
        self._observers_lock = Locker("observers_lock", async_lock=True)

    async def set_observer(self, observer: NebulaObserver):
        async with self._observers_lock:
            self._observers.append(observer)
            
    def _build_url(self, resource: str, **kwargs) -> str:
        url = f"http://{self._hub_url}+{factory_requests_path(resource=resource, **kwargs)}"
        return url
    
    async def _post(
        self,
        url: str,
        model_cls: Type[BaseModel] | None = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        try:
            data = payload
            if model_cls is not None:
                data = model_cls(**(payload or {})).model_dump()
            return await APIUtils.post(url, data)
        except Exception as e:
            return None

    """                                                     ###############################
                                                            #         REST METHODS        #
                                                            ###############################
    """
    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------
    
    async def run_scenario(self, user: str, role: str, scenario_data: List[Dict]):
        url_request = self._build_url("run")
        payload = {"scenario_data": scenario_data, "user": user, "role": role}
        response = await self._post(url_request, RunScenarioRequest, payload)
        #TODO filter responses

    async def stop_scenario(self, federation_id: str, experiment_type: str, stop_all: bool = False):
        pass
    
    async def resources_stop_scenario(self, federation_id: str) -> None:
        pass

    async def remove_scenario(self, federation_id: str, request: controller_requests.RemoveScenarioRequest):
        pass

    async def get_scenarios(self, user: str, role: str) -> Any:
        pass

    async def update_scenario(self, federation_id: str, request: controller_requests.UpdateScenarioRequest):
        pass

    async def set_scenario_status_to_finished(self, federation_id: str, stop_all: bool = False):
        pass
    
    async def get_running_scenarios(self, get_all: bool = False) -> Any:
        pass

    async def check_scenario(self, user: str, role: str, federation_id: str):
        pass

    async def get_scenario_by_federation_id(self, federation_id: str):
        pass
    
    async def remove_nodes_by_federation_id(self, federation_id: str):
        pass
    
    async def list_nodes_by_federation_id(self, federation_id: str):
        pass

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    
    async def get_notes_by_federation_id(self, federation_id: str):
        pass

    async def update_note_by_federation_id(self, federation_id: str, notes: str):
        pass

    async def remove_note_by_federation_id(self, federation_id: str):
        pass

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    
    async def list_users(self, all_info: bool = False):
        pass

    async def get_user_by_federation_id(self, federation_id: str):
        pass

    async def add_user(self, user: str, password: str, role: str):
        pass

    async def remove_user(self, user: str):
        pass

    async def update_user(self, user: str, password: str, role: str):
        pass

    async def verify_user(self, user: str, password: str):
        pass

    """                                                     ###############################
                                                            #          WEB SOCKET         #
                                                            ###############################
    """
    
    async def update_node(self, federation_id: str, config: Dict[str, Any]):
        pass
    
    async def node_done(self, federation_id: str, node_idx):
        pass

    # --------------------------
    # WebSocket handling
    # --------------------------
    async def _listen_ws(self):
        try:
            async with websockets.connect(self._ws_url) as ws:
                self._logger.info("WebSocket connected to HUB")
                while not self._stop_ws.is_set():
                    msg = await ws.recv()
                    if self._observer:
                        await self._observer.on_update(msg)
        except Exception as e:
            if self._observer:
                await self._observer.on_error(e)

    def start_listening(self):
        """Levanta una tarea en background para escuchar al HUB."""
        self._stop_ws.clear()
        self._ws_task = asyncio.create_task(self._listen_ws())

    async def stop_listening(self):
        """Detiene la escucha del WebSocket."""
        self._stop_ws.set()
        if self._ws_task:
            await self._ws_task
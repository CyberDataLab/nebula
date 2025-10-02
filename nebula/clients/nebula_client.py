import asyncio
import json
from typing import Type
import websockets
from nebula.controller.hub.utils_requests import *
from nebula.utils import APIUtils
from nebula.core.utils.locker import Locker
from abc import ABC, abstractmethod

"""
KEYPOINTS:
    - User creates an instance of NebulaClient giving the hub_url to communicate to
    - After execute the 'run_scenario' method a persistant connection is created to receive
      update/done/finish using that connection
    - When an event is received all observers are notificated
    - 'close_connection_with_nebula' stops the connection with the service
"""

class NebulaObserver(ABC):
    abstractmethod
    async def on_update(self, event: NodeUpdateRequest): 
        raise NotImplementedError
    abstractmethod
    async def on_done(self, event: NodeDoneRequest): 
        raise NotImplementedError
    abstractmethod
    async def on_finish(self, event: ScenarioFinishEvent):
        raise NotImplementedError 
    @abstractmethod
    async def on_error(self, error: Exception):
        raise NotImplementedError

class NebulaClient:
    def __init__(self, hub_url: str):
        self._hub_url = hub_url
        self._observers: List[NebulaObserver] = None
        self._observers_lock = Locker("observers_lock", async_lock=True)
        self._persistent_connection_task: asyncio.Task = None
        self._persistent_connection_url: str = None
        self._ws = None

    async def set_observer(self, observer: NebulaObserver):
        async with self._observers_lock:
            self._observers.append(observer)
            
    async def remove_observer(self, observer: NebulaObserver):
        async with self._observers_lock:
            self._observers.remove(observer)
            
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
    #                           Scenarios
    # ------------------------------------------------------------------
    
    async def run_scenario(self, user: str, role: str, scenario_data: List[Dict]):
        url_request = self._build_url("run")
        payload = {"scenario_data": scenario_data, "user": user, "role": role}
        response = await self._post(url_request, RunScenarioRequest, payload)
        #TODO filter responses
        #TODO receive persisten connection url on response to open WS
        # self._persistent_connection_url = response.url_ws
        self._persistent_connection_task = asyncio.create_task(self._open_persistent_connection())

    async def stop_scenario(self, federation_id: str, experiment_type: str, stop_all: bool = False):
        url_request = self._build_url("stop", federation_id=federation_id)
        payload = {"experiment_type": experiment_type, "stop_all": stop_all}
        response = await self._post(url_request, StopScenarioRequest, payload)
        #TODO filter responses
    
    async def remove_scenario(self, federation_id: str, user: str, experiment_type: str, scenario_name: str):
        url_request = self._build_url("stop", federation_id=federation_id)
        payload = {"user": user, "experiment_type": experiment_type, "scenario_name": scenario_name}
        response = await self._post(url_request, RemoveScenarioRequest, payload)
        #TODO filter responses

    async def get_scenarios(self, user: str, role: str) -> Any:
        url_request = self._build_url("get_scenarios_by_user", user=user, role=role)
        response = await self._post(url_request)
        #TODO filter responses

    async def get_running_scenarios(self, user: str, role: str, get_all: bool = False):
        url_request = self._build_url("running")
        payload = {"user": user, "role": role, "get_all": get_all}
        response = await self._post(url_request, RunningScenariosRequest, payload)
        #TODO filter responses

    async def check_scenario(self, user: str, role: str, federation_id: str):
        url_request = self._build_url("check_scenario", user=user, role=role, federation_id=federation_id)
        response = await self._post(url_request)
        #TODO filter responses

    async def get_scenario_by_federation_id(self, federation_id: str):
        url_request = self._build_url("get_scenario_by_federation_id", federation_id=federation_id)
        response = await self._post(url_request)
        #TODO filter responses
    
    async def nodes_remove_by_federation_id(self, federation_id: str):
        url_request = self._build_url("nodes_remove", federation_id=federation_id)
        response = await self._post(url_request)
        #TODO filter responses
    
    async def nodes_list_by_federation_id(self, federation_id: str):
        url_request = self._build_url("nodes_list", federation_id=federation_id)
        response = await self._post(url_request)
        #TODO filter responses

    # ------------------------------------------------------------------
    #                           Notes
    # ------------------------------------------------------------------
    
    async def get_notes_by_federation_id(self, federation_id: str):
        url_request = self._build_url("notes_by_federation_id", federation_id=federation_id)
        response = await self._post(url_request)
        #TODO filter responses

    async def update_note_by_federation_id(self, federation_id: str, notes: str):
        url_request = self._build_url("notes_update", federation_id=federation_id)
        response = await self._post(url_request)
        #TODO filter responses

    async def remove_note_by_federation_id(self, federation_id: str):
        url_request = self._build_url("notes_remove", federation_id=federation_id)
        response = await self._post(url_request)
        #TODO filter responses

    # ------------------------------------------------------------------
    #                           Users
    # ------------------------------------------------------------------
    
    async def list_users(self, user:str, role: str, all_info: bool = False):
        url_request = self._build_url("user_list")
        payload = {"user": user, "role": role, "all_info": all_info}
        response = await self._post(url_request, UserListRequest, payload)
        #TODO filter responses

    async def add_user(self, user: str, password: str, role: str):
        url_request = self._build_url("user_list")
        payload = {"user": user, "role": role, "password": password}
        response = await self._post(url_request, AddUserRequest, payload)
        #TODO filter responses

    async def delete_user(self, user: str, role: str, user_to_delete: str):
        url_request = self._build_url("user_delete")
        payload = {"user": user, "role": role, "user_to_delete": user_to_delete}
        response = await self._post(url_request, DeleteUserRequest, payload)
        #TODO filter responsesass

    async def update_user(self, user: str, password: str, role: str):
        url_request = self._build_url("user_update")
        payload = {"user": user, "role": role, "password": password}
        response = await self._post(url_request, UpdateUserRequest, payload)
        #TODO filter responses

    async def verify_user(self, user: str, password: str):
        url_request = self._build_url("user_verify")
        payload = {"user": user, "password": password}
        response = await self._post(url_request, VerifyUserRequest, payload)
        #TODO filter responses

    """                                                     ###############################
                                                            #          WEB SOCKET         #
                                                            ###############################
    """
    # ------------------------------------------------------------------
    #                       WebSocket handling
    # ------------------------------------------------------------------
    
    def _parse_message(self, raw_msg):
        envelope = WSMessage.model_validate_json(raw_msg)
        model_cls = EVENT_MAP.get(envelope.type, None)
        if not model_cls:
            raise ValueError(f"Unknown message type {envelope.type}")
        event = model_cls.model_validate(envelope.payload)
        return (envelope.type, event)
    
    async def _dispatch_event(self, event_type: str, event: BaseModel):
        observers_snapshot = []
        async with self._observers_lock:
            if self._observers:
                observers_snapshot = list(self._observers)
                
        for observer in observers_snapshot:
            # Task vs await cause of high concurrency.
            # done/finish are critical events
            if event_type == "update":
                asyncio.create_task(observer.on_update(event))
            elif event_type == "done":
                await observer.on_done(event)
            else:
                await observer.on_finish(event)
    
    async def _open_persistent_connection(self):
        try:
            async with websockets.connect(self._persistent_connection_url) as ws:
                self._ws = ws
                while True:
                    raw_msg = await ws.recv()
                    e_type, event = self._parse_message(raw_msg=raw_msg)
                    await self._dispatch_event(event_type=e_type, event=event)
        except asyncio.CancelledError:
            try:
                await self._ws.close(code=1000, reason="Client requested shutdown")
            except Exception:
                pass
            # Expected closing
            raise
        except Exception as e:
            async with self._observers_lock:
                for observer in self._observers:
                    asyncio.create_task(observer.on_error(e))
    
    async def close_connection_with_nebula(self):
        if self._persistent_connection_task and not self._persistent_connection_task.done():
            try:
                # HUB notification of disconnection
                if self._ws and self._ws.open:
                    await self._ws.send(json.dumps({"type": "disconnect"}))
                # Task cancellation
                self._persistent_connection_task.cancel()
                await self._persistent_connection_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                pass
 
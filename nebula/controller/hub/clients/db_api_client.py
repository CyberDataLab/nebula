import logging
from typing import Any, Dict, Optional, Type

import nebula.database.schemas.requests as DBReq
from nebula.utils import APIUtils
from pydantic import BaseModel


class DatabaseAPIClient:
    """Async HTTP client used to interact with the Database API."""

    def __init__(
        self,
        db_port: str | int,
        db_host: str,
        logger: logging.Logger | None,
    ) -> None:
        """Configure the database API endpoint."""
        self._db_port = str(db_port)
        self._db_host = db_host
        self._db_api_url = f"http://{db_host}:{self._db_port}"
        self._logger = logger

    def _ensure_initialized(self) -> None:
        if not self._db_api_url:
            raise RuntimeError("DatabaseAPIClient not initialized")

    def _build_url(self, path: str) -> str:
        self._ensure_initialized()
        return f"{self._db_api_url}{path}"

    async def _post(
        self,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        model_cls: Type[BaseModel] | None = None,
    ) -> Any:
        try:
            data = payload
            if model_cls is not None:
                data = model_cls(**(payload or {})).model_dump()
            return await APIUtils.post(url, data)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def _get(
        self,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        model_cls: Type[BaseModel] | None = None,
    ) -> Any:
        try:
            params = payload
            if model_cls is not None:
                params = model_cls(**(payload or {})).model_dump()
            return await APIUtils.get(url, params)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def read_root(self) -> Any:
        url = self._build_url(DBReq.factory_requests_path("init"))
        try:
            return await APIUtils.get(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def save_scenario(self, federation_id: str, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("save", federation_id=federation_id)
        url = self._build_url(path)
        return await self._post(url, payload, DBReq.SaveScenarioRequest)

    async def stop_scenario(self, federation_id: str, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("stop", federation_id=federation_id)
        url = self._build_url(path)
        return await self._post(url, payload, DBReq.StopScenarioRequest)

    async def remove_scenario(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path("remove", federation_id=federation_id)
        url = self._build_url(path)
        return await self._post(url)

    async def get_scenarios_by_user(self, user: str, role: str) -> Any:
        path = DBReq.factory_requests_path("get_scenarios_by_user", user=user, role=role)
        url = self._build_url(path)
        return await self._get(url)

    async def finish_scenario(self, federation_id: str, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("finish", federation_id=federation_id)
        url = self._build_url(path)
        return await self._post(url, payload, DBReq.FinishScenarioRequest)

    async def get_running_scenarios(self, get_all: bool = False) -> Any:
        path = DBReq.factory_requests_path("running")
        url = self._build_url(path)
        payload = {"get_all": get_all}
        return await self._get(url, payload, DBReq.GetRunningScenarioRequest)

    async def check_scenario(self, user: str, role: str, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "check_scenario", user=user, role=role, federation_id=federation_id
        )
        url = self._build_url(path)
        return await self._get(url)

    async def get_scenario_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "get_scenarios_by_scenario_name", federation_id=federation_id
        )
        url = self._build_url(path)
        return await self._get(url)

    async def list_nodes_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "get_nodes_by_scenario_name", federation_id=federation_id
        )
        url = self._build_url(path)
        return await self._get(url)

    async def update_node(self, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("update_nodes")
        url = self._build_url(path)
        return await self._post(url, payload, DBReq.UpdateNodesRequest)

    async def remove_nodes_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path("remove_nodes", federation_id=federation_id)
        url = self._build_url(path)
        return await self._post(url)

    async def get_notes_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "get_notes_by_scenario_name", federation_id=federation_id
        )
        url = self._build_url(path)
        return await self._get(url)

    async def update_notes_by_federation_id(self, federation_id: str, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path(
            "update_notes", federation_id=federation_id
        )
        url = self._build_url(path)
        return await self._post(url, payload, DBReq.UpdateNotesRequest)

    async def remove_notes_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "remove_notes", federation_id=federation_id
        )
        url = self._build_url(path)
        return await self._post(url)

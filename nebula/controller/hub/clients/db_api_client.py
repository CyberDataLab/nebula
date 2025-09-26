import logging
from typing import Any, Dict, Optional

import nebula.database.utils_requests as DBReq
from nebula.utils import APIUtils


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

    async def read_root(self) -> Any:
        url = self._build_url(DBReq.factory_requests_path("init"))
        try:
            return await APIUtils.get(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def update_scenario(self, federation_id: str, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("update", federation_id=federation_id)
        url = self._build_url(path)
        try:
            request = DBReq.UpdateScenarioRequest(**payload)
            return await APIUtils.post(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def stop_scenario(self, federation_id: str, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("stop", federation_id=federation_id)
        url = self._build_url(path)
        try:
            request = DBReq.StopScenarioRequest(**payload)
            return await APIUtils.post(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def remove_scenario(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path("remove", federation_id=federation_id)
        url = self._build_url(path)
        try:
            return await APIUtils.post(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def get_scenarios_by_user(self, user: str, role: str) -> Any:
        path = DBReq.factory_requests_path("get_scenarios_by_user", user=user, role=role)
        url = self._build_url(path)
        try:
            return await APIUtils.get(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def finish_scenario(self, federation_id: str, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("finish", federation_id=federation_id)
        url = self._build_url(path)
        try:
            request = DBReq.FinishScenarioRequest(**payload)
            return await APIUtils.post(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def get_running_scenarios(self, get_all: bool = False) -> Any:
        path = DBReq.factory_requests_path("running")
        url = self._build_url(path)
        try:
            request = DBReq.GetRunningScenarioRequest(get_all=get_all)
            return await APIUtils.get(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def check_scenario(self, user: str, role: str, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "check_scenario", user=user, role=role, federation_id=federation_id
        )
        url = self._build_url(path)
        try:
            return await APIUtils.get(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def get_scenario_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "get_scenarios_by_scenario_name", federation_id=federation_id
        )
        url = self._build_url(path)
        try:
            return await APIUtils.get(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def list_nodes_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "get_nodes_by_scenario_name", federation_id=federation_id
        )
        url = self._build_url(path)
        try:
            return await APIUtils.get(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def update_node(self, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("update_nodes")
        url = self._build_url(path)
        try:
            request = DBReq.UpdateNodesRequest(**payload)
            return await APIUtils.post(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def remove_nodes_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path("remove_nodes", federation_id=federation_id)
        url = self._build_url(path)
        try:
            return await APIUtils.post(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def get_notes_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "get_notes_by_scenario_name", federation_id=federation_id
        )
        url = self._build_url(path)
        try:
            return await APIUtils.get(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def update_notes_by_federation_id(self, federation_id: str, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path(
            "update_notes", federation_id=federation_id
        )
        url = self._build_url(path)
        try:
            request = DBReq.UpdateNotesRequest(**payload)
            return await APIUtils.post(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def remove_notes_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "remove_notes", federation_id=federation_id
        )
        url = self._build_url(path)
        try:
            return await APIUtils.post(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def list_users(self, all_info: bool = False) -> Any:
        path = DBReq.factory_requests_path("list_users")
        url = self._build_url(path)
        try:
            request = DBReq.ListUsersRequest(all_info=all_info)
            return await APIUtils.get(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def get_user_by_federation_id(self, federation_id: str) -> Any:
        path = DBReq.factory_requests_path(
            "get_user_by_scenario_name", federation_id=federation_id
        )
        url = self._build_url(path)
        try:
            return await APIUtils.get(url)
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def add_user(self, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("add_user")
        url = self._build_url(path)
        try:
            request = DBReq.AddUserRequest(**payload)
            return await APIUtils.post(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def delete_user(self, user: str) -> Any:
        path = DBReq.factory_requests_path("delete_user")
        url = self._build_url(path)
        try:
            request = DBReq.DeleteUserRequest(user=user)
            return await APIUtils.post(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def update_user(self, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("update_user")
        url = self._build_url(path)
        try:
            request = DBReq.UpdateUserRequest(**payload)
            return await APIUtils.post(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

    async def verify_user(self, payload: Dict[str, Any]) -> Any:
        path = DBReq.factory_requests_path("verify_user")
        url = self._build_url(path)
        try:
            request = DBReq.VerifyUserRequest(**payload)
            return await APIUtils.post(url, request.model_dump())
        except Exception as exc:
            self._logger.info(exc)
            return None

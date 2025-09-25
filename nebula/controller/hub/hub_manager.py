import asyncio
from datetime import datetime
import json
import logging
import os
from typing import Any, Dict, Optional

import aiohttp
from fastapi import HTTPException, Request, UploadFile, status

from nebula.controller.http_helpers import remote_get, remote_post_form
from nebula.controller.hub.clients.db_api_client import DatabaseAPIClient
from nebula.controller.hub.clients.federation_api_client import FederationAPIClient
from nebula.utils import APIUtils, HashUtils
import nebula.controller.hub.utils_requests as controller_requests

class HubManager:
    """Encapsulates the controller business logic so the API layer stays thin."""

    def __init__(self, logger: logging.Logger = None):
        self.database_api_url = os.environ.get(
            "NEBULA_DATABASE_API_URL", "http://nebula-database:5051"
        )
        self.database_client = DatabaseAPIClient(
            db_port=os.environ.get("NEBULA_DATABASE_API_PORT", 5051),
            db_host=os.environ.get("NEBULA_DATABASE_API_HOST", "nebula-database"),
            logger=logger
        )
        self.federation_client = FederationAPIClient(
            fed_controller_port = os.environ.get("NEBULA_FEDERATION_CONTROLLER_PORT"),
            fed_controller_host = os.environ.get("NEBULA_CONTROLLER_HOST"),
            logger=logger
        )
        self.logger = logger

    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------
    async def run_scenario(self, run_scenario_request: controller_requests.RunScenarioRequest):
        """
        Launches a new scenario based on the provided configuration.

        Args:
            scenario_data (dict): The complete configuration of the scenario to be executed.
            role (str): The role of the user initiating the scenario.
            user (str): The username of the user initiating the scenario.

        Returns:
            str: The name of the scenario that was started.
        """
        try:
            federation_id = HashUtils.generate_md5(f"nebula_{run_scenario_request.user}_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}")
            response = await self.federation_client.run_scenario(
                user=run_scenario_request.user,
                federation_id=federation_id,
                scenario_data=run_scenario_request.scenario_data,
            )
            if response:
                await self.database_client.update_scenario(
                    federation_id,
                    {
                        "alias": response["alias"],
                        "scenario_name": response["scenario_name"],
                        "start_time": response["start_time"],
                        "end_time": "",
                        "scenario": run_scenario_request.scenario_data,
                        "status": "running",
                        "username":run_scenario_request.user,
                    },
                )
                return {"federation_id": federation_id}
            else:
                raise HTTPException(status_code=500, detail="Error starting scenario")
        except Exception as e:
            logging.info(e)

    async def stop_scenario(self, federation_id: str, stop_all: bool = False) -> None: #TODO stop_all with queues
        try:
            response = await self.federation_client.stop_scenario(
                experiment_type="all" if stop_all else "nebula",
                federation_id=federation_id,
            )
            if response:
                await self.database_client.stop_scenario(
                    federation_id,
                    {"all": stop_all},
                )
            else:
                raise HTTPException(status_code=500, detail="Error stopping scenario")
        except Exception as exc:
            self.logger.exception(
                "Error stopping scenario %s: %s", federation_id, exc
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def remove_scenario(
        self,
        federation_id: str,
        request: controller_requests.RemoveScenarioRequest,
    ) -> Dict[str, Any]: #TODO remove_scenario with fed_client
        try:
            await self.database_client.remove_scenario(federation_id)
            # ScenarioManagement.remove_files_by_scenario(request.scenario_name)
        except Exception as exc:
            self.logger.exception(
                "Error removing scenario %s (%s): %s",
                request.scenario_name,
                federation_id,
                exc,
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def get_scenarios(self, user: str, role: str) -> Any:
        try:
            return await self.database_client.get_scenarios_by_user(user, role)
        except Exception as exc:
            self.logger.exception("Error obtaining scenarios: %s", exc)
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def update_scenario(
        self,
        federation_id: str,
        request: controller_requests.UpdateScenarioRequest,
    ) -> Any:
        try:
            return await self.database_client.update_scenario(federation_id, request.model_dump())
        except Exception as exc:
            self.logger.exception(
                "Error updating scenario %s (%s): %s",
                request.scenario_name,
                federation_id,
                exc,
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def set_scenario_status_to_finished(
        self, federation_id: str, stop_all: bool = False
    ) -> Any:
        try:
            return await self.database_client.finish_scenario(federation_id, {"all": stop_all})
        except Exception as exc:
            self.logger.exception(
                "Error setting scenario %s to finished: %s", federation_id, exc
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def get_running_scenarios(self, get_all: bool = False) -> Any:
        try:
            return await self.database_client.get_running_scenarios(get_all)
        except Exception as exc:
            self.logger.exception("Error obtaining running scenarios: %s", exc)
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def check_scenario(self, user: str, role: str, federation_id: str) -> Any:
        try:
            return await self.database_client.check_scenario(user, role, federation_id)
        except Exception as exc:
            self.logger.exception("Error checking scenario with role: %s", exc)
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def get_scenario_by_federation_id(self, federation_id: str) -> Any:
        try:
            return await self.database_client.get_scenario_by_federation_id(federation_id)
        except Exception as exc:
            self.logger.exception(
                "Error obtaining scenario %s: %s", federation_id, exc
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    async def list_nodes_by_federation_id(self, federation_id: str) -> Any:
        try:
            return await self.database_client.list_nodes_by_federation_id(federation_id)
        except Exception as exc:
            self.logger.exception(
                "Error obtaining nodes for %s: %s", federation_id, exc
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def update_node(self, federation_id: str, request: Request) -> Any:
        try:
            config: Dict[str, Any] = await request.json()
            config["timestamp"] = str(datetime.now())

            mobility_args = config.get("mobility_args")
            if not mobility_args:
                config["mobility_args"] = {"latitude": "38.0235", "longitude": "-1.1744"}

            validated = controller_requests.UpdateNodesRequest(**config)

            payload = validated.model_dump()
            payload["extras"] = payload.get("mobility_args", {})
            payload.setdefault("scenario_args", {})
            payload["scenario_args"]["federation"] = federation_id

            return await self.database_client.update_node(federation_id, payload)
        except Exception as exc:
            self.logger.exception("Error updating nodes: %s", exc)
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def node_done(self, scenario_name: str, request: Request) -> Any: # TODO redo for the frontend
        url = (
            f"http://{os.environ['NEBULA_ENV_TAG']}_{os.environ['NEBULA_PREFIX_TAG']}_{os.environ['NEBULA_USER_TAG']}_"
            f"nebula-frontend/platform/dashboard/{scenario_name}/node/done"
        )

        data = await request.json()
        return await APIUtils.post(url, data=data)

    async def remove_nodes_by_federation_id(self, federation_id: str) -> Dict[str, Any]:
        try:
            await self.database_client.remove_nodes_by_federation_id(federation_id)
        except Exception as exc:
            self.logger.exception("Error removing nodes: %s", exc)
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    async def get_notes_by_federation_id(self, federation_id: str) -> Any:
        try:
            return await self.database_client.get_notes_by_federation_id(federation_id)
        except Exception as exc:
            self.logger.exception(
                "Error obtaining notes for %s: %s", federation_id, exc
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def update_note_by_federation_id(self, federation_id: str, notes: str) -> Any:
        try:
            return await self.database_client.update_notes_by_federation_id(federation_id, notes)
        except Exception as exc:
            self.logger.exception(
                "Error updating notes for %s: %s", federation_id, exc
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def remove_note_by_federation_id(self, federation_id: str) -> Dict[str, Any]:
        try:
            return await self.database_client.remove_notes_by_federation_id(federation_id)
        except Exception as exc:
            self.logger.exception(
                "Error removing notes for %s: %s", federation_id, exc
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    async def list_users(self, all_info: bool = False) -> Any:
        try:
            return await self.database_client.list_users(all_info)
        except Exception as exc:
            self.logger.exception("Error retrieving users: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error retrieving users: {exc}",
            ) from exc

    async def get_user_by_federation_id(self, federation_id: str) -> Any:
        try:
            return await self.database_client.get_user_by_federation_id(federation_id)
        except Exception as exc:
            self.logger.exception(
                "Error obtaining user for %s: %s", federation_id, exc
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def add_user(self, user: str, password: str, role: str) -> Any:
        try:
            return await self.database_client.add_user(user, password, role)
        except Exception as exc:
            self.logger.exception("Error adding user: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error adding user: {exc}",
            ) from exc

    async def remove_user(self, user: str) -> Any:
        try:
            return await self.database_client.delete_user(user)
        except Exception as exc:
            self.logger.exception("Error deleting user: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting user: {exc}",
            ) from exc

    async def update_user(self, user: str, password: str, role: str) -> Any:
        try:
            return await self.database_client.update_user(user, password, role)
        except Exception as exc:
            self.logger.exception("Error updating user: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error updating user: {exc}",
            ) from exc

    async def verify_user(self, user: str, password: str) -> Any:
        try:
            return await self.database_client.verify_user(user, password)
        except HTTPException as exc:
            if exc.status_code == 401:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc
            self.logger.exception("Error verifying user: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error verifying user: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Discovery / Physical management
    # ------------------------------------------------------------------
    async def discover_vpn(self) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "tailscale",
                "status",
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            out, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(err.decode())

            data = json.loads(out.decode())

            ips = []
            for peer in data.get("Peer", {}).values():
                for ip in peer.get("TailscaleIPs", []):
                    if ":" not in ip:
                        ips.append(ip)

            return {"ips": ips}
        except Exception as exc:
            self.logger.error("Error discovering VPN devices: %s", exc)
            raise HTTPException(status_code=500, detail="No devices discovered") from exc

    async def physical_run(self, ip: str) -> Any:
        status_code, data = await remote_get(ip, "/run/")

        if status_code == 200:
            return data
        if status_code is None:
            raise HTTPException(status_code=502, detail=f"Node unreachable: {data}")
        raise HTTPException(status_code=status_code, detail=data)

    async def physical_stop(self, ip: str) -> Any:
        status_code, data = await remote_get(ip, "/stop/")

        if status_code == 200:
            return data
        if status_code is None:
            raise HTTPException(status_code=502, detail=f"Node unreachable: {data}")
        raise HTTPException(status_code=status_code, detail=data)

    async def physical_setup(
        self,
        ip: str,
        config: UploadFile,
        global_test: UploadFile,
        train_set: UploadFile,
    ) -> Any:
        form = aiohttp.FormData()
        await config.seek(0)
        form.add_field(
            "config",
            config.file,
            filename=config.filename,
            content_type="application/json",
        )
        await global_test.seek(0)
        form.add_field(
            "global_test",
            global_test.file,
            filename=global_test.filename,
            content_type="application/octet-stream",
        )
        await train_set.seek(0)
        form.add_field(
            "train_set",
            train_set.file,
            filename=train_set.filename,
            content_type="application/octet-stream",
        )

        status_code, data = await remote_post_form(
            ip, "/setup/", form, method="PUT"
        )

        if status_code == 201:
            return data
        if status_code is None:
            raise HTTPException(status_code=502, detail=f"Node unreachable: {data}")
        raise HTTPException(status_code=status_code, detail=data)

    async def get_physical_node_state(self, ip: str) -> Dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=3)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"http://{ip}/state/") as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return {"running": False, "error": f"HTTP {resp.status}"}
        except Exception as exc:
            return {"running": False, "error": str(exc)}

    async def get_physical_scenario_state(
        self, federation_id: str
    ) -> Dict[str, Any]:
        scenario = await self.get_scenario_by_federation_id(federation_id)
        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario not found")

        nodes = await self.list_nodes_by_federation_id(federation_id)
        if not nodes:
            raise HTTPException(status_code=404, detail="No nodes found for scenario")

        ips = [node["ip"] for node in nodes]
        tasks = [self.get_physical_node_state(ip) for ip in ips]
        states = await asyncio.gather(*tasks)

        nodes_state = dict(zip(ips, states))
        any_running = any(state.get("running") for state in states)
        all_available = all(
            (not state.get("running")) and (not state.get("error")) for state in states
        )

        return {
            "running": any_running,
            "nodes_state": nodes_state,
            "all_available": all_available,
        }


# Singleton used by the API layer
hub_manager = HubManager()

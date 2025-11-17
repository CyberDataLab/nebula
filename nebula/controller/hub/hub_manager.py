import asyncio
from datetime import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional
import aiohttp
from fastapi import HTTPException, Request, UploadFile, WebSocket, status
from nebula.controller.http_helpers import remote_get, remote_post_form
from nebula.auth.api import AuthenticatedUser
from nebula.auth.policy import (
    actor_username,
    actor_role,
    can_impersonate,
    resolve_username,
)
from nebula.controller.hub.clients.auth_client import AuthClient, build_auth_client
from nebula.controller.hub.clients.db_api_client import DatabaseAPIClient
from nebula.controller.hub.clients.federation_api_client import FederationAPIClient
from nebula.controller.hub.scenario_queue_manager import ScenarioQueueManager
from nebula.utils import APIUtils, HashUtils, TermEscapeCodeFormatter
import nebula.controller.hub.utils_requests as hub_requests
from nebula.controller.hub.real_time_manager import RealTimeManager
from nebula.kafka.clients.admin_client import NebulaKafkaAdmin

class HubManager:
    """Encapsulates the controller business logic so the API layer stays thin."""

    def __init__(self):
        manager_log = os.environ.get("NEBULA_HUB_LOG")
        TermEscapeCodeFormatter.configure_logger(manager_log)
        self.logger = logging.getLogger("Hub-Manager")
        self.logger.setLevel(logging.INFO)

        self.database_client = DatabaseAPIClient(
            db_port=os.environ.get("NEBULA_DATABASE_PORT"),
            db_host=os.environ.get("NEBULA_DATABASE_HOST"),
            logger=self.logger
        )
        self.federation_client = FederationAPIClient(
            fed_controller_port = os.environ.get("NEBULA_FEDERATION_CONTROLLER_PORT"),
            fed_controller_host = os.environ.get("NEBULA_CONTROLLER_HOST"),
            logger=self.logger
        )

        self._scenario_qeue_manager = ScenarioQueueManager(self.logger)
        self._real_time_manager = RealTimeManager(self.logger)
        self._kafka_admin_client = NebulaKafkaAdmin(user=os.environ.get("KAFKA_SUPER_USER_NAME"), password=os.environ.get("KAFKA_SUPER_USER_PASS"), broker=os.environ.get("KAFKA_BROKER"), client_id="hub", logger=self.logger)
        self._auth_client: AuthClient = build_auth_client()

    @property
    def sqm(self):
        """Scenario Qeue Manager instance"""
        return self._scenario_qeue_manager

    @property
    def rtm(self):
        """Real Time Manager instance"""
        return self._real_time_manager

    @property
    def kac(self):
        """Kafka Admin Client"""
        return self._kafka_admin_client

    def _generate_federation_ids(self, user: str, scenario_datas: List) -> List[str]:
        federation_ids = []
        for i, sd in enumerate(scenario_datas):
            id = HashUtils.generate_md5(f"nebula_{user}_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}_{i}")    # Add index to hash
            federation_ids.append(id)
        return federation_ids

    async def init(self):
        # Delay to let ensure Kafka server is ready
        await asyncio.sleep(10)

        # Configure Kafka setup using admin client
        await self.kac.init()

    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------
    async def run_scenario(self, actor: AuthenticatedUser, scenario_data, request: Request):
        """
        Launches a new scenario based on the provided configuration.

        Args:
            scenario_data (dict): The complete configuration of the scenario to be executed.
            actor (AuthenticatedUser): The authenticated user initiating the scenario.

        Returns:
            str: The name of the scenario that was started.
        """
        user_host = request.client.host
        user_port = request.client.port
        user_dest = f"{user_host}:{user_port}"
        username = actor_username(actor)
        role = actor_role(actor)
        scenario_payload = dict(scenario_data)

        try:
            hkc = NebulaKafkaAdmin(user=os.environ.get("KAFKA_SUPER_USER_NAME"), password=os.environ.get("KAFKA_SUPER_USER_PASS"), broker=os.environ.get("KAFKA_BROKER"), client_id="hub", logger=self.logger)
            await hkc.init()

            # # Generate IDs for all scenarios
            # federation_ids = self._generate_federation_ids(user, [scenario_data])

            # # Save scenarios on User Scenario Qeue
            # await self.sqm.add_scenarios(user, user_dest, federation_ids, [scenario_data])

            # # Get first scenario to execute
            # _, federation_id, scenario_data = await self.sqm.get_next_scenario(user=user)

            # #TODO modify to use role on query
            # response = await self.federation_client.run_scenario(
            #     user=user,
            #     #role=role,
            #     federation_id=federation_id,
            #     scenario_data=scenario_data,
            # )
            # if response:
            #     await self.database_client.save_scenario(
            #         federation_id,
            #         {
            #             "alias": response["alias"],
            #             "scenario_name": response["scenario_name"],
            #             "start_time": response["start_time"],
            #             "end_time": "",
            #             "scenario": scenario_data,
            #             "status": "running",
            #             "username":user,
            #         },
            #     )
            #     return {"federation_id": federation_id}
            # else:
            #     raise HTTPException(status_code=500, detail="Error starting scenario")
        except Exception as e:
            self.logger.exception(f"Error running scenario for user '{user}\n{e}'")

    async def stop_scenario(self, federation_id: str, experiment_type: str, stop_all: bool = False) -> None: #TODO stop_all with queues
        try:
            response = await self.federation_client.stop_scenario(
                experiment_type=experiment_type,
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

    async def resources_stop_scenario(self, federation_id: str) -> None:
        try:
            await self.database_client.stop_scenario(
                federation_id,
                {"all": False},
            )
            #TODO notify frontend
        except Exception as exc:
            self.logger.exception(
                f"Error stopping scenario {federation_id}"
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def remove_scenario(
        self,
        federation_id: str,
        request: hub_requests.RemoveScenarioRequest,
    ) -> Dict[str, Any]:
        try:
            await self.federation_client.remove_scenario(federation_id, request.experiment_type, request.user, request.scenario_name)
            await self.database_client.remove_scenario(federation_id)
        except Exception as exc:
            self.logger.exception(
                "Error removing scenario %s (%s): %s",
                request.scenario_name,
                federation_id,
                exc,
            )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def get_scenarios(self, actor: AuthenticatedUser, requested_user: str) -> Any:
        try:
            # Trace request vs token identity for auditing
            self.logger.info(
                "actor_roles=%s requested_user=%s",
                ",".join(sorted(actor.roles)) or "none",
                (requested_user or "").upper(),
            )
            role = actor_role(actor)
            username = resolve_username(actor, requested_user)
            return await self.database_client.get_scenarios_by_user(username, role)
        except Exception as exc:
            self.logger.exception("Error obtaining scenarios: %s", exc)
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def update_scenario(
        self,
        federation_id: str,
        request: hub_requests.UpdateScenarioRequest,
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

    async def check_scenario(self, actor: AuthenticatedUser, requested_user: str, federation_id: str) -> Any:
        try:
            self.logger.info(
                "actor_roles=%s requested_user=%s",
                ",".join(sorted(actor.roles)) or "none",
                (requested_user or "").upper(),
            )
            role = actor_role(actor)
            username = resolve_username(actor, requested_user)
            return await self.database_client.check_scenario(username, role, federation_id)
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

    #TODO CORE -> FEderationController -> HUB -> USUARIO CONCRETO
    async def update_node(self, federation_id: str, config: Dict[str, Any]) -> Any:
        #TODO command para decidir si quieres recibir o no las updates de los nodos (pensando en el uso por terminal)
        try:
            data = {
                "device_args": config.get("device_args", {}),
                "network_args": config.get("network_args", {}),
                "mobility_args": config.get("mobility_args", {"latitude": 38.0235, "longitude": -1.1744}),
                "federation_args": config.get("federation_args", {}),
                "scenario_args": config.get("scenario_args", {}),
                "timestamp": config.get("timestamp", str(datetime.now())),
            }

            await self.database_client.update_node(data)

            #TODO push node update to user
            user_dest = await self.sqm.get_user_destination(federation_id)

        except KeyError as e:
            # Missing critical keys in the JSON
            self.logger.exception("Missing required key in config: %s", e)
            raise HTTPException(status_code=422, detail=f"Missing required key in config: {e}") from e
        except Exception as exc:
            self.logger.exception("Error updating nodes: %s", exc)
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def node_done(self, federation_id: str, node_idx) -> Any: # TODO redo for the frontend

        user_dest = await self.sqm.get_user_destination(federation_id)
        #TODO push node done to user

        # url = (
        #     f"http://{os.environ['NEBULA_ENV_TAG']}_{os.environ['NEBULA_PREFIX_TAG']}_{os.environ['NEBULA_USER_TAG']}_"
        #     f"nebula-frontend/platform/dashboard/{scenario_name}/node/done"
        # )

        # data = await request.json()
        # return await APIUtils.post(url, data=data)

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
            return await self.database_client.update_notes_by_federation_id(federation_id, {"notes": notes})
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
    # Authentication
    # ------------------------------------------------------------------
    async def login(self, request: hub_requests.LoginRequest) -> Dict[str, Any]:
        if request.grant_type == "password":
            if not request.username or not request.password:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="username and password must be provided for password grant",
                )
        elif request.grant_type == "refresh_token":
            if not request.refresh_token:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="refresh_token must be provided for refresh_token grant",
                )
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported grant type '{request.grant_type}'",
            )

        try:
            return await self._auth_client.obtain_token(
                grant_type=request.grant_type,
                username=request.username,
                password=request.password,
                refresh_token=request.refresh_token,
                client_id=request.client_id,
                client_secret=request.client_secret,
                scope=request.scope,
                auth_url=request.auth_url,
                realm=request.realm,
            )
        except HTTPException:
            raise
        except Exception as exc:
            self.logger.exception("Unexpected error during Keycloak login flow: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to obtain token from Keycloak.",
            ) from exc

    async def logout(self, request: hub_requests.LogoutRequest) -> Dict[str, Any]:
        try:
            return await self._auth_client.logout(
                refresh_token=request.refresh_token,
                client_id=request.client_id,
                client_secret=request.client_secret,
                auth_url=request.auth_url,
                realm=request.realm,
            )
        except HTTPException:
            raise
        except Exception as exc:
            self.logger.exception("Unexpected error during Keycloak logout flow: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to revoke token with Keycloak.",
            ) from exc

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    async def list_users(self, actor: AuthenticatedUser, all_info: bool = False) -> Dict[str, Any]:
        if not can_impersonate(actor):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Only administrators can list users.",
            )
        try:
            users = await self._auth_client.list_users(actor, all_info=all_info)
        except HTTPException:
            raise
        except Exception as exc:
            self.logger.exception("Error listing users: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to list users from the identity provider.",
            ) from exc
        return {"users": users}

    async def add_user(self, actor: AuthenticatedUser, user: str, password: str, role: str) -> Any:
        if not can_impersonate(actor):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Only administrators can create users.",
            )
        if not user or not password or not role:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="user, password and role are required.",
            )

        try:
            return await self._auth_client.register_user(actor, user, password, role)
        except HTTPException:
            raise
        except Exception as exc:
            self.logger.exception("Error registering user %s: %s", user, exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to register user with the identity provider.",
            ) from exc

    async def remove_user(self, actor: AuthenticatedUser, user: str) -> Any:
        if not can_impersonate(actor):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Only administrators can delete users.",
            )
        if not user:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="user is required.")
        try:
            return await self._auth_client.delete_user(actor, user)
        except HTTPException:
            raise
        except Exception as exc:
            self.logger.exception("Error deleting user %s: %s", user, exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to delete user with the identity provider.",
            ) from exc

    async def update_user(self, actor: AuthenticatedUser, user: str, password: str, role: str) -> Any:
        if not can_impersonate(actor):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Only administrators can update users.",
            )
        if not user:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="user is required.")

        try:
            return await self._auth_client.update_user(actor, user, password, role)
        except HTTPException:
            raise
        except Exception as exc:
            self.logger.exception("Error updating user %s: %s", user, exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to update user with the identity provider.",
            ) from exc

    async def verify_user(self, user: str, password: str) -> Any:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Password verification is handled by Keycloak. Use its token endpoints.",
        )

    async def open_real_time_client(self, websocket: WebSocket, channel_id: str):
        token = websocket.query_params.get("token")
        if not token:
            authorization = websocket.headers.get("authorization")
            if authorization and authorization.lower().startswith("bearer "):
                token = authorization.split(" ", 1)[1].strip()

        if not token:
            await websocket.close(code=4401, reason="Missing bearer token")
            return

        try:
            await self._auth_client.authenticate(token)
        except HTTPException as exc:
            await websocket.close(code=4003, reason=exc.detail)
            return

        await self.rtm.open_real_time_client(websocket, channel_id)

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

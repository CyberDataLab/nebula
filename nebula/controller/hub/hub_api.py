import argparse
import asyncio
import logging

import uvicorn
from fastapi import Body, Depends, FastAPI, File, Request, UploadFile, WebSocket, status
from fastapi.concurrency import asynccontextmanager

import nebula.controller.hub.utils_requests as hub_requests
from nebula.auth.api import AuthenticatedUser, get_current_user
from nebula.controller.hub.hub_manager import HubManager

hub_manager = HubManager()
logger = logging.getLogger("Hub-API")
logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    - Configures logging on startup.
    """
    global hub_manager
    logger.info("DEBUG: Lifespan startup - initializing HubManager")
    asyncio.create_task(hub_manager.init())

    # Code to run on startup
    yield

    # Code to run on shutdown
    pass


# Initialize FastAPI app outside the Controller class
app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def log_request_headers(request: Request, call_next):
    """
    Log every incoming HTTP request, including headers, so operators can
    inspect the authentication tokens being sent to the hub API.
    """
    client = f"{request.client.host}:{request.client.port}" if request.client else "unknown"
    headers_snapshot = {key: value for key, value in request.headers.items()}
    logger.info(
        "Incoming request %s %s from %s headers=%s",
        request.method,
        request.url.path,
        client,
        headers_snapshot,
    )
    response = await call_next(request)
    return response


@app.post(hub_requests.Routes.LOGIN)
async def login(request: hub_requests.LoginRequest):
    return await hub_manager.login(request)


@app.post(hub_requests.Routes.LOGOUT)
async def logout(request: hub_requests.LogoutRequest):
    return await hub_manager.logout(request)


# def validate_physical_fields(data: dict):
#     if data.get("deployment") != "physical":
#         return

#     ips = data.get("physical_ips")
#     if not ips:
#         raise HTTPException(
#             status_code=400,
#             detail="physical deployment requires 'physical_ips'"
#         )

#     if len(ips) != data.get("n_nodes"):
#         raise HTTPException(
#             status_code=400,
#             detail="'physical_ips' must have the same length as 'n_nodes'"
#         )

#     try:
#         for ip in ips:
#             ipaddress.ip_address(ip)
#             print(ip)
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


@app.post(hub_requests.Routes.RUN)
async def run_scenario(
    run_scenario_request: hub_requests.RunScenarioRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.run_scenario(current_user, run_scenario_request.scenario_data, request)


@app.post(hub_requests.Routes.STOP)
async def stop_scenario(
    federation_id: str,
    experiment_type: str = Body(False, embed=True),
    all: bool = Body(False, embed=True),
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    await hub_manager.stop_scenario(federation_id, experiment_type=experiment_type, stop_all=all)


@app.post(hub_requests.Routes.RESOURCES_STOP)
async def resources_stop_scenario(
    federation_id: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.resources_stop_scenario(federation_id)


@app.post(hub_requests.Routes.REMOVE)
async def remove_scenario(
    federation_id: str,
    request: hub_requests.RemoveScenarioRequest,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.remove_scenario(federation_id, request)


@app.get(hub_requests.Routes.GET_SCENARIOS_BY_USER)
async def get_scenarios(
    user: str,
    role: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.get_scenarios(current_user, user)


@app.post(hub_requests.Routes.UPDATE)
async def update_scenario(
    federation_id: str,
    request: hub_requests.UpdateScenarioRequest,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.update_scenario(federation_id, request)


@app.post(hub_requests.Routes.FINISH)
async def set_scenario_status_to_finished(
    federation_id: str,
    all: bool = Body(False, embed=True),
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.set_scenario_status_to_finished(federation_id, stop_all=all)


@app.get(hub_requests.Routes.RUNNING)
async def get_running_scenario_endpoint(
    get_all: bool = False,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.get_running_scenarios(get_all=get_all)


@app.get(hub_requests.Routes.CHECK_SCENARIO)
async def check_scenario(
    user: str,
    role: str,
    federation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.check_scenario(current_user, user, federation_id)


@app.get(hub_requests.Routes.GET_SCENARIO_BY_FEDERATION_ID)
async def get_scenario_by_federation_id(
    federation_id: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.get_scenario_by_federation_id(federation_id)


@app.get(hub_requests.Routes.NODES_LIST)
async def list_nodes_by_federation_id_endpoint(
    federation_id: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.list_nodes_by_federation_id(federation_id)


@app.post(hub_requests.Routes.NODES_UPDATE)
async def update_nodes(
    federation_id: str,
    node_update_request: hub_requests.NodeUpdateRequest,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.update_node(federation_id, node_update_request.config)


@app.post(hub_requests.Routes.NODES_DONE)
async def node_done(
    federation_id: str,
    node_done_request: hub_requests.NodeDoneRequest,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.node_done(federation_id, node_done_request.idx)


@app.post(hub_requests.Routes.NODES_REMOVE)
async def remove_nodes_by_federation_id_endpoint(
    federation_id: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.remove_nodes_by_federation_id(federation_id)


@app.get(hub_requests.Routes.NOTES_BY_FEDERATION_ID)
async def get_notes_by_federation_id(
    federation_id: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.get_notes_by_federation_id(federation_id)


@app.post(hub_requests.Routes.NOTES_UPDATE)
async def update_notes_by_federation_id(
    federation_id: str,
    notes: str = Body(..., embed=True),
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.update_note_by_federation_id(federation_id, notes)


@app.post(hub_requests.Routes.NOTES_REMOVE)
async def remove_notes_by_federation_id_endpoint(
    federation_id: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.remove_note_by_federation_id(federation_id)


@app.get(hub_requests.Routes.USER_LIST)
async def list_users_controller(
    all_info: bool = False,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.list_users(current_user, all_info=all_info)


@app.get(hub_requests.Routes.DISCOVER_VPN)
async def discover_vpn(
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.discover_vpn()


@app.get(hub_requests.Routes.PHYSICAL_RUN, tags=["physical"])
async def physical_run(
    ip: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.physical_run(ip)


@app.get(hub_requests.Routes.PHYSICAL_STOP, tags=["physical"])
async def physical_stop(
    ip: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.physical_stop(ip)


@app.put(hub_requests.Routes.PHYSICAL_SETUP, tags=["physical"], status_code=status.HTTP_201_CREATED)
async def physical_setup(
    ip: str,
    config: UploadFile = File(..., description="*.json* configuration file"),
    global_test: UploadFile = File(..., description="Global Dataset*.h5*"),
    train_set: UploadFile = File(..., description="Training dataset*.h5*"),
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.physical_setup(ip, config, global_test, train_set)


# ──────────────────────────────────────────────────────────────
# Physical · single-node state
# ──────────────────────────────────────────────────────────────
@app.get(hub_requests.Routes.PHYSICAL_STATE, tags=["physical"])
async def get_physical_node_state(
    ip: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.get_physical_node_state(ip)


# ──────────────────────────────────────────────────────────────
# Physical · aggregate state for an entire scenario
# ──────────────────────────────────────────────────────────────
@app.get(hub_requests.Routes.PHYSICAL_SCENARIO_STATE, tags=["physical"])
async def get_physical_scenario_state(
    federation_id: str,
    _current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.get_physical_scenario_state(federation_id)


@app.post(hub_requests.Routes.USER_ADD)
async def add_user_controller(
    user: str = Body(...),
    password: str = Body(...),
    role: str = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.add_user(current_user, user, password, role)


@app.post(hub_requests.Routes.USER_DELETE)
async def remove_user_controller(
    user: str = Body(..., embed=True),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.remove_user(current_user, user)


@app.post(hub_requests.Routes.USER_UPDATE)
async def update_user_controller(
    user: str = Body(...),
    password: str = Body(...),
    role: str = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await hub_manager.update_user(current_user, user, password, role)


if __name__ == "__main__":
    # Parse args from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5050, help="Port to run the controller on.")
    args = parser.parse_args()
    logging.info(f"Starting frontend on port {args.port}")
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=args.port)

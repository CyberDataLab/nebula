import argparse
import asyncio
import importlib
import logging
import os
import re

import uvicorn
from fastapi import Body, FastAPI, File, Request, UploadFile, WebSocket, status
from fastapi.concurrency import asynccontextmanager

from nebula.controller.hub.hub_manager import HubManager
import nebula.controller.hub.utils_requests as controller_requests
from nebula.utils import TermEscapeCodeFormatter


hub_manager = HubManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    - Configures logging on startup.
    """
    # Code to run on startup
    yield

    # Code to run on shutdown
    pass

# Initialize FastAPI app outside the Controller class
app = FastAPI(lifespan=lifespan)

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


@app.post(controller_requests.Routes.RUN)
async def run_scenario(run_scenario_request: controller_requests.RunScenarioRequest, request: Request):
    return await hub_manager.run_scenario(run_scenario_request.user, run_scenario_request.role, run_scenario_request.scenario_data, request)

@app.post(controller_requests.Routes.STOP)
async def stop_scenario(
    federation_id: str,
    experiment_type: str,
    all: bool = Body(False, embed=True),
):
    await hub_manager.stop_scenario(federation_id, experiment_type=experiment_type, stop_all=all)


@app.post(controller_requests.Routes.RESOURCES_STOP)
async def resources_stop_scenario(
    federation_id: str,
):
    return await hub_manager.resources_stop_scenario(federation_id)


@app.post(controller_requests.Routes.REMOVE)
async def remove_scenario(
    federation_id: str,
    request: controller_requests.RemoveScenarioRequest,
):
    return await hub_manager.remove_scenario(federation_id, request)


@app.get(controller_requests.Routes.GET_SCENARIOS_BY_USER)
async def get_scenarios(
    user: str,
    role: str,
):
    return await hub_manager.get_scenarios(user, role)


@app.post(controller_requests.Routes.UPDATE)
async def update_scenario(
    federation_id: str,
    request: controller_requests.UpdateScenarioRequest,
):
    return await hub_manager.update_scenario(federation_id, request)


@app.post(controller_requests.Routes.FINISH)
async def set_scenario_status_to_finished(
    federation_id: str,
    all: bool = Body(False, embed=True),
):
    return await hub_manager.set_scenario_status_to_finished(federation_id, stop_all=all)


@app.get(controller_requests.Routes.RUNNING)
async def get_running_scenario_endpoint(get_all: bool = False):
    return await hub_manager.get_running_scenarios(get_all=get_all)


@app.get(controller_requests.Routes.CHECK_SCENARIO)
async def check_scenario(
    user: str,
    role: str,
    federation_id: str,
):
    return await hub_manager.check_scenario(user, role, federation_id)


@app.get(controller_requests.Routes.GET_SCENARIO_BY_FEDERATION_ID)
async def get_scenario_by_federation_id(
    federation_id: str,
):
    return await hub_manager.get_scenario_by_federation_id(federation_id)


@app.get(controller_requests.Routes.NODES_LIST)
async def list_nodes_by_federation_id_endpoint(
    federation_id: str,
):
    return await hub_manager.list_nodes_by_federation_id(federation_id)


@app.post(controller_requests.Routes.NODES_UPDATE)
async def update_nodes(
    federation_id: str,
    node_update_request: controller_requests.NodeUpdateRequest,
):
    return await hub_manager.update_node(federation_id, node_update_request.config)


@app.post(controller_requests.Routes.NODES_DONE)
async def node_done(
    federation_id: str,
    node_done_request: controller_requests.NodeDoneRequest,
):
    return await hub_manager.node_done(federation_id, node_done_request.idx)


@app.post(controller_requests.Routes.NODES_REMOVE)
async def remove_nodes_by_federation_id_endpoint(
    federation_id: str,
):
    return await hub_manager.remove_nodes_by_federation_id(federation_id)


@app.get(controller_requests.Routes.NOTES_BY_FEDERATION_ID)
async def get_notes_by_federation_id(
    federation_id: str,
):
    return await hub_manager.get_notes_by_federation_id(federation_id)


@app.post(controller_requests.Routes.NOTES_UPDATE)
async def update_notes_by_federation_id(
    federation_id: str,
    notes: str = Body(..., embed=True),
):
    return await hub_manager.update_note_by_federation_id(federation_id, notes)


@app.post(controller_requests.Routes.NOTES_REMOVE)
async def remove_notes_by_federation_id_endpoint(
    federation_id: str,
):
    return await hub_manager.remove_note_by_federation_id(federation_id)


@app.get(controller_requests.Routes.USER_LIST)
async def list_users_controller(all_info: bool = False):
    return await hub_manager.list_users(all_info=all_info)


@app.get(controller_requests.Routes.USER_BY_FEDERATION_ID)
async def get_user_by_federation_id_endpoint(
    federation_id: str,
):
    return await hub_manager.get_user_by_federation_id(federation_id)


@app.get(controller_requests.Routes.DISCOVER_VPN)
async def discover_vpn():
    return await hub_manager.discover_vpn()


@app.get(controller_requests.Routes.PHYSICAL_RUN, tags=["physical"])
async def physical_run(ip: str):
    return await hub_manager.physical_run(ip)


@app.get(controller_requests.Routes.PHYSICAL_STOP, tags=["physical"])
async def physical_stop(ip: str):
    return await hub_manager.physical_stop(ip)


@app.put(controller_requests.Routes.PHYSICAL_SETUP, tags=["physical"],
         status_code=status.HTTP_201_CREATED)
async def physical_setup(
    ip: str,
    config:      UploadFile = File(..., description="*.json* configuration file"),
    global_test: UploadFile = File(..., description="Global Dataset*.h5*"),
    train_set:   UploadFile = File(..., description="Training dataset*.h5*"),
):
    return await hub_manager.physical_setup(ip, config, global_test, train_set)

# ──────────────────────────────────────────────────────────────
# Physical · single-node state
# ──────────────────────────────────────────────────────────────
@app.get(controller_requests.Routes.PHYSICAL_STATE, tags=["physical"])
async def get_physical_node_state(ip: str):
    return await hub_manager.get_physical_node_state(ip)


# ──────────────────────────────────────────────────────────────
# Physical · aggregate state for an entire scenario
# ──────────────────────────────────────────────────────────────
@app.get(controller_requests.Routes.PHYSICAL_SCENARIO_STATE, tags=["physical"])
async def get_physical_scenario_state(federation_id: str):
    return await hub_manager.get_physical_scenario_state(federation_id)


@app.post(controller_requests.Routes.USER_ADD)
async def add_user_controller(user: str = Body(...), password: str = Body(...), role: str = Body(...)):
    return await hub_manager.add_user(user, password, role)


@app.post(controller_requests.Routes.USER_DELETE)
async def remove_user_controller(user: str = Body(..., embed=True)):
    return await hub_manager.remove_user(user)


@app.post(controller_requests.Routes.USER_UPDATE)
async def update_user_controller(user: str = Body(...), password: str = Body(...), role: str = Body(...)):
    return await hub_manager.update_user(user, password, role)


@app.post(controller_requests.Routes.USER_VERIFY)
async def verify_user_controller(user: str = Body(...), password: str = Body(...)):
    return await hub_manager.verify_user(user, password)

@app.websocket("/ws/{channel_id}")
async def open_real_time_client(websocket: WebSocket, channel_id: str):
    return await hub_manager.open_real_time_client(websocket, channel_id)

if __name__ == "__main__":
    # Parse args from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5050, help="Port to run the controller on.")
    args = parser.parse_args()
    logging.info(f"Starting frontend on port {args.port}")
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=args.port)

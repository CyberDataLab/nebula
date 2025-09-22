import argparse
import os
import logging
from fastapi import FastAPI, Body, Path, Request
from fastapi.concurrency import asynccontextmanager
from typing import Dict
from typing import Annotated
from functools import wraps
from fastapi import HTTPException
from nebula.utils import LoggerUtils
from nebula.controller.federation.federation_controller import FederationController 
from nebula.controller.federation.factory_federation_controller import federation_controller_factory
from nebula.controller.federation.utils_requests import RunScenarioRequest, StopScenarioRequest, NodeUpdateRequest, NodeDoneRequest, Routes

fed_controllers: Dict[str, FederationController] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    log_path = os.environ.get("NEBULA_FEDERATION_CONTROLLER_LOG")

    # Configure and register the logger under the name "controller"
    LoggerUtils.configure_logger(name="Federation-Controller", log_file=log_path)

    # Retrieve the logger by name
    logger = logging.getLogger("Federation-Controller")
    logger.info("Logger initialized for Federation Controller")

    # Create all controller types
    hub_port = os.environ.get("NEBULA_CONTROLLER_PORT")
    controller_host = os.environ.get("NEBULA_CONTROLLER_HOST")
    hub_url = f"http://{controller_host}:{hub_port}"

    #["docker", "processes", "physical"]
    for exp_type in ["docker", "process"]:
        fed_controllers[exp_type] = federation_controller_factory(exp_type, hub_url, logger)
        logger.info(f"{exp_type} Federation controller created.")

    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def read_root():
    """
    Root endpoint of the NEBULA Controller API.

    Returns:
        dict: A welcome message indicating the API is accessible.
    """
    logger = logging.getLogger("Federation-Controller")
    logger.info("Test curl succesfull")
    return {"message": "Welcome to the NEBULA Federation Controller API"}

@app.post(Routes.RUN)
async def run_scenario(run_scenario_request: RunScenarioRequest):
    global fed_controllers
    experiment_type = run_scenario_request.scenario_data["deployment"]
    logger = logging.getLogger("Federation-Controller")
    logger.info(f"[API]: run experiment request for deployment type: {experiment_type}")
    controller = fed_controllers.get(experiment_type, None)
    if controller:
        return await controller.run_scenario(run_scenario_request.federation_id, run_scenario_request.scenario_data, run_scenario_request.user)
    else:
        return {"message": "Experiment type not allowed"}
    
@app.post(Routes.STOP)
async def stop_scenario(stop_scenario_request: StopScenarioRequest):
    global fed_controllers
    experiment_type = stop_scenario_request.experiment_type
    controller = fed_controllers.get(experiment_type, None)
    logger = logging.getLogger("Federation-Controller")
    logger.info(f"[API]: stop experiment request for federation ID: {stop_scenario_request.federation_id}")
    if controller:
        return await controller.stop_scenario(stop_scenario_request.federation_id)
    else:
        return {"message": "Experiment type not allowed"}

@app.post(Routes.UPDATE)
async def update_nodes(
    federation_id: str,
    node_update_request: NodeUpdateRequest,
):
    global fed_controllers
    experiment_type = node_update_request.config["scenario_args"]["deployment"]
    controller = fed_controllers.get(experiment_type, None)
    if controller:
        return await controller.update_nodes(federation_id, node_update_request)
    else:
        return {"message": "Experiment type not allowed on response for update message.."}

@app.post(Routes.DONE)
async def node_done(
    federation_id: str,
    node_done_request: NodeDoneRequest,
):
    global fed_controllers
    experiment_type = node_done_request.deployment
    controller = fed_controllers.get(experiment_type, None)
    if controller:
        return await controller.node_done(federation_id, node_done_request)
    else:
        return {"message": "Experiment type not allowed on responde for Node done message.."}

if __name__ == "__main__":
    # Parse args from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5051, help="Port to run the Federation controller on.")
    args = parser.parse_args()
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)

    
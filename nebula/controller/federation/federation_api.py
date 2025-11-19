import argparse
import os
import logging
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from typing import Dict
from nebula.utils import LoggerUtils
from nebula.controller.federation.federation_broker import FederationBroker
from nebula.controller.federation.federation_controller import FederationController
from nebula.controller.federation.schemas.requests import *
from nebula.controller.federation.schemas.responses import *
from nebula.controller.federation.schemas.errors import *

controller_broker: FederationBroker = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global controller_broker
    log_path = os.environ.get("NEBULA_FEDERATION_CONTROLLER_LOG")

    # Configure and register the logger under the name "controller"
    LoggerUtils.configure_logger(name="Federation-Controller", log_file=log_path)

    # Retrieve the logger by name
    logger = logging.getLogger("Federation-Controller")
    logger.info("Logger initialized for Federation Controller")

    hub_port = os.environ.get("NEBULA_CONTROLLER_PORT")
    controller_host = os.environ.get("NEBULA_CONTROLLER_HOST")
    hub_url = f"http://{controller_host}:{hub_port}"

    controller_broker = FederationBroker(hub_url=hub_url, logger=logger)
    await controller_broker.init(broker=os.environ.get("KAFKA_BROKER"), user=os.environ.get("KAFKA_CONTROLLER_USER"), password=os.environ.get("KAFKA_CONTROLLER_PASSWORD"))

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

@app.post(
    Routes.RUN,
    response_model=RunScenarioResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request - wrong experiment type"},
        404: {"model": ErrorResponse, "description": "Scenario ID not found"},
        409: {"model": ErrorResponse, "description": "Conflict - Scenario ID exists"},
        500: {"model": ErrorResponse, "description": "Error while building scenario"},
    },
    summary="Run a new scenario",
    description=(
        "Starts a new federated learning scenario based on the provided configuration."
    ),
)
async def run_scenario(run_scenario_request: RunScenarioRequest):
    global controller_broker
    experiment_type = run_scenario_request.scenario_data["deployment"]
    logger = logging.getLogger("Federation-Controller")
    logger.info(f"[API]: run experiment request for deployment type: {experiment_type}")
    return await controller_broker.run_scenario(
        experiment_type,
        run_scenario_request.federation_id,
        run_scenario_request.scenario_data,
        run_scenario_request.user,
    )

@app.post(
    Routes.STOP,
    response_model=StopScenarioResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request - wrong experiment type"},
        500: {"model": ErrorResponse, "description": "Error while stopping scenario"},
    },
    summary="Stop a running scenario",
    description=(
        "Stops a running scenario and free all the resources used"
    ),
)
async def stop_scenario(
    federation_id: str,
    stop_scenario_request: StopScenarioRequest
):
    global controller_broker
    logger = logging.getLogger("Federation-Controller")
    logger.info(f"[API]: stop experiment request for federation ID: {federation_id}")
    experiment_type = stop_scenario_request.experiment_type
    return await controller_broker.stop_scenario(experiment_type, federation_id)

@app.post(
    Routes.REMOVE,
    response_model=RemoveScenarioResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request - wrong experiment type"},
        409: {"model": ErrorResponse, "description": "Scenario is currently active"},
        500: {"model": ErrorResponse, "description": "Error while removing scenario files"},
    },
    summary="Remove federation files",
    description=(
        "Removes files from a not running scenario"
    ),
)
async def scenario_remove(
    federation_id: str,
    remove_scenario_request: RemoveScenarioRequest,
):
    global controller_broker
    experiment_type = remove_scenario_request.experiment_type
    return await controller_broker.remove_scenario(federation_id, **remove_scenario_request.model_dump())
    # controller = fed_controllers.get(experiment_type, None)
    # if controller:
    #     return await controller.remove_scenario(federation_id, **remove_scenario_request.model_dump())
    # else:
    #     raise_error(BAD_CONTROLLER)

if __name__ == "__main__":
    # Parse args from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5051, help="Port to run the Federation controller on.")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)

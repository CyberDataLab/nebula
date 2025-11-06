import argparse
import os
import logging
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from typing import Dict
from nebula.utils import LoggerUtils
from nebula.controller.federation.federation_broker import FederationBroker
from nebula.controller.federation.federation_controller import FederationController 
from nebula.controller.federation.factory_federation_controller import federation_controller_factory
from nebula.controller.federation.schemas.requests import *
from nebula.controller.federation.schemas.responses import *
from nebula.controller.federation.schemas.errors import *
from nebula.controller.federation.utils.api_utils import raise_error

fed_controllers: Dict[str, FederationController] = {}
controller_broker: FederationBroker = None

@asynccontextmanager
async def lifespan(app: FastAPI):
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
    await controller_broker.init()

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
    return await controller_broker.run_scenario(experiment_type, run_scenario_request.model_dump())
    # controller = fed_controllers.get(experiment_type, None)
    # if controller:
    #     return await controller.run_scenario(run_scenario_request.model_dump())
    # else:
    #     raise_error(BAD_CONTROLLER)
    
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
    # controller = fed_controllers.get(experiment_type, None)
    # if controller:
    #     return await controller.stop_scenario(federation_id)
    # else:
    #     raise_error(BAD_CONTROLLER)

# @app.post(
#     Routes.UPDATE,
#     response_model=NodeUpdateResponse,
#     responses={                                   
#         400: {"model": ErrorResponse, "description": "Bad Request - wrong experiment type"},
#         404: {"model": ErrorResponse, "description": "Scenario ID not found"},
#         500: {"model": ErrorResponse, "description": "Error while stopping scenario"},
#     },
#     summary="Node update information",
#     description=(
#         "Nodes notify their updates to the controller"
#     ),
# )
# async def update_nodes(
#     federation_id: str,
#     node_update_request: NodeUpdateRequest,
# ):
#     global fed_controllers
#     experiment_type = node_update_request.config["scenario_args"]["deployment"]
#     controller = fed_controllers.get(experiment_type, None)
#     if controller:
#         return await controller.update_nodes(federation_id, **node_update_request.model_dump())
#     else:
#         raise_error(BAD_CONTROLLER)

# @app.post(
#     Routes.DONE,
#     response_model=NodeDoneResponse,
#     responses={                                   
#         400: {"model": ErrorResponse, "description": "Bad Request - wrong experiment type"},
#         404: {"model": ErrorResponse, "description": "Scenario ID not found"},
#     },
#     summary="Node done notification",
#     description=(
#         "Nodes notify when they have finished their process"
#     ),
# )
# async def node_done(
#     federation_id: str,
#     node_done_request: NodeDoneRequest,
# ):
#     global fed_controllers
#     experiment_type = node_done_request.deployment
#     controller = fed_controllers.get(experiment_type, None)
#     if controller:
#         return await controller.node_done(federation_id, **node_done_request.model_dump())
#     else:
#         raise_error(BAD_CONTROLLER)
    
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
    return await controller_broker.remove_scenario(experiment_type, federation_id, **remove_scenario_request.model_dump())
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

    
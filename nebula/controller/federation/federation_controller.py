import argparse
import os
import logging
from abc import ABC, abstractmethod
from fastapi import FastAPI, Body, Path, Request
from fastapi.concurrency import asynccontextmanager
from typing import Dict
from typing import Annotated
from functools import wraps
from fastapi import HTTPException
from nebula.utils import LoggerUtils


class FederationController(ABC):
    
    def __init__(self, logger):
        self._logger = logger    

    @abstractmethod
    async def run_scenario(self, scenario_data: Dict, role: str, user: str):
        pass

    @abstractmethod
    async def stop_scenario(self, scenario_name: str, username: str, all: bool):
        pass

    @abstractmethod
    async def remove_scenario(self, scenario_name: str):
        pass

    @abstractmethod
    async def update_nodes(self, scenario_name: str, request: Request):
        pass

def federation_controller_factory(mode: str, logger) -> FederationController:
    from nebula.controller.federation.docker_federation_controller import DockerFederationController
    from nebula.controller.federation.processes_federation_controller import ProcessesFederationController
    from nebula.controller.federation.physicall_federation_controller import PhysicalFederationController
    
    if mode == "docker":
        return DockerFederationController(logger)
    elif mode == "physical":
        return PhysicalFederationController(logger)
    elif mode == "processes":
        return ProcessesFederationController(logger)
    else:
        raise ValueError("Unknown federation mode")

def require_initialized_controller(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if fed_controller is None:
            raise HTTPException(status_code=400, detail="FederationController not initialized")
        return await func(*args, **kwargs)
    return wrapper
    
@asynccontextmanager
async def lifespan(app: FastAPI):
    log_path = os.environ.get("NEBULA_FEDERATION_CONTROLLER_LOG")

    # Configure and register the logger under the name "controller"
    LoggerUtils.configure_logger(name="Federation-Controller", log_file=log_path)

    # Retrieve the logger by name
    logger = logging.getLogger("Federation-Controller")
    logger.info("Logger initialized for Federation Controller")

    yield

app = FastAPI(lifespan=lifespan)
fed_controller: FederationController = None

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

@app.post("/init")
async def init_federation_experiment(payload: dict = Body(...)):
    global fed_controller

    experiment_type = payload["type"]
    logger = logging.getLogger("Federation-Controller")
    fed_controller = federation_controller_factory(experiment_type, logger)

    return {"message": f"{experiment_type} controller initialized"}

@app.post("/scenarios/run")
@require_initialized_controller
async def run_scenario(
    scenario_data: dict = Body(..., embed=True),
    role: str = Body(..., embed=True),
    user: str = Body(..., embed=True),
):
    global fed_controller
    return await fed_controller.run_scenario(scenario_data, role, user)

@app.post("/scenarios/stop")
@require_initialized_controller
async def stop_scenario(
    scenario_name: str = Body(..., embed=True),
    username: str = Body(..., embed=True),
    all: bool = Body(False, embed=True),
):
    global fed_controller
    return await fed_controller.stop_scenario(scenario_name, username, all)

@app.post("/scenarios/remove")
@require_initialized_controller
async def remove_scenario(
    scenario_name: str = Body(..., embed=True),
):
    global fed_controller
    return await fed_controller.remove_scenario(scenario_name)

@app.post("/nodes/{scenario_name}/update")
@require_initialized_controller
async def update_nodes(
    scenario_name: Annotated[
        str,
        Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid scenario name"),
    ],
    request: Request,
):
    global fed_controller
    return await fed_controller.update_nodes(scenario_name, request)


if __name__ == "__main__":
    # Parse args from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5051, help="Port to run the Federation controller on.")
    args = parser.parse_args()
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
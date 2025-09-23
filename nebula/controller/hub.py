import argparse
import asyncio
from datetime import datetime
import importlib
import ipaddress
import json
import logging
import os
import re
import copy
from typing import Annotated

import aiohttp
import psutil
import uvicorn
from fastapi import Body, FastAPI, Request, status, HTTPException, Path, File, UploadFile
from fastapi.concurrency import asynccontextmanager
from nebula.controller.http_helpers import remote_get, remote_post_form
from nebula.utils import APIUtils, DockerUtils
import nebula.controller.federation.utils_requests as federation_requests
import nebula.controller.utils_requests as controller_requests

# URL for the database API
DATABASE_API_URL = os.environ.get("NEBULA_DATABASE_API_URL", "http://nebula-database:5051")


# Setup controller logger
class TermEscapeCodeFormatter(logging.Formatter):
    """
    Custom logging formatter that removes ANSI terminal escape codes from log messages.

    This formatter is useful when you want to clean up log outputs by stripping out
    any terminal color codes or formatting sequences before logging them to a file
    or other non-terminal output.

    Attributes:
        fmt (str): Format string for the log message.
        datefmt (str): Format string for the date in the log message.
        style (str): Formatting style (default is '%').
        validate (bool): Whether to validate the format string.

    Methods:
        format(record): Strips ANSI escape codes from the log message and formats it.
    """

    def __init__(self, fmt=None, datefmt=None, style="%", validate=True):
        """
        Initializes the TermEscapeCodeFormatter.

        Args:
            fmt (str, optional): The format string for the log message.
            datefmt (str, optional): The format string for the date.
            style (str, optional): The formatting style. Defaults to '%'.
            validate (bool, optional): Whether to validate the format string. Defaults to True.
        """
        super().__init__(fmt, datefmt, style, validate)

    def format(self, record):
        """
        Formats the specified log record, stripping out any ANSI escape codes.

        Args:
            record (logging.LogRecord): The log record to be formatted.

        Returns:
            str: The formatted log message with escape codes removed.
        """
        escape_re = re.compile(r"\x1b\[[0-9;]*m")
        record.msg = re.sub(escape_re, "", str(record.msg))
        return super().format(record)


def configure_logger(controller_log):
    """
    Configures the logging system for the controller.

    - Sets a format for console and file logging.
    - Creates a console handler with INFO level.
    - Creates a file handler for 'controller.log' with INFO level.
    - Configures specific Uvicorn loggers to use the file handler
      without duplicating log messages.
    """
    log_console_format = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(TermEscapeCodeFormatter(log_console_format))
    console_handler_file = logging.FileHandler(os.path.join(controller_log), mode="w")
    console_handler_file.setLevel(logging.INFO)
    console_handler_file.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[
            console_handler,
            console_handler_file,
        ],
    )
    uvicorn_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access"]
    for logger_name in uvicorn_loggers:
        logger = logging.getLogger(logger_name)
        logger.handlers = []  # Remove existing handlers
        logger.propagate = False  # Prevent duplicate logs
        handler = logging.FileHandler(os.path.join(controller_log), mode="a")
        handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
        logger.addHandler(handler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    - Configures logging on startup.
    """
    # Code to run on startup
    controller_log: str = os.environ.get("NEBULA_CONTROLLER_LOG")
    configure_logger(controller_log)

    yield

    # Code to run on shutdown
    pass


# Initialize FastAPI app outside the Controller class
app = FastAPI(lifespan=lifespan)


# Define endpoints outside the Controller class
@app.get(controller_requests.Routes.INIT)
async def read_root():
    """
    Root endpoint of the NEBULA Controller API.

    Returns:
        dict: A welcome message indicating the API is accessible.
    """
    return {"message": "Welcome to the NEBULA Controller API"}


@app.get(controller_requests.Routes.STATUS)
async def get_status():
    """
    Check the status of the NEBULA Controller API.

    Returns:
        dict: A status message confirming the API is running.
    """
    return {"status": "NEBULA Controller API is running"}


@app.get(controller_requests.Routes.RESOURCES)
async def get_resources():
    """
    Get system resource usage including RAM and GPU memory usage.

    Returns:
        dict: A dictionary containing:
            - gpus (int): Number of GPUs detected.
            - memory_percent (float): Percentage of used RAM.
            - gpu_memory_percent (List[float]): List of GPU memory usage percentages.
    """
    devices = 0
    gpu_memory_percent = []

    # Obtain available RAM
    memory_info = await asyncio.to_thread(psutil.virtual_memory)

    if importlib.util.find_spec("pynvml") is not None:
        try:
            import pynvml

            await asyncio.to_thread(pynvml.nvmlInit)
            devices = await asyncio.to_thread(pynvml.nvmlDeviceGetCount)

            # Obtain GPU info
            for i in range(devices):
                handle = await asyncio.to_thread(pynvml.nvmlDeviceGetHandleByIndex, i)
                memory_info_gpu = await asyncio.to_thread(pynvml.nvmlDeviceGetMemoryInfo, handle)
                memory_used_percent = (memory_info_gpu.used / memory_info_gpu.total) * 100
                gpu_memory_percent.append(memory_used_percent)

        except Exception:  # noqa: S110
            pass

    return {
        # "cpu_percent": psutil.cpu_percent(),
        "gpus": devices,
        "memory_percent": memory_info.percent,
        "gpu_memory_percent": gpu_memory_percent,
    }


@app.get(controller_requests.Routes.LEAST_MEMORY_GPU)
async def get_least_memory_gpu():
    """
    Identify the GPU with the highest memory usage above a threshold (50%).

    Note:
        Despite the name, this function returns the GPU using the **most**
        memory above 50% usage.

    Returns:
        dict: A dictionary with the index of the GPU using the most memory above the threshold,
              or None if no such GPU is found.
    """
    gpu_with_least_memory_index = None

    if importlib.util.find_spec("pynvml") is not None:
        max_memory_used_percent = 50
        try:
            import pynvml

            await asyncio.to_thread(pynvml.nvmlInit)
            devices = await asyncio.to_thread(pynvml.nvmlDeviceGetCount)

            # Obtain GPU info
            for i in range(devices):
                handle = await asyncio.to_thread(pynvml.nvmlDeviceGetHandleByIndex, i)
                memory_info = await asyncio.to_thread(pynvml.nvmlDeviceGetMemoryInfo, handle)
                memory_used_percent = (memory_info.used / memory_info.total) * 100

                # Obtain GPU with less memory available
                if memory_used_percent > max_memory_used_percent:
                    max_memory_used_percent = memory_used_percent
                    gpu_with_least_memory_index = i

        except Exception:  # noqa: S110
            pass

    return {
        "gpu_with_least_memory_index": gpu_with_least_memory_index,
    }


@app.get(controller_requests.Routes.AVAILABLE_GPUS)
async def get_available_gpu():
    """
    Get the list of GPUs with memory usage below 5%.

    Returns:
        dict: A dictionary with a list of GPU indices that are mostly free (usage < 5%).
    """
    available_gpus = []

    if importlib.util.find_spec("pynvml") is not None:
        try:
            import pynvml

            await asyncio.to_thread(pynvml.nvmlInit)
            devices = await asyncio.to_thread(pynvml.nvmlDeviceGetCount)

            # Obtain GPU info
            for i in range(devices):
                handle = await asyncio.to_thread(pynvml.nvmlDeviceGetHandleByIndex, i)
                memory_info = await asyncio.to_thread(pynvml.nvmlDeviceGetMemoryInfo, handle)
                memory_used_percent = (memory_info.used / memory_info.total) * 100

                # Obtain available GPUs
                if memory_used_percent < 5:
                    available_gpus.append(i)

            return {
                "available_gpus": available_gpus,
            }
        except Exception:  # noqa: S110
            pass


def validate_physical_fields(data: dict):
    if data.get("deployment") != "physical":
        return

    ips = data.get("physical_ips")
    if not ips:
        raise HTTPException(
            status_code=400,
            detail="physical deployment requires 'physical_ips'"
        )

    if len(ips) != data.get("n_nodes"):
        raise HTTPException(
            status_code=400,
            detail="'physical_ips' must have the same length as 'n_nodes'"
        )

    try:
        for ip in ips:
            ipaddress.ip_address(ip)
            print(ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(controller_requests.Routes.RUN)
async def run_scenario(run_scenario_request: controller_requests.RunScenarioRequest):
    """
    Launches a new scenario based on the provided configuration.

    Args:
        scenario_data (dict): The complete configuration of the scenario to be executed.
        role (str): The role of the user initiating the scenario.
        user (str): The username of the user initiating the scenario.

    Returns:
        str: The name of the scenario that was started.
    """
    import hashlib
    def generate_id(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    response = None

    try:
        fed_controller_port = os.environ.get("NEBULA_FEDERATION_CONTROLLER_PORT")
        fed_controller_host = os.environ.get("NEBULA_CONTROLLER_HOST")
        url_run_scenario = f"http://{fed_controller_host}:{fed_controller_port}" + federation_requests.factory_requests_path("run")
        #init_fed_req = InitFederationRequest(experiment_type="docker")
        federation_id = generate_id(f"nebula_{run_scenario_request.user}_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}")
        run_scenario_req = federation_requests.RunScenarioRequest(scenario_data=run_scenario_request.scenario_data, federation_id=federation_id, user=run_scenario_request.user) #TODO ID per experiment
        #await APIUtils.post(url_init_fed_controller, init_fed_req.model_dump())
        response = await APIUtils.post(url_run_scenario, run_scenario_req.model_dump())
    except Exception as e:
        logging.info(e)

    # Unpack request data (role is intentionally ignored for now)
    scenario_data = run_scenario_request.scenario_data
    user = run_scenario_request.user

    # validate_physical_fields(scenario_data)

    # Manager for the actual scenario
    #scenarioManagement = ScenarioManagement(scenario_data, user)

    if response:
        try:
            logging.info("[FER] entro response")
            await update_scenario(
                federation_id=federation_id,
                scenario_name=response["scenario_name"],
                start_time=response["start_time"],
                end_time="",
                scenario=run_scenario_request.scenario_data,
                status="running",
                username=run_scenario_request.user,
            )

            return response["federation_id"]
        except Exception as e:
            logging.info(e)
    else:
        raise HTTPException(500, detail={"failed running scenario"})

@app.post(controller_requests.Routes.STOP) #TODO redo method
async def stop_scenario(
    scenario_name: str = Body(..., embed=True),
    all: bool = Body(False, embed=True),
):
    """
    Stops the execution of a federated learning scenario and performs cleanup operations.

    This endpoint:
        - Stops all participant containers associated with the specified scenario.
        - Removes Docker containers and network resources tied to the scenario and user.
        - Sets the scenario's status to "finished" in the database.
        - Optionally finalizes all active scenarios if the 'all' flag is set.

    Args:
        scenario_name (str): Name of the scenario to stop.
        username (str): User who initiated the stop operation.
        all (bool): Whether to stop all running scenarios instead of just one (default: False).

    Raises:
        HTTPException: Returns a 500 status code if any step fails.

    Note:
        This function does not currently trigger statistics generation.
    """
    fed_controller_port = os.environ.get("NEBULA_FEDERATION_CONTROLLER_PORT")
    fed_controller_host = os.environ.get("NEBULA_CONTROLLER_HOST")
    url_stop_scenario = f"http://{fed_controller_host}:{fed_controller_port}" + federation_requests.factory_requests_path("stop")
    stop_scenario_req = federation_requests.StopScenarioRequest(federation_id="id_nebula")
    try:
        path = federation_requests.factory_requests_path("stop")
        payload = federation_requests.StopScenarioRequest(scenario_name=scenario_name, all=all).model_dump()
        await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
        await APIUtils.post(url_stop_scenario, stop_scenario_req.model_dump())
    except Exception as e:
        logging.info(f"ERROR: sending stop scenario to federation Controller: {e}")

    # from nebula.controller.scenarios import ScenarioManagement

    # ScenarioManagement.cleanup_scenario_containers()
    # try:
    #     if all:
    #         await scenario_set_all_status_to_finished()
    #     else:
    #         await scenario_set_status_to_finished(scenario_name)
    # except Exception as e:
    #     logging.exception(f"Error setting scenario {scenario_name} to finished: {e}")
    #     raise HTTPException(status_code=500, detail="Internal server error")


@app.post(controller_requests.Routes.REMOVE)
async def remove_scenario(
    scenario_name: str = Body(..., embed=True),
):
    """
    Removes a scenario from the database by its name.

    Args:
        scenario_name (str): Name of the scenario to remove.

    Returns:
        dict: A message indicating successful removal.
    """
    from nebula.controller.scenarios import ScenarioManagement

    try:
        path = controller_requests.factory_requests_path("remove")
        payload = controller_requests.ScenarioRemoveRequest(scenario_name=scenario_name).model_dump()
        await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
        ScenarioManagement.remove_files_by_scenario(scenario_name)

    except Exception as e:
        logging.exception(f"Error removing scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Scenario {scenario_name} removed successfully"}


@app.get(controller_requests.Routes.GET_SCENARIOS_BY_USER)
async def get_scenarios(
    user: Annotated[str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid username")],
    role: Annotated[str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid role")],
):
    """
    Retrieves all scenarios associated with a given user and role.

    Args:
        user (str): Username to filter scenarios.
        role (str): Role of the user (e.g., "admin").

    Returns:
        dict: A list of scenarios and the currently running scenario.
    """
    try:
        path = controller_requests.factory_requests_path("get_scenarios_by_user", user=user, role=role)
        return await APIUtils.get(f"{DATABASE_API_URL}{path}")
    except Exception as e:
        logging.exception(f"Error obtaining scenarios: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(controller_requests.Routes.UPDATE)
async def update_scenario(
    federation_id: str = Body(..., embed=True),
    scenario_name: str = Body(..., embed=True),
    start_time: str = Body(..., embed=True),
    end_time: str = Body(..., embed=True),
    scenario: dict = Body(..., embed=True),
    status: str = Body(..., embed=True),
    username: str = Body(..., embed=True),
):
    """
    Updates the status and metadata of a scenario.

    Args:
        scenario_name (str): Name of the scenario.
        start_time (str): Start time of the scenario.
        end_time (str): End time of the scenario.
        scenario (dict): Scenario configuration.
        status (str): New status of the scenario (e.g., "running", "finished").
        username (str): User performing the update.

    Returns:
        dict: A message confirming the update.
    """
    try:
        payload = controller_requests.ScenarioUpdateRequest(
            federation_id=federation_id,
            scenario_name=scenario_name,
            start_time=start_time,
            end_time=end_time,
            scenario=scenario,
            status=status,
            username=username,
        ).model_dump()
        path = controller_requests.factory_requests_path("update")
        logging.info(f"[FER] route {DATABASE_API_URL}{path}")
        return await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except Exception as e:
        logging.exception(f"Error updating scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(controller_requests.Routes.FINISH)
async def set_scenario_status_to_finished(
    scenario_name: str = Body(..., embed=True), all: bool = Body(False, embed=True)
):
    """
    Sets the status of a scenario (or all scenarios) to 'finished'.

    Args:
        scenario_name (str): Name of the scenario to mark as finished.
        all (bool): If True, sets all scenarios to finished.

    Returns:
        dict: A message confirming the operation.
    """
    try:
        payload = controller_requests.ScenarioFinishRequest(scenario_name=scenario_name, all=all).model_dump()
        path = controller_requests.factory_requests_path("finish")
        return await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except Exception as e:
        logging.exception(f"Error setting scenario {scenario_name} to finished: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(controller_requests.Routes.RUNNING)
async def get_running_scenario_endpoint(get_all: bool = False):
    """
    Retrieves the currently running scenario(s).

    Args:
        get_all (bool): If True, retrieves all running scenarios.

    Returns:
        dict or list: Running scenario(s) information.
    """
    try:
        path = controller_requests.factory_requests_path("running")
        return await APIUtils.get(f"{DATABASE_API_URL}{path}", params={"get_all": str(get_all)})
    except Exception as e:
        logging.exception(f"Error obtaining running scenario: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(controller_requests.Routes.CHECK_SCENARIO)
async def check_scenario(
    user: Annotated[str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid username")],
    role: Annotated[str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid role")],
    scenario_name: Annotated[
        str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid scenario name")
    ],
):
    """
    Checks if a scenario is allowed for a specific role.

    Args:
        role (str): Role to validate.
        scenario_name (str): Name of the scenario.

    Returns:
        dict: Whether the scenario is allowed for the role.
    """
    try:
        path = controller_requests.factory_requests_path("check_scenario", user=user, role=role, scenario_name=scenario_name)
        return await APIUtils.get(f"{DATABASE_API_URL}{path}")
    except Exception as e:
        logging.exception(f"Error checking scenario with role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(controller_requests.Routes.GET_SCENARIOS_BY_SCENARIO_NAME)
async def get_scenario_by_name_endpoint(
    scenario_name: Annotated[
        str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid scenario name")
    ],
):
    """
    Fetches a scenario by its name.

    Args:
        scenario_name (str): The name of the scenario.

    Returns:
        dict: The scenario data.
    """
    try:
        path = controller_requests.factory_requests_path("get_scenarios_by_scenario_name", scenario_name=scenario_name)
        return await APIUtils.get(f"{DATABASE_API_URL}{path}")
    except Exception as e:
        logging.exception(f"Error obtaining scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(controller_requests.Routes.NODES_BY_SCENARIO_NAME)
async def list_nodes_by_scenario_name_endpoint(
    scenario_name: Annotated[
        str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid scenario name")
    ],
):
    """
    Lists all nodes associated with a specific scenario.

    Args:
        scenario_name (str): Name of the scenario.

    Returns:
        list: List of nodes.
    """
    try:
        path = controller_requests.factory_requests_path("get_nodes_by_scenario_name", scenario_name=scenario_name)
        return await APIUtils.get(f"{DATABASE_API_URL}{path}")
    except Exception as e:
        logging.exception(f"Error obtaining nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(controller_requests.Routes.NODES_UPDATE_BY_SCENARIO)
async def update_nodes(
    scenario_name: Annotated[
        str,
        Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid scenario name"),
    ],
    request: Request,
):
    """
    Updates the configuration of a node in the database and notifies the frontend.

    Args:
        scenario_name (str): The scenario to which the node belongs.
        request (Request): The HTTP request containing the node data.

    Returns:
        dict: Confirmation or response from the frontend.
    """
    try:
        config:dict = await request.json()
        config["timestamp"] = str(datetime.now())

        mobility_args = config.get("mobility_args", None)
        if not mobility_args:
            # default Murcia coordinates if none provided
            config["mobility_args"] = {"latitude": "38.0235", "longitude": "-1.1744"}
        # Validate and normalize payload
        validated = controller_requests.NodesUpdateRequest(**config)

        # Build payload and include extras with mobility data
        payload = validated.model_dump()
        payload["extras"] = payload.get("mobility_args", {})

        # Update the node in database with validated data and extras
        path = controller_requests.factory_requests_path("update_nodes")
        await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except Exception as e:
        logging.exception(f"Error updating nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    url = (
        f"http://{os.environ['NEBULA_ENV_TAG']}_{os.environ['NEBULA_PREFIX_TAG']}_{os.environ['NEBULA_USER_TAG']}_nebula-frontend/platform/dashboard/{scenario_name}/node/update"
    )

    return await APIUtils.post(url, data=config)


@app.post(controller_requests.Routes.NODES_DONE_BY_SCENARIO)
async def node_done(
    scenario_name: Annotated[
        str,
        Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid scenario name"),
    ],
    request: Request,
):
    """
    Endpoint to forward node status to the frontend.

    Receives a JSON payload and forwards it to the frontend's /node/done route
    for the given scenario.

    Parameters:
    - scenario_name: Name of the scenario.
    - request: HTTP request with JSON body.

    Returns the response from the frontend or raises an HTTPException if it fails.
    """
    url = f"http://{os.environ['NEBULA_ENV_TAG']}_{os.environ['NEBULA_PREFIX_TAG']}_{os.environ['NEBULA_USER_TAG']}_nebula-frontend/platform/dashboard/{scenario_name}/node/done"

    data = await request.json()

    return await APIUtils.post(url, data=data)


@app.post(controller_requests.Routes.NODES_REMOVE)
async def remove_nodes_by_scenario_name_endpoint(scenario_name: str = Body(..., embed=True)):
    """
    Endpoint to remove all nodes associated with a scenario.

    Body Parameters:
    - scenario_name: Name of the scenario whose nodes should be removed.

    Returns a success message or an error if something goes wrong.
    """
    try:
        path = controller_requests.factory_requests_path("remove_nodes")
        payload = controller_requests.NodesRemoveRequest(scenario_name=scenario_name).model_dump()
        await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except Exception as e:
        logging.exception(f"Error removing nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Nodes for scenario {scenario_name} removed successfully"}


@app.get(controller_requests.Routes.NOTES_BY_SCENARIO_NAME)
async def get_notes_by_scenario_name(
    scenario_name: Annotated[
        str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid scenario name")
    ],
):
    """
    Endpoint to retrieve notes associated with a scenario.
    """
    try:
        path = controller_requests.factory_requests_path("get_notes_by_scenario_name", scenario_name=scenario_name)
        return await APIUtils.get(f"{DATABASE_API_URL}{path}")
    except Exception as e:
        logging.exception(f"Error obtaining notes for scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(controller_requests.Routes.NOTES_UPDATE)
async def update_notes_by_scenario_name(scenario_name: str = Body(..., embed=True), notes: str = Body(..., embed=True)):
    """
    Endpoint to update notes for a given scenario.

    Body Parameters:
    - scenario_name: Name of the scenario.
    - notes: Text content to store as notes.

    Returns a success message or an error if something goes wrong.
    """
    try:
        payload = controller_requests.NotesUpdateRequest(scenario_name=scenario_name, notes=notes).model_dump()
        path = controller_requests.factory_requests_path("update_notes")
        return await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except Exception as e:
        logging.exception(f"Error updating notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(controller_requests.Routes.NOTES_REMOVE)
async def remove_notes_by_scenario_name_endpoint(scenario_name: str = Body(..., embed=True)):
    """
    Endpoint to remove notes associated with a scenario.

    Body Parameters:
    - scenario_name: Name of the scenario.

    Returns a success message or an error if something goes wrong.
    """
    try:
        path = controller_requests.factory_requests_path("remove_notes")
        payload = controller_requests.NotesRemoveRequest(scenario_name=scenario_name).model_dump()
        await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except Exception as e:
        logging.exception(f"Error removing notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Notes for scenario {scenario_name} removed successfully"}


@app.get(controller_requests.Routes.USER_LIST)
async def list_users_controller(all_info: bool = False):
    """
    Endpoint to list all users in the database.

    Query Parameters:
    - all_info (bool): If True, returns full user info as dictionaries.

    Returns a list of users or raises an HTTPException on error.
    """
    try:
        path = controller_requests.factory_requests_path("list_users")
        return await APIUtils.get(f"{DATABASE_API_URL}{path}", params={"all_info": str(all_info)})
    except Exception as e:
        logging.exception(f"Error retrieving users: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error retrieving users: {e}")


@app.get(controller_requests.Routes.USER_BY_SCENARIO_NAME)
async def get_user_by_scenario_name_endpoint(
    scenario_name: Annotated[
        str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid scenario name")
    ],
):
    """
    Endpoint to retrieve the user assigned to a scenario.

    Path Parameters:
    - scenario_name: Name of the scenario.

    Returns user info or raises an HTTPException on error.
    """
    try:
        path = controller_requests.factory_requests_path("get_user_by_scenario_name", scenario_name=scenario_name)
        return await APIUtils.get(f"{DATABASE_API_URL}{path}")
    except Exception as e:
        logging.exception(f"Error obtaining user for scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(controller_requests.Routes.DISCOVER_VPN)
async def discover_vpn():
    """
    Calls the Tailscale CLI to fetch the current status in JSON format,
    extracts all IPv4 addresses (by filtering out any address containing “:”),
    and returns them as a JSON object {"ips": [...]}.
    """
    try:
        # 1) Launch the `tailscale status --json` subprocess
        proc = await asyncio.create_subprocess_exec(
            "tailscale", "status", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 2) Wait for it to finish and capture stdout/stderr
        out, err = await proc.communicate()
        if proc.returncode != 0:
            # If the CLI returned an error, raise to be caught below
            raise RuntimeError(err.decode())

        # 3) Parse the JSON output
        data = json.loads(out.decode())

        # 4) Collect only the IPv4 addresses from each peer
        ips = []
        for peer in data.get("Peer", {}).values():
            for ip in peer.get("TailscaleIPs", []):
                if ":" not in ip:
                    # Skip IPv6 entries (they contain colons)
                    ips.append(ip)

        # 5) Return the list of IPv4s
        return {"ips": ips}

    except Exception as e:
        # 6) Log any failure and respond with HTTP 500
        logging.error(f"Error discovering VPN devices: {e}")
        raise HTTPException(status_code=500, detail="No devices discovered")


@app.get(controller_requests.Routes.PHYSICAL_RUN, tags=["physical"])
async def physical_run(ip: str):
    status, data = await remote_get(ip, "/run/")

    if status == 200:
        return data
    if status is None:
        raise HTTPException(status_code=502, detail=f"Node unreachable: {data}")
    raise HTTPException(status_code=status, detail=data)


@app.get(controller_requests.Routes.PHYSICAL_STOP, tags=["physical"])
async def physical_stop(ip: str):
    status, data = await remote_get(ip, "/stop/")
    if status == 200:
        return data
    if status is None:
        raise HTTPException(status_code=502, detail=f"Node unreachable: {data}")
    raise HTTPException(status_code=status, detail=data)


@app.put(controller_requests.Routes.PHYSICAL_SETUP, tags=["physical"],
         status_code=status.HTTP_201_CREATED)
async def physical_setup(
    ip: str,
    config:      UploadFile = File(..., description="*.json* configuration file"),
    global_test: UploadFile = File(..., description="Global Dataset*.h5*"),
    train_set:   UploadFile = File(..., description="Training dataset*.h5*"),
):

    form = aiohttp.FormData()
    await config.seek(0)
    form.add_field("config", config.file,
                   filename=config.filename, content_type="application/json")
    await global_test.seek(0)
    form.add_field("global_test", global_test.file,
                   filename=global_test.filename, content_type="application/octet-stream")
    await train_set.seek(0)
    form.add_field("train_set", train_set.file,
                   filename=train_set.filename, content_type="application/octet-stream")

    status_code, data = await remote_post_form(
        ip, "/setup/", form, method="PUT"
    )

    if status_code == 201:
        return data
    if status_code is None:
        raise HTTPException(status_code=502, detail=f"Node unreachable: {data}")
    raise HTTPException(status_code=status_code, detail=data)

# ──────────────────────────────────────────────────────────────
# Physical · single-node state
# ──────────────────────────────────────────────────────────────
@app.get(controller_requests.Routes.PHYSICAL_STATE, tags=["physical"])
async def get_physical_node_state(ip: str):
    """
    Query a single Raspberry Pi (or other node) for its training state.

    Parameters
    ----------
    ip : str
        IP address or hostname of the node.

    Returns
    -------
    dict
        • running (bool) – True if a training process is active.
        • error   (str)  – Optional error message when the node is unreachable
                            or returns a non-200 HTTP status.
    """
    # Short global timeout so a dead node doesn't block the whole request
    timeout = aiohttp.ClientTimeout(total=3)            # seconds

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"http://{ip}/state/") as resp:
                if resp.status == 200:
                    # Forward the node's own JSON, expected to be {"running": bool}
                    return await resp.json()
                # Node responded but with an HTTP error code
                return {"running": False,
                        "error": f"HTTP {resp.status}"}
    except Exception as exc:
        # Network errors, timeouts, DNS failures, …
        return {"running": False, "error": str(exc)}


# ──────────────────────────────────────────────────────────────
# Physical · aggregate state for an entire scenario
# ──────────────────────────────────────────────────────────────
@app.get(controller_requests.Routes.PHYSICAL_SCENARIO_STATE, tags=["physical"])
async def get_physical_scenario_state(scenario_name: str):
    """
    Check the training state of *every* physical node assigned to a scenario.

    Parameters
    ----------
    scenario_name : str
        Scenario identifier.

    Returns
    -------
    dict
        {
          "running":       bool,            # True  ⇢ at least one node is training
          "nodes_state":   { ip: {...} },   # result from each /state/ call
          "all_available": bool             # True  ⇢ every node responded and
                                            #          none is training
        }
    """
    # 1) Retrieve scenario metadata and node list from the DB
    scenario = await get_scenario_by_name_endpoint(scenario_name)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    nodes = await list_nodes_by_scenario_name_endpoint(scenario_name)
    if not nodes:
        raise HTTPException(status_code=404, detail="No nodes found for scenario")

    # 2) Probe all nodes concurrently
    ips   = [n["ip"] for n in nodes]
    tasks = [get_physical_node_state(ip) for ip in ips]
    states = await asyncio.gather(*tasks)               # parallel HTTP calls

    # 3) Aggregate results
    nodes_state  = dict(zip(ips, states))
    any_running  = any(s.get("running") for s in states)
    # 'all_available' is true only if *every* node answered with running=False
    # *and* without an error field.
    all_available = all(
        (not s.get("running")) and (not s.get("error")) for s in states
    )

    return {
        "running": any_running,
        "nodes_state": nodes_state,
        "all_available": all_available,
    }


@app.post(controller_requests.Routes.USER_ADD)
async def add_user_controller(user: str = Body(...), password: str = Body(...), role: str = Body(...)):
    """
    Endpoint to add a new user to the database.

    Body Parameters:
    - user: Username.
    - password: Password for the new user.
    - role: Role assigned to the user (e.g., "admin", "user").

    Returns a success message or an error if the user could not be added.
    """
    try:
        payload = controller_requests.UserAddRequest(user=user, password=password, role=role).model_dump()
        path = controller_requests.factory_requests_path("add_user")
        return await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except Exception as e:
        logging.exception(f"Error adding user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error adding user: {e}")


@app.post(controller_requests.Routes.USER_DELETE)
async def remove_user_controller(user: str = Body(..., embed=True)):
    """
    Controller endpoint that inserts a new user into the database.

    Parameters:
    - user: The username for the new user.

    Returns a success message if the user is deleted, or an HTTP error if an exception occurs.
    """
    try:
        path = controller_requests.factory_requests_path("delete_user")
        payload = controller_requests.UserDeleteRequest(user=user).model_dump()
        return await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except Exception as e:
        logging.exception(f"Error deleting user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting user: {e}")


@app.post(controller_requests.Routes.USER_UPDATE)
async def update_user_controller(user: str = Body(...), password: str = Body(...), role: str = Body(...)):
    """
    Controller endpoint that modifies a user of the database.

    Parameters:
    - user: The username of the user.
    - password: The user's password.
    - role: The role of the user.

    Returns a success message if the user is updated, or an HTTP error if an exception occurs.
    """
    try:
        payload = controller_requests.UserUpdateRequest(user=user, password=password, role=role).model_dump()
        path = controller_requests.factory_requests_path("update_user")
        return await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except Exception as e:
        logging.exception(f"Error updating user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error updating user: {e}")


@app.post(controller_requests.Routes.USER_VERIFY)
async def verify_user_controller(user: str = Body(...), password: str = Body(...)):
    """
    Endpoint to verify user credentials.

    Body Parameters:
    - user: Username.
    - password: Password.

    Returns the user role on success or raises an error on failure.
    """
    try:
        payload = controller_requests.UserVerifyRequest(user=user, password=password).model_dump()
        path = controller_requests.factory_requests_path("verify_user")
        return await APIUtils.post(f"{DATABASE_API_URL}{path}", data=payload)
    except HTTPException as e:
        if e.status_code == 401:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from e
        logging.exception(f"Error verifying user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error verifying user: {e}")


if __name__ == "__main__":
    # Parse args from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5050, help="Port to run the controller on.")
    args = parser.parse_args()
    logging.info(f"Starting frontend on port {args.port}")
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=args.port)

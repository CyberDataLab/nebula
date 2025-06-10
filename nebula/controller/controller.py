import argparse
import asyncio
import datetime
import importlib
import logging
import os
import re
from typing import Annotated

import aiohttp
import psutil
import uvicorn
from fastapi import Body, FastAPI, HTTPException, Path, Request, status
from fastapi.concurrency import asynccontextmanager

from nebula.controller.database import scenario_set_all_status_to_finished, scenario_set_status_to_finished
from nebula.utils import DockerUtils


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


os.environ["NEBULA_CONTROLLER_NAME"] = os.environ.get("USER")


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
    databases_dir: str = os.environ.get("NEBULA_DATABASES_DIR")
    controller_log: str = os.environ.get("NEBULA_CONTROLLER_LOG")

    from nebula.controller.database import initialize_databases

    await initialize_databases(databases_dir)

    configure_logger(controller_log)

    yield


# Initialize FastAPI app outside the Controller class
app = FastAPI(lifespan=lifespan)


# Define endpoints outside the Controller class
@app.get("/")
async def read_root():
    """
    Root endpoint of the NEBULA Controller API.

    Returns:
        dict: A welcome message indicating the API is accessible.
    """
    return {"message": "Welcome to the NEBULA Controller API"}


@app.get("/status")
async def get_status():
    """
    Check the status of the NEBULA Controller API.

    Returns:
        dict: A status message confirming the API is running.
    """
    return {"status": "NEBULA Controller API is running"}


@app.get("/resources")
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


@app.get("/least_memory_gpu")
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


@app.get("/available_gpus/")
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


@app.post("/scenarios/run")
async def run_scenario(
    scenario_data: dict = Body(..., embed=True), role: str = Body(..., embed=True), user: str = Body(..., embed=True)
):
    """
    Launches a new scenario based on the provided configuration.

    Args:
        scenario_data (dict): The complete configuration of the scenario to be executed.
        role (str): The role of the user initiating the scenario.
        user (str): The username of the user initiating the scenario.

    Returns:
        str: The name of the scenario that was started.
    """

    import subprocess

    from nebula.controller.scenarios import ScenarioManagement

    # Manager for the actual scenario
    scenarioManagement = ScenarioManagement(scenario_data, user)

    await update_scenario(
        scenario_name=scenarioManagement.scenario_name,
        start_time=scenarioManagement.start_date_scenario,
        end_time="",
        scenario=scenario_data,
        status="running",
        role=role,
        username=user,
    )

    # Run the actual scenario
    try:
        if scenarioManagement.scenario.mobility:
            additional_participants = scenario_data["additional_participants"]
            schema_additional_participants = scenario_data["schema_additional_participants"]
            scenarioManagement.load_configurations_and_start_nodes(
                additional_participants, schema_additional_participants
            )
        else:
            scenarioManagement.load_configurations_and_start_nodes()
    except subprocess.CalledProcessError as e:
        logging.exception(f"Error docker-compose up: {e}")
        return

    return scenarioManagement.scenario_name


@app.post("/scenarios/stop")
async def stop_scenario(
    scenario_name: str = Body(..., embed=True),
    username: str = Body(..., embed=True),
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
    from nebula.controller.scenarios import ScenarioManagement

    ScenarioManagement.stop_participants(scenario_name)
    DockerUtils.remove_containers_by_prefix(f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_{username}-participant")
    DockerUtils.remove_docker_network(
        f"{(os.environ.get('NEBULA_CONTROLLER_NAME'))}_{str(username).lower()}-nebula-net-scenario"
    )
    try:
        if all:
            scenario_set_all_status_to_finished()
        else:
            scenario_set_status_to_finished(scenario_name)
    except Exception as e:
        logging.exception(f"Error setting scenario {scenario_name} to finished: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    # Generate statistics for the scenario
    # path = FileUtils.check_path(os.environ.get("NEBULA_LOGS_DIR"), scenario_name)
    # ScenarioManagement.generate_statistics(path)


@app.post("/scenarios/remove")
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
    from nebula.controller.database import remove_scenario_by_name
    from nebula.controller.scenarios import ScenarioManagement

    try:
        remove_scenario_by_name(scenario_name)
        ScenarioManagement.remove_files_by_scenario(scenario_name)
    except Exception as e:
        logging.exception(f"Error removing scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Scenario {scenario_name} removed successfully"}


@app.get("/scenarios/{user}/{role}")
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
    from nebula.controller.database import get_all_scenarios_and_check_completed, get_running_scenario

    try:
        scenarios = get_all_scenarios_and_check_completed(username=user, role=role)
        if role == "admin":
            scenario_running = get_running_scenario()
        else:
            scenario_running = get_running_scenario(username=user)
    except Exception as e:
        logging.exception(f"Error obtaining scenarios: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"scenarios": scenarios, "scenario_running": scenario_running}


@app.post("/scenarios/update")
async def update_scenario(
    scenario_name: str = Body(..., embed=True),
    start_time: str = Body(..., embed=True),
    end_time: str = Body(..., embed=True),
    scenario: dict = Body(..., embed=True),
    status: str = Body(..., embed=True),
    role: str = Body(..., embed=True),
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
        role (str): Role associated with the scenario.
        username (str): User performing the update.

    Returns:
        dict: A message confirming the update.
    """
    from nebula.controller.database import scenario_update_record
    from nebula.controller.scenarios import Scenario

    try:
        scenario = Scenario.from_dict(scenario)
        scenario_update_record(scenario_name, start_time, end_time, scenario, status, role, username)
    except Exception as e:
        logging.exception(f"Error updating scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Scenario {scenario_name} updated successfully"}


@app.post("/scenarios/set_status_to_finished")
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
    from nebula.controller.database import scenario_set_all_status_to_finished, scenario_set_status_to_finished

    try:
        if all:
            scenario_set_all_status_to_finished()
        else:
            scenario_set_status_to_finished(scenario_name)
    except Exception as e:
        logging.exception(f"Error setting scenario {scenario_name} to finished: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Scenario {scenario_name} status set to finished successfully"}


@app.get("/scenarios/running")
async def get_running_scenario(get_all: bool = False):
    """
    Retrieves the currently running scenario(s).

    Args:
        get_all (bool): If True, retrieves all running scenarios.

    Returns:
        dict or list: Running scenario(s) information.
    """
    from nebula.controller.database import get_running_scenario

    try:
        return get_running_scenario(get_all=get_all)
    except Exception as e:
        logging.exception(f"Error obtaining running scenario: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/scenarios/check/{role}/{scenario_name}")
async def check_scenario(
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
    from nebula.controller.database import check_scenario_with_role

    try:
        allowed = check_scenario_with_role(role, scenario_name)
        return {"allowed": allowed}
    except Exception as e:
        logging.exception(f"Error checking scenario with role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/scenarios/{scenario_name}")
async def get_scenario_by_name(
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
    from nebula.controller.database import get_scenario_by_name

    try:
        scenario = get_scenario_by_name(scenario_name)
    except Exception as e:
        logging.exception(f"Error obtaining scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return scenario


@app.get("/nodes/{scenario_name}")
async def list_nodes_by_scenario_name(
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
    from nebula.controller.database import list_nodes_by_scenario_name

    try:
        nodes = list_nodes_by_scenario_name(scenario_name)
    except Exception as e:
        logging.exception(f"Error obtaining nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return nodes


@app.post("/nodes/{scenario_name}/update")
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
    from nebula.controller.database import update_node_record

    try:
        config = await request.json()
        timestamp = datetime.datetime.now()
        # Update the node in database
        await update_node_record(
            str(config["device_args"]["uid"]),
            str(config["device_args"]["idx"]),
            str(config["network_args"]["ip"]),
            str(config["network_args"]["port"]),
            str(config["device_args"]["role"]),
            str(config["network_args"]["neighbors"]),
            str(config["mobility_args"]["latitude"]),
            str(config["mobility_args"]["longitude"]),
            str(timestamp),
            str(config["scenario_args"]["federation"]),
            str(config["federation_args"]["round"]),
            str(config["scenario_args"]["name"]),
            str(config["tracking_args"]["run_hash"]),
            str(config["device_args"]["malicious"]),
        )
    except Exception as e:
        logging.exception(f"Error updating nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    url = (
        f"http://{os.environ['NEBULA_CONTROLLER_NAME']}_nebula-frontend/platform/dashboard/{scenario_name}/node/update"
    )

    config["timestamp"] = str(timestamp)

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=config) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise HTTPException(status_code=response.status, detail="Error posting data")

    return {"message": "Nodes updated successfully in the database"}


@app.post("/nodes/{scenario_name}/done")
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
    url = f"http://{os.environ['NEBULA_CONTROLLER_NAME']}_nebula-frontend/platform/dashboard/{scenario_name}/node/done"

    data = await request.json()

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise HTTPException(status_code=response.status, detail="Error posting data")

    return {"message": "Nodes done"}


@app.post("/nodes/remove")
async def remove_nodes_by_scenario_name(scenario_name: str = Body(..., embed=True)):
    """
    Endpoint to remove all nodes associated with a scenario.

    Body Parameters:
    - scenario_name: Name of the scenario whose nodes should be removed.

    Returns a success message or an error if something goes wrong.
    """
    from nebula.controller.database import remove_nodes_by_scenario_name

    try:
        remove_nodes_by_scenario_name(scenario_name)
    except Exception as e:
        logging.exception(f"Error removing nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Nodes for scenario {scenario_name} removed successfully"}


@app.get("/notes/{scenario_name}")
async def get_notes_by_scenario_name(
    scenario_name: Annotated[
        str, Path(regex="^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Valid scenario name")
    ],
):
    """
    Endpoint to retrieve notes associated with a scenario.

    Path Parameters:
    - scenario_name: Name of the scenario.

    Returns the notes or raises an HTTPException on error.
    """
    from nebula.controller.database import get_notes

    try:
        notes = get_notes(scenario_name)
    except Exception as e:
        logging.exception(f"Error obtaining notes {notes}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return notes


@app.post("/notes/update")
async def update_notes_by_scenario_name(scenario_name: str = Body(..., embed=True), notes: str = Body(..., embed=True)):
    """
    Endpoint to update notes for a given scenario.

    Body Parameters:
    - scenario_name: Name of the scenario.
    - notes: Text content to store as notes.

    Returns a success message or an error if something goes wrong.
    """
    from nebula.controller.database import save_notes

    try:
        save_notes(scenario_name, notes)
    except Exception as e:
        logging.exception(f"Error updating notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Notes for scenario {scenario_name} updated successfully"}


@app.post("/notes/remove")
async def remove_notes_by_scenario_name(scenario_name: str = Body(..., embed=True)):
    """
    Endpoint to remove notes associated with a scenario.

    Body Parameters:
    - scenario_name: Name of the scenario.

    Returns a success message or an error if something goes wrong.
    """
    from nebula.controller.database import remove_note

    try:
        remove_note(scenario_name)
    except Exception as e:
        logging.exception(f"Error removing notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Notes for scenario {scenario_name} removed successfully"}


@app.get("/user/list")
async def list_users_controller(all_info: bool = False):
    """
    Endpoint to list all users in the database.

    Query Parameters:
    - all_info (bool): If True, returns full user info as dictionaries.

    Returns a list of users or raises an HTTPException on error.
    """
    from nebula.controller.database import list_users

    try:
        user_list = list_users(all_info)
        if all_info:
            # Convert each sqlite3.Row to a dictionary so that it is JSON serializable.
            user_list = [dict(user) for user in user_list]
        return {"users": user_list}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error retrieving users: {e}")


@app.get("/user/{scenario_name}")
async def get_user_by_scenario_name(
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
    from nebula.controller.database import get_user_by_scenario_name

    try:
        user = get_user_by_scenario_name(scenario_name)
    except Exception as e:
        logging.exception(f"Error obtaining user {user}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return user


@app.post("/user/add")
async def add_user_controller(user: str = Body(...), password: str = Body(...), role: str = Body(...)):
    """
    Endpoint to add a new user to the database.

    Body Parameters:
    - user: Username.
    - password: Password for the new user.
    - role: Role assigned to the user (e.g., "admin", "user").

    Returns a success message or an error if the user could not be added.
    """
    from nebula.controller.database import add_user

    try:
        add_user(user, password, role)
        return {"detail": "User added successfully"}
    except Exception as e:
        logging.exception(f"Error adding user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error adding user: {e}")


@app.post("/user/delete")
async def remove_user_controller(user: str = Body(..., embed=True)):
    """
    Controller endpoint that inserts a new user into the database.

    Parameters:
    - user: The username for the new user.

    Returns a success message if the user is deleted, or an HTTP error if an exception occurs.
    """
    from nebula.controller.database import delete_user_from_db

    try:
        delete_user_from_db(user)
        return {"detail": "User deleted successfully"}
    except Exception as e:
        logging.exception(f"Error deleting user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting user: {e}")


@app.post("/user/update")
async def update_user_controller(user: str = Body(...), password: str = Body(...), role: str = Body(...)):
    """
    Controller endpoint that modifies a user of the database.

    Parameters:
    - user: The username of the user.
    - password: The user's password.
    - role: The role of the user.

    Returns a success message if the user is updated, or an HTTP error if an exception occurs.
    """
    from nebula.controller.database import update_user

    try:
        update_user(user, password, role)
        return {"detail": "User updated successfully"}
    except Exception as e:
        logging.exception(f"Error updating user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error updating user: {e}")


@app.post("/user/verify")
async def verify_user_controller(user: str = Body(...), password: str = Body(...)):
    """
    Endpoint to verify user credentials.

    Body Parameters:
    - user: Username.
    - password: Password.

    Returns the user role on success or raises an error on failure.
    """
    from nebula.controller.database import get_user_info, list_users, verify

    try:
        user_submitted = user.upper()
        if (user_submitted in list_users()) and verify(user_submitted, password):
            user_info = get_user_info(user_submitted)
            return {"user": user_submitted, "role": user_info[2]}
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except Exception as e:
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

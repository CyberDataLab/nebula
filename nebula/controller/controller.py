import asyncio
import datetime
import importlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Annotated

import aiohttp
import docker
import psutil
import uvicorn
from dotenv import load_dotenv
from fastapi import Body, FastAPI, Request, status, HTTPException, Path
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from nebula.addons.env import check_environment
from nebula.config.config import Config
from nebula.config.mender import Mender
from nebula.controller.database import scenario_set_all_status_to_finished, scenario_set_status_to_finished
from nebula.controller.scenarios import Scenario, ScenarioManagement
from nebula.utils import DockerUtils, FileUtils, SocketUtils


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

os.environ["NEBULA_CONTROLLER_NAME"] = os.environ["USER"]

# Initialize FastAPI app outside the Controller class
app = FastAPI()

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
    scenario_data: dict = Body(..., embed=True),
    role: str = Body(..., embed=True),
    user: str = Body(..., embed=True)
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
        username=user
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
    all: bool = Body(False, embed=True)
):
    from nebula.controller.scenarios import ScenarioManagement

    ScenarioManagement.stop_participants(scenario_name)
    DockerUtils.remove_containers_by_prefix(f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_{username}-participant")
    DockerUtils.remove_docker_network(
        f"{(os.environ.get('NEBULA_CONTROLLER_NAME'))}_{str(username).lower()}-nebula-net-scenario"
    )
    ScenarioManagement.stop_blockchain()
    try:
        if all:
            scenario_set_all_status_to_finished()
        else:
            scenario_set_status_to_finished(scenario_name)
    except Exception as e:
        logging.error(f"Error setting scenario {scenario_name} to finished: {e}")
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

    try:
        remove_scenario_by_name(scenario_name)
        ScenarioManagement.remove_files_by_scenario(scenario_name)
    except Exception as e:
        logging.error(f"Error removing scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Scenario {scenario_name} removed successfully"}


@app.get("/scenarios/{user}/{role}")
async def get_scenarios(
    user: Annotated[
        str, 
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid username"
        )
    ],
    role: Annotated[
        str, 
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid role"
        )
    ]
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
        logging.error(f"Error obtaining scenarios: {e}")
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
    username: str = Body(..., embed=True)
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

    try:
        scenario = Scenario.from_dict(scenario)
        scenario_update_record(scenario_name, start_time, end_time, scenario, status, role, username)
    except Exception as e:
        logging.error(f"Error updating scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Scenario {scenario_name} updated successfully"}


@app.post("/scenarios/set_status_to_finished")
async def set_scenario_status_to_finished(
    scenario_name: str = Body(..., embed=True),
    all: bool = Body(False, embed=True)
):
    """
    Sets the status of a scenario (or all scenarios) to 'finished'.

    Args:
        scenario_name (str): Name of the scenario to mark as finished.
        all (bool): If True, sets all scenarios to finished.

    Returns:
        dict: A message confirming the operation.
    """
    from nebula.controller.database import scenario_set_status_to_finished, scenario_set_all_status_to_finished

    try:
        if all:
            scenario_set_all_status_to_finished()
        else:
            scenario_set_status_to_finished(scenario_name)
    except Exception as e:
        logging.error(f"Error setting scenario {scenario_name} to finished: {e}")
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
        logging.error(f"Error obtaining running scenario: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/scenarios/check/{role}/{scenario_name}")
async def check_scenario(
    role: Annotated[
        str, 
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid role"
        )
    ],
    scenario_name: Annotated[
        str,
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid scenario name"
        )
    ]
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
        logging.error(f"Error checking scenario with role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/scenarios/{scenario_name}")
async def get_scenario_by_name(
    scenario_name: Annotated[
        str,
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid scenario name"
        )
    ]
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
        logging.error(f"Error obtaining scenario {scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    
    return scenario


@app.get("/nodes/{scenario_name}")
async def list_nodes_by_scenario_name(
    scenario_name: Annotated[
        str,
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid scenario name"
        )
    ]
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
        logging.error(f"Error obtaining nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return nodes


@app.post("/nodes/{scenario_name}/update")
async def update_nodes(
    scenario_name: Annotated[
        str,
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid scenario name"
        ),
    ],
    request: Request
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
        logging.error(f"Error updating nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    
    port = os.environ["NEBULA_FRONTEND_PORT"]
    url = f"http://localhost:{port}/platform/dashboard/{scenario_name}/node/update"
    
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
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid scenario name"
        ),
    ],
    request: Request
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
    port = os.environ["NEBULA_FRONTEND_PORT"]
    url = f"http://localhost:{port}/platform/dashboard/{scenario_name}/node/done"
    
    data = await request.json()
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise HTTPException(status_code=response.status, detail="Error posting data")

    return {"message": "Nodes done"}   


@app.post("/nodes/remove")
async def remove_nodes_by_scenario_name(
    scenario_name: str = Body(..., embed=True)
):
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
        logging.error(f"Error removing nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Nodes for scenario {scenario_name} removed successfully"}


@app.get("/notes/{scenario_name}")
async def get_notes_by_scenario_name(
    scenario_name: Annotated[
        str,
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid scenario name"
        )
    ]
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
        logging.error(f"Error obtaining notes {notes}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    
    return notes


@app.post("/notes/update")
async def update_notes_by_scenario_name(
    scenario_name: str = Body(..., embed=True),
    notes: str = Body(..., embed=True)
):
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
        logging.error(f"Error updating notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    
    return {"message": f"Notes for scenario {scenario_name} updated successfully"}


@app.post("/notes/remove")
async def remove_notes_by_scenario_name(
    scenario_name: str = Body(..., embed=True)
):
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
        logging.error(f"Error removing notes: {e}")
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving users: {e}"
        )
    

@app.get("/user/{scenario_name}")
async def get_user_by_scenario_name(
    scenario_name: Annotated[
        str,
        Path(
            regex="^[a-zA-Z0-9_-]+$",
            min_length=1,
            max_length=50,
            description="Valid scenario name"
        )
    ]
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
        logging.error(f"Error obtaining user {user}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    
    return user


@app.post("/user/add")
async def add_user_controller(
    user: str = Body(...),
    password: str = Body(...),
    role: str = Body(...)
):
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
        logging.error(f"Error adding user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding user: {e}"
        )
    

@app.post("/user/delete")
async def remove_user_controller(
    user: str = Body(..., embed=True)
):
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
        logging.error(f"Error deleting user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting user: {e}"
        )
    

@app.post("/user/update")
async def add_user_controller(
    user: str = Body(...),
    password: str = Body(...),
    role: str = Body(...)
):
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
        logging.error(f"Error updating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating user: {e}"
        )
    

@app.post("/user/verify")
async def add_user_controller(
    user: str = Body(...),
    password: str = Body(...)
):
    """
    Endpoint to verify user credentials.

    Body Parameters:
    - user: Username.
    - password: Password.

    Returns the user role on success or raises an error on failure.
    """
    from nebula.controller.database import list_users, verify, get_user_info

    try:
        user_submitted = user.upper()
        if (user_submitted in list_users()) and verify(user_submitted, password):
            user_info = get_user_info(user_submitted)
            return {"user": user_submitted, "role": user_info[2]}
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except Exception as e:
        logging.error(f"Error verifying user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error verifying user: {e}"
        )


class NebulaEventHandler(PatternMatchingEventHandler):
    """
    NebulaEventHandler handles file system events for .sh scripts.

    This class monitors the creation, modification, and deletion of .sh scripts
    in a specified directory.
    """

    patterns = ["*.sh", "*.ps1"]

    def __init__(self):
        super(NebulaEventHandler, self).__init__()
        self.last_processed = {}
        self.timeout_ns = 5 * 1e9
        self.processing_files = set()
        self.lock = threading.Lock()

    def _should_process_event(self, src_path: str) -> bool:
        current_time_ns = time.time_ns()
        logging.info(f"Current time (ns): {current_time_ns}")
        with self.lock:
            if src_path in self.last_processed:
                logging.info(f"Last processed time for {src_path}: {self.last_processed[src_path]}")
                last_time = self.last_processed[src_path]
                if current_time_ns - last_time < self.timeout_ns:
                    return False
            self.last_processed[src_path] = current_time_ns
        return True

    def _is_being_processed(self, src_path: str) -> bool:
        with self.lock:
            if src_path in self.processing_files:
                logging.info(f"Skipping {src_path} as it is already being processed.")
                return True
            self.processing_files.add(src_path)
        return False

    def _processing_done(self, src_path: str):
        with self.lock:
            if src_path in self.processing_files:
                self.processing_files.remove(src_path)

    def verify_nodes_ports(self, src_path):
        parent_dir = os.path.dirname(src_path)
        base_dir = os.path.basename(parent_dir)
        scenario_path = os.path.join(os.path.dirname(parent_dir), base_dir)

        try:
            port_mapping = {}
            new_port_start = 50000

            participant_files = sorted(
                f for f in os.listdir(scenario_path) if f.endswith(".json") and f.startswith("participant")
            )

            for filename in participant_files:
                file_path = os.path.join(scenario_path, filename)
                with open(file_path) as json_file:
                    node = json.load(json_file)
                current_port = node["network_args"]["port"]
                port_mapping[current_port] = SocketUtils.find_free_port(start_port=new_port_start)
                logging.info(
                    f"Participant file: {filename} | Current port: {current_port} | New port: {port_mapping[current_port]}"
                )
                new_port_start = port_mapping[current_port] + 1

            for filename in participant_files:
                file_path = os.path.join(scenario_path, filename)
                with open(file_path) as json_file:
                    node = json.load(json_file)
                current_port = node["network_args"]["port"]
                node["network_args"]["port"] = port_mapping[current_port]
                neighbors = node["network_args"]["neighbors"]

                for old_port, new_port in port_mapping.items():
                    neighbors = neighbors.replace(f":{old_port}", f":{new_port}")

                node["network_args"]["neighbors"] = neighbors

                with open(file_path, "w") as f:
                    json.dump(node, f, indent=4)

        except Exception as e:
            print(f"Error processing JSON files: {e}")

    def on_created(self, event):
        """
        Handles the event when a file is created.
        """
        if event.is_directory:
            return
        src_path = event.src_path
        if not self._should_process_event(src_path):
            return
        if self._is_being_processed(src_path):
            return
        logging.info("File created: %s" % src_path)
        try:
            self.verify_nodes_ports(src_path)
            self.run_script(src_path)
        finally:
            self._processing_done(src_path)

    def on_deleted(self, event):
        """
        Handles the event when a file is deleted.
        """
        if event.is_directory:
            return
        src_path = event.src_path
        if not self._should_process_event(src_path):
            return
        if self._is_being_processed(src_path):
            return
        logging.info("File deleted: %s" % src_path)
        directory_script = os.path.dirname(src_path)
        pids_file = os.path.join(directory_script, "current_scenario_pids.txt")
        logging.info(f"Killing processes from {pids_file}")
        try:
            self.kill_script_processes(pids_file)
            os.remove(pids_file)
        except FileNotFoundError:
            logging.warning(f"{pids_file} not found.")
        except Exception as e:
            logging.exception(f"Error while killing processes: {e}")
        finally:
            self._processing_done(src_path)

    def run_script(self, script):
        try:
            logging.info(f"Running script: {script}")
            if script.endswith(".sh"):
                result = subprocess.run(["bash", script], capture_output=True, text=True)
                logging.info(f"Script output:\n{result.stdout}")
                if result.stderr:
                    logging.error(f"Script error:\n{result.stderr}")
            elif script.endswith(".ps1"):
                subprocess.Popen(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                )
            else:
                logging.error("Unsupported script format.")
                return
        except Exception as e:
            logging.exception(f"Error while running script: {e}")

    def kill_script_processes(self, pids_file):
        try:
            with open(pids_file) as f:
                pids = f.readlines()
                for pid in pids:
                    try:
                        pid = int(pid.strip())
                        if psutil.pid_exists(pid):
                            process = psutil.Process(pid)
                            children = process.children(recursive=True)
                            logging.info(f"Forcibly killing process {pid} and {len(children)} child processes...")
                            for child in children:
                                try:
                                    logging.info(f"Forcibly killing child process {child.pid}")
                                    child.kill()
                                except psutil.NoSuchProcess:
                                    logging.warning(f"Child process {child.pid} already terminated.")
                                except Exception as e:
                                    logging.exception(f"Error while forcibly killing child process {child.pid}: {e}")
                            try:
                                logging.info(f"Forcibly killing main process {pid}")
                                process.kill()
                            except psutil.NoSuchProcess:
                                logging.warning(f"Process {pid} already terminated.")
                            except Exception as e:
                                logging.exception(f"Error while forcibly killing main process {pid}: {e}")
                        else:
                            logging.warning(f"PID {pid} does not exist.")
                    except ValueError:
                        logging.exception(f"Invalid PID value in file: {pid}")
                    except Exception as e:
                        logging.exception(f"Error while forcibly killing process {pid}: {e}")
        except FileNotFoundError:
            logging.exception(f"PID file not found: {pids_file}")
        except Exception as e:
            logging.exception(f"Error while reading PIDs from file: {e}")


class Controller:
    def __init__(self, args):
        """
        Initializes the main controller class for the NEBULA system.

        Parses and stores all configuration values from the provided `args` object,
        which is expected to come from an argument parser (e.g., argparse).

        Parameters (from `args`):
        - scenario_name (str): Name of the current scenario.
        - federation (str): Federation type used in the simulation.
        - topology (str): Path to the topology file.
        - controllerport (int): Port for the controller service (default: 5000).
        - wafport (int): Port for the WAF service (default: 6000).
        - webport (int): Port for the frontend (default: 6060).
        - grafanaport (int): Port for Grafana (default: 6040).
        - lokiport (int): Port for Loki logs (default: 6010).
        - statsport (int): Port for the statistics module (default: 8080).
        - simulation (bool): Whether the scenario runs in simulation mode.
        - config (str): Path to the configuration directory.
        - databases (str): Path to the databases directory (default: /opt/nebula).
        - logs (str): Path to the log directory.
        - certs (str): Path to the certificates directory.
        - env (str): Path to the environment (venv, etc.).
        - production (bool): Whether the system is running in production mode.
        - advanced_analytics (bool): Whether advanced analytics are enabled.
        - matrix (str): Path to the evaluation matrix file.
        - root_path (str): Root path of the application.
        - network_subnet (str): Custom Docker network subnet.
        - network_gateway (str): Custom Docker network gateway.
        - use_blockchain (bool): Whether the blockchain component is enabled.

        This method also:
        - Sets platform type (`windows` or `unix`)
        - Configures logging
        - Dynamically selects free ports if the specified ones are in use
        - Initializes configuration and deployment objects
        """
        self.scenario_name = args.scenario_name if hasattr(args, "scenario_name") else None
        self.start_date_scenario = None
        self.federation = args.federation if hasattr(args, "federation") else None
        self.topology = args.topology if hasattr(args, "topology") else None
        self.controller_port = int(args.controllerport) if hasattr(args, "controllerport") else 5000
        self.waf_port = int(args.wafport) if hasattr(args, "wafport") else 6000
        self.frontend_port = int(args.webport) if hasattr(args, "webport") else 6060
        self.grafana_port = int(args.grafanaport) if hasattr(args, "grafanaport") else 6040
        self.loki_port = int(args.lokiport) if hasattr(args, "lokiport") else 6010
        self.statistics_port = int(args.statsport) if hasattr(args, "statsport") else 8080
        self.simulation = args.simulation
        self.config_dir = args.config
        self.databases_dir = args.databases if hasattr(args, "databases") else "/opt/nebula"
        self.log_dir = args.logs
        self.cert_dir = args.certs
        self.env_path = args.env
        self.production = args.production if hasattr(args, "production") else False
        self.advanced_analytics = args.advanced_analytics if hasattr(args, "advanced_analytics") else False
        self.matrix = args.matrix if hasattr(args, "matrix") else None
        self.root_path = (
            args.root_path
            if hasattr(args, "root_path")
            else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        self.host_platform = "windows" if sys.platform == "win32" else "unix"

        # Network configuration (nodes deployment in a network)
        self.network_subnet = args.network_subnet if hasattr(args, "network_subnet") else None
        self.network_gateway = args.network_gateway if hasattr(args, "network_gateway") else None

        # Configure logger
        self.configure_logger()

        # Check ports available
        if not SocketUtils.is_port_open(self.controller_port):
            self.controller_port = SocketUtils.find_free_port()

        if not SocketUtils.is_port_open(self.frontend_port):
            self.frontend_port = SocketUtils.find_free_port(self.controller_port + 1)

        if not SocketUtils.is_port_open(self.statistics_port):
            self.statistics_port = SocketUtils.find_free_port(self.frontend_port + 1)

        self.config = Config(entity="controller")
        self.topologymanager = None
        self.n_nodes = 0
        self.mender = None if self.simulation else Mender()
        self.use_blockchain = args.use_blockchain if hasattr(args, "use_blockchain") else False
        self.gpu_available = False

        # Reference the global app instance
        self.app = app

    def configure_logger(self):
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
        console_handler_file = logging.FileHandler(os.path.join(self.log_dir, "controller.log"), mode="a")
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
            handler = logging.FileHandler(os.path.join(self.log_dir, "controller.log"), mode="a")
            handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
            logger.addHandler(handler)

    def start(self):
        """
        Starts the NEBULA controller.

        - Displays the welcome banner.
        - Loads environment variables from the `.env` file.
        - Saves the process PID to 'controller.pid'.
        - Checks the environment and saves configuration to environment variables.
        - Launches the FastAPI app in a daemon thread.
        - Initializes databases.
        - In production mode, starts the WAF and logs WAF and Grafana ports.
        - Runs the frontend and logs its URL.
        - Starts a watchdog to monitor configuration directory changes.
        - If enabled, initializes the Mender module for artifact deployment.
        - Captures SIGTERM and SIGINT signals for graceful shutdown.
        - Keeps the process running until termination signal or Ctrl+C.
        """
        banner = """
                        ███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗
                        ████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗
                        ██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║
                        ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║
                        ██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║
                        ╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
                          A Platform for Decentralized Federated Learning
                            Created by Enrique Tomás Martínez Beltrán
                              https://github.com/CyberDataLab/nebula
                    """
        print("\x1b[0;36m" + banner + "\x1b[0m")

        # Load the environment variables
        load_dotenv(self.env_path)

        # Save controller pid
        with open(os.path.join(os.path.dirname(__file__), "controller.pid"), "w") as f:
            f.write(str(os.getpid()))

        # Check information about the environment
        check_environment()

        # Save the configuration in environment variables
        logging.info("Saving configuration in environment variables...")
        os.environ["NEBULA_ROOT"] = self.root_path
        os.environ["NEBULA_LOGS_DIR"] = self.log_dir
        os.environ["NEBULA_CONFIG_DIR"] = self.config_dir
        os.environ["NEBULA_CERTS_DIR"] = self.cert_dir
        os.environ["NEBULA_ROOT_HOST"] = self.root_path
        os.environ["NEBULA_HOST_PLATFORM"] = self.host_platform
        os.environ["NEBULA_CONTROLLER_HOST"] = "host.docker.internal"
        os.environ["NEBULA_STATISTICS_PORT"] = str(self.statistics_port)
        os.environ["NEBULA_CONTROLLER_PORT"] = str(self.controller_port)
        os.environ["NEBULA_FRONTEND_PORT"] = str(self.frontend_port)

        # Start the FastAPI app in a daemon thread
        app_thread = threading.Thread(target=self.run_controller_api, daemon=True)
        app_thread.start()
        logging.info(f"NEBULA Controller is running at port {self.controller_port}")

        from nebula.controller.database import initialize_databases

        asyncio.run(initialize_databases(self.databases_dir))

        if self.production:
            self.run_waf()
            logging.info(f"NEBULA WAF is running at port {self.waf_port}")
            logging.info(f"Grafana Dashboard is running at port {self.grafana_port}")

        self.run_frontend()
        logging.info(f"NEBULA Frontend is running at http://localhost:{self.frontend_port}")
        logging.info(f"NEBULA Databases created in {self.databases_dir}")

        # Watchdog for running additional scripts in the host machine (i.e. during the execution of a federation)
        event_handler = NebulaEventHandler()
        observer = Observer()
        observer.schedule(event_handler, path=self.config_dir, recursive=True)
        observer.start()

        if self.mender:
            logging.info("[Mender.module] Mender module initialized")
            time.sleep(2)
            mender = Mender()
            logging.info("[Mender.module] Getting token from Mender server: {}".format(os.getenv("MENDER_SERVER")))
            mender.renew_token()
            time.sleep(2)
            logging.info(
                "[Mender.module] Getting devices from {} with group Cluster_Thun".format(os.getenv("MENDER_SERVER"))
            )
            time.sleep(2)
            devices = mender.get_devices_by_group("Cluster_Thun")
            logging.info("[Mender.module] Getting a pool of devices: 5 devices")
            # devices = devices[:5]
            for i in self.config.participants:
                logging.info(
                    "[Mender.module] Device {} | IP: {}".format(i["device_args"]["idx"], i["network_args"]["ip"])
                )
                logging.info("[Mender.module] \tCreating artifacts...")
                logging.info("[Mender.module] \tSending NEBULA Core...")
                # mender.deploy_artifact_device("my-update-2.0.mender", i['device_args']['idx'])
                logging.info("[Mender.module] \tSending configuration...")
                time.sleep(5)
            sys.exit(0)

        logging.info("Press Ctrl+C for exit from NEBULA (global exit)")

        # Adjust signal handling inside the start method
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Closing NEBULA (exiting from components)... Please wait")
            observer.stop()
            self.stop()

        observer.join()

    def signal_handler(self, sig, frame):
        """
        Handler for termination signals (SIGTERM, SIGINT).

        - Logs signal reception.
        - Executes a graceful shutdown by calling self.stop().
        - Exits the process with sys.exit(0).

        Parameters:
        - sig: The signal number received.
        - frame: The current stack frame at signal reception.
        """
        logging.info("Received termination signal, shutting down...")
        self.stop()
        sys.exit(0)

    def run_controller_api(self):
        """
        Runs the FastAPI controller application using Uvicorn.

        - Binds to all network interfaces (0.0.0.0).
        - Uses the port specified in self.controller_port.
        - Disables Uvicorn's default logging configuration to use custom logging.
        """
        uvicorn.run(
            self.app,
            host="0.0.0.0",
            port=self.controller_port,
            log_config=None,  # Prevent Uvicorn from configuring logging
        )

    def run_waf(self):
        """
        Starts the Web Application Firewall (WAF) and related monitoring containers.

        - Creates a Docker network named based on the current user.
        - Starts the 'nebula-waf' container with logs volume and port mapping.
        - Starts the 'nebula-waf-grafana' container for monitoring dashboards,
          setting environment variables for Grafana configuration.
        - Starts the 'nebula-waf-loki' container for log aggregation with a config file.
        - Starts the 'nebula-waf-promtail' container to collect logs from nginx.

        All containers are connected to the same Docker network with assigned static IPs.
        """
        network_name = f"{os.environ['USER']}_nebula-net-base"
        base = DockerUtils.create_docker_network(network_name)

        client = docker.from_env()

        volumes_waf = ["/var/log/nginx"]

        ports_waf = [80]

        host_config_waf = client.api.create_host_config(
            binds=[f"{os.environ['NEBULA_LOGS_DIR']}/waf/nginx:/var/log/nginx"],
            privileged=True,
            port_bindings={80: self.waf_port},
        )

        networking_config_waf = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.200")
        })

        container_id_waf = client.api.create_container(
            image="nebula-waf",
            name=f"{os.environ['USER']}_nebula-waf",
            detach=True,
            volumes=volumes_waf,
            host_config=host_config_waf,
            networking_config=networking_config_waf,
            ports=ports_waf,
        )

        client.api.start(container_id_waf)

        environment = {
            "GF_SECURITY_ADMIN_PASSWORD": "admin",
            "GF_USERS_ALLOW_SIGN_UP": "false",
            "GF_SERVER_HTTP_PORT": "3000",
            "GF_SERVER_PROTOCOL": "http",
            "GF_SERVER_DOMAIN": f"localhost:{self.grafana_port}",
            "GF_SERVER_ROOT_URL": f"http://localhost:{self.grafana_port}/grafana/",
            "GF_SERVER_SERVE_FROM_SUB_PATH": "true",
            "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH": "/var/lib/grafana/dashboards/dashboard.json",
            "GF_METRICS_MAX_LIMIT_TSDB": "0",
        }

        ports = [3000]

        host_config = client.api.create_host_config(
            port_bindings={3000: self.grafana_port},
        )

        networking_config = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.201")
        })

        container_id = client.api.create_container(
            image="nebula-waf-grafana",
            name=f"{os.environ['USER']}_nebula-waf-grafana",
            detach=True,
            environment=environment,
            host_config=host_config,
            networking_config=networking_config,
            ports=ports,
        )

        client.api.start(container_id)

        command = ["-config.file=/mnt/config/loki-config.yml"]

        ports_loki = [3100]

        host_config_loki = client.api.create_host_config(
            port_bindings={3100: self.loki_port},
        )

        networking_config_loki = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.202")
        })

        container_id_loki = client.api.create_container(
            image="nebula-waf-loki",
            name=f"{os.environ['USER']}_nebula-waf-loki",
            detach=True,
            command=command,
            host_config=host_config_loki,
            networking_config=networking_config_loki,
            ports=ports_loki,
        )

        client.api.start(container_id_loki)

        volumes_promtail = ["/var/log/nginx"]

        host_config_promtail = client.api.create_host_config(
            binds=[
                f"{os.environ['NEBULA_LOGS_DIR']}/waf/nginx:/var/log/nginx",
            ],
        )

        networking_config_promtail = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.203")
        })

        container_id_promtail = client.api.create_container(
            image="nebula-waf-promtail",
            name=f"{os.environ['USER']}_nebula-waf-promtail",
            detach=True,
            volumes=volumes_promtail,
            host_config=host_config_promtail,
            networking_config=networking_config_promtail,
        )

        client.api.start(container_id_promtail)

    def run_frontend(self):
        """
        Starts the NEBULA frontend Docker container.

        - Checks if Docker is running (different checks for Windows and Unix).
        - Detects if an NVIDIA GPU is available and sets a flag.
        - Creates a Docker network named based on the current user.
        - Prepares environment variables and volume mounts for the container.
        - Binds ports for HTTP (80) and statistics (8080).
        - Starts the 'nebula-frontend' container connected to the created network
          with static IP assignment.
        """
        if sys.platform == "win32":
            if not os.path.exists("//./pipe/docker_Engine"):
                raise Exception(
                    "Docker is not running, please check if Docker is running and Docker Compose is installed."
                )
        else:
            if not os.path.exists("/var/run/docker.sock"):
                raise Exception(
                    "/var/run/docker.sock not found, please check if Docker is running and Docker Compose is installed."
                )

        try:
            subprocess.check_call(["nvidia-smi"])
            self.gpu_available = True
        except Exception:
            logging.info("No GPU available for the frontend, nodes will be deploy in CPU mode")

        network_name = f"{os.environ['USER']}_nebula-net-base"

        # Create the Docker network
        base = DockerUtils.create_docker_network(network_name)

        client = docker.from_env()

        environment = {
            "NEBULA_CONTROLLER_NAME": os.environ["USER"],
            "NEBULA_PRODUCTION": self.production,
            "NEBULA_GPU_AVAILABLE": self.gpu_available,
            "NEBULA_ADVANCED_ANALYTICS": self.advanced_analytics,
            "NEBULA_FRONTEND_LOG": "/nebula/app/logs/frontend.log",
            "NEBULA_LOGS_DIR": "/nebula/app/logs/",
            "NEBULA_CONFIG_DIR": "/nebula/app/config/",
            "NEBULA_CERTS_DIR": "/nebula/app/certs/",
            "NEBULA_ENV_PATH": "/nebula/app/.env",
            "NEBULA_ROOT_HOST": self.root_path,
            "NEBULA_HOST_PLATFORM": self.host_platform,
            "NEBULA_DEFAULT_USER": "admin",
            "NEBULA_DEFAULT_PASSWORD": "admin",
            "NEBULA_FRONTEND_PORT": self.frontend_port,
            "NEBULA_CONTROLLER_PORT": self.controller_port,
            "NEBULA_CONTROLLER_HOST": "host.docker.internal",
        }

        volumes = ["/nebula", "/var/run/docker.sock", "/etc/nginx/sites-available/default"]

        ports = [80, 8080]

        host_config = client.api.create_host_config(
            binds=[
                f"{self.root_path}:/nebula",
                "/var/run/docker.sock:/var/run/docker.sock",
                f"{self.root_path}/nebula/frontend/config/nebula:/etc/nginx/sites-available/default",
            ],
            extra_hosts={"host.docker.internal": "host-gateway"},
            port_bindings={80: self.frontend_port, 8080: self.statistics_port},
        )

        networking_config = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.100")
        })

        container_id = client.api.create_container(
            image="nebula-frontend",
            name=f"{os.environ['USER']}_nebula-frontend",
            detach=True,
            environment=environment,
            volumes=volumes,
            host_config=host_config,
            networking_config=networking_config,
            ports=ports,
        )

        client.api.start(container_id)

    @staticmethod
    def stop_waf():
        """
        Stops all running Docker containers whose names start with
        the pattern '<user>_nebula-waf'.

        This is used to cleanly shut down the WAF-related containers.
        """
        DockerUtils.remove_containers_by_prefix(f"{os.environ['USER']}_nebula-waf")

    @staticmethod
    def stop():
        """
        Gracefully shuts down the entire NEBULA system by performing the following steps:
        
        - Logs the shutdown initiation.
        - Removes all Docker containers with names starting with '<user>_'.
        - Stops blockchain services and participant nodes via ScenarioManagement.
        - Stops the WAF containers by calling stop_waf().
        - Removes Docker networks with names starting with '<user>_'.
        - Attempts to kill the controller process using its PID stored in 'controller.pid'.
        - Handles any exceptions during PID reading or killing by logging them.
        - Exits the program with status code 0.
        """
        logging.info("Closing NEBULA (exiting from components)... Please wait")
        DockerUtils.remove_containers_by_prefix(f"{os.environ['USER']}_")
        ScenarioManagement.stop_blockchain()
        ScenarioManagement.stop_participants()
        Controller.stop_waf()
        DockerUtils.remove_docker_networks_by_prefix(f"{os.environ['USER']}_")
        controller_pid_file = os.path.join(os.path.dirname(__file__), "controller.pid")
        try:
            with open(controller_pid_file) as f:
                pid = int(f.read())
                os.kill(pid, signal.SIGKILL)
                os.remove(controller_pid_file)
        except Exception as e:
            logging.exception(f"Error while killing controller process: {e}")
        sys.exit(0)

import argparse
import asyncio
import datetime
import io
import json
import logging
import os
import signal
import sys
import time
import zipfile
from urllib.parse import urlencode

import aiohttp
import requests
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


class Settings:
    """
    Configuration settings for the Nebula application, loaded from environment variables with sensible defaults.
    
    Attributes:
        controller_host (str): Hostname or IP address of the Nebula controller service.
        controller_port (int): Port on which the Nebula controller listens (default: 5000).
        resources_threshold (float): Threshold for resource usage alerts (default: 0.0).
        port (int): Port for the Nebula frontend service (default: 6060).
        production (bool): Whether the application is running in production mode.
        gpu_available (bool): Whether GPU resources are available.
        advanced_analytics (bool): Whether advanced analytics features are enabled.
        host_platform (str): Underlying host operating platform (e.g., 'unix').
        log_dir (str): Directory path where application logs are stored.
        config_dir (str): Directory path for general configuration files.
        cert_dir (str): Directory path for SSL/TLS certificates.
        root_host_path (str): Root path on the host for volume mounting.
        config_frontend_dir (str): Subdirectory for frontend-specific configuration (default: 'config').
        env_file (str): Path to the environment file to load additional variables (default: '.env').
        statistics_port (int): Port for the statistics/metrics endpoint (default: 8080).
        PERMANENT_SESSION_LIFETIME (datetime.timedelta): Duration for session permanence (default: 60 minutes).
        templates_dir (str): Directory name containing template files (default: 'templates').
        frontend_log (str): File path for the frontend log output.
    """
    controller_host: str = os.environ.get("NEBULA_CONTROLLER_HOST")
    controller_port: int = os.environ.get("NEBULA_CONTROLLER_PORT", 5000)
    resources_threshold: float = 0.0
    port: int = os.environ.get("NEBULA_FRONTEND_PORT", 6060)
    production: bool = os.environ.get("NEBULA_PRODUCTION", "False") == "True"
    gpu_available: bool = os.environ.get("NEBULA_GPU_AVAILABLE", "False") == "True"
    advanced_analytics: bool = os.environ.get("NEBULA_ADVANCED_ANALYTICS", "False") == "True"
    host_platform: str = os.environ.get("NEBULA_HOST_PLATFORM", "unix")
    log_dir: str = os.environ.get("NEBULA_LOGS_DIR")
    config_dir: str = os.environ.get("NEBULA_CONFIG_DIR")
    cert_dir: str = os.environ.get("NEBULA_CERTS_DIR")
    root_host_path: str = os.environ.get("NEBULA_ROOT_HOST")
    config_frontend_dir: str = os.environ.get("NEBULA_CONFIG_FRONTEND_DIR", "config")
    env_file: str = os.environ.get("NEBULA_ENV_PATH", ".env")
    statistics_port: int = os.environ.get("NEBULA_STATISTICS_PORT", 8080)
    PERMANENT_SESSION_LIFETIME: datetime.timedelta = datetime.timedelta(minutes=60)
    templates_dir: str = "templates"
    frontend_log: str = os.environ.get("NEBULA_FRONTEND_LOG", "/nebula/app/logs/frontend.log")


settings = Settings()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.frontend_log, mode="w"),
    ],
)

uvicorn_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access"]
for logger_name in uvicorn_loggers:
    logger = logging.getLogger(logger_name)
    logger.propagate = False  # Prevent duplicate logs
    handler = logging.FileHandler(settings.frontend_log, mode="a")
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
    logger.addHandler(handler)

if os.path.exists(settings.env_file):
    logging.info(f"Loading environment variables from {settings.env_file}")
    load_dotenv(settings.env_file, override=True)

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from nebula.utils import DockerUtils, FileUtils

logging.info(f"🚀  Starting Nebula Frontend on port {settings.port}")

logging.info(f"NEBULA_PRODUCTION: {settings.production}")

if "SECRET_KEY" not in os.environ:
    logging.info("Generating SECRET_KEY")
    os.environ["SECRET_KEY"] = os.urandom(24).hex()
    logging.info(f"Saving SECRET_KEY to {settings.env_file}")
    with open(settings.env_file, "a") as f:
        f.write(f"SECRET_KEY={os.environ['SECRET_KEY']}\n")
else:
    logging.info("SECRET_KEY already set")

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY"),
    session_cookie=f"session_{os.environ.get('NEBULA_FRONTEND_PORT')}",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/platform/static", StaticFiles(directory="static"), name="static")


class ConnectionManager:
    """
    Manages WebSocket client connections, broadcasts messages to all connected clients, and retains a history of exchanged messages.

    Attributes:
        historic_messages (dict[str, dict]): Stores each received or broadcast message keyed by timestamp (formatted as "%Y-%m-%d %H:%M:%S").
        active_connections (list[WebSocket]): List of currently open WebSocket connections.

    Methods:
        async connect(websocket: WebSocket):
            Accepts a new WebSocket connection, registers it, and broadcasts a control message indicating the new client count.
        disconnect(websocket: WebSocket):
            Removes the specified WebSocket from the active connections list if present.
        add_message(message: str):
            Parses the incoming JSON-formatted message string, timestamps it, and adds it to historic_messages.
        async send_personal_message(message: str, websocket: WebSocket):
            Sends a text message to a single WebSocket; on connection closure, cleans up the connection.
        async broadcast(message: str):
            Logs the message via add_message, then iterates through active_connections to send the message to all clients;
            collects and removes any connections that have been closed or error out, logging exceptions as needed.
        get_historic() -> dict[str, dict]:
            Returns the full history of timestamped messages.
    """
    def __init__(self):
        self.historic_messages = {}
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        message = {
            "type": "control",
            "message": f"Client #{len(self.active_connections)} connected",
        }
        try:
            await self.broadcast(json.dumps(message))
        except:
            pass

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    def add_message(self, message):
        current_timestamp = datetime.datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S")
        self.historic_messages.update({current_timestamp: json.loads(message)})

    async def send_personal_message(self, message: str, websocket: WebSocket):
        try:
            await websocket.send_text(message)
        except RuntimeError:
            # Connection was closed, remove it from active connections
            self.disconnect(websocket)

    async def broadcast(self, message: str):
        self.add_message(message)
        disconnected_websockets = []

        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except RuntimeError:
                # Mark connection for removal
                disconnected_websockets.append(connection)
            except Exception as e:
                logging.exception(f"Error broadcasting message: {e}")
                disconnected_websockets.append(connection)

        # Remove disconnected websockets
        for websocket in disconnected_websockets:
            self.disconnect(websocket)

    def get_historic(self):
        return self.historic_messages


manager = ConnectionManager()


@app.websocket("/platform/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    """
    WebSocket endpoint for real-time chat at /platform/ws/{client_id}.

    Parameters:
        websocket (WebSocket): The client’s WebSocket connection instance.
        client_id (int): Unique identifier for the connecting client.

    Functionality:
        - On connection: registers the client via manager.connect(websocket).
        - Message loop: awaits incoming text frames, wraps each in a control message including the client_id, and broadcasts to all active clients using manager.broadcast().
        - On WebSocketDisconnect: deregisters the client via manager.disconnect(websocket) and broadcasts a “client left” control message.
        - Error handling: logs exceptions during broadcast or any unexpected WebSocket errors, ensuring the connection is cleaned up on failure.
    """
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = {
                "type": "control",
                "message": f"Client #{client_id} says: {data}",
            }
            try:
                await manager.broadcast(json.dumps(message))
            except Exception as e:
                logging.exception(f"Error broadcasting message: {e}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        try:
            message = {"type": "control", "message": f"Client #{client_id} left the chat"}
            await manager.broadcast(json.dumps(message))
        except Exception as e:
            logging.exception(f"Error broadcasting disconnect message: {e}")
    except Exception as e:
        logging.exception(f"WebSocket error: {e}")
        manager.disconnect(websocket)


templates = Jinja2Templates(directory=settings.templates_dir)


def datetimeformat(value, format="%B %d, %Y %H:%M"):
    """
    Formats a datetime string into a specified output format.

    Parameters:
        value (str): Input datetime string in "%Y-%m-%d %H:%M:%S" format.
        format (str): Desired output datetime format (default: "%B %d, %Y %H:%M").

    Returns:
        str: The datetime string formatted according to the provided format.
    """
    return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime(format)


def add_global_context(request: Request):
    """
    Add global context variables for template rendering.

    Parameters:
        request (Request): The incoming request object.

    Returns:
        dict[str, bool]: 
            is_production: Flag indicating if the application is running in production mode.
    """
    return {
        "is_production": settings.production,
    }


templates.env.filters["datetimeformat"] = datetimeformat
templates.env.globals.update(add_global_context=add_global_context)


def get_session(request: Request) -> dict:
    """
    Retrieve the session data associated with the incoming request.

    Parameters:
        request (Request): The HTTP request object containing session information.

    Returns:
        dict: The session data dictionary stored in the request.
    """
    return request.session


class UserData:
    """
    Holds runtime state and synchronization events for user-specific scenario execution.

    Attributes:
        nodes_registration (dict): Mapping of node identifiers to their registration data.
        scenarios_list (list): Ordered list of scenario identifiers or objects to be executed.
        scenarios_list_length (int): Total number of scenarios in scenarios_list.
        scenarios_finished (int): Count of scenarios that have completed execution.
        nodes_finished (list): List of node identifiers that have finished processing.
        stop_all_scenarios_event (asyncio.Event): Event used to signal all scenarios should be halted.
        finish_scenario_event (asyncio.Event): Event used to signal a single scenario has finished.
    """
    def __init__(self):
        self.nodes_registration = {}
        self.scenarios_list = []
        self.scenarios_list_length = 0
        self.scenarios_finished = 0
        self.nodes_finished = []
        self.stop_all_scenarios_event = asyncio.Event()
        self.finish_scenario_event = asyncio.Event()


user_data_store = {}


# Detect CTRL+C from parent process
async def signal_handler(signal, frame):
    """
    Asynchronous signal handler for Ctrl+C (SIGINT) in the frontend.

    Logs the interrupt event, schedules all scenarios to be marked as finished by creating an asyncio task for `scenario_set_status_to_finished(all=True)`, and then exits the process.

    Parameters:
        signal (int): The signal number received (e.g., signal.SIGINT).
        frame (types.FrameType): The current stack frame at the moment the signal was handled.
    """
    logging.info("You pressed Ctrl+C [frontend]!")
    asyncio.get_event_loop().create_task(scenario_set_status_to_finished(all=True))
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Custom HTTP exception handler for Starlette applications.

    Parameters:
        request (Request): The incoming HTTP request object.
        exc (StarletteHTTPException): The HTTP exception instance containing the status code to handle.

    Functionality:
        - Builds a context dict with the request and its session.
        - For specific HTTP status codes (401, 403, 404, 405, 413), returns a TemplateResponse rendering the corresponding error page and status.
        - For all other status codes, delegates to the application's default exception handler.

    Returns:
        Response: Either a TemplateResponse for the matched error code or the default exception handler’s response.
    """
    context = {"request": request, "session": request.session}
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return templates.TemplateResponse("401.html", context, status_code=exc.status_code)
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        return templates.TemplateResponse("403.html", context, status_code=exc.status_code)
    elif exc.status_code == status.HTTP_404_NOT_FOUND:
        return templates.TemplateResponse("404.html", context, status_code=exc.status_code)
    elif exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        return templates.TemplateResponse("405.html", context, status_code=exc.status_code)
    elif exc.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE:
        return templates.TemplateResponse("413.html", context, status_code=exc.status_code)
    return await request.app.default_exception_handler(request, exc)


async def controller_get(url):
    """
    Fetch JSON data from a remote controller endpoint via asynchronous HTTP GET.

    Parameters:
        url (str): The full URL of the controller API endpoint.

    Returns:
        Any: Parsed JSON response when the HTTP status code is 200.

    Raises:
        HTTPException: If the response status is not 200, raises with the response status code and an error detail.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise HTTPException(status_code=response.status, detail="Error fetching data")
            

async def controller_post(url, data=None):
    """
    Asynchronously send a JSON payload via HTTP POST to a controller endpoint and parse the response.

    Parameters:
        url (str): The full URL of the controller API endpoint.
        data (Any, optional): JSON-serializable payload to include in the POST request (default: None).

    Returns:
        Any: Parsed JSON response when the HTTP status code is 200.

    Raises:
        HTTPException: If the response status is not 200, with the status code and an error detail.
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise HTTPException(status_code=response.status, detail="Error posting data")
            

async def get_available_gpus():
    """
    Fetch the list of available GPUs from the controller service.

    Returns:
        Any: Parsed JSON response containing available GPU information.

    Raises:
        HTTPException: If the underlying HTTP request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/available_gpus"
    return await controller_get(url)


async def get_least_memory_gpu():
    """
    Fetch the GPU with the least memory usage from the controller service.

    Returns:
        Any: Parsed JSON response with details of the GPU having the least memory usage.

    Raises:
        HTTPException: If the underlying HTTP request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/least_memory_gpu"
    return await controller_get(url)


async def deploy_scenario(scenario_data, role, user):
    """
    Deploy a new scenario on the controller with the given parameters.

    Parameters:
        scenario_data (Any): Data payload describing the scenario to run.
        role (str): Role identifier for the scenario execution.
        user (str): Username initiating the deployment.

    Returns:
        Any: Parsed JSON response confirming scenario deployment.

    Raises:
        HTTPException: If the underlying HTTP POST request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/scenarios/run"
    data = {"scenario_data": scenario_data, "role": role, "user": user}
    return await controller_post(url, data)


async def stop_scenario_by_name(scenario_name, username, all=False):
    """
    Stops a running scenario via the NEBULA controller.

    This function sends an HTTP POST request to the controller to stop a specific scenario.
    It can stop only the nodes associated with a particular user, or all nodes in the scenario
    if specified.

    Args:
        scenario_name (str): The name of the scenario to be stopped.
        username (str): The username requesting the scenario to be stopped.
        all (bool, optional): If True, stops all nodes in the scenario regardless of the user.
            Defaults to False.

    Returns:
        dict: Response from the controller indicating the result of the operation.

    Raises:
        HTTPException: If the request to the controller fails or returns an error.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/scenarios/stop"
    data = {"scenario_name": scenario_name, "username": username, "all": all}
    return await controller_post(url, data)


async def get_scenarios(user, role):
    """
    Retrieve all scenarios available for a specific user and role.

    Parameters:
        user (str): Username to query scenarios for.
        role (str): Role identifier to filter scenarios.

    Returns:
        Any: Parsed JSON response listing available scenarios.

    Raises:
        HTTPException: If the underlying HTTP GET request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/scenarios/{user}/{role}"
    return await controller_get(url)


async def scenario_update_record(scenario_name, start_time, end_time, scenario, status, role, username):
    """
    Update the record of a scenario’s execution status on the controller.

    Parameters:
        scenario_name (str): Unique name of the scenario.
        start_time (str): ISO-formatted start timestamp.
        end_time (str): ISO-formatted end timestamp.
        scenario (Any): Scenario payload or identifier.
        status (str): New status value (e.g., 'running', 'finished').
        role (str): Role associated with the scenario.
        username (str): User who ran or updated the scenario.

    Raises:
        HTTPException: If the underlying HTTP POST request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/scenarios/update"
    data = {"scenario_name": scenario_name, "start_time": start_time, "end_time": end_time, "scenario": scenario, "status": status, "role": role, "username": username}
    await controller_post(url, data)


async def scenario_set_status_to_finished(scenario_name, all=False):
    """
    Mark one or all scenarios as finished on the controller.

    Parameters:
        scenario_name (str): Name of the scenario to update.
        all (bool): If True, mark all scenarios as finished; otherwise only the named one.

    Raises:
        HTTPException: If the underlying HTTP POST request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/scenarios/set_status_to_finished"
    data = {"scenario_name": scenario_name, "all": all}
    await controller_post(url, data)


async def remove_scenario_by_name(scenario_name):
    """
    Remove a scenario by name from the controller’s records.

    Parameters:
        scenario_name (str): Name of the scenario to remove.

    Raises:
        HTTPException: If the underlying HTTP POST request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/scenarios/remove"
    data = {"scenario_name": scenario_name}
    await controller_post(url, data)


async def check_scenario_with_role(role, scenario_name):
    """
    Check if a specific scenario is allowed for the session's role.

    Parameters:
        session (dict): Session data containing at least a 'role' key.
        scenario_name (str): Name of the scenario to check.

    Returns:
        bool: True if the scenario is allowed for the role, False otherwise.

    Raises:
        HTTPException: If the underlying HTTP GET request fails.
    """
    url = (
                f"http://{settings.controller_host}:{settings.controller_port}/scenarios/check/{role}/{scenario_name}"
            )
    check_data = await controller_get(url)
    return check_data.get("allowed", False)
            
            
async def get_scenario_by_name(scenario_name):
    """
    Fetch the details of a scenario by name from the controller.

    Parameters:
        scenario_name (str): Name of the scenario to retrieve.

    Returns:
        Any: Parsed JSON response with scenario details.

    Raises:
        HTTPException: If the underlying HTTP GET request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/scenarios/{scenario_name}"
    return await controller_get(url)


async def get_running_scenarios(get_all=False):
    """
    Retrieve a list of currently running scenarios.

    Parameters:
        get_all (bool): If True, include all running scenarios; if False, apply default filtering.

    Returns:
        Any: Parsed JSON response listing running scenarios.

    Raises:
        HTTPException: If the underlying HTTP GET request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/scenarios/running?get_all={get_all}"
    return await controller_get(url)


async def list_nodes_by_scenario_name(scenario_name):
    """
    List all nodes associated with a given scenario.
    
    Parameters:
        scenario_name (str): Name of the scenario to list nodes for.
    
    Returns:
        Any: Parsed JSON response containing node details.
    
    Raises:
        HTTPException: If the underlying HTTP GET request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/nodes/{scenario_name}"
    return await controller_get(url)


async def update_node_record(uid, idx, ip, port, role, neighbors, latitude, longitude, timestamp, federation, round_number, scenario_name, run_hash, malicious):
    """
    Update the record of a node’s state on the controller.

    Parameters:
        uid (str): Unique node identifier.
        idx (int): Node index within the scenario.
        ip (str): Node IP address.
        port (int): Node port number.
        role (str): Node role in the scenario.
        neighbors (Any): Neighboring node references.
        latitude (float): Node’s latitude coordinate.
        longitude (float): Node’s longitude coordinate.
        timestamp (str): ISO-formatted timestamp of the update.
        federation (str): Federation identifier.
        round_number (int): Current round number in the scenario.
        scenario_name (str): Name of the scenario.
        run_hash (str): Unique hash for this scenario run.
        malicious (bool): Flag indicating if the node is malicious.

    Raises:
        HTTPException: If the underlying HTTP POST request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/nodes/update"
    data = {
        "node_uid": uid,
        "node_idx": idx,
        "node_ip": ip,
        "node_port": port,
        "node_role": role,
        "node_neighbors": neighbors,
        "node_latitude": latitude,
        "node_longitude": longitude,
        "node_timestamp": timestamp,
        "node_federation": federation,
        "node_round": round_number,
        "node_scenario_name": scenario_name,
        "node_run_hash": run_hash,
        "malicious": malicious,
    }
    await controller_post(url, data)


async def remove_nodes_by_scenario_name(scenario_name):
    """
    Remove all nodes associated with a scenario from the controller records.

    Parameters:
        scenario_name (str): Name of the scenario whose nodes should be removed.

    Raises:
        HTTPException: If the underlying HTTP POST request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/nodes/remove"
    data = {"scenario_name": scenario_name}
    await controller_post(url, data)


async def get_notes(scenario_name):
    """
    Fetch saved notes for a specific scenario.

    Parameters:
        scenario_name (str): Name of the scenario to retrieve notes for.

    Returns:
        Any: Parsed JSON response containing the notes.

    Raises:
        HTTPException: If the underlying HTTP GET request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/notes/{scenario_name}"
    return await controller_get(url)


async def save_notes(scenario_name, notes):
    """
    Save or update notes for a specific scenario on the controller.

    Parameters:
        scenario_name (str): Name of the scenario to attach notes to.
        notes (Any): Content of the notes to be saved.

    Raises:
        HTTPException: If the underlying HTTP POST request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/notes/update"
    data = {"scenario_name": scenario_name, "notes": notes}
    await controller_post(url, data)


async def remove_note(scenario_name):
    """
    Remove notes for a specific scenario from the controller.
    
    Parameters:
        scenario_name (str): Name of the scenario whose notes should be removed.
    
    Raises:
        HTTPException: If the underlying HTTP POST request fails.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/notes/remove"
    data = {"scenario_name": scenario_name}
    await controller_post(url, data)


async def list_users(allinfo=True):
    """
    Retrieves the list of users by calling the controller endpoint.
    
    Parameters:
    - all_info (bool): If True, retrieves detailed information for each user.
    
    Returns:
    - A list of users, as provided by the controller.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/user/list?all_info={allinfo}"
    data = await controller_get(url)
    user_list = data["users"]

    return user_list


async def get_user_by_scenario_name(scenario_name):
    """
    Fetch user data for a given scenario from the controller.

    Parameters:
    - scenario_name (str): The name of the scenario whose user data to retrieve.

    Returns:
    - dict: The user data associated with the specified scenario.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/user/{scenario_name}"
    return await controller_get(url)


async def add_user(user, password, role):
    """
    Create a new user via the controller endpoint.

    Parameters:
    - user (str): The username for the new user.
    - password (str): The password for the new user.
    - role (str): The role assigned to the new user.

    Returns:
    - None
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/user/add"
    data = {"user": user, "password": password, "role": role}
    await controller_post(url, data)


async def update_user(user, password, role):
    """
    Update an existing user's credentials and role via the controller endpoint.

    Parameters:
    - user (str): The username of the user to update.
    - password (str): The new password for the user.
    - role (str): The new role to assign to the user.

    Returns:
    - None
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/user/update"
    data = {"user": user, "password": password, "role": role}
    await controller_post(url, data)


async def delete_user(user):
    """
    Delete an existing user via the controller endpoint.

    Parameters:
    - user (str): The username of the user to delete.

    Returns:
    - None
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/user/delete"
    data = {"user": user}
    await controller_post(url, data)


async def verify_user(user, password):
    """
    Verify a user's credentials against the controller.

    Parameters:
    - user (str): The username to verify.
    - password (str): The password to verify for the user.

    Returns:
    - dict: The verification result from the controller, typically including authentication status.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/user/verify"
    data = {"user": user, "password": password}
    return await controller_post(url, data)


@app.get("/", response_class=HTMLResponse)
async def index():
    """
    Handle root path by redirecting to the platform home page.

    Returns:
        RedirectResponse: Redirects client to the '/platform' endpoint.
    """
    return RedirectResponse(url="/platform")


@app.get("/platform", response_class=HTMLResponse)
@app.get("/platform/", response_class=HTMLResponse)
async def nebula_home(request: Request):
    """
    Render the Nebula platform home page.

    Parameters:
        request (Request): FastAPI request object.

    Returns:
        HTMLResponse: Rendered 'index.html' template with alerts context.
    """
    alerts = []
    return templates.TemplateResponse("index.html", {"request": request, "alerts": alerts})


@app.get("/platform/historic")
async def nebula_ws_historic(session: dict = Depends(get_session)):
    """
    Retrieve historical data for admin users.

    Parameters:
        session (dict): Session data extracted via dependency.

    Returns:
        JSONResponse: Historical data if available, otherwise an error message.
    """
    if session.get("role") == "admin":
        historic = manager.get_historic()
        if historic:
            pretty_historic = historic
            return JSONResponse(content=pretty_historic)
        else:
            return JSONResponse({"status": "error", "message": "Historic not found"})


@app.get("/platform/dashboard/{scenario_name}/private", response_class=HTMLResponse)
async def nebula_dashboard_private(request: Request, scenario_name: str, session: dict = Depends(get_session)):
    """
    Render the private scenario dashboard for authenticated users.

    Parameters:
        request (Request): FastAPI request object.
        scenario_name (str): Name of the scenario to display.
        session (dict): Session data extracted via dependency.

    Returns:
        HTMLResponse: Rendered 'private.html' template with scenario context.

    Raises:
        HTTPException: 401 Unauthorized if the user is not authenticated.
    """
    if "user" in session:
        return templates.TemplateResponse("private.html", {"request": request, "scenario_name": scenario_name})
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.get("/platform/admin", response_class=HTMLResponse)
async def nebula_admin(request: Request, session: dict = Depends(get_session)):
    """
    Render the admin interface showing a list of users for admin role.

    Parameters:
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.

    Returns:
        HTMLResponse: Rendered 'admin.html' template with user table context.

    Raises:
        HTTPException: 401 Unauthorized if the user is not an admin.
    """
    if session.get("role") == "admin":
        user_list = await list_users()
        
        user_table = zip(
            range(1, len(user_list) + 1),
            [user["user"] for user in user_list],
            [user["role"] for user in user_list],
            strict=False,
        )
        return templates.TemplateResponse("admin.html", {"request": request, "users": user_table})
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.post("/platform/dashboard/{scenario_name}/save_note")
async def save_note_for_scenario(scenario_name: str, request: Request, session: dict = Depends(get_session)):
    """
    Save notes for a specific scenario for authenticated users.

    Parameters:
        scenario_name (str): Name of the scenario.
        request (Request): FastAPI request object containing JSON payload.
        session (dict): Session data extracted via dependency.

    Returns:
        JSONResponse: {"status": "success"} on success, or error message on failure.
    """
    if "user" in session:
        data = await request.json()
        notes = data["notes"]
        try:
            await save_notes(scenario_name, notes)
            return JSONResponse({"status": "success"})
        except Exception as e:
            logging.exception(e)
            return JSONResponse(
                {"status": "error", "message": "Could not save the notes"},
                status_code=500,
            )
    else:
        return JSONResponse({"status": "error", "message": "User not logged in"}, status_code=401)


@app.get("/platform/dashboard/{scenario_name}/notes")
async def get_notes_for_scenario(scenario_name: str):
    """
    Retrieve saved notes for a specific scenario.

    Parameters:
        scenario_name (str): Name of the scenario to retrieve notes for.

    Returns:
        JSONResponse: {"status": "success", "notes": <notes>} if found, otherwise an error message.
    """
    notes_record = await get_notes(scenario_name)
    if notes_record:
        notes_data = dict(notes_record)
        return JSONResponse({"status": "success", "notes": notes_data["scenario_notes"]})
    else:
        return JSONResponse({"status": "error", "message": "Notes not found for the specified scenario"})


@app.get("/platform/dashboard/{scenario_name}/config")
async def get_config_for_scenario(scenario_name: str):
    """
    Load configuration for a specific scenario from the filesystem.

    Parameters:
        scenario_name (str): Name of the scenario to load configuration for.

    Returns:
        JSONResponse: {"status": "success", "config": <data>} if successful, or error message if file not found or invalid JSON.
    """
    json_path = os.path.join(os.environ.get("NEBULA_CONFIG_DIR"), scenario_name, "scenario.json")

    try:
        with open(json_path) as file:
            scenarios_data = json.load(file)

        if scenarios_data:
            return JSONResponse({"status": "success", "config": scenarios_data})
        else:
            return JSONResponse({"status": "error", "message": "Configuration not found for the specified scenario"})

    except FileNotFoundError:
        return JSONResponse({"status": "error", "message": "scenario.json file not found"})
    except json.JSONDecodeError:
        return JSONResponse({"status": "error", "message": "Error decoding JSON file"})


@app.post("/platform/login")
async def nebula_login(
    request: Request,
    session: dict = Depends(get_session),
    user: str = Form(...),
    password: str = Form(...),
):
    """
    Authenticate a user and initialize session data.

    Parameters:
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.
        user (str): Username provided in form data.
        password (str): Password provided in form data.

    Returns:
        JSONResponse: {"message": "Login successful"} with HTTP 200 status on success.
    """
    data = await verify_user(user, password)
    session["user"] = data.get("user")
    session["role"] = data.get("role")
    return JSONResponse({"message": "Login successful"}, status_code=200)


@app.get("/platform/logout")
async def nebula_logout(request: Request, session: dict = Depends(get_session)):
    """
    Log out the authenticated user and redirect to the platform home.

    Parameters:
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.

    Returns:
        RedirectResponse: Redirects client to the '/platform' endpoint.
    """
    session.pop("user", None)
    return RedirectResponse(url="/platform")


@app.get("/platform/user/delete/{user}/")
async def nebula_delete_user(user: str, request: Request, session: dict = Depends(get_session)):
    """
    Delete a specified user account via admin privileges, preventing deletion of 'ADMIN' or self.

    Parameters:
        user (str): Username of the account to delete.
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.

    Returns:
        RedirectResponse: Redirects client to '/platform/admin' on success.

    Raises:
        HTTPException: 403 Forbidden if attempting to delete 'ADMIN' or the current user.
    """
    if session.get("role") == "admin":
        if user == "ADMIN":  # ADMIN account can't be deleted.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if user == session["user"]:  # Current user can't delete himself.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        await delete_user(user)
        return RedirectResponse(url="/platform/admin")


@app.post("/platform/user/add")
async def nebula_add_user(
    request: Request,
    session: dict = Depends(get_session),
    user: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    """
    Add a new user to the system via form submission, available only to admin users, with basic username validation.

    Parameters:
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.
        user (str): Username provided in form data.
        password (str): Password provided in form data.
        role (str): Role provided in form data.

    Returns:
        RedirectResponse: Redirects client to '/platform/admin' with status 303 on success.

    Raises:
        HTTPException: 401 Unauthorized if the current user is not an admin.
    """
    # Only admin users can add new users.
    if session.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    # Basic validation on the user value before calling the controller.
    user_list = await list_users()
    
    if user.upper() in user_list or " " in user or "'" in user or '"' in user:
        return RedirectResponse(url="/platform/admin", status_code=status.HTTP_303_SEE_OTHER)
    
    # Call the controller's endpoint to add the user. 
    await add_user(user, password, role)
    return RedirectResponse(url="/platform/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/platform/user/update")
async def nebula_update_user(
    request: Request,
    session: dict = Depends(get_session),
    user: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    """
    Update an existing user's credentials and role via form submission, accessible only to admin users.

    Parameters:
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.
        user (str): Username provided in form data.
        password (str): New password provided in form data.
        role (str): New role provided in form data.

    Returns:
        RedirectResponse: Redirects client to '/platform/admin' on success, or to '/platform' if unauthorized.
    """
    if "user" not in session or session["role"] != "admin":
        return RedirectResponse(url="/platform", status_code=status.HTTP_302_FOUND)
      
    await update_user(user, password, role)
    return RedirectResponse(url="/platform/admin", status_code=status.HTTP_302_FOUND)


@app.get("/platform/api/dashboard/runningscenario", response_class=JSONResponse)
async def nebula_dashboard_runningscenario(session: dict = Depends(get_session)):
    """
    Get information about currently running scenario(s) for the authenticated user or admin.

    Parameters:
        session (dict): Session data extracted via dependency.

    Returns:
        JSONResponse: JSON object containing running scenario details and status, or {"scenario_status": "not running"}.
    """
    if session.get("role") == "admin":
        scenario_running = await get_running_scenarios()
    elif "user" in session:
        scenario_running = await get_running_scenarios(session["user"])
    if scenario_running:
        scenario_running_as_dict = dict(scenario_running)
        scenario_running_as_dict["scenario_status"] = "running"
        return JSONResponse(scenario_running_as_dict)
    else:
        return JSONResponse({"scenario_status": "not running"})


async def get_host_resources():
    """
    Retrieve host resource usage data from the controller endpoint.

    Returns:
        dict: Parsed JSON resource metrics on success, or {'error': <message>} on parse failure.
        None: If the HTTP response status is not 200.
    """
    url = f"http://{settings.controller_host}:{settings.controller_port}/resources"
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        if response.status == 200:
            try:
                return await response.json()
            except Exception as e:
                return {"error": f"Failed to parse JSON: {e}"}
        else:
            return None


async def check_enough_resources():
    """
    Check if the host's memory usage is below the configured threshold.

    Returns:
        bool: True if sufficient resources are available (or threshold is 0.0), False otherwise.
    """
    resources = await get_host_resources()

    mem_percent = resources.get("memory_percent")

    if settings.resources_threshold == 0.0:
        return True

    if mem_percent >= settings.resources_threshold:
        return False

    return True


async def wait_for_enough_ram():
    """
    Asynchronously wait until the host's memory usage falls below 80% of its initial measurement.

    Returns:
        None
    """
    resources = await get_host_resources()
    initial_ram = resources.get("memory_percent")

    desired_ram = initial_ram * 0.8

    while True:
        resources = await get_host_resources()
        actual_ram = resources.get("memory_percent")

        if actual_ram <= desired_ram:
            break

        await asyncio.sleep(1)


async def monitor_resources():
    """
    Continuously monitor host resources and, if usage exceeds the threshold, stop the last running scenario after broadcasting a message, then wait for resources to recover.

    Returns:
        None
    """
    while True:
        enough_resources = await check_enough_resources()
        if not enough_resources:
            running_scenarios = await get_running_scenarios(get_all=True)
            if running_scenarios:
                last_running_scenario = running_scenarios.pop()
                running_scenario_as_dict = dict(last_running_scenario)
                scenario_name = running_scenario_as_dict["name"]
                user = running_scenario_as_dict["username"]
                # Send message of the scenario that has been stopped
                scenario_exceed_resources = {
                    "type": "exceed_resources",
                    "user": user,
                }
                try:
                    await manager.broadcast(json.dumps(scenario_exceed_resources))
                except Exception:
                    pass
                await stop_scenario_by_name(scenario_name, user)
                user_data = user_data_store[user]
                user_data.scenarios_list_length -= 1
                await wait_for_enough_ram()
                user_data.finish_scenario_event.set()

        await asyncio.sleep(20)


try:
    asyncio.create_task(monitor_resources())
except Exception as e:
    logging.exception(f"Error creating monitoring background_task {e}")


@app.get("/platform/api/dashboard", response_class=JSONResponse)
@app.get("/platform/dashboard", response_class=HTMLResponse)
async def nebula_dashboard(request: Request, session: dict = Depends(get_session)):
    """
    Render or return the dashboard view or API data for the current user.

    Parameters:
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.

    Returns:
        TemplateResponse: Rendered 'dashboard.html' for HTML endpoint.
        JSONResponse: List of scenario dictionaries or status message for API endpoint.

    Raises:
        HTTPException: 401 Unauthorized for invalid path access.
    """
    if "user" in session:
        response = await get_scenarios(session["user"], session["role"])
        scenarios = response.get("scenarios")
        scenario_running = response.get("scenario_running")

        if session["user"] not in user_data_store:
            user_data_store[session["user"]] = UserData()

        user_data = user_data_store[session["user"]]
    else:
        scenarios = None
        scenario_running = None

    bool_completed = False
    if scenario_running:
        bool_completed = scenario_running["status"] == "completed"
    if scenarios:
        if request.url.path == "/platform/dashboard":
            return templates.TemplateResponse(
                "dashboard.html",
                {
                    "request": request,
                    "scenarios": scenarios,
                    "scenarios_list_length": user_data.scenarios_list_length,
                    "scenarios_finished": user_data.scenarios_finished,
                    "scenario_running": scenario_running,
                    "scenario_completed": bool_completed,
                    "user_logged_in": session.get("user"),
                    "user_role": session.get("role"),
                    "user_data_store": user_data_store,
                },
            )
        elif request.url.path == "/platform/api/dashboard":
            scenarios_as_dict = [dict(row) for row in scenarios]
            return JSONResponse(scenarios_as_dict)
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    else:
        if request.url.path == "/platform/dashboard":
            return templates.TemplateResponse(
                "dashboard.html",
                {
                    "request": request,
                    "user_logged_in": session.get("user"),
                },
            )
        elif request.url.path == "/platform/api/dashboard":
            return JSONResponse({"scenarios_status": "not found in database"})
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.get("/platform/api/dashboard/{scenario_name}/monitor", response_class=JSONResponse)
@app.get("/platform/dashboard/{scenario_name}/monitor", response_class=HTMLResponse)
async def nebula_dashboard_monitor(scenario_name: str, request: Request, session: dict = Depends(get_session)):
    """
    Display or return monitoring information for a specific scenario, including node statuses.

    Parameters:
        scenario_name (str): Name of the scenario to monitor.
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.

    Returns:
        TemplateResponse: Rendered 'monitor.html' for HTML endpoint.
        JSONResponse: JSON object containing scenario status, node list, and scenario metadata.

    Raises:
        HTTPException: 401 Unauthorized for invalid path access.
    """
    scenario = await get_scenario_by_name(scenario_name)
    if scenario:
        nodes_list = await list_nodes_by_scenario_name(scenario_name)
        if nodes_list:
            formatted_nodes = []
            for node in nodes_list:
                # Calculate initial status based on timestamp
                timestamp = datetime.datetime.strptime(node["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
                is_online = (datetime.datetime.now() - timestamp) <= datetime.timedelta(seconds=25)

                formatted_nodes.append({
                    "uid": node["uid"],
                    "idx": node["idx"],
                    "ip": node["ip"],
                    "port": node["port"],
                    "role": node["role"],
                    "neighbors": node["neighbors"],
                    "latitude": node["latitude"],
                    "longitude": node["longitude"],
                    "timestamp": node["timestamp"],
                    "federation": node["federation"],
                    "round": str(node["round"]),
                    "scenario_name": node["scenario"],
                    "hash": node["hash"],
                    "malicious": node["malicious"],
                    "status": is_online,
                })

            # For HTML response, return the template with basic data
            if request.url.path == f"/platform/dashboard/{scenario_name}/monitor":
                return templates.TemplateResponse(
                    "monitor.html",
                    {
                        "request": request,
                        "scenario_name": scenario_name,
                        "scenario": scenario,
                        "nodes": [list(node.values()) for node in formatted_nodes],
                        "user_logged_in": session.get("user"),
                    },
                )
            # For API response, return the formatted node data
            elif request.url.path == f"/platform/api/dashboard/{scenario_name}/monitor":
                return JSONResponse({
                    "scenario_status": scenario["status"],
                    "nodes": formatted_nodes,
                    "scenario_name": scenario["name"],
                    "title": scenario["title"],
                    "description": scenario["description"],
                })
            else:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        else:
            # No nodes found
            if request.url.path == f"/platform/dashboard/{scenario_name}/monitor":
                return templates.TemplateResponse(
                    "monitor.html",
                    {
                        "request": request,
                        "scenario_name": scenario_name,
                        "scenario": scenario,
                        "nodes": [],
                        "user_logged_in": session.get("user"),
                    },
                )
            elif request.url.path == f"/platform/api/dashboard/{scenario_name}/monitor":
                return JSONResponse({
                    "scenario_status": scenario["status"],
                    "nodes": [],
                    "scenario_name": scenario["name"],
                    "title": scenario["title"],
                    "description": scenario["description"],
                })
            else:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    else:
        # Scenario not found
        if request.url.path == f"/platform/dashboard/{scenario_name}/monitor":
            return templates.TemplateResponse(
                "monitor.html",
                {
                    "request": request,
                    "scenario_name": scenario_name,
                    "scenario": None,
                    "nodes": [],
                    "user_logged_in": session.get("user"),
                },
            )
        elif request.url.path == f"/platform/api/dashboard/{scenario_name}/monitor":
            return JSONResponse({"scenario_status": "not exists"})
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.post("/platform/dashboard/{scenario_name}/node/update")
async def nebula_update_node(scenario_name: str, request: Request):
    """
    Process a node update request for a scenario and broadcast the updated node information.

    Parameters:
        scenario_name (str): Name of the scenario.
        request (Request): FastAPI request object containing a JSON payload with node update data.

    Returns:
        JSONResponse: {"message": "Node updated", "status": "success"} on success.

    Raises:
        HTTPException: 400 Bad Request if the content type is not application/json.
    """
    if request.method == "POST":
        if request.headers.get("content-type") == "application/json":
            config = await request.json()

            node_update = {
                "type": "node_update",
                "scenario_name": scenario_name,
                "uid": config["device_args"]["uid"],
                "idx": config["device_args"]["idx"],
                "ip": config["network_args"]["ip"],
                "port": str(config["network_args"]["port"]),
                "role": config["device_args"]["role"],
                "malicious": config["device_args"]["malicious"],
                "neighbors": config["network_args"]["neighbors"],
                "latitude": config["mobility_args"]["latitude"],
                "longitude": config["mobility_args"]["longitude"],
                "timestamp": config["timestamp"],
                "federation": config["scenario_args"]["federation"],
                "round": config["federation_args"]["round"],
                "name": config["scenario_args"]["name"],
                "status": True,
                "neighbors_distance": config["mobility_args"]["neighbors_distance"],
                "malicious": str(config["device_args"]["malicious"])
            }

            try:
                await manager.broadcast(json.dumps(node_update))
            except Exception:
                pass

            return JSONResponse({"message": "Node updated", "status": "success"}, status_code=200)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


# Recieve a stopped node
@app.post("/platform/dashboard/{scenario_name}/node/done")
async def node_stopped(scenario_name: str, request: Request):
    """
    Handle notification that a node has finished its task; mark the node as finished,
    stop the scenario if all nodes are done, and signal scenario completion.

    Parameters:
        scenario_name (str): Name of the scenario.
        request (Request): FastAPI request object containing a JSON payload with the finished node index.

    Returns:
        JSONResponse: Message indicating node completion status or scenario completion.

    Raises:
        HTTPException: 400 Bad Request if the content type is not application/json.
    """
    user = await get_user_by_scenario_name(scenario_name)
    user_data = user_data_store[user]

    if request.headers.get("content-type") == "application/json":
        data = await request.json()
        user_data.nodes_finished.append(data["idx"])
        nodes_list = await list_nodes_by_scenario_name(scenario_name)
        finished = True
        # Check if all the nodes of the scenario have finished the experiment
        for node in nodes_list:
            if str(node["idx"]) not in map(str, user_data.nodes_finished):
                finished = False

        if finished:
            await stop_scenario_by_name(scenario_name, user)
            user_data.nodes_finished.clear()
            user_data.finish_scenario_event.set()
            return JSONResponse(
                status_code=200,
                content={"message": "All nodes finished, scenario marked as completed."},
            )
        else:
            return JSONResponse(
                status_code=200,
                content={"message": "Node marked as finished, waiting for other nodes."},
            )
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


@app.get("/platform/dashboard/{scenario_name}/topology/image/")
async def nebula_monitor_image(scenario_name: str):
    """
    Serve the topology image for a given scenario if available.

    Parameters:
        scenario_name (str): Name of the scenario.

    Returns:
        FileResponse: The topology.png image for the scenario.

    Raises:
        HTTPException: 404 Not Found if the topology image does not exist.
    """
    topology_image = FileUtils.check_path(settings.config_dir, os.path.join(scenario_name, "topology.png"))
    if os.path.exists(topology_image):
        return FileResponse(topology_image, media_type="image/png", filename=f"{scenario_name}_topology.png")
    else:
        raise HTTPException(status_code=404, detail="Topology image not found")


@app.get("/platform/dashboard/{scenario_name}/stop/{stop_all}")
async def nebula_stop_scenario(
    scenario_name: str,
    stop_all: bool,
    request: Request,
    session: dict = Depends(get_session),
):
    """
    Stop one or all scenarios for the current user and redirect to the dashboard.
    
    Parameters:
        scenario_name (str): Name of the scenario to stop.
        stop_all (bool): If True, stop all scenarios; otherwise stop only the specified one.
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.
    
    Returns:
        RedirectResponse: Redirects to the '/platform/dashboard' endpoint.
    
    Raises:
        HTTPException: 401 Unauthorized if the user is not authenticated or lacks permission.
    """
    if "user" in session:
        user = await get_user_by_scenario_name(scenario_name)
        user_data = user_data_store[user]

        if session["role"] == "demo":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if stop_all:
            user_data.stop_all_scenarios_event.set()
            user_data.scenarios_list_length = 0
            user_data.scenarios_finished = 0
            await stop_scenario_by_name(scenario_name, user)
        else:
            user_data.finish_scenario_event.set()
            user_data.scenarios_list_length -= 1
            await stop_scenario_by_name(scenario_name, user)
        return RedirectResponse(url="/platform/dashboard")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


async def remove_scenario(scenario_name=None, user=None):
    """
    Remove all data and resources associated with a scenario, including nodes, notes, and files.

    Parameters:
        scenario_name (str, optional): Name of the scenario to remove.
        user (str, optional): Username associated with the scenario.

    Returns:
        None
    """
    from nebula.controller.scenarios import ScenarioManagement

    user_data = user_data_store[user]

    if settings.advanced_analytics:
        logging.info("Advanced analytics enabled")
    # Remove registered nodes and conditions
    user_data.nodes_registration.pop(scenario_name, None)
    await remove_nodes_by_scenario_name(scenario_name)
    await remove_scenario_by_name(scenario_name)
    await remove_note(scenario_name)


@app.get("/platform/dashboard/{scenario_name}/relaunch")
async def nebula_relaunch_scenario(
    scenario_name: str, background_tasks: BackgroundTasks, session: dict = Depends(get_session)
):
    """
    Relaunch a previously run scenario by loading its configuration, enqueuing it,
    and starting execution in the background.

    Parameters:
        scenario_name (str): Name of the scenario to relaunch.
        background_tasks (BackgroundTasks): FastAPI BackgroundTasks instance for deferred execution.
        session (dict): Session data extracted via dependency.

    Returns:
        RedirectResponse: Redirects to the '/platform/dashboard' endpoint.

    Raises:
        HTTPException: 401 Unauthorized if the user is not authenticated or lacks permission.
    """
    user_data = user_data_store[session["user"]]

    if "user" in session:
        if session["role"] == "demo":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        elif session["role"] == "user":
            if not await check_scenario_with_role(session["role"], scenario_name):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

        scenario_path = FileUtils.check_path(settings.config_dir, os.path.join(scenario_name, "scenario.json"))
        with open(scenario_path) as scenario_file:
            scenario = json.load(scenario_file)

        user_data.scenarios_list_length = user_data.scenarios_list_length + 1

        if user_data.scenarios_list_length == 1:
            user_data.scenarios_finished = 0
            user_data.scenarios_list.clear()
            user_data.scenarios_list.append(scenario)
            background_tasks.add_task(run_scenarios, session["role"], session["user"])
        else:
            user_data.scenarios_list.append(scenario)

        return RedirectResponse(url="/platform/dashboard", status_code=303)
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.get("/platform/dashboard/{scenario_name}/remove")
async def nebula_remove_scenario(scenario_name: str, session: dict = Depends(get_session)):
    """
    Remove a scenario for the authenticated user and redirect back to the dashboard.

    Parameters:
        scenario_name (str): Name of the scenario to remove.
        session (dict): Session data extracted via dependency.

    Returns:
        RedirectResponse: Redirects to the '/platform/dashboard' endpoint.

    Raises:
        HTTPException: 401 Unauthorized if the user is not authenticated or lacks permission.
    """
    if "user" in session:
        if session["role"] == "demo":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        elif session["role"] == "user":
            if not await check_scenario_with_role(session["role"], scenario_name):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await remove_scenario(scenario_name, session["user"])
        return RedirectResponse(url="/platform/dashboard")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


if settings.advanced_analytics:
    logging.info("Advanced analytics enabled")
else:
    logging.info("Advanced analytics disabled")

    # TENSORBOARD START

@app.get("/platform/dashboard/statistics/", response_class=HTMLResponse)
@app.get("/platform/dashboard/{scenario_name}/statistics/", response_class=HTMLResponse)
async def nebula_dashboard_statistics(request: Request, scenario_name: str = None):
    """
    Render the TensorBoard statistics page for all experiments or filter by scenario.

    Parameters:
        request (Request): FastAPI request object.
        scenario_name (str, optional): Scenario name to filter statistics by; defaults to None.

    Returns:
        TemplateResponse: Rendered 'statistics.html' with the appropriate URL parameter for TensorBoard.
    """
    statistics_url = "/platform/statistics/"
    if scenario_name is not None:
        statistics_url += f"?smoothing=0&runFilter={scenario_name}"

    return templates.TemplateResponse("statistics.html", {"request": request, "statistics_url": statistics_url})

@app.api_route("/platform/statistics/", methods=["GET", "POST"])
@app.api_route("/platform/statistics/{path:path}", methods=["GET", "POST"])
async def statistics_proxy(request: Request, path: str = None, session: dict = Depends(get_session)):
    """
    Proxy requests to the TensorBoard backend to fetch experiment statistics,
    rewriting URLs and filtering headers as needed.

    Parameters:
        request (Request): FastAPI request object with original headers, cookies, and body.
        path (str, optional): Specific TensorBoard sub-path to proxy; defaults to None.
        session (dict): Session data extracted via dependency.

    Returns:
        Response: The proxied TensorBoard response with adjusted headers and content.

    Raises:
        HTTPException: 401 Unauthorized if the user is not authenticated.
    """
    if "user" in session:
        query_string = urlencode(request.query_params)

        url = "http://localhost:8080"
        tensorboard_url = f"{url}{('/' + path) if path else ''}" + ("?" + query_string if query_string else "")

        headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}

        response = requests.request(
            method=request.method,
            url=tensorboard_url,
            headers=headers,
            data=await request.body(),
            cookies=request.cookies,
            allow_redirects=False,
        )

        excluded_headers = [
            "content-encoding",
            "content-length",
            "transfer-encoding",
            "connection",
        ]

        filtered_headers = [
            (name, value) for name, value in response.raw.headers.items() if name.lower() not in excluded_headers
        ]

        if "text/html" in response.headers["Content-Type"]:
            content = response.text
            content = content.replace("url(/", "url(/platform/statistics/")
            content = content.replace('src="/', 'src="/platform/statistics/')
            content = content.replace('href="/', 'href="/platform/statistics/')
            response = Response(content, response.status_code, dict(filtered_headers))
            return response

        if path and path.endswith(".js"):
            content = response.text
            content = content.replace(
                "experiment/${s}/data/plugin",
                "nebula/statistics/experiment/${s}/data/plugin",
            )
            response = Response(content, response.status_code, dict(filtered_headers))
            return response

        return Response(response.content, response.status_code, dict(filtered_headers))

    else:
        raise HTTPException(status_code=401)

@app.get("/experiment/{path:path}")
@app.post("/experiment/{path:path}")
async def metrics_proxy(path: str = None, request: Request = None):
    """
    Proxy experiment metric requests to the platform statistics endpoint.

    Parameters:
        path (str): The dynamic path segment to append to the statistics URL.
        request (Request): FastAPI request object containing query parameters.

    Returns:
        RedirectResponse: Redirects the client to the corresponding platform statistics experiment URL.
    """
    query_params = request.query_params
    new_url = "/platform/statistics/experiment/" + path
    if query_params:
        new_url += "?" + urlencode(query_params)

    return RedirectResponse(url=new_url)

    # TENSORBOARD END


def zipdir(path, ziph):
    """
    Recursively add all files from a directory into a zip archive.

    Parameters:
        path (str): The root directory whose contents will be zipped.
        ziph (zipfile.ZipFile): An open ZipFile handle to which files will be written.

    Returns:
        None
    """
    # ziph is zipfile handle
    for root, _, files in os.walk(path):
        for file in files:
            ziph.write(
                os.path.join(root, file),
                os.path.relpath(os.path.join(root, file), os.path.join(path, "..")),
            )


@app.get("/platform/dashboard/{scenario_name}/download/logs")
async def nebula_dashboard_download_logs_metrics(
    scenario_name: str, request: Request, session: dict = Depends(get_session)
):
    """
    Package scenario logs and configuration into a zip archive and stream it to the client.

    Parameters:
        scenario_name (str): Name of the scenario whose files are to be downloaded.
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.

    Returns:
        StreamingResponse: A zip file containing the scenario’s logs and configuration.

    Raises:
        HTTPException: 401 Unauthorized if the user is not logged in.
        HTTPException: 404 Not Found if the log or config folder does not exist.
    """
    if "user" in session:
        log_folder = FileUtils.check_path(settings.log_dir, scenario_name)
        config_folder = FileUtils.check_path(settings.config_dir, scenario_name)
        if os.path.exists(log_folder) and os.path.exists(config_folder):
            # Crear un archivo zip con los logs y los archivos de configuración, enviarlo al usuario
            memory_file = io.BytesIO()
            with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zipf:
                zipdir(log_folder, zipf)
                zipdir(config_folder, zipf)

            memory_file.seek(0)

            return StreamingResponse(
                memory_file,
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename={scenario_name}.zip"},
            )
        else:
            raise HTTPException(status_code=404, detail="Log or config folder not found")
    else:
        raise HTTPException(status_code=401)


@app.get("/platform/dashboard/deployment/", response_class=HTMLResponse)
async def nebula_dashboard_deployment(request: Request, session: dict = Depends(get_session)):
    """
    Render the deployment dashboard with running scenarios and GPU availability.

    Parameters:
        request (Request): FastAPI request object.
        session (dict): Session data extracted via dependency.

    Returns:
        HTMLResponse: Rendered 'deployment.html' template with scenario and GPU context.
    """
    scenario_running = await get_running_scenarios()
    return templates.TemplateResponse(
        "deployment.html",
        {
            "request": request,
            "scenario_running": scenario_running,
            "user_logged_in": session.get("user"),
            "gpu_available": settings.gpu_available,
        },
    )


async def assign_available_gpu(scenario_data, role):
    """
    Assign available GPU(s) or default to CPU for a scenario based on system resources and user role.

    Parameters:
        scenario_data (dict): Scenario configuration dict to be updated with accelerator settings.
        role (str): User role ('user', 'admin', or other).

    Returns:
        dict: Updated scenario_data including 'accelerator' and 'gpu_id' fields.
    """
    available_gpus = []

    response = await get_available_gpus()
    # Obtain available system_gpus
    available_system_gpus = response.get("available_gpus", None) if response is not None else None

    if available_system_gpus:
        running_scenarios = await get_running_scenarios(get_all=True)
        # Obtain currently used gpus
        if running_scenarios:
            running_gpus = []
            # Obtain associated gpus of the running scenarios
            for scenario in running_scenarios:
                scenario_gpus = json.loads(scenario["gpu_id"])
                # Obtain the list of gpus in use without duplicates
                for gpu in scenario_gpus:
                    if gpu not in running_gpus:
                        running_gpus.append(gpu)

            # Add available system gpus if they are not in use
            for gpu in available_system_gpus:
                if gpu not in running_gpus:
                    available_gpus.append(gpu)
        else:
            available_gpus = available_system_gpus

    # Assign gpus based in user role
    if len(available_gpus) > 0:
        if role == "user":
            scenario_data["accelerator"] = "gpu"
            scenario_data["gpu_id"] = [available_gpus.pop()]
        elif role == "admin":
            scenario_data["accelerator"] = "gpu"
            scenario_data["gpu_id"] = available_gpus
        else:
            scenario_data["accelerator"] = "cpu"
            scenario_data["gpu_id"] = []
    else:
        scenario_data["accelerator"] = "cpu"
        scenario_data["gpu_id"] = []

    return scenario_data


async def run_scenario(scenario_data, role, user):
    """
    Deploy a single scenario: assign resources, register it, and start its participants.

    Parameters:
        scenario_data (dict): The scenario configuration data.
        role (str): The role of the user initiating the scenario.
        user (str): Username associated with the scenario.

    Returns:
        None
    """
    user_data = user_data_store[user]

    scenario_data = await assign_available_gpu(scenario_data, role)
     
    scenario_name = await deploy_scenario(scenario_data, role, user)

    user_data.nodes_registration[scenario_name] = {
        "n_nodes": scenario_data["n_nodes"],
        "nodes": set(),
    }

    user_data.nodes_registration[scenario_name]["condition"] = asyncio.Condition()


# Deploy the list of scenarios
async def run_scenarios(role, user):
    """
    Sequentially execute all enqueued scenarios for a user, waiting for each to complete
    and for sufficient resources before starting the next.

    Parameters:
        role (str): The role of the user initiating the scenarios.
        user (str): Username associated with the scenarios.

    Returns:
        None
    """
    try:
        user_data = user_data_store[user]

        for scenario_data in user_data.scenarios_list:
            user_data.finish_scenario_event.clear()
            logging.info(f"Running scenario {scenario_data['scenario_title']}")
            await run_scenario(scenario_data, role, user)
            # Waits till the scenario is completed
            while not user_data.finish_scenario_event.is_set() and not user_data.stop_all_scenarios_event.is_set():
                await asyncio.sleep(1)

            # Wait until theres enough resources to launch the next scenario
            while not await check_enough_resources():
                await asyncio.sleep(1)

            if user_data.stop_all_scenarios_event.is_set():
                user_data.stop_all_scenarios_event.clear()
                user_data.scenarios_list_length = 0
                return
            user_data.scenarios_finished += 1
            await asyncio.sleep(5)
    finally:
        user_data.scenarios_list_length = 0


@app.post("/platform/dashboard/deployment/run")
async def nebula_dashboard_deployment_run(
    request: Request,
    background_tasks: BackgroundTasks,
    session: dict = Depends(get_session),
):
    """
    Handle incoming deployment requests to run one or more scenarios, enqueue them,
    and trigger background execution.
    
    Parameters:
        request (Request): FastAPI request object containing a JSON list of scenarios to run.
        background_tasks (BackgroundTasks): Instance for scheduling tasks.
        session (dict): Session data extracted via dependency.
    
    Returns:
        RedirectResponse: Redirects to '/platform/dashboard' on successful enqueue.
    
    Raises:
        HTTPException: 401 Unauthorized if the user is not logged in or content type is invalid.
        HTTPException: 503 Service Unavailable if resources are insufficient.
    """
    enough_resources = await check_enough_resources()

    if "user" not in session:
        raise HTTPException(status_code=401, detail="Login in to deploy scenarios")
    elif not enough_resources:
        raise HTTPException(status_code=503, detail="Not enough resources to run a scenario")

    if request.headers.get("content-type") != "application/json":
        raise HTTPException(status_code=401)

    data = await request.json()
    user_data = user_data_store[session["user"]]

    if user_data.scenarios_list_length < 1:
        user_data.scenarios_finished = 0
        user_data.scenarios_list_length = len(data)
        user_data.scenarios_list = data
        background_tasks.add_task(run_scenarios, session["role"], session["user"])
    else:
        user_data.scenarios_list_length += len(data)
        user_data.scenarios_list.extend(data)
        await asyncio.sleep(3)
    logging.info(
        f"Running deployment with {len(data)} scenarios_list_length: {user_data.scenarios_list_length} scenarios"
    )
    return RedirectResponse(url="/platform/dashboard", status_code=303)
    # return Response(content="Success", status_code=200)


if __name__ == "__main__":
    # Parse args from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000, help="Port to run the frontend on.")
    args = parser.parse_args()
    logging.info(f"Starting frontend on port {args.port}")
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=args.port)

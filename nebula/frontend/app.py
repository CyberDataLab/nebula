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

from ansi2html import Ansi2HTMLConverter
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
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from nebula.frontend.database import (
    add_user,
    check_scenario_with_role,
    delete_user_from_db,
    get_all_scenarios_and_check_completed,
    get_notes,
    get_running_scenario,
    get_scenario_by_name,
    get_user_by_scenario_name,
    get_user_info,
    initialize_databases,
    list_nodes_by_scenario_name,
    list_users,
    remove_nodes_by_scenario_name,
    remove_note,
    remove_scenario_by_name,
    save_notes,
    scenario_set_all_status_to_finished,
    scenario_set_status_to_finished,
    scenario_update_record,
    update_node_record,
    update_user,
    verify,
    verify_hash_algorithm,
)
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
                logging.error(f"Error broadcasting message: {e}")
                disconnected_websockets.append(connection)
        
        # Remove disconnected websockets
        for websocket in disconnected_websockets:
            self.disconnect(websocket)

    def get_historic(self):
        return self.historic_messages


manager = ConnectionManager()


@app.websocket("/platform/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
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
                logging.error(f"Error broadcasting message: {e}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        try:
            message = {"type": "control", "message": f"Client #{client_id} left the chat"}
            await manager.broadcast(json.dumps(message))
        except Exception as e:
            logging.error(f"Error broadcasting disconnect message: {e}")
    except Exception as e:
        logging.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


templates = Jinja2Templates(directory=settings.templates_dir)


def datetimeformat(value, format="%B %d, %Y %H:%M"):
    return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime(format)


def add_global_context(request: Request):
    return {
        "is_production": settings.production,
    }


templates.env.filters["datetimeformat"] = datetimeformat
templates.env.globals.update(add_global_context=add_global_context)


def get_session(request: Request) -> dict:
    return request.session


def set_default_user():
    username = os.environ.get("NEBULA_DEFAULT_USER", "admin")
    password = os.environ.get("NEBULA_DEFAULT_PASSWORD", "admin")
    if not list_users():
        add_user(username, password, "admin")
    if not verify_hash_algorithm(username):
        update_user(username, password, "admin")


@app.on_event("startup")
async def startup_event():
    await initialize_databases()
    set_default_user()


class UserData:
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
def signal_handler(signal, frame):
    logging.info("You pressed Ctrl+C [frontend]!")
    scenario_set_all_status_to_finished()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
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


@app.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/platform")


@app.get("/platform", response_class=HTMLResponse)
@app.get("/platform/", response_class=HTMLResponse)
async def nebula_home(request: Request):
    alerts = []
    return templates.TemplateResponse("index.html", {"request": request, "alerts": alerts})


@app.get("/platform/historic")
async def nebula_ws_historic(session: dict = Depends(get_session)):
    if session.get("role") == "admin":
        historic = manager.get_historic()
        if historic:
            pretty_historic = historic
            return JSONResponse(content=pretty_historic)
        else:
            return JSONResponse({"status": "error", "message": "Historic not found"})


@app.get("/platform/dashboard/{scenario_name}/private", response_class=HTMLResponse)
async def nebula_dashboard_private(request: Request, scenario_name: str, session: dict = Depends(get_session)):
    if "user" in session:
        return templates.TemplateResponse("private.html", {"request": request, "scenario_name": scenario_name})
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.get("/platform/admin", response_class=HTMLResponse)
async def nebula_admin(request: Request, session: dict = Depends(get_session)):
    if session.get("role") == "admin":
        user_list = list_users(all_info=True)
        user_table = zip(
            range(1, len(user_list) + 1),
            [user[0] for user in user_list],
            [user[2] for user in user_list],
            strict=False,
        )
        return templates.TemplateResponse("admin.html", {"request": request, "users": user_table})
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.post("/platform/dashboard/{scenario_name}/save_note")
async def save_note_for_scenario(scenario_name: str, request: Request, session: dict = Depends(get_session)):
    if "user" in session:
        data = await request.json()
        notes = data["notes"]
        try:
            save_notes(scenario_name, notes)
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
    notes_record = get_notes(scenario_name)
    if notes_record:
        notes_data = dict(zip(notes_record.keys(), notes_record, strict=False))
        return JSONResponse({"status": "success", "notes": notes_data["scenario_notes"]})
    else:
        return JSONResponse({"status": "error", "message": "Notes not found for the specified scenario"})


@app.get("/platform/dashboard/{scenario_name}/config")
async def get_config_for_scenario(scenario_name: str):
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
    user_submitted = user.upper()
    if (user_submitted in list_users()) and verify(user_submitted, password):
        user_info = get_user_info(user_submitted)
        session["user"] = user_submitted
        session["role"] = user_info[2]
        return JSONResponse({"message": "Login successful"}, status_code=200)
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.get("/platform/logout")
async def nebula_logout(request: Request, session: dict = Depends(get_session)):
    session.pop("user", None)
    return RedirectResponse(url="/platform")


@app.get("/platform/user/delete/{user}/")
async def nebula_delete_user(user: str, request: Request, session: dict = Depends(get_session)):
    if session.get("role") == "admin":
        if user == "ADMIN":  # ADMIN account can't be deleted.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if user == session["user"]:  # Current user can't delete himself.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        delete_user_from_db(user)
        return RedirectResponse(url="/platform/admin")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.post("/platform/user/add")
async def nebula_add_user(
    request: Request,
    session: dict = Depends(get_session),
    user: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    if session.get("role") == "admin":  # only Admin should be able to add user.
        user_list = list_users(all_info=True)
        if user.upper() in user_list or " " in user or "'" in user or '"' in user:
            return RedirectResponse(url="/platform/admin", status_code=status.HTTP_303_SEE_OTHER)
        else:
            add_user(user, password, role)
            return RedirectResponse(url="/platform/admin", status_code=status.HTTP_303_SEE_OTHER)
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.post("/platform/user/update")
async def nebula_update_user(
    request: Request,
    session: dict = Depends(get_session),
    user: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    if "user" not in session or session["role"] != "admin":
        return RedirectResponse(url="/platform", status_code=status.HTTP_302_FOUND)
    update_user(user, password, role)
    return RedirectResponse(url="/platform/admin", status_code=status.HTTP_302_FOUND)


@app.get("/platform/api/dashboard/runningscenario", response_class=JSONResponse)
async def nebula_dashboard_runningscenario(session: dict = Depends(get_session)):
    if session.get("role") == "admin":
        scenario_running = get_running_scenario()
    elif "user" in session:
        scenario_running = get_running_scenario(session["user"])
    if scenario_running:
        scenario_running_as_dict = dict(scenario_running)
        scenario_running_as_dict["scenario_status"] = "running"
        return JSONResponse(scenario_running_as_dict)
    else:
        return JSONResponse({"scenario_status": "not running"})


async def get_host_resources():
    url = f"http://{settings.controller_host}:{settings.controller_port}/resources"
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        if response.status == 200:
            try:
                return await response.json()
            except Exception as e:
                return {"error": f"Failed to parse JSON: {e}"}
        else:
            return None


async def get_available_gpus():
    url = f"http://{settings.controller_host}:{settings.controller_port}/available_gpus"
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        if response.status == 200:
            try:
                return await response.json()
            except Exception as e:
                return {"error": f"Failed to parse JSON: {e}"}
        else:
            return None


async def get_least_memory_gpu():
    url = f"http://{settings.controller_host}:{settings.controller_port}/least_memory_gpu"
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        if response.status == 200:
            try:
                return await response.json()
            except Exception as e:
                return {"error": f"Failed to parse JSON: {e}"}
        else:
            return None


async def check_enough_resources():
    resources = await get_host_resources()

    mem_percent = resources.get("memory_percent")

    if settings.resources_threshold == 0.0:
        return True

    if mem_percent >= settings.resources_threshold:
        return False

    return True


async def wait_for_enough_ram():
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
    while True:
        enough_resources = await check_enough_resources()
        if not enough_resources:
            running_scenarios = get_running_scenario(get_all=True)
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
                stop_scenario(scenario_name, user)
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
    if "user" in session:
        scenarios = get_all_scenarios_and_check_completed(
            username=session["user"], role=session["role"]
        )  # Get all scenarios after checking if they are completed
        if session.get("role") == "admin":
            scenario_running = get_running_scenario()
        else:
            scenario_running = get_running_scenario(username=session["user"])

        if session["user"] not in user_data_store:
            user_data_store[session["user"]] = UserData()

        user_data = user_data_store[session["user"]]
    else:
        scenarios = None
        scenario_running = None

    bool_completed = False
    if scenario_running:
        bool_completed = scenario_running[6] == "completed"
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
    scenario = get_scenario_by_name(scenario_name)
    if scenario:
        nodes_list = list_nodes_by_scenario_name(scenario_name)
        if nodes_list:
            formatted_nodes = []
            for node in nodes_list:
                # Calculate initial status based on timestamp
                timestamp = datetime.datetime.strptime(node[8], "%Y-%m-%d %H:%M:%S.%f")
                is_online = (datetime.datetime.now() - timestamp) <= datetime.timedelta(seconds=25)
                
                formatted_nodes.append({
                    "uid": node[0],
                    "idx": node[1],
                    "ip": node[2],
                    "port": node[3],
                    "role": node[4],
                    "neighbors": node[5],
                    "latitude": node[6],
                    "longitude": node[7],
                    "timestamp": node[8],
                    "federation": node[9],
                    "round": str(node[10]),
                    "scenario_name": node[11],
                    "hash": node[12],
                    "malicious": node[13],
                    "status": is_online
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
                    "scenario_status": scenario[5],
                    "nodes": formatted_nodes,
                    "scenario_name": scenario[0],
                    "scenario_title": scenario[3],
                    "scenario_description": scenario[4],
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
                    "scenario_status": scenario[5],
                    "nodes": [],
                    "scenario_name": scenario[0],
                    "scenario_title": scenario[3],
                    "scenario_description": scenario[4],
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


def update_topology(scenario_name, nodes_list, nodes_config):
    import numpy as np

    nodes = []
    for node in nodes_list:
        nodes.append(node[2] + ":" + str(node[3]))
    matrix = np.zeros((len(nodes), len(nodes)))
    for node in nodes_list:
        for neighbour in node[5].split(" "):
            if neighbour != "" and neighbour in nodes:
                matrix[
                    nodes.index(node[2] + ":" + str(node[3])),
                    nodes.index(neighbour),
                ] = 1
    from nebula.addons.topologymanager import TopologyManager

    tm = TopologyManager(n_nodes=len(nodes_list), topology=matrix, scenario_name=scenario_name)
    tm.update_nodes(nodes_config)
    try:
        tm.draw_graph(path=os.path.join(settings.config_dir, scenario_name, "topology.png"))
    except FileNotFoundError:
        logging.exception("Topology.png not found in config dir")


@app.post("/platform/dashboard/{scenario_name}/node/update")
async def nebula_update_node(scenario_name: str, request: Request):
    if request.method == "POST":
        if request.headers.get("content-type") == "application/json":
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

            neighbors_distance = config["mobility_args"]["neighbors_distance"]

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
                "timestamp": str(timestamp),
                "federation": config["scenario_args"]["federation"],
                "round": config["federation_args"]["round"],
                "name": config["scenario_args"]["name"],
                "status": True,
                "neighbors_distance": neighbors_distance,
                "malicious": str(config["device_args"]["malicious"])
            }

            try:
                await manager.broadcast(json.dumps(node_update))
            except Exception:
                pass

            return JSONResponse({"message": "Node updated", "status": "success"}, status_code=200)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


@app.post("/platform/dashboard/{scenario_name}/node/register")
async def nebula_register_node(scenario_name: str, request: Request, session: dict = Depends(get_session)):
    user_data = user_data_store[session["user"]]

    if request.headers.get("content-type") == "application/json":
        data = await request.json()
        node = data["node"]
        logging.info(f"Registering node {node} for scenario {scenario_name}")
        async with user_data.nodes_registration[scenario_name]["condition"]:
            user_data.nodes_registration[scenario_name]["nodes"].add(node)
            logging.info(f"Node {node} registered")
            if (
                len(user_data.nodes_registration[scenario_name]["nodes"])
                == user_data.nodes_registration[scenario_name]["n_nodes"]
            ):
                user_data.nodes_registration[scenario_name]["condition"].notify_all()
                logging.info("All nodes registered")

        return JSONResponse({"message": "Node registered", "status": "success"}, status_code=200)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


@app.get("/platform/dashboard/scenarios/node/list")
async def nebula_list_all_scenarios(session: dict = Depends(get_session)):
    user_data = user_data_store[session["user"]]

    if "user" not in session or session["role"] not in ["admin", "user"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    scenarios = {}
    for scenario_name, scenario_info in user_data.nodes_registration.items():
        scenarios[scenario_name] = list(scenario_info["nodes"])

    if not scenarios:
        return JSONResponse({"message": "No scenarios found", "status": "error"}, status_code=404)

    return JSONResponse({"scenarios": scenarios, "status": "success"}, status_code=200)


@app.get("/platform/dashboard/scenarios/node/erase")
async def nebula_erase_all_nodes(session: dict = Depends(get_session)):
    user_data = user_data_store[session["user"]]

    if "user" not in session or session["role"] not in ["admin", "user"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    user_data.nodes_registration.clear()
    return JSONResponse({"message": "All nodes erased", "status": "success"}, status_code=200)


@app.get("/platform/dashboard/{scenario_name}/node/wait")
async def nebula_wait_nodes(scenario_name: str, session: dict = Depends(get_session)):
    user_data = user_data_store[session["user"]]

    if scenario_name not in user_data.nodes_registration:
        return JSONResponse({"message": "Scenario not found", "status": "error"}, status_code=404)

    async with user_data.nodes_registration[scenario_name]["condition"]:
        while (
            len(user_data.nodes_registration[scenario_name]["nodes"])
            < user_data.nodes_registration[scenario_name]["n_nodes"]
        ):
            await user_data.nodes_registration[scenario_name]["condition"].wait()
        return JSONResponse({"message": "All nodes registered", "status": "success"}, status_code=200)


@app.get("/platform/dashboard/{scenario_name}/node/{id}/infolog")
async def nebula_monitor_log(scenario_name: str, id: str):
    logs = FileUtils.check_path(settings.log_dir, os.path.join(scenario_name, f"participant_{id}.log"))
    if os.path.exists(logs):
        return FileResponse(logs, media_type="text/plain", filename=f"participant_{id}.log")
    else:
        raise HTTPException(status_code=404, detail="Log file not found")


@app.get(
    "/platform/dashboard/{scenario_name}/node/{id}/infolog/{number}",
    response_class=PlainTextResponse,
)
async def nebula_monitor_log_x(scenario_name: str, id: str, number: int):
    logs = FileUtils.check_path(settings.log_dir, os.path.join(scenario_name, f"participant_{id}.log"))
    if os.path.exists(logs):
        with open(logs) as f:
            lines = f.readlines()[-number:]
            lines = "".join(lines)
            converter = Ansi2HTMLConverter()
            html_text = converter.convert(lines, full=False)
            return Response(content=html_text, media_type="text/plain")
    else:
        return Response(content="No logs available", media_type="text/plain")


@app.get("/platform/dashboard/{scenario_name}/node/{id}/debuglog")
async def nebula_monitor_log_debug(scenario_name: str, id: str):
    logs = FileUtils.check_path(settings.log_dir, os.path.join(scenario_name, f"participant_{id}_debug.log"))
    if os.path.exists(logs):
        return FileResponse(logs, media_type="text/plain", filename=f"participant_{id}_debug.log")
    else:
        raise HTTPException(status_code=404, detail="Log file not found")


@app.get("/platform/dashboard/{scenario_name}/node/{id}/errorlog")
async def nebula_monitor_log_error(scenario_name: str, id: str):
    logs = FileUtils.check_path(settings.log_dir, os.path.join(scenario_name, f"participant_{id}_error.log"))
    if os.path.exists(logs):
        return FileResponse(logs, media_type="text/plain", filename=f"participant_{id}_error.log")
    else:
        raise HTTPException(status_code=404, detail="Log file not found")


@app.get("/platform/dashboard/{scenario_name}/topology/image/")
async def nebula_monitor_image(scenario_name: str):
    topology_image = FileUtils.check_path(settings.config_dir, os.path.join(scenario_name, "topology.png"))
    if os.path.exists(topology_image):
        return FileResponse(topology_image, media_type="image/png", filename=f"{scenario_name}_topology.png")
    else:
        raise HTTPException(status_code=404, detail="Topology image not found")


def stop_scenario(scenario_name, user):
    from nebula.scenarios import ScenarioManagement

    ScenarioManagement.stop_participants(scenario_name)
    DockerUtils.remove_containers_by_prefix(f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_{user}-participant")
    DockerUtils.remove_docker_network(
        f"{(os.environ.get('NEBULA_CONTROLLER_NAME'))}_{str(user).lower()}-nebula-net-scenario"
    )
    ScenarioManagement.stop_blockchain()
    scenario_set_status_to_finished(scenario_name)
    # Generate statistics for the scenario
    path = FileUtils.check_path(settings.log_dir, scenario_name)
    ScenarioManagement.generate_statistics(path)


def stop_all_scenarios():
    from nebula.scenarios import ScenarioManagement

    ScenarioManagement.stop_participants()
    ScenarioManagement.stop_blockchain()
    scenario_set_all_status_to_finished()


@app.get("/platform/dashboard/{scenario_name}/stop/{stop_all}")
async def nebula_stop_scenario(
    scenario_name: str,
    stop_all: bool,
    request: Request,
    session: dict = Depends(get_session),
):
    if "user" in session:
        user = get_user_by_scenario_name(scenario_name)
        user_data = user_data_store[user]

        if session["role"] == "demo":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        # elif session["role"] == "user":
        #     if not check_scenario_with_role(session["role"], scenario_name):
        #         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if stop_all:
            user_data.stop_all_scenarios_event.set()
            user_data.scenarios_list_length = 0
            user_data.scenarios_finished = 0
            stop_scenario(scenario_name, user)
        else:
            user_data.finish_scenario_event.set()
            user_data.scenarios_list_length -= 1
            stop_scenario(scenario_name, user)
        return RedirectResponse(url="/platform/dashboard")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


def remove_scenario(scenario_name=None, user=None):
    from nebula.scenarios import ScenarioManagement

    user_data = user_data_store[user]

    if settings.advanced_analytics:
        logging.info("Advanced analytics enabled")
    # Remove registered nodes and conditions
    user_data.nodes_registration.pop(scenario_name, None)
    remove_nodes_by_scenario_name(scenario_name)
    remove_scenario_by_name(scenario_name)
    remove_note(scenario_name)
    ScenarioManagement.remove_files_by_scenario(scenario_name)


@app.get("/platform/dashboard/{scenario_name}/relaunch")
async def nebula_relaunch_scenario(
    scenario_name: str, background_tasks: BackgroundTasks, session: dict = Depends(get_session)
):
    user_data = user_data_store[session["user"]]

    if "user" in session:
        if session["role"] == "demo":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        elif session["role"] == "user":
            if not check_scenario_with_role(session["role"], scenario_name):
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
    if "user" in session:
        if session["role"] == "demo":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        elif session["role"] == "user":
            if not check_scenario_with_role(session["role"], scenario_name):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        remove_scenario(scenario_name, session["user"])
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
        statistics_url = "/platform/statistics/"
        if scenario_name is not None:
            statistics_url += f"?smoothing=0&runFilter={scenario_name}"

        return templates.TemplateResponse("statistics.html", {"request": request, "statistics_url": statistics_url})

    @app.api_route("/platform/statistics/", methods=["GET", "POST"])
    @app.api_route("/platform/statistics/{path:path}", methods=["GET", "POST"])
    async def statistics_proxy(request: Request, path: str = None, session: dict = Depends(get_session)):
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
        query_params = request.query_params
        new_url = "/platform/statistics/experiment/" + path
        if query_params:
            new_url += "?" + urlencode(query_params)

        return RedirectResponse(url=new_url)

    # TENSORBOARD END


def zipdir(path, ziph):
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
    scenario_running = get_running_scenario()
    return templates.TemplateResponse(
        "deployment.html",
        {
            "request": request,
            "scenario_running": scenario_running,
            "user_logged_in": session.get("user"),
            "gpu_available": settings.gpu_available,
        },
    )


def attack_node_assign(
    nodes,
    federation,
    attack,
    poisoned_node_percent,
    poisoned_sample_percent,
    poisoned_noise_percent,
):
    """Identify which nodes will be attacked"""
    import math
    import random

    attack_matrix = []
    n_nodes = len(nodes)
    if n_nodes == 0:
        return attack_matrix

    nodes_index = []
    # Get the nodes index
    if federation == "DFL":
        nodes_index = list(nodes.keys())
    else:
        for node in nodes:
            if nodes[node]["role"] != "server":
                nodes_index.append(node)

    n_nodes = len(nodes_index)
    # Number of attacked nodes, round up
    num_attacked = int(math.ceil(poisoned_node_percent / 100 * n_nodes))
    if num_attacked > n_nodes:
        num_attacked = n_nodes

    # Get the index of attacked nodes
    attacked_nodes = random.sample(nodes_index, num_attacked)

    # Assign the role of each node
    for node in nodes:
        node_att = "No Attack"
        attack_sample_persent = 0
        poisoned_ratio = 0
        if (node in attacked_nodes) or (nodes[node]["malicious"]):
            node_att = attack
            attack_sample_persent = poisoned_sample_percent / 100
            poisoned_ratio = poisoned_noise_percent / 100
        nodes[node]["attacks"] = node_att
        nodes[node]["poisoned_sample_percent"] = attack_sample_persent
        nodes[node]["poisoned_ratio"] = poisoned_ratio
        attack_matrix.append([node, node_att, attack_sample_persent, poisoned_ratio])
    return nodes, attack_matrix


import math


def mobility_assign(nodes, mobile_participants_percent):
    """Assign mobility to nodes"""
    import random

    # Number of mobile nodes, round down
    num_mobile = math.floor(mobile_participants_percent / 100 * len(nodes))
    if num_mobile > len(nodes):
        num_mobile = len(nodes)

    # Get the index of mobile nodes
    mobile_nodes = random.sample(list(nodes.keys()), num_mobile)

    # Assign the role of each node
    for node in nodes:
        node_mob = False
        if node in mobile_nodes:
            node_mob = True
        nodes[node]["mobility"] = node_mob
    return nodes


# Recieve a stopped node
@app.post("/platform/dashboard/{scenario_name}/node/done")
async def node_stopped(scenario_name: str, request: Request):
    user = get_user_by_scenario_name(scenario_name)
    user_data = user_data_store[user]

    if request.headers.get("content-type") == "application/json":
        data = await request.json()
        user_data.nodes_finished.append(data["idx"])
        nodes_list = list_nodes_by_scenario_name(scenario_name)
        finished = True
        # Check if all the nodes of the scenario have finished the experiment
        for node in nodes_list:
            if str(node[1]) not in map(str, user_data.nodes_finished):
                finished = False

        if finished:
            stop_scenario(scenario_name, user)
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


async def assign_available_gpu(scenario_data, role):
    available_gpus = []

    response = await get_available_gpus()
    # Obtain available system_gpus
    available_system_gpus = response.get("available_gpus", None) if response is not None else None

    if available_system_gpus:
        running_scenarios = get_running_scenario(get_all=True)
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
    import subprocess

    from nebula.scenarios import ScenarioManagement

    user_data = user_data_store[user]

    scenario_data = await assign_available_gpu(scenario_data, role)
    # Manager for the actual scenario
    scenarioManagement = ScenarioManagement(scenario_data, user)

    scenario_update_record(
        scenario_name=scenarioManagement.scenario_name,
        username=user,
        start_time=scenarioManagement.start_date_scenario,
        end_time="",
        status="running",
        title=scenario_data["scenario_title"],
        description=scenario_data["scenario_description"],
        network_subnet=scenario_data["network_subnet"],
        model=scenario_data["model"],
        dataset=scenario_data["dataset"],
        rounds=scenario_data["rounds"],
        role=role,
        gpu_id=json.dumps(scenario_data["gpu_id"]),
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

    user_data.nodes_registration[scenarioManagement.scenario_name] = {
        "n_nodes": scenario_data["n_nodes"],
        "nodes": set(),
    }

    user_data.nodes_registration[scenarioManagement.scenario_name]["condition"] = asyncio.Condition()


# Deploy the list of scenarios
async def run_scenarios(role, user):
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

import argparse
import asyncio
import datetime
import io
import json
import logging
import os
import signal
import sys
import zipfile
from urllib.parse import urlencode

import requests

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

logging.basicConfig(level=logging.INFO)


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
    get_run_hashes_scenario,
    get_running_scenario,
    get_scenario_by_name,
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
from nebula.frontend.utils import Utils


class Settings:
    port: int = os.environ.get("NEBULA_FRONTEND_PORT", 6060)
    production: bool = os.environ.get("NEBULA_PRODUCTION", "False") == "True"
    gpu_available: bool = os.environ.get("NEBULA_GPU_AVAILABLE", "False") == "True"
    advanced_analytics: bool = os.environ.get("NEBULA_ADVANCED_ANALYTICS", "False") == "True"
    host_platform: str = os.environ.get("NEBULA_HOST_PLATFORM", "unix")
    log_dir: str = os.environ.get("NEBULA_LOGS_DIR")
    config_dir: str = os.environ.get("NEBULA_CONFIG_DIR")
    cert_dir: str = os.environ.get("NEBULA_CERTS_DIR")
    root_host_path: str = os.environ.get("NEBULA_ROOT_HOST")
    config_frontend_dir: str = os.environ.get("FEDELLAR_CONFIG_FRONTEND_DIR", "config")
    statistics_port: int = os.environ.get("NEBULA_STATISTICS_PORT", 8080)
    secret_key: str = os.environ.get("SECRET_KEY", os.urandom(24).hex())
    PERMANENT_SESSION_LIFETIME: datetime.timedelta = datetime.timedelta(minutes=60)
    templates_dir: str = "templates"


settings = Settings()

logging.info(f"NEBULA_PRODUCTION: {settings.production}")
logging.info(f"NEBULA_ADVANCED_ANALYTICS: {settings.advanced_analytics}")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/nebula/static", StaticFiles(directory="static"), name="static")


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        message = {
            "type": "control",
            "message": f"Client #{len(self.active_connections)} connected",
        }
        await self.broadcast(json.dumps(message))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


manager = ConnectionManager()


@app.websocket("/nebula/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = {
                "type": "control",
                "message": f"Client #{client_id} says: {data}",
            }
            await manager.broadcast(json.dumps(message))
            # await manager.send_personal_message(f"You wrote: {data}", websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        message = {"type": "control", "message": f"Client #{client_id} left the chat"}
        await manager.broadcast(json.dumps(message))


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


nodes_registration = {}

scenarios_list_length = 0

scenarios_finished = 0


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
    return RedirectResponse(url="/nebula")


@app.get("/nebula", response_class=HTMLResponse)
@app.get("/nebula/", response_class=HTMLResponse)
async def nebula_home(request: Request):
    alerts = []
    return templates.TemplateResponse("index.html", {"request": request, "alerts": alerts})


@app.get("/nebula/dashboard/{scenario_name}/private", response_class=HTMLResponse)
async def nebula_dashboard_private(request: Request, scenario_name: str, session: dict = Depends(get_session)):
    if "user" in session:
        return templates.TemplateResponse("private.html", {"request": request, "scenario_name": scenario_name})
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.get("/nebula/admin", response_class=HTMLResponse)
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


@app.post("/nebula/dashboard/{scenario_name}/save_note")
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


@app.get("/nebula/dashboard/{scenario_name}/notes")
async def get_notes_for_scenario(scenario_name: str):
    notes_record = get_notes(scenario_name)
    if notes_record:
        notes_data = dict(zip(notes_record.keys(), notes_record, strict=False))
        return JSONResponse({"status": "success", "notes": notes_data["scenario_notes"]})
    else:
        return JSONResponse({"status": "error", "message": "Notes not found for the specified scenario"})


@app.post("/nebula/login")
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


@app.get("/nebula/logout")
async def nebula_logout(request: Request, session: dict = Depends(get_session)):
    session.pop("user", None)
    return RedirectResponse(url="/nebula")


@app.get("/nebula/user/delete/{user}/")
async def nebula_delete_user(user: str, request: Request, session: dict = Depends(get_session)):
    if session.get("role") == "admin":
        if user == "ADMIN":  # ADMIN account can't be deleted.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if user == session["user"]:  # Current user can't delete himself.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        delete_user_from_db(user)
        return RedirectResponse(url="/nebula/admin")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.post("/nebula/user/add")
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
            return RedirectResponse(url="/nebula/admin")
        else:
            add_user(user, password, role)
            return RedirectResponse(url="/nebula/admin")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.post("/nebula/user/update")
async def nebula_update_user(
    request: Request,
    session: dict = Depends(get_session),
    user: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    if session.get("role") == "admin":
        user_list = list_users()
        if user not in user_list:
            return RedirectResponse(url="/nebula/admin")
        else:
            update_user(user, password, role)
            return RedirectResponse(url="/nebula/admin")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.get("/nebula/api/dashboard/runningscenario", response_class=JSONResponse)
async def nebula_dashboard_runningscenario():
    scenario_running = get_running_scenario()
    if scenario_running:
        scenario_running_as_dict = dict(scenario_running)
        scenario_running_as_dict["scenario_status"] = "running"
        return JSONResponse(scenario_running_as_dict)
    else:
        return JSONResponse({"scenario_status": "not running"})


@app.get("/nebula/api/dashboard", response_class=JSONResponse)
@app.get("/nebula/dashboard", response_class=HTMLResponse)
async def nebula_dashboard(request: Request, session: dict = Depends(get_session)):
    if "user" in session:
        scenarios = get_all_scenarios_and_check_completed()  # Get all scenarios after checking if they are completed
        scenario_running = get_running_scenario()
    else:
        scenarios = None
        scenario_running = None

    bool_completed = False
    if scenario_running:
        bool_completed = scenario_running[5] == "completed"

    if scenarios:
        if request.url.path == "/nebula/dashboard":
            return templates.TemplateResponse(
                "dashboard.html",
                {
                    "request": request,
                    "scenarios": scenarios,
                    "scenarios_list_length": scenarios_list_length,
                    "scenarios_finished": scenarios_finished,
                    "scenario_running": scenario_running,
                    "scenario_completed": bool_completed,
                    "user_logged_in": session.get("user"),
                },
            )
        elif request.url.path == "/nebula/api/dashboard":
            scenarios_as_dict = [dict(row) for row in scenarios]
            return JSONResponse(scenarios_as_dict)
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    else:
        if request.url.path == "/nebula/dashboard":
            return templates.TemplateResponse(
                "dashboard.html",
                {
                    "request": request,
                    "user_logged_in": session.get("user"),
                },
            )
        elif request.url.path == "/nebula/api/dashboard":
            return JSONResponse({"scenarios_status": "not found in database"})
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@app.get("/nebula/api/dashboard/{scenario_name}/monitor", response_class=JSONResponse)
@app.get("/nebula/dashboard/{scenario_name}/monitor", response_class=HTMLResponse)
async def nebula_dashboard_monitor(scenario_name: str, request: Request, session: dict = Depends(get_session)):
    scenario = get_scenario_by_name(scenario_name)
    if scenario:
        nodes_list = list_nodes_by_scenario_name(scenario_name)
        if nodes_list:
            nodes_config = []
            nodes_status = []
            for node in nodes_list:
                nodes_config.append((node[2], node[3], node[4]))  # IP, Port, Role
                if datetime.datetime.now() - datetime.datetime.strptime(
                    node[8], "%Y-%m-%d %H:%M:%S.%f"
                ) > datetime.timedelta(seconds=25):
                    nodes_status.append(False)
                else:
                    nodes_status.append(True)
            nodes_table = zip(
                [x[0] for x in nodes_list],  # UID
                [x[1] for x in nodes_list],  # IDX
                [x[2] for x in nodes_list],  # IP
                [x[3] for x in nodes_list],  # Port
                [x[4] for x in nodes_list],  # Role
                [x[5] for x in nodes_list],  # Neighbors
                [x[6] for x in nodes_list],  # Latitude
                [x[7] for x in nodes_list],  # Longitude
                [x[8] for x in nodes_list],  # Timestamp
                [x[9] for x in nodes_list],  # Federation
                [x[10] for x in nodes_list],  # Round
                [x[11] for x in nodes_list],  # Scenario name
                [x[12] for x in nodes_list],  # Run hash
                nodes_status,
                strict=False,  # Status
            )

            topology_path = Utils.check_path(settings.config_dir, os.path.join(scenario_name, "topology.png"))
            if os.path.exists(topology_path):
                latest_participant_file_mtime = max([
                    os.path.getmtime(
                        os.path.join(
                            settings.config_dir,
                            scenario_name,
                            f"participant_{node[1]}.json",
                        )
                    )
                    for node in nodes_list
                ])
                if os.path.getmtime(topology_path) < latest_participant_file_mtime:
                    update_topology(scenario[0], nodes_list, nodes_config)
            else:
                update_topology(scenario[0], nodes_list, nodes_config)

            if request.url.path == f"/nebula/dashboard/{scenario_name}/monitor":
                return templates.TemplateResponse(
                    "monitor.html",
                    {
                        "request": request,
                        "scenario_name": scenario_name,
                        "scenario": scenario,
                        "nodes": nodes_table,
                        "user_logged_in": session.get("user"),
                    },
                )
            elif request.url.path == f"/nebula/api/dashboard/{scenario_name}/monitor":
                return JSONResponse({
                    "scenario_status": scenario[5],
                    "nodes_table": list(nodes_table),
                    "scenario_name": scenario[0],
                    "scenario_title": scenario[3],
                    "scenario_description": scenario[4],
                })
            else:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        else:
            if request.url.path == f"/nebula/dashboard/{scenario_name}/monitor":
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
            elif request.url.path == f"/nebula/api/dashboard/{scenario_name}/monitor":
                return JSONResponse({
                    "scenario_status": scenario[5],
                    "nodes_table": [],
                    "scenario_name": scenario[0],
                    "scenario_title": scenario[3],
                    "scenario_description": scenario[4],
                })
            else:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    else:
        if request.url.path == f"/nebula/dashboard/{scenario_name}/monitor":
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
        elif request.url.path == f"/nebula/api/dashboard/{scenario_name}/monitor":
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
            if neighbour != "":
                if neighbour in nodes:
                    matrix[
                        nodes.index(node[2] + ":" + str(node[3])),
                        nodes.index(neighbour),
                    ] = 1
    from nebula.addons.topologymanager import TopologyManager

    tm = TopologyManager(n_nodes=len(nodes_list), topology=matrix, scenario_name=scenario_name)
    tm.update_nodes(nodes_config)
    tm.draw_graph(path=os.path.join(settings.config_dir, scenario_name, "topology.png"))


@app.post("/nebula/dashboard/{scenario_name}/node/update")
async def nebula_update_node(scenario_name: str, request: Request, session: dict = Depends(get_session)):
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
                "neighbors": config["network_args"]["neighbors"],
                "latitude": config["mobility_args"]["latitude"],
                "longitude": config["mobility_args"]["longitude"],
                "timestamp": str(timestamp),
                "federation": config["scenario_args"]["federation"],
                "round": config["federation_args"]["round"],
                "name": config["scenario_args"]["name"],
                "status": True,
                "neighbors_distance": neighbors_distance,
            }

            try:
                await manager.broadcast(json.dumps(node_update))
            except Exception as e:
                logging.exception(f"Error sending node_update to socketio: {e}")
                pass

            return JSONResponse({"message": "Node updated", "status": "success"}, status_code=200)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


@app.post("/nebula/dashboard/{scenario_name}/node/register")
async def nebula_register_node(scenario_name: str, request: Request):
    if request.headers.get("content-type") == "application/json":
        data = await request.json()
        node = data["node"]
        logging.info(f"Registering node {node} for scenario {scenario_name}")
        async with nodes_registration[scenario_name]["condition"]:
            nodes_registration[scenario_name]["nodes"].add(node)
            logging.info(f"Node {node} registered")
            if len(nodes_registration[scenario_name]["nodes"]) == nodes_registration[scenario_name]["n_nodes"]:
                nodes_registration[scenario_name]["condition"].notify_all()
                logging.info("All nodes registered")

        return JSONResponse({"message": "Node registered", "status": "success"}, status_code=200)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


@app.get("/nebula/dashboard/scenarios/node/list")
async def nebula_list_all_scenarios(session: dict = Depends(get_session)):
    if "user" not in session or session["role"] not in ["admin", "user"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    scenarios = {}
    for scenario_name, scenario_info in nodes_registration.items():
        scenarios[scenario_name] = list(scenario_info["nodes"])

    if not scenarios:
        return JSONResponse({"message": "No scenarios found", "status": "error"}, status_code=404)

    return JSONResponse({"scenarios": scenarios, "status": "success"}, status_code=200)


@app.get("/nebula/dashboard/scenarios/node/erase")
async def nebula_erase_all_nodes(session: dict = Depends(get_session)):
    if "user" not in session or session["role"] not in ["admin", "user"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    nodes_registration.clear()
    return JSONResponse({"message": "All nodes erased", "status": "success"}, status_code=200)


@app.get("/nebula/dashboard/{scenario_name}/node/wait")
async def nebula_wait_nodes(scenario_name: str):
    if scenario_name not in nodes_registration:
        return JSONResponse({"message": "Scenario not found", "status": "error"}, status_code=404)

    async with nodes_registration[scenario_name]["condition"]:
        while len(nodes_registration[scenario_name]["nodes"]) < nodes_registration[scenario_name]["n_nodes"]:
            await nodes_registration[scenario_name]["condition"].wait()
        return JSONResponse({"message": "All nodes registered", "status": "success"}, status_code=200)


@app.get("/nebula/dashboard/{scenario_name}/node/{id}/infolog")
async def nebula_monitor_log(scenario_name: str, id: str):
    logs = Utils.check_path(settings.log_dir, os.path.join(scenario_name, f"participant_{id}.log"))
    if os.path.exists(logs):
        return FileResponse(logs, media_type="text/plain", filename=f"participant_{id}.log")
    else:
        raise HTTPException(status_code=404, detail="Log file not found")


@app.get(
    "/nebula/dashboard/{scenario_name}/node/{id}/infolog/{number}",
    response_class=PlainTextResponse,
)
async def nebula_monitor_log_x(scenario_name: str, id: str, number: int):
    logs = Utils.check_path(settings.log_dir, os.path.join(scenario_name, f"participant_{id}.log"))
    if os.path.exists(logs):
        with open(logs) as f:
            lines = f.readlines()[-number:]
            lines = "".join(lines)
            converter = Ansi2HTMLConverter()
            html_text = converter.convert(lines, full=False)
            return Response(content=html_text, media_type="text/plain")
    else:
        return Response(content="No logs available", media_type="text/plain")


@app.get("/nebula/dashboard/{scenario_name}/node/{id}/debuglog")
async def nebula_monitor_log_debug(scenario_name: str, id: str):
    logs = Utils.check_path(settings.log_dir, os.path.join(scenario_name, f"participant_{id}_debug.log"))
    if os.path.exists(logs):
        return FileResponse(logs, media_type="text/plain", filename=f"participant_{id}_debug.log")
    else:
        raise HTTPException(status_code=404, detail="Log file not found")


@app.get("/nebula/dashboard/{scenario_name}/node/{id}/errorlog")
async def nebula_monitor_log_error(scenario_name: str, id: str):
    logs = Utils.check_path(settings.log_dir, os.path.join(scenario_name, f"participant_{id}_error.log"))
    if os.path.exists(logs):
        return FileResponse(logs, media_type="text/plain", filename=f"participant_{id}_error.log")
    else:
        raise HTTPException(status_code=404, detail="Log file not found")


@app.get("/nebula/dashboard/{scenario_name}/topology/image/")
async def nebula_monitor_image(scenario_name: str):
    topology_image = Utils.check_path(settings.log_dir, os.path.join(scenario_name, "topology.png"))
    if os.path.exists(topology_image):
        return FileResponse(topology_image, media_type="image/png")
    else:
        raise HTTPException(status_code=404, detail="Topology image not found")


def stop_scenario(scenario_name):
    from nebula.scenarios import ScenarioManagement

    ScenarioManagement.stop_participants()
    ScenarioManagement.stop_blockchain()
    scenario_set_status_to_finished(scenario_name)


def stop_all_scenarios():
    from nebula.scenarios import ScenarioManagement

    ScenarioManagement.stop_participants()
    ScenarioManagement.stop_blockchain()
    scenario_set_all_status_to_finished()


@app.get("/nebula/dashboard/{scenario_name}/stop/{stop_all}")
async def nebula_stop_scenario(
    scenario_name: str,
    stop_all: bool,
    request: Request,
    session: dict = Depends(get_session),
):
    if "user" in session:
        if session["role"] == "demo":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        elif session["role"] == "user":
            if not check_scenario_with_role(session["role"], scenario_name):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if stop_all:
            stop_all_scenarios_event.set()
            global scenarios_list_length
            global scenarios_finished
            scenarios_list_length = 0
            scenarios_finished = 0
            stop_scenario(scenario_name)
        else:
            finish_scenario_event.set()
            stop_scenario(scenario_name)
        return RedirectResponse(url="/nebula/dashboard")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


def remove_scenario(scenario_name=None):
    from nebula.scenarios import ScenarioManagement

    if settings.advanced_analytics:
        from aim.sdk.repo import Repo

        # NEBULALOGGER START
        try:
            repo = Repo.from_path(f"{settings.log_dir}")
            list_tuples_participant_hash = get_run_hashes_scenario(scenario_name)
            hashes = [tuple[1] for tuple in list_tuples_participant_hash]
            logging.info(f"Removing statistics from {scenario_name}: {hashes}")
            success, remaining_runs = repo.delete_runs(hashes)
            if success:
                logging.info(f"Successfully deleted {len(hashes)} runs.")
            else:
                logging.info("Something went wrong while deleting runs.")
                logging.info(f"Remaining runs: {remaining_runs}")
        except Exception as e:
            logging.exception(f"Error removing statistics from {scenario_name}: {e}")
            pass
        # NEBULALOGGER END
    # Remove registered nodes and conditions
    nodes_registration.pop(scenario_name, None)
    remove_nodes_by_scenario_name(scenario_name)
    remove_scenario_by_name(scenario_name)
    remove_note(scenario_name)
    ScenarioManagement.remove_files_by_scenario(scenario_name)


@app.get("/nebula/dashboard/{scenario_name}/remove")
async def nebula_remove_scenario(scenario_name: str, request: Request, session: dict = Depends(get_session)):
    if "user" in session:
        if session["role"] == "demo":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        elif session["role"] == "user":
            if not check_scenario_with_role(session["role"], scenario_name):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        remove_scenario(scenario_name)
        return RedirectResponse(url="/nebula/dashboard")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


if settings.advanced_analytics:
    logging.info("Advanced analytics enabled")

    # NEBULALOGGER START
    def get_tracking_hash_scenario(scenario_name):
        import requests

        url = f"http://127.0.0.1:{settings.statistics_port}/nebula/statistics/api/experiments"
        # Get JSON data from the URL
        response = requests.get(url)
        if response.status_code == 200:
            experiments = response.json()
            for experiment in experiments:
                if experiment["name"] == scenario_name:
                    return experiment["id"]

        return None

    @app.get("/nebula/dashboard/statistics/", response_class=HTMLResponse)
    @app.get("/nebula/dashboard/{scenario_name}/statistics/", response_class=HTMLResponse)
    async def nebula_dashboard_statistics(request: Request, scenario_name: str = None):
        statistics_url = "/nebula/statistics/"
        if scenario_name is not None:
            experiment_hash = get_tracking_hash_scenario(scenario_name=scenario_name)
            statistics_url += f"experiments/{experiment_hash}/runs"

        return templates.TemplateResponse("statistics.html", {"request": request, "statistics_url": statistics_url})

    @app.get(
        "/nebula/dashboard/{scenario_name}/node/{hash}/metrics",
        response_class=HTMLResponse,
    )
    async def nebula_dashboard_node_metrics(request: Request, scenario_name: str, hash: str):
        statistics_url = f"/nebula/statistics/runs/{hash}/metrics"
        return templates.TemplateResponse("statistics.html", {"request": request, "statistics_url": statistics_url})

    @app.api_route("/nebula/statistics/", methods=["GET", "POST"])
    @app.api_route("/nebula/statistics/{path:path}", methods=["GET", "POST"])
    async def statistics_proxy(request: Request, path: str = None, session: dict = Depends(get_session)):
        if "user" in session:
            query_string = urlencode(request.query_params)

            url = f"http://127.0.0.1:{settings.statistics_port}/nebula/statistics"
            url = f"{url}{('/' + path) if path else '/'}" + (f"?{query_string}" if query_string else "")

            headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}

            response = requests.request(
                method=request.method,
                url=url,
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

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(filtered_headers),
            )
        else:
            raise HTTPException(status_code=401)

    @app.get("/nebula/dashboard/{scenario_name}/download/metrics")
    async def nebula_dashboard_download_metrics(
        scenario_name: str, request: Request, session: dict = Depends(get_session)
    ):
        from aim.sdk.repo import Repo

        if "user" in session:
            # Obtener las métricas del escenario
            os.makedirs(
                Utils.check_path(settings.log_dir, os.path.join(scenario_name, "metrics")),
                exist_ok=True,
            )

            aim_repo = Repo.from_path("/nebula/nebula/app/logs")
            query = f"run.experiment == '{scenario_name}'"
            df = aim_repo.query_metrics(query).dataframe()

            hash_to_participant = {hash: participant for participant, hash in get_run_hashes_scenario(scenario_name)}
            df["participant"] = df["run.hash"].map(hash_to_participant)
            df.drop(
                columns=["run", "run.hash", "metric.context", "epoch"],
                axis=1,
                inplace=True,
            )
            cols = df.columns.tolist()
            cols.remove("participant")
            cols.remove("metric.name")
            df = df.reindex(columns=["participant", "metric.name"] + cols)

            for name, group in df.groupby("participant"):
                group.to_csv(
                    os.path.join(settings.log_dir, scenario_name, "metrics", f"{name}.csv"),
                    index=True,
                )

            # Crear un archivo zip con las métricas, enviarlo al usuario y eliminarlo
            memory_file = io.BytesIO()
            with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zipf:
                zipdir(os.path.join(settings.log_dir, scenario_name, "metrics"), zipf)

            memory_file.seek(0)

            return StreamingResponse(
                memory_file,
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename={scenario_name}_metrics.zip"},
            )
        else:
            raise HTTPException(status_code=401)

    # NEBULALOGGER END
else:
    logging.info("Advanced analytics disabled")

    # TENSORBOARD START
    @app.get("/nebula/dashboard/statistics/", response_class=HTMLResponse)
    @app.get("/nebula/dashboard/{scenario_name}/statistics/", response_class=HTMLResponse)
    async def nebula_dashboard_statistics(request: Request, scenario_name: str = None):
        statistics_url = "/nebula/statistics/"
        if scenario_name is not None:
            statistics_url += f"?smoothing=0&runFilter={scenario_name}"

        return templates.TemplateResponse("statistics.html", {"request": request, "statistics_url": statistics_url})

    @app.api_route("/nebula/statistics/", methods=["GET", "POST"])
    @app.api_route("/nebula/statistics/{path:path}", methods=["GET", "POST"])
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
                content = content.replace("url(/", "url(/nebula/statistics/")
                content = content.replace('src="/', 'src="/nebula/statistics/')
                content = content.replace('href="/', 'href="/nebula/statistics/')
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
        new_url = "/nebula/statistics/experiment/" + path
        if query_params:
            new_url += "?" + urlencode(query_params)

        return RedirectResponse(url=new_url)

    # TENSORBOARD END


def zipdir(path, ziph):
    # ziph is zipfile handle
    for root, dirs, files in os.walk(path):
        for file in files:
            ziph.write(
                os.path.join(root, file),
                os.path.relpath(os.path.join(root, file), os.path.join(path, "..")),
            )


@app.get("/nebula/dashboard/{scenario_name}/download/logs")
async def nebula_dashboard_download_logs_metrics(
    scenario_name: str, request: Request, session: dict = Depends(get_session)
):
    if "user" in session:
        log_folder = Utils.check_path(settings.log_dir, scenario_name)
        config_folder = Utils.check_path(settings.config_dir, scenario_name)
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


@app.get("/nebula/dashboard/deployment/", response_class=HTMLResponse)
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


# Stop all scenarios in the scenarios_list
stop_all_scenarios_event = asyncio.Event()

# Finish actual scenario
finish_scenario_event = asyncio.Event()

# Nodes that completed the experiment
nodes_finished = []


# Recieve a stopped node
@app.post("/nebula/dashboard/{scenario_name}/node/done")
async def node_stopped(scenario_name: str, request: Request):
    if request.headers.get("content-type") == "application/json":
        data = await request.json()
        nodes_finished.append(data["idx"])
        nodes_list = list_nodes_by_scenario_name(scenario_name)
        finished = True
        # Check if all the nodes of the scenario have finished the experiment
        for node in nodes_list:
            if str(node[1]) not in map(str, nodes_finished):
                finished = False

        if finished:
            nodes_finished.clear()
            finish_scenario_event.set()
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


async def run_scenario(scenario_data, role):
    import subprocess

    from nebula.scenarios import ScenarioManagement

    # Manager for the actual scenario
    scenarioManagement = ScenarioManagement(scenario_data)

    scenario_update_record(
        scenario_name=scenarioManagement.scenario_name,
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

    nodes_registration[scenarioManagement.scenario_name] = {
        "n_nodes": scenario_data["n_nodes"],
        "nodes": set(),
    }

    nodes_registration[scenarioManagement.scenario_name]["condition"] = asyncio.Condition()

    return scenarioManagement.scenario_name


# Deploy the list of scenarios
async def run_scenarios(data, role):
    global scenarios_finished
    for scenario_data in data:
        finish_scenario_event.clear()
        logging.info(f"Running scenario {scenario_data['scenario_title']}")
        scenario_name = await run_scenario(scenario_data, role)
        # Waits till the scenario is completed
        while not finish_scenario_event.is_set() and not stop_all_scenarios_event.is_set():
            await asyncio.sleep(1)
        if stop_all_scenarios_event.is_set():
            stop_all_scenarios_event.clear()
            stop_scenario(scenario_name)
            return
        scenarios_finished = scenarios_finished + 1
        stop_scenario(scenario_name)
        await asyncio.sleep(5)


@app.post("/nebula/dashboard/deployment/run")
async def nebula_dashboard_deployment_run(
    request: Request,
    background_tasks: BackgroundTasks,
    session: dict = Depends(get_session),
):
    if "user" not in session or session["role"] in ["demo", "user"] and get_running_scenario():
        raise HTTPException(status_code=401)

    if request.headers.get("content-type") != "application/json":
        raise HTTPException(status_code=401)

    stop_all_scenarios()
    finish_scenario_event.clear()
    stop_all_scenarios_event.clear()
    data = await request.json()
    global scenarios_finished, scenarios_list_length
    scenarios_finished = 0
    scenarios_list_length = len(data)
    logging.info(f"Running deployment with {len(data)} scenarios")
    background_tasks.add_task(run_scenarios, data, session["role"])
    return RedirectResponse(url="/nebula/dashboard", status_code=303)
    # return Response(content="Success", status_code=200)


if __name__ == "__main__":
    # Parse args from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000, help="Port to run the frontend on.")
    args = parser.parse_args()
    logging.info(f"Starting frontend on port {args.port}")
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=args.port)

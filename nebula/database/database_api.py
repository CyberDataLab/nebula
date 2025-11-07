
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.concurrency import asynccontextmanager

from nebula.database.database_adapter_factory import factory_database_adapter
from nebula.database.schemas.requests import (
    Routes,
    SaveScenarioRequest,
    StopScenarioRequest,
    FinishScenarioRequest,
    UpdateNodesRequest,
    UpdateNotesRequest,
    GetScenariosRequest,
    GetRunningScenarioRequest,
    CheckScenarioRequest,
)

from nebula.database.schemas.responses import *
from nebula.database.database_broker import DatabaseBroker

database_broker: DatabaseBroker = None

DEFAULT_DB_ERRORS = {
    403: {"model": ErrorResponse, "description": "Database permission denied."},
    422: {"model": ErrorResponse, "description": "Invalid data format."},
    500: {"model": ErrorResponse, "description": "Internal database or query failure."},
    503: {"model": ErrorResponse, "description": "Database unavailable."},
    504: {"model": ErrorResponse, "description": "Database connection timeout."},
}

# Setup logger
def configure_logger(log_file):
    """
    Configures the logging system for the database API.
    """
    log_console_format = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_console_format))
    file_handler = logging.FileHandler(log_file, mode="w")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[
            console_handler,
            file_handler,
        ],
    )
    uvicorn_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access"]
    for logger_name in uvicorn_loggers:
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = False
        handler = logging.FileHandler(log_file, mode="a")
        handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
        logger.addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager for the database API.
    """
    # Code to run on startup
    db_log = os.environ.get("NEBULA_DATABASE_LOG", "database.log")
    configure_logger(db_log)

    database_broker = DatabaseBroker(database_adapter="PostgresDB", broker="", user="", password="", logger=db_log)
    await database_broker.init()

    yield

    # Code to run on shutdown
    await database_broker.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get(Routes.INIT)
async def read_root():
    return {"message": "Welcome to the NEBULA Database API"}


# Scenarios
@app.post(
    Routes.SAVE,
    response_model=SaveScenarioResponse,
    responses=DEFAULT_DB_ERRORS,
    summary="Save a scenario or update an existing one.",
    description=(
        "Save a new federated learning scenario or update the information for an existing one."
    ),
)
async def save_scenario(
    federation_id: str,
    request: SaveScenarioRequest,
):
    success = await database_broker.save_scenario(
        federation_id = federation_id,
        **request.model_dump()
    )
    return SaveScenarioResponse(success=success)


@app.post(
    Routes.STOP,
    response_model=StopScenarioResponse,
    responses=DEFAULT_DB_ERRORS,
    summary="Change status to finish on scenario.",
    description=(
        "Change status to finish on a single scenario or change all statuses if required."
    ),
)
async def stop_scenario(
    federation_id: str,
    request: StopScenarioRequest,
):
    success = await database_broker.stop_scenario(federation_id, **request.model_dump())
    return StopScenarioResponse(success=success)


@app.post(
    Routes.REMOVE,
    response_model=RemoveScenarioResponse,
    responses=DEFAULT_DB_ERRORS,
    summary="Remove scenario.",
    description=(
        "Delete a scenario from the database by its unique name."
    ),
)
async def remove_scenario(
    federation_id: str
):
    success = await database_broker.remove_scenario(federation_id)
    return RemoveScenarioResponse(success=success)


@app.get(
    Routes.GET_SCENARIOS_BY_USER,
    response_model=GetScenariosResponse,
    responses=DEFAULT_DB_ERRORS,
    summary="Get all scenarios.",
    description=(
        "Get all scenarios on database, including separatatly the one running if there is currently one."
    ),
)
async def get_scenarios(
    request: GetScenariosRequest = Depends()
):
    scenarios_dict = await database_broker.get_scenarios(**request.model_dump())
    return GetScenariosResponse(scenarios=scenarios_dict)


@app.post(
    Routes.FINISH,
    response_model=FinishScenarioResponse,
    responses=DEFAULT_DB_ERRORS,
    summary="Set scenarios to finish state.",
    description=(
        "Set all scenarios or a specified one to state finish."
    ),
)
async def set_scenario_status_to_finished(
    federation_id: str,
    request: FinishScenarioRequest,
):
    success = await database_broker.set_scenario_status_to_finished(federation_id, **request.model_dump())
    return FinishScenarioResponse(success=success)


@app.get(
    Routes.RUNNING,
    response_model=GetRunningScenarioResponse,
    responses=DEFAULT_DB_ERRORS,
    summary="Get scenarios running.",
    description=(
        "Get all scenarios running or filtered by user."
    ),
)
async def get_running_scenario(request: GetRunningScenarioRequest = Depends()):
    scenarios = await database_broker.get_running_scenario(**request.model_dump())
    return GetRunningScenarioResponse(scenarios=scenarios)


@app.get(
    Routes.CHECK_SCENARIO,
    response_model=CheckScenarioResponse,
    responses=DEFAULT_DB_ERRORS,
    summary="Verify scenarios access.",
    description=(
        "Verify if a scenario exists that the user with the given role and username can access."
    ),
)
async def check_scenario(
    request: CheckScenarioRequest = Depends()
):
    allowed = await database_broker.check_scenario(**request.model_dump())
    return CheckScenarioRequest(allowed=allowed)


@app.get(
    Routes.GET_SCENARIOS_BY_SCENARIO_NAME,
    response_model=GetScenarioByID,
    responses=DEFAULT_DB_ERRORS,
    summary="Get a scenario.",
    description=(
        "Retrieves the complete record for a scenario using its ID."
    ),
)
async def get_scenario_by_name(
    federation_id: str
):
    scenario = await database_broker.get_scenario_by_name(federation_id)
    return GetScenarioByID(scenario=scenario)


# Nodes
@app.get(
    Routes.NODES_BY_FEDERATION_ID,
    response_model=ListNodesByIDResponse,
    responses=DEFAULT_DB_ERRORS,
    summary="Get nodes from a scenario.",
    description=(
        "Fetches all nodes associated with a specific scenario, ordered by their index as integers."
    ),
)
async def list_nodes_by_federation_id(
    federation_id: str
):
    nodes = await database_broker.list_nodes_by_federation_id(federation_id)
    return ListNodesByIDResponse(nodes=nodes)

@app.post(
    Routes.NODES_REMOVE,
    response_model=RemoveNodesByID,
    responses=DEFAULT_DB_ERRORS,
    summary="Remove nodes for a scenario.",
    description=(
        "Deletes all nodes associated with a specific scenario from the database."
    ),
)
async def remove_nodes_by_federation_id(federation_id: str):
    success = await database_broker.remove_nodes_by_federation_id(federation_id)
    return RemoveNodesByID(success=success)


# Notes
@app.get(
    Routes.NOTES_BY_FEDERATION_ID,
    response_model=GetNotesByID,
    responses=DEFAULT_DB_ERRORS,
    summary="Get scenario notes",
    description=(
        "Retrieve notes associated with a specific scenario."
    ),
)
async def get_notes_by_federation_id(
    federation_id: str
):
    notes_record = await database_broker.get_notes_by_federation_id(federation_id)
    return GetNotesByID(notes=notes_record)


@app.post(
    Routes.NOTES_UPDATE,
    response_model=SaveNotesByID,
    responses=DEFAULT_DB_ERRORS,
    summary="Save scenario notes",
    description=(
        "Save or update notes associated with a specific scenario."
    ),
)
async def update_notes_by_scenario_name(federation_id: str, request: UpdateNotesRequest):
    success = await database_broker.update_notes_by_scenario_name(federation_id ,**request.model_dump())
    return SaveNotesByID(success=success)


@app.post(
    Routes.NOTES_REMOVE,
    response_model=RemoveNotesByID,
    responses=DEFAULT_DB_ERRORS,
    summary="Remove scenario notes",
    description=(
        "Delete the note associated with a specific scenario."
    ),
)
async def remove_notes_by_federation_id(federation_id: str):
    success = await database_broker.remove_nodes_by_federation_id(federation_id)
    return RemoveNotesByID(success=success)

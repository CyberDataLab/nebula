
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.concurrency import asynccontextmanager

from nebula.database.database_adapter_factory import factory_database_adapter
from nebula.database.utils_requests import (
    Routes,
    ScenarioUpdateRequest,
    ScenarioStopRequest,
    ScenarioRemoveRequest,
    ScenarioFinishRequest,
    NotesUpdateRequest,
    NotesRemoveRequest,
    NodesRemoveRequest,
    UserAddRequest,
    UserDeleteRequest,
    UserUpdateRequest,
    UserVerifyRequest,
    NodesUpdateRequest,
    GetScenariosRequest,
    GetRunningScenarioRequest,
    CheckScenarioRequest,
    GetScenarioByNameRequest,
    ListNodesByScenarioNameRequest,
    GetNotesByScenarioNameRequest,
    ListUsersRequest,
    GetUserByScenarioNameRequest,
)

# Get a database instance
db = factory_database_adapter("PostgresDB")


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

    # Initialize the database connection pool
    await db._init_db_pool()
    await db._insert_default_admin()

    yield

    # Code to run on shutdown
    await db._close_db_pool()


app = FastAPI(lifespan=lifespan)


@app.get(Routes.INIT)
async def read_root():
    return {"message": "Welcome to the NEBULA Database API"}


# Scenarios
@app.post(Routes.UPDATE)
async def update_scenario(
    payload: ScenarioUpdateRequest,
):
    try:
        await db._scenario_update_record(
            **payload.model_dump()
        )
        return {"message": f"Scenario {payload.scenario_name} updated successfully"}
    except Exception as e:
        logging.exception(
            f"Error updating scenario {payload.scenario_name}: {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.STOP)
async def stop_scenario(
    payload: ScenarioStopRequest,
):
    try:
        await db._finish_scenario(payload.scenario_name, payload.all)
        return {"message": "Finished status set successfully"}
    except Exception as e:
        logging.exception(
            f"Error stopping scenario {payload.scenario_name}: {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.REMOVE)
async def remove_scenario(
    payload: ScenarioRemoveRequest,
):
    try:
        await db._remove_scenario_by_name(payload.scenario_name)
        return {"message": f"Scenario {payload.scenario_name} removed successfully"}
    except Exception as e:
        logging.exception(
            f"Error removing scenario {payload.scenario_name}: {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(Routes.GET_SCENARIOS_BY_USER)
async def get_scenarios(
    payload: GetScenariosRequest = Depends()
):
    try:
        return await db._get_scenarios(payload.user, payload.role)
    except Exception as e:
        logging.exception(f"Error obtaining scenarios: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.FINISH)
async def set_scenario_status_to_finished(
    payload: ScenarioFinishRequest,
):
    try:
        await db._finish_scenario(
            payload.scenario_name, payload.all
        )
        return {"message": "Finished status set successfully"}
    except Exception as e:
        logging.exception(
            f"Error setting scenario {payload.scenario_name} to finished: {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(Routes.RUNNING)
async def get_running_scenario_endpoint(payload: GetRunningScenarioRequest = Depends()):
    try:
        return await db._get_running_scenario(get_all=payload.get_all)
    except Exception as e:
        logging.exception(f"Error obtaining running scenario: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(Routes.CHECK_SCENARIO)
async def check_scenario(
    payload: CheckScenarioRequest = Depends()
):
    try:
        params = CheckScenarioRequest(**payload.model_dump())
        allowed = await db._check_scenario_with_role(params.role, params.scenario_name, params.user)
        return {"allowed": allowed}
    except Exception as e:
        logging.exception(f"Error checking scenario with role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(Routes.GET_SCENARIOS_BY_SCENARIO_NAME)
async def get_scenario_by_name_endpoint(
    payload: GetScenarioByNameRequest = Depends(),
):
    try:
        scenario = await db._get_scenario_by_name(payload.scenario_name)
        return scenario
    except Exception as e:
        logging.exception(f"Error obtaining scenario {payload.scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Nodes
@app.get(Routes.NODES_BY_SCENARIO_NAME)
async def list_nodes_by_scenario_name_endpoint(
    payload: ListNodesByScenarioNameRequest = Depends()
):
    try:
        nodes = await db._list_nodes_by_scenario_name(payload.scenario_name)
        return nodes
    except Exception as e:
        logging.exception(f"Error obtaining nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.NODES_UPDATE)
async def update_node_record(payload: NodesUpdateRequest):
    try:
        # Build extras from mobility_args
        extras = {
            "latitude": payload.mobility_args.latitude,
            "longitude": payload.mobility_args.longitude,
        }
        await db._update_node_record(
            str(payload.device_args.uid),
            str(payload.device_args.idx),
            str(payload.network_args.ip),
            str(payload.network_args.port),
            str(payload.device_args.role),
            payload.network_args.neighbors,
            extras,
            str(payload.timestamp),
            str(payload.scenario_args.federation),
            str(payload.federation_args.round),
            str(payload.scenario_args.name),
            str(payload.tracking_args.run_hash),
            bool(payload.device_args.malicious),
        )
        return {"message": "Node updated successfully"}
    except Exception as e:
        logging.exception(f"Error updating node: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.NODES_REMOVE)
async def remove_nodes_by_scenario_name_endpoint(payload: NodesRemoveRequest):
    try:
        await db._remove_nodes_by_scenario_name(payload.scenario_name)
        return {"message": f"Nodes for scenario {payload.scenario_name} removed successfully"}
    except Exception as e:
        logging.exception(f"Error removing nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Notes
@app.get(Routes.NOTES_BY_SCENARIO_NAME)
async def get_notes_by_scenario_name(
    payload: GetNotesByScenarioNameRequest = Depends()
):
    try:
        notes_record = await db._get_notes(payload.scenario_name)
        return notes_record
    except Exception as e:
        logging.exception(f"Error obtaining notes for scenario {payload.scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.NOTES_UPDATE)
async def update_notes_by_scenario_name(payload: NotesUpdateRequest):
    try:
        await db._save_notes(payload.scenario_name, payload.notes)
        return {"message": f"Notes for scenario {payload.scenario_name} updated successfully"}
    except Exception as e:
        logging.exception(f"Error updating notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.NOTES_REMOVE)
async def remove_notes_by_scenario_name_endpoint(payload: NotesRemoveRequest):
    try:
        await db._remove_note(payload.scenario_name)
        return {"message": f"Notes for scenario {payload.scenario_name} removed successfully"}
    except Exception as e:
        logging.exception(f"Error removing notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Users
@app.get(Routes.USER_LIST)
async def list_users_controller(payload: ListUsersRequest = Depends()):
    try:
        return {"users": await db._list_users(payload.all_info)}
    except Exception as e:
        logging.exception(f"Error retrieving users: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error retrieving users: {e}")


@app.get(Routes.USER_BY_SCENARIO_NAME)
async def get_user_by_scenario_name_endpoint(
    payload: GetUserByScenarioNameRequest = Depends()
):
    try:
        user = await db._get_user_by_scenario_name(payload.scenario_name)
        return user
    except Exception as e:
        logging.exception(f"Error obtaining user for scenario {payload.scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.USER_ADD)
async def add_user_controller(payload: UserAddRequest):
    try:
        await db._add_user(payload.user, payload.password, payload.role)
        return {"detail": "User added successfully"}
    except Exception as e:
        logging.exception(f"Error adding user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error adding user: {e}")


@app.post(Routes.USER_DELETE)
async def remove_user_controller(payload: UserDeleteRequest):
    try:
        await db._delete_user_from_db(payload.user)
        return {"detail": "User deleted successfully"}
    except Exception as e:
        logging.exception(f"Error deleting user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting user: {e}")


@app.post(Routes.USER_UPDATE)
async def update_user_controller(payload: UserUpdateRequest):
    try:
        await db._update_user(payload.user, payload.password, payload.role)
        return {"detail": "User updated successfully"}
    except Exception as e:
        logging.exception(f"Error updating user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error updating user: {e}")


@app.post(Routes.USER_VERIFY)
async def verify_user_controller(payload: UserVerifyRequest):
    try:
        auth = await db._verify(payload.user, payload.password)
        if auth:
            return auth
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except Exception as e:
        logging.exception(f"Error verifying user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error verifying user: {e}")

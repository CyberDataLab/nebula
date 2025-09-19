
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
    request: ScenarioUpdateRequest,
):
    try:
        await db._scenario_update_record(
            **request.model_dump()
        )
        return {"message": f"Scenario {request.scenario_name} updated successfully"}
    except Exception as e:
        logging.exception(
            f"Error updating scenario {request.scenario_name}: {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.STOP)
async def stop_scenario(
    request: ScenarioStopRequest,
):
    try:
        await db._finish_scenario(request.scenario_name, request.all)
        return {"message": "Finished status set successfully"}
    except Exception as e:
        logging.exception(
            f"Error stopping scenario {request.scenario_name}: {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.REMOVE)
async def remove_scenario(
    request: ScenarioRemoveRequest,
):
    try:
        await db._remove_scenario_by_name(request.scenario_name)
        return {"message": f"Scenario {request.scenario_name} removed successfully"}
    except Exception as e:
        logging.exception(
            f"Error removing scenario {request.scenario_name}: {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(Routes.GET_SCENARIOS_BY_USER)
async def get_scenarios(
    request: GetScenariosRequest = Depends()
):
    try:
        return await db._get_scenarios(request.user, request.role)
    except Exception as e:
        logging.exception(f"Error obtaining scenarios: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.FINISH)
async def set_scenario_status_to_finished(
    request: ScenarioFinishRequest,
):
    try:
        await db._finish_scenario(
            request.scenario_name, request.all
        )
        return {"message": "Finished status set successfully"}
    except Exception as e:
        logging.exception(
            f"Error setting scenario {request.scenario_name} to finished: {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(Routes.RUNNING)
async def get_running_scenario_endpoint(request: GetRunningScenarioRequest = Depends()):
    try:
        return await db._get_running_scenario(get_all=request.get_all)
    except Exception as e:
        logging.exception(f"Error obtaining running scenario: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(Routes.CHECK_SCENARIO)
async def check_scenario(
    request: CheckScenarioRequest = Depends()
):
    try:
        allowed = await db._check_scenario_with_role(**request.model_dump())
        return {"allowed": allowed}
    except Exception as e:
        logging.exception(f"Error checking scenario with role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(Routes.GET_SCENARIOS_BY_SCENARIO_NAME)
async def get_scenario_by_name_endpoint(
    request: GetScenarioByNameRequest = Depends(),
):
    try:
        scenario = await db._get_scenario_by_name(request.scenario_name)
        return scenario
    except Exception as e:
        logging.exception(f"Error obtaining scenario {request.scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Nodes
@app.get(Routes.NODES_BY_SCENARIO_NAME)
async def list_nodes_by_scenario_name_endpoint(
    request: ListNodesByScenarioNameRequest = Depends()
):
    try:
        nodes = await db._list_nodes_by_scenario_name(request.scenario_name)
        return nodes
    except Exception as e:
        logging.exception(f"Error obtaining nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.NODES_UPDATE)
async def update_node_record(request: NodesUpdateRequest):
    try:
        # Build extras from mobility_args
        extras = {
            "latitude": request.mobility_args.latitude,
            "longitude": request.mobility_args.longitude,
        }
        await db._update_node_record(
            str(request.device_args.uid),
            str(request.device_args.idx),
            str(request.network_args.ip),
            str(request.network_args.port),
            str(request.device_args.role),
            request.network_args.neighbors,
            extras,
            str(request.timestamp),
            str(request.scenario_args.federation),
            str(request.federation_args.round),
            str(request.scenario_args.name),
            str(request.tracking_args.run_hash),
            bool(request.device_args.malicious),
        )
        return {"message": "Node updated successfully"}
    except Exception as e:
        logging.exception(f"Error updating node: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.NODES_REMOVE)
async def remove_nodes_by_scenario_name_endpoint(request: NodesRemoveRequest):
    try:
        await db._remove_nodes_by_scenario_name(request.scenario_name)
        return {"message": f"Nodes for scenario {request.scenario_name} removed successfully"}
    except Exception as e:
        logging.exception(f"Error removing nodes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Notes
@app.get(Routes.NOTES_BY_SCENARIO_NAME)
async def get_notes_by_scenario_name(
    request: GetNotesByScenarioNameRequest = Depends()
):
    try:
        notes_record = await db._get_notes(request.scenario_name)
        return notes_record
    except Exception as e:
        logging.exception(f"Error obtaining notes for scenario {request.scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.NOTES_UPDATE)
async def update_notes_by_scenario_name(request: NotesUpdateRequest):
    try:
        await db._save_notes(**request.model_dump())
        return {"message": f"Notes for scenario {request.scenario_name} updated successfully"}
    except Exception as e:
        logging.exception(f"Error updating notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.NOTES_REMOVE)
async def remove_notes_by_scenario_name_endpoint(request: NotesRemoveRequest):
    try:
        await db._remove_note(request.scenario_name)
        return {"message": f"Notes for scenario {request.scenario_name} removed successfully"}
    except Exception as e:
        logging.exception(f"Error removing notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Users
@app.get(Routes.USER_LIST)
async def list_users_controller(request: ListUsersRequest = Depends()):
    try:
        return {"users": await db._list_users(request.all_info)}
    except Exception as e:
        logging.exception(f"Error retrieving users: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error retrieving users: {e}")


@app.get(Routes.USER_BY_SCENARIO_NAME)
async def get_user_by_scenario_name_endpoint(
    request: GetUserByScenarioNameRequest = Depends()
):
    try:
        user = await db._get_user_by_scenario_name(request.scenario_name)
        return user
    except Exception as e:
        logging.exception(f"Error obtaining user for scenario {request.scenario_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(Routes.USER_ADD)
async def add_user_controller(request: UserAddRequest):
    try:
        await db._add_user(**request.model_dump())
        return {"detail": "User added successfully"}
    except Exception as e:
        logging.exception(f"Error adding user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error adding user: {e}")


@app.post(Routes.USER_DELETE)
async def remove_user_controller(request: UserDeleteRequest):
    try:
        await db._delete_user_from_db(request.user)
        return {"detail": "User deleted successfully"}
    except Exception as e:
        logging.exception(f"Error deleting user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting user: {e}")


@app.post(Routes.USER_UPDATE)
async def update_user_controller(request: UserUpdateRequest):
    try:
        await db._update_user(**request.model_dump())
        return {"detail": "User updated successfully"}
    except Exception as e:
        logging.exception(f"Error updating user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error updating user: {e}")


@app.post(Routes.USER_VERIFY)
async def verify_user_controller(request: UserVerifyRequest):
    try:
        auth = await db._verify(**request.model_dump())
        if auth:
            return auth
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except HTTPException as e:
    # Propagate intended HTTP errors (e.g., 401) without wrapping
        raise e
    except Exception as e:
        logging.exception(f"Error verifying user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error verifying user: {e}")

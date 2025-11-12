from typing import Any, Dict, List

from pydantic import BaseModel


class Routes:
    # Scenarios
    INIT = "/"
    SAVE = "/scenarios/{federation_id}/save"
    STOP = "/scenarios/{federation_id}/stop"
    REMOVE = "/scenarios/{federation_id}/remove"
    FINISH = "/scenarios/{federation_id}/set_status_to_finished"
    RUNNING = "/scenarios/running"
    CHECK_SCENARIO = "/scenarios/check/{user}/{role}/{federation_id}"
    GET_SCENARIOS_BY_USER = "/scenarios/{user}/{role}"
    GET_SCENARIOS_BY_SCENARIO_NAME = "/scenarios/{federation_id}"

    # Nodes
    NODES_BY_FEDERATION_ID = "/nodes/{federation_id}"
    NODES_REMOVE = "/nodes/{federation_id}/remove"

    # Notes
    NOTES_BY_FEDERATION_ID = "/notes/{federation_id}"
    NOTES_UPDATE = "/notes/{federation_id}/update"
    NOTES_REMOVE = "/notes/{federation_id}/remove"


class SaveScenarioRequest(BaseModel):
    alias: str
    scenario_name: str
    start_time: str
    end_time: str
    scenario: Dict[str, Any]
    status: str
    username: str

class StopScenarioRequest(BaseModel):
    all: bool = False

class FinishScenarioRequest(BaseModel):
    all: bool = False

class UpdateNotesRequest(BaseModel):
    notes: str

class GetScenariosRequest(BaseModel):
    user: str
    role: str

class GetRunningScenarioRequest(BaseModel):
    get_all: bool = False

class CheckScenarioRequest(BaseModel):
    user: str
    role: str
    federation_id: str


def factory_requests_path(resource: str, user: str = "", role: str = "", federation_id: str = "") -> str:
    if resource == "init":
        return Routes.INIT
    elif resource == "save":
        return Routes.SAVE.format(federation_id=federation_id)
    elif resource == "stop":
        return Routes.STOP.format(federation_id=federation_id)
    elif resource == "remove":
        return Routes.REMOVE.format(federation_id=federation_id)
    elif resource == "finish":
        return Routes.FINISH.format(federation_id=federation_id)
    elif resource == "running":
        return Routes.RUNNING
    elif resource == "check_scenario":
        return Routes.CHECK_SCENARIO.format(user=user, role=role, federation_id=federation_id)
    elif resource == "get_scenarios_by_user":
        return Routes.GET_SCENARIOS_BY_USER.format(user=user, role=role)
    elif resource == "get_scenarios_by_scenario_name":
        return Routes.GET_SCENARIOS_BY_SCENARIO_NAME.format(federation_id=federation_id)
    # Nodes
    elif resource == "get_nodes_by_scenario_name":
        return Routes.NODES_BY_FEDERATION_ID.format(federation_id=federation_id)
    elif resource == "remove_nodes":
        return Routes.NODES_REMOVE.format(federation_id=federation_id)
    # Notes
    elif resource == "get_notes_by_scenario_name":
        return Routes.NOTES_BY_FEDERATION_ID.format(federation_id=federation_id)
    elif resource == "update_notes":
        return Routes.NOTES_UPDATE.format(federation_id=federation_id)
    elif resource == "remove_notes":
        return Routes.NOTES_REMOVE.format(federation_id=federation_id)
    else:
        raise Exception(f"resource not found: {resource}")

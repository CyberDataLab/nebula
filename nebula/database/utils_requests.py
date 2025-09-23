from typing import Any, Dict, List

from pydantic import BaseModel, confloat, conint


class Routes:
    # Scenarios
    INIT = "/"
    UPDATE = "/scenarios/update"
    STOP = "/scenarios/stop"
    REMOVE = "/scenarios/remove"
    FINISH = "/scenarios/set_status_to_finished"
    RUNNING = "/scenarios/running"
    CHECK_SCENARIO = "/scenarios/check/{user}/{role}/{scenario_name}"
    GET_SCENARIOS_BY_USER = "/scenarios/{user}/{role}"
    GET_SCENARIOS_BY_SCENARIO_NAME = "/scenarios/{scenario_name}"

    # Nodes
    NODES_BY_SCENARIO_NAME = "/nodes/{scenario_name}"
    NODES_UPDATE = "/nodes/update"
    NODES_REMOVE = "/nodes/remove"

    # Notes
    NOTES_BY_SCENARIO_NAME = "/notes/{scenario_name}"
    NOTES_UPDATE = "/notes/update"
    NOTES_REMOVE = "/notes/remove"

    # Users
    USER_LIST = "/user/list"
    USER_BY_SCENARIO_NAME = "/user/{scenario_name}"
    USER_ADD = "/user/add"
    USER_DELETE = "/user/delete"
    USER_UPDATE = "/user/update"
    USER_VERIFY = "/user/verify"


class ScenarioUpdateRequest(BaseModel):
    federation_id: str
    scenario_name: str
    start_time: str
    end_time: str
    scenario: Dict[str, Any]
    status: str
    username: str


class ScenarioStopRequest(BaseModel):
    scenario_name: str
    all: bool = False


class ScenarioRemoveRequest(BaseModel):
    scenario_name: str


class ScenarioFinishRequest(BaseModel):
    scenario_name: str
    all: bool = False


class NotesUpdateRequest(BaseModel):
    scenario_name: str
    notes: str


class NotesRemoveRequest(BaseModel):
    scenario_name: str


class NodesRemoveRequest(BaseModel):
    scenario_name: str


class UserAddRequest(BaseModel):
    user: str
    password: str
    role: str


class UserDeleteRequest(BaseModel):
    user: str


class UserUpdateRequest(BaseModel):
    user: str
    password: str
    role: str


class UserVerifyRequest(BaseModel):
    user: str
    password: str


# Nodes update payload
class DeviceArgs(BaseModel):
    uid: str
    idx: int
    role: str
    malicious: bool


class NetworkArgs(BaseModel):
    ip: str
    port: conint(ge=1, le=65535)  # type: ignore[valid-type]
    neighbors: List[Any]


class MobilityArgs(BaseModel):
    latitude: confloat(ge=-90, le=90)  # type: ignore[valid-type]
    longitude: confloat(ge=-180, le=180)  # type: ignore[valid-type]


class TrackingArgs(BaseModel):
    run_hash: str


class FederationArgs(BaseModel):
    round: int


class ScenarioArgs(BaseModel):
    federation: str
    name: str


class NodesUpdateRequest(BaseModel):
    device_args: DeviceArgs
    network_args: NetworkArgs
    mobility_args: MobilityArgs
    tracking_args: TrackingArgs
    federation_args: FederationArgs
    scenario_args: ScenarioArgs
    timestamp: str

class GetScenariosRequest(BaseModel):
    user: str
    role: str


class GetRunningScenarioRequest(BaseModel):
    get_all: bool = False


class CheckScenarioRequest(BaseModel):
    user: str
    role: str
    scenario_name: str


class GetScenarioByNameRequest(BaseModel):
    scenario_name: str


class ListNodesByScenarioNameRequest(BaseModel):
    scenario_name: str


class GetNotesByScenarioNameRequest(BaseModel):
    scenario_name: str


class ListUsersRequest(BaseModel):
    all_info: bool = False


class GetUserByScenarioNameRequest(BaseModel):
    scenario_name: str


def factory_requests_path(resource: str, user: str = "", role: str = "", scenario_name: str = "") -> str:
    if resource == "init":
        return Routes.INIT
    elif resource == "update":
        return Routes.UPDATE
    elif resource == "stop":
        return Routes.STOP
    elif resource == "remove":
        return Routes.REMOVE
    elif resource == "finish":
        return Routes.FINISH
    elif resource == "running":
        return Routes.RUNNING
    elif resource == "check_scenario":
        return Routes.CHECK_SCENARIO.format(user=user, role=role, scenario_name=scenario_name)
    elif resource == "get_scenarios_by_user":
        return Routes.GET_SCENARIOS_BY_USER.format(user=user, role=role)
    elif resource == "get_scenarios_by_scenario_name":
        return Routes.GET_SCENARIOS_BY_SCENARIO_NAME.format(scenario_name=scenario_name)
    # Nodes
    elif resource == "get_nodes_by_scenario_name":
        return Routes.NODES_BY_SCENARIO_NAME.format(scenario_name=scenario_name)
    elif resource == "update_nodes":
        return Routes.NODES_UPDATE
    elif resource == "remove_nodes":
        return Routes.NODES_REMOVE
    # Notes
    elif resource == "get_notes_by_scenario_name":
        return Routes.NOTES_BY_SCENARIO_NAME.format(scenario_name=scenario_name)
    elif resource == "update_notes":
        return Routes.NOTES_UPDATE
    elif resource == "remove_notes":
        return Routes.NOTES_REMOVE
    # Users
    elif resource == "list_users":
        return Routes.USER_LIST
    elif resource == "get_user_by_scenario_name":
        return Routes.USER_BY_SCENARIO_NAME.format(scenario_name=scenario_name)
    elif resource == "add_user":
        return Routes.USER_ADD
    elif resource == "delete_user":
        return Routes.USER_DELETE
    elif resource == "update_user":
        return Routes.USER_UPDATE
    elif resource == "verify_user":
        return Routes.USER_VERIFY
    else:
        raise Exception(f"resource not found: {resource}")

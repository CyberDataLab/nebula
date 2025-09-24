from typing import Any, Dict, List

from pydantic import BaseModel, conint, confloat


class Routes:
    # General
    INIT = "/"
    STATUS = "/status"
    RESOURCES = "/resources"
    LEAST_MEMORY_GPU = "/least_memory_gpu"
    AVAILABLE_GPUS = "/available_gpus/"

    # Scenarios (Controller + DB API routing)
    RUN = "/scenarios/run"
    UPDATE = "/scenarios/{federation_id}/update"
    STOP = "/scenarios/{federation_id}/stop"
    REMOVE = "/scenarios/{federation_id}/remove"
    FINISH = "/scenarios/{federation_id}/set_status_to_finished"
    RUNNING = "/scenarios/running"
    CHECK_SCENARIO = "/scenarios/check/{user}/{role}/{federation_id}"
    GET_SCENARIOS_BY_USER = "/scenarios/{user}/{role}"
    GET_SCENARIO_BY_FEDERATION_ID = "/scenarios/{federation_id}"

    # Nodes
    NODES_BY_FEDERATION_ID = "/nodes/{federation_id}"
    NODES_UPDATE = "/nodes/update"
    NODES_UPDATE_BY_FEDERATION = "/nodes/{federation_id}/update"
    NODES_DONE_BY_SCENARIO = "/nodes/{scenario_name}/done"
    NODES_REMOVE = "/nodes/{federation_id}/remove"

    # Notes
    NOTES_BY_FEDERATION_ID = "/notes/{federation_id}"
    NOTES_UPDATE = "/notes/{federation_id}/update"
    NOTES_REMOVE = "/notes/{federation_id}/remove"

    # Users
    USER_LIST = "/user/list"
    USER_BY_FEDERATION_ID = "/user/{federation_id}"
    USER_ADD = "/user/add"
    USER_DELETE = "/user/delete"
    USER_UPDATE = "/user/update"
    USER_VERIFY = "/user/verify"

    # Discovery / Physical management
    DISCOVER_VPN = "/discover-vpn"
    PHYSICAL_RUN = "/physical/run"
    PHYSICAL_STOP = "/physical/stop"
    PHYSICAL_SETUP = "/physical/setup"
    PHYSICAL_STATE = "/physical/state"
    PHYSICAL_SCENARIO_STATE = "/physical/{federation_id}/state"


class RunScenarioRequest(BaseModel):
    """Request model to trigger a scenario run on the controller.

    - Only requires scenario_data and user.
    - Extra fields (e.g., role, federation_id) are ignored.
    """
    scenario_data: Dict[str, Any]
    user: str


class ScenarioUpdateRequest(BaseModel):
    alias: str
    scenario_name: str
    start_time: str
    end_time: str
    scenario: Dict[str, Any]
    status: str
    username: str


class ScenarioStopRequest(BaseModel):
    all: bool = False


class ScenarioRemoveRequest(BaseModel):
    scenario_name: str


class ScenarioFinishRequest(BaseModel):
    all: bool = False


class NotesUpdateRequest(BaseModel):
    notes: str


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


def factory_requests_path(
    resource: str,
    user: str = "",
    role: str = "",
    federation_id: str = "",
) -> str:
    """Build paths for requests to the Database API from the Controller.

    This factory only maps DB API resources; controller endpoints do not require mapping here.
    """
    if resource == "init":
        return Routes.INIT
    elif resource == "update":
        return Routes.UPDATE.format(federation_id=federation_id)
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
        return Routes.GET_SCENARIO_BY_FEDERATION_ID.format(federation_id=federation_id)
    # Nodes
    elif resource == "get_nodes_by_scenario_name":
        return Routes.NODES_BY_FEDERATION_ID.format(federation_id=federation_id)
    elif resource == "update_nodes":
        return Routes.NODES_UPDATE
    elif resource == "remove_nodes":
        return Routes.NODES_REMOVE.format(federation_id=federation_id)
    # Notes
    elif resource == "get_notes_by_scenario_name":
        return Routes.NOTES_BY_FEDERATION_ID.format(federation_id=federation_id)
    elif resource == "update_notes":
        return Routes.NOTES_UPDATE.format(federation_id=federation_id)
    elif resource == "remove_notes":
        return Routes.NOTES_REMOVE.format(federation_id=federation_id)
    # Users
    elif resource == "list_users":
        return Routes.USER_LIST
    elif resource == "get_user_by_scenario_name":
        return Routes.USER_BY_FEDERATION_ID.format(federation_id=federation_id)
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

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, conint, confloat


class RunScenarioRequest(BaseModel):
    """Request model to trigger a scenario run on the controller.

    - Only requires scenario_data and user.
    - Extra fields (e.g., role, federation_id) are ignored.
    """
    #TODO List[Dict]
    scenario_data: Dict[str, Any]
    user: str
    role: str


class UpdateScenarioRequest(BaseModel):
    alias: str
    scenario_name: str
    start_time: str
    end_time: str
    scenario: Dict[str, Any]
    status: str
    username: str


class StopScenarioRequest(BaseModel):
    experiment_type: str
    all: bool = False


class RemoveScenarioRequest(BaseModel):
    user: str
    experiment_type: str
    scenario_name: str


class FinishScenarioRequest(BaseModel):
    all: bool = False


class UpdateNotesRequest(BaseModel):
    notes: str


class AddUserRequest(BaseModel):
    user: str
    password: str
    role: str


class DeleteUserRequest(BaseModel):
    user: str


class UpdateUserRequest(BaseModel):
    user: str
    password: str
    role: str


class VerifyUserRequest(BaseModel):
    user: str
    password: str


class NodeUpdateRequest(BaseModel):
    config: Dict[str, Any] = {}    
    
    
class NodeDoneRequest(BaseModel):
    idx: int

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
    RESOURCES_STOP = "/scenarios/{federation_id}/resources_stop"
    REMOVE = "/scenarios/{federation_id}/remove"
    FINISH = "/scenarios/{federation_id}/set_status_to_finished"
    RUNNING = "/scenarios/running"
    CHECK_SCENARIO = "/scenarios/check/{user}/{role}/{federation_id}"
    GET_SCENARIOS_BY_USER = "/scenarios/{user}/{role}"
    GET_SCENARIO_BY_FEDERATION_ID = "/scenarios/{federation_id}"

    # Nodes
    NODES_LIST = "/nodes/{federation_id}"
    NODES_UPDATE = "/nodes/{federation_id}/update"
    NODES_DONE = "/nodes/{federation_id}/done"
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

    @classmethod
    def format(cls, route: str, **kwargs) -> str:
        return getattr(cls, route).format(**kwargs)


def factory_requests_path(resource: str, **kwargs) -> str:
    try:
        return Routes.format(resource.upper(), **kwargs)
    except AttributeError:
        raise ValueError(f"Resource not found: {resource}")
    except KeyError as e:
        raise ValueError(f"Missing parameter for route '{resource}': {e}")

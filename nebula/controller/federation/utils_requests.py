from pydantic import BaseModel
from typing import Dict, Any

class RunScenarioRequest(BaseModel):
    scenario_data: Dict[str, Any]
    user: str
    federation_id: str
    
class StopScenarioRequest(BaseModel):
    experiment_type: str
    federation_id: str
    
class NodeUpdateRequest(BaseModel):
    config: Dict[str, Any] = {}    
    
class NodeDoneRequest(BaseModel):
    idx: int
    deployment: str
    name: str
    federation_id: str
    
class Routes:
    INIT = "/init"
    RUN = "/scenarios/run"
    STOP = "/scenarios/stop"
    UPDATE = "/nodes/{federation_id}/update"
    DONE = "/nodes/{federation_id}/done"
    FINISH = "/scenarios/{federation_id}/finish"
    
def factory_requests_path(resource: str, scenario_name: str = "", federation_id: str = "") -> str:
    if resource == "init":
        return "/init"
    elif resource == "run":
        return Routes.RUN
    elif resource == "stop":
        return Routes.STOP
    elif resource == "update":
        return Routes.UPDATE.format(federation_id=federation_id)
    elif resource == "done":
        return Routes.DONE.format(federation_id=federation_id)
    elif resource == "finish":
        return Routes.FINISH.format(federation_id=federation_id)
    else:
        raise Exception(f"resource not found: {resource}")
    
    
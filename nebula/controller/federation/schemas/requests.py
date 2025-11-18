from fastapi import HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

class RunScenarioRequest(BaseModel):
    scenario_data: Dict[str, Any]
    user: str
    federation_id: str

class StopScenarioRequest(BaseModel):
    experiment_type: str

class RemoveScenarioRequest(BaseModel):
    experiment_type: str
    user: str
    scenario_name: str

class Routes:
    INIT = "/init"
    RUN = "/scenarios/run"
    STOP = "/scenarios/{federation_id}/stop"
    FINISH = "/scenarios/{federation_id}/finish"
    REMOVE = "/scenario/{federation_id}/remove"

    @classmethod
    def format(cls, route: str, **kwargs) -> str:
        return getattr(cls, route).format(**kwargs)

def factory_requests(resource: str, **kwargs) -> str:
    try:
        return Routes.format(resource.upper(), **kwargs)
    except AttributeError:
        raise ValueError(f"Resource not found: {resource}")
    except KeyError as e:
        raise ValueError(f"Missing parameter for route '{resource}': {e}")

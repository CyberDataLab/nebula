from pydantic import BaseModel
from typing import Optional

class RunScenarioResponse(BaseModel):
    federation_id: str
    start_time: str
    alias: str 
    scenario_name: str
    
class StopScenarioResponse(BaseModel):
    federation_id: str

class RemoveScenarioResponse(BaseModel):
    federation_id: str
    additional_info: str

class NodeUpdateResponse(BaseModel):
    federation_id: str
    
class NodeDoneResponse(BaseModel):
    federation_id: str
    idx: str

class ErrorResponse(BaseModel):
    error: str
    message: str
    internal_code: Optional[int] = None


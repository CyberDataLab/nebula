from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel

class UpdateScenarioResponse(BaseModel):
    success: bool

class StopScenarioResponse(BaseModel):
    success: bool
    
class RemoveScenarioResponse(BaseModel):
    success: bool

class FinishScenarioResponse(BaseModel):
    success: bool

class UpdateNodesResponse(BaseModel):
    updated: bool

class GetScenariosResponse(BaseModel):
    scenarios: Dict[str, Any]

class GetRunningScenarioResponse(BaseModel):
    scenarios: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]

class CheckScenarioResponse(BaseModel):
    allowed: bool
    
class GetScenarioByID(BaseModel):
    scenario: Optional[Dict[str, Any]]
    
class ListNodesByIDResponse(BaseModel):
    nodes: List[Dict[str, Any]]
    
class RemoveNodesByID(BaseModel):
    success: bool
    
class GetNotesByID(BaseModel):
    notes: Optional[Dict[str, Any]]
    
class SaveNotesByID(BaseModel):
    success: bool
    
class RemoveNotesByID(BaseModel):
    success: bool

class ErrorResponse(BaseModel):
    error: str
    message: str
    internal_code: Optional[int] = None
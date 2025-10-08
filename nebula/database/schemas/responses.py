from typing import Optional
from pydantic import BaseModel

class UpdateScenarioResponse(BaseModel):
    pass
    # alias: str
    # scenario_name: str
    # start_time: str
    # end_time: str
    # scenario: Dict[str, Any]
    # status: str
    # username: str

class StopScenarioResponse(BaseModel):
    pass
    # all: bool = False

class FinishScenarioResponse(BaseModel):
    pass
    # all: bool = False

class UpdateNotesResponse(BaseModel):
    pass
    # notes: str

class AddUserResponse(BaseModel):
    pass
    # user: str
    # password: str
    # role: str

class DeleteUserResponse(BaseModel):
    pass
    # user: str

class UpdateUserResponse(BaseModel):
    pass
    # user: str
    # password: str
    # role: str

class VerifyUserResponse(BaseModel):
    pass
    # user: str
    # password: str

class UpdateNodesResponse(BaseModel):
    pass
    # device_args: DeviceArgs
    # network_args: NetworkArgs
    # mobility_args: MobilityArgs
    # federation_args: FederationArgs
    # scenario_args: ScenarioArgs
    # timestamp: str

class GetScenariosResponse(BaseModel):
    pass
    # user: str
    # role: str

class GetRunningScenarioResponse(BaseModel):
    pass
    # get_all: bool = False

class CheckScenarioResponse(BaseModel):
    pass
    # user: str
    # role: str
    # federation_id: str

class ListUsersResponse(BaseModel):
    pass
    # all_info: bool = False
    
class ErrorResponse(BaseModel):
    error: str
    message: str
    internal_code: Optional[int] = None
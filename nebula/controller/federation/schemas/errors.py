from enum import IntEnum
from dataclasses import dataclass


class ErrorCode(IntEnum):
    # Federation
    FEDERATION_ALREADY_EXISTS = 1001
    FEDERATION_NOT_FOUND = 1002
    FEDERATION_INIT_FAILED = 1003

    # Scenarios
    SCENARIO_BUILD_FAILED = 1101
    SCENARIO_INIT_FAILED = 1102
    SCENARIO_STOP_FAILED = 1111
    SCENARIO_REMOVE_ACTIVE_FEDERATION = 1121
    SCENARIO_REMOVE_FILES_NOT_FOUND = 1122
    SCENARIO_REMOVE_LOGFILE_NOT_FOUND = 1123
    SCENARIO_REMOVE_CONFIG_NOT_FOUND = 1123
    SCENARIO_REMOVE_FAILED = 1125

    # Nodes
    NODE_UPDATE_FAILED = 1201
    NODE_DONE_FAILED = 1202
    
    # Controllers
    BAD_CONTROLLER = 1301

    # General
    UNKNOWN_ERROR = 1999

@dataclass(frozen=True)
class ErrorDefinition:
    code: ErrorCode
    http_status: int
    error: str
    message: str


# --- Controllers ---
BAD_CONTROLLER = ErrorDefinition(
    code=ErrorCode.BAD_CONTROLLER,
    http_status=400,
    error="UnknownExperimentType",
    message="Experiment type not supported in the system."
)

# --- Federation ---
FEDERATION_ALREADY_EXISTS = ErrorDefinition(
    code=ErrorCode.FEDERATION_ALREADY_EXISTS,
    http_status=409,
    error="FederationAlreadyExists",
    message="Federation ID already exists in the system."
)

FEDERATION_NOT_FOUND = ErrorDefinition(
    code=ErrorCode.FEDERATION_NOT_FOUND,
    http_status=404,
    error="FederationIDNotFound",
    message="Federation ID not found in the current pool."
)

FEDERATION_INIT_FAILED = ErrorDefinition(
    code=ErrorCode.FEDERATION_INIT_FAILED,
    http_status=500,
    error="FederationInitFailed",
    message="Unable to initialize federation properly."
)

# --- Scenarios ---
SCENARIO_BUILD_FAILED = ErrorDefinition(
    code=ErrorCode.SCENARIO_BUILD_FAILED,
    http_status=500,
    error="ScenarioBuildFailed",
    message="Scenario configuration could not be generated correctly."
)

SCENARIO_INIT_FAILED = ErrorDefinition(
    code=ErrorCode.SCENARIO_INIT_FAILED,
    http_status=500,
    error="ScenarioInitFailed",
    message="Scenario initialization failed unexpectedly."
)

SCENARIO_STOP_FAILED = ErrorDefinition(
    code=ErrorCode.SCENARIO_STOP_FAILED,
    http_status=500,
    error="ScenarioStopFailed",
    message="Scenario stop failed unexpectedly."
)

SCENARIO_REMOVE_FILES_NOT_FOUND = ErrorDefinition(
    code=ErrorCode.SCENARIO_REMOVE_FILES_NOT_FOUND,
    http_status=404,
    error="FederationFilesNotFound",
    message="Can not find files from federation."
)

SCENARIO_REMOVE_ACTIVE_FEDERATION = ErrorDefinition(
    code=ErrorCode.SCENARIO_REMOVE_ACTIVE_FEDERATION,
    http_status=409,
    error="RemoveActiveFederation",
    message="Trying to remove files from an active federation."
)

SCENARIO_REMOVE_FAILED = ErrorDefinition(
    code=ErrorCode.SCENARIO_REMOVE_FAILED,
    http_status=500,
    error="ScenarioRemovedFailed",
    message="Scenario removed failed unexpectedly."
)

# --- Nodes ---
NODE_UPDATE_FAILED = ErrorDefinition(
    code=ErrorCode.NODE_UPDATE_FAILED,
    http_status=500,
    error="NodeUpdateFailed",
    message="Node update request failed to process correctly."
)

NODE_DONE_FAILED = ErrorDefinition(
    code=ErrorCode.NODE_DONE_FAILED,
    http_status=400,
    error="NodeDoneFailed",
    message="Node done event could not be processed."
)

# --- Default ---
UNKNOWN_ERROR = ErrorDefinition(
    code=ErrorCode.UNKNOWN_ERROR,
    http_status=500,
    error="UnknownError",
    message="An unknown error occurred during processing."
)


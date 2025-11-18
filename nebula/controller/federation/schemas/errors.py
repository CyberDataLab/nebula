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
    SCENARIO_REMOVE_FAILED = 1125

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


# ============================================================
# ERROR CONTROLLER
# ============================================================
BAD_CONTROLLER = ErrorDefinition(
    code=ErrorCode.BAD_CONTROLLER,
    http_status=400,
    error="UnknownExperimentType",
    message="Experiment type not supported in the system."
)

# ============================================================
# ERROR FEDERATION
# ============================================================
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

# ============================================================
# ERROR SCENARIOS
# ============================================================
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

# --- DEFAULT ---
UNKNOWN_ERROR = ErrorDefinition(
    code=ErrorCode.UNKNOWN_ERROR,
    http_status=500,
    error="UnknownError",
    message="An unknown error occurred during processing."
)

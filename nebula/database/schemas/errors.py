from enum import IntEnum
from dataclasses import dataclass

# ============================================================
# ERROR CODES ENUM (10000+ reserved for DB layer)
# ============================================================

class DatabaseErrorCode(IntEnum):
    # Pool / Connection
    POOL_NOT_INITIALIZED = 10001
    CONNECTION_FAILED = 10002
    CONNECTION_TIMEOUT = 10003
    CONNECTION_CLOSED = 10004

    # Querys
    TABLE_NOT_FOUND = 10101
    COLUMN_NOT_FOUND = 10102
    QUERY_FAILED = 10103
    PERMISSION_DENIED = 10104
    DATA_FORMAT_ERROR = 10105

    # General
    UNKNOWN_DB_ERROR = 10999

# ============================================================
# ERROR STRUCTURE DEFINITION
# ============================================================

@dataclass(frozen=True)
class DatabaseErrorDefinition:
    code: DatabaseErrorCode
    http_status: int
    error: str
    message: str

# ============================================================
# DEFINITIONS
# ============================================================

# --- Pool / Connection ---
POOL_NOT_INITIALIZED = DatabaseErrorDefinition(
    code=DatabaseErrorCode.POOL_NOT_INITIALIZED,
    http_status=500,
    error="DatabasePoolNotInitialized",
    message="Database pool not initialized before query execution."
)

CONNECTION_FAILED = DatabaseErrorDefinition(
    code=DatabaseErrorCode.CONNECTION_FAILED,
    http_status=503,
    error="DatabaseConnectionFailed",
    message="Unable to establish a database connection."
)

CONNECTION_TIMEOUT = DatabaseErrorDefinition(
    code=DatabaseErrorCode.CONNECTION_TIMEOUT,
    http_status=504,
    error="DatabaseConnectionTimeout",
    message="Timed out while acquiring a database connection from the pool."
)

CONNECTION_CLOSED = DatabaseErrorDefinition(
    code=DatabaseErrorCode.CONNECTION_CLOSED,
    http_status=500,
    error="DatabaseConnectionClosed",
    message="The database connection was unexpectedly closed."
)


# --- Querys ---
TABLE_NOT_FOUND = DatabaseErrorDefinition(
    code=DatabaseErrorCode.TABLE_NOT_FOUND,
    http_status=500,
    error="DatabaseTableNotFound",
    message="The specified database table does not exist."
)

COLUMN_NOT_FOUND = DatabaseErrorDefinition(
    code=DatabaseErrorCode.COLUMN_NOT_FOUND,
    http_status=500,
    error="DatabaseColumnNotFound",
    message="A required column was not found in the query result."
)

QUERY_FAILED = DatabaseErrorDefinition(
    code=DatabaseErrorCode.QUERY_FAILED,
    http_status=500,
    error="DatabaseQueryFailed",
    message="An error occurred while executing the SQL query."
)

PERMISSION_DENIED = DatabaseErrorDefinition(
    code=DatabaseErrorCode.PERMISSION_DENIED,
    http_status=403,
    error="DatabasePermissionDenied",
    message="Insufficient privileges to perform the requested query."
)

DATA_FORMAT_ERROR = DatabaseErrorDefinition(
    code=DatabaseErrorCode.DATA_FORMAT_ERROR,
    http_status=422,
    error="DatabaseDataFormatError",
    message="Unexpected data format or conversion error during query execution."
)

# --- DEFAULT ---
UNKNOWN_DB_ERROR = DatabaseErrorDefinition(
    code=DatabaseErrorCode.UNKNOWN_DB_ERROR,
    http_status=500,
    error="UnknownDatabaseError",
    message="An unknown database error occurred."
)

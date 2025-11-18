from fastapi import HTTPException
from nebula.database.schemas.responses import ErrorResponse
from nebula.database.schemas.errors import DatabaseErrorDefinition

def raise_error(error_def: DatabaseErrorDefinition):
    """raise HTTP exception with standar format."""
    raise HTTPException(
        status_code=error_def.http_status,
        detail=ErrorResponse(
            error=error_def.error,
            message=error_def.message,
            internal_code=error_def.code,
        ).model_dump()
    )

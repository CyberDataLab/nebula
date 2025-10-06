from fastapi import HTTPException
from nebula.controller.federation.schemas.requests import factory_requests
from nebula.controller.federation.schemas.responses import ErrorResponse
from nebula.controller.federation.schemas.errors import ErrorDefinition
from nebula.utils import APIUtils

def raise_error(error_def: ErrorDefinition):
    """Lanza una excepción HTTP con el formato estándar."""
    raise HTTPException(
        status_code=error_def.http_status,
        detail=ErrorResponse(
            error=error_def.error,
            message=error_def.message,
            internal_code=error_def.code,
        ).model_dump()
    )
    
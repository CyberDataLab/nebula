"""Authentication helpers for the NEBULA controller."""

from .models import AuthenticatedUser
from .keycloak import (
    authenticate_token,
    get_current_user,
    obtain_token,
    require_roles,
    require_scope,
)
from .policy import (
    actor_username,
    actor_role,
    can_impersonate,
    resolve_username,
)

__all__ = [
    "AuthenticatedUser",
    "authenticate_token",
    "get_current_user",
    "obtain_token",
    "require_roles",
    "require_scope",
    "actor_username",
    "actor_role",
    "can_impersonate",
    "resolve_username",
]

"""Facade module exposing the public authentication helpers."""

from .models import AuthenticatedUser
from .keycloak.api import (
    authenticate_token,
    get_current_user,
    list_users,
    obtain_token,
    register_user,
    delete_user,
    logout,
    require_roles,
    require_scope,
    update_user,
)
from .policy import (
    actor_role,
    actor_username,
    can_impersonate,
    resolve_username,
)

__all__ = [
    "AuthenticatedUser",
    "authenticate_token",
    "get_current_user",
    "obtain_token",
    "logout",
    "list_users",
    "register_user",
    "delete_user",
    "update_user",
    "require_roles",
    "require_scope",
    "actor_username",
    "actor_role",
    "can_impersonate",
    "resolve_username",
]

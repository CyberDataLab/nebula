"""Authorization and identity helpers shared across the controller."""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from nebula.auth.models import AuthenticatedUser


def actor_username(actor: AuthenticatedUser) -> str:
    """Return a normalized username for the actor."""
    candidate = actor.username or actor.email or actor.subject
    return candidate.upper() if candidate else ""


def actor_role(actor: AuthenticatedUser) -> str:
    """Map Keycloak roles to application roles used by the DB layer."""
    role_mapping = {
        "admin": "admin",
        "user": "viewer",
    }
    for key, value in role_mapping.items():
        if actor.has_role(key):
            return value
    return "viewer"


def can_impersonate(actor: AuthenticatedUser) -> bool:
    """Return True if the actor can impersonate other users."""
    normalized_roles = {role.lower() for role in actor.roles}
    elevated_roles = {"admin"}
    return bool(normalized_roles & elevated_roles)


def resolve_username(actor: AuthenticatedUser, requested_user: Optional[str]) -> str:
    """Resolve the effective username considering impersonation policy."""
    username = actor_username(actor)
    requested_upper = (requested_user or "").upper()

    if requested_upper and requested_upper != username:
        if not can_impersonate(actor):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Token and user path mismatch")
        return requested_upper

    if not username and requested_upper:
        return requested_upper

    if not username:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Token missing user identity")

    return username

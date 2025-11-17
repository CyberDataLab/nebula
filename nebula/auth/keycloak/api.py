"""Composable Keycloak helpers organized into small, testable modules."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nebula.auth.models import AuthenticatedUser
from .factories import KeycloakComponentFactory
from .user_manager import KeycloakUserManager

_factory = KeycloakComponentFactory()
_authenticator = _factory.authenticator()
_token_client = _factory.token_client()
_bearer_dependency = HTTPBearer(auto_error=False)


def _get_user_manager() -> KeycloakUserManager:
    return _factory.user_manager()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_dependency),
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")
    return await _authenticator.authenticate(credentials.credentials)


async def obtain_token(
    *,
    grant_type: str = "password",
    username: Optional[str] = None,
    password: Optional[str] = None,
    refresh_token: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    scope: Optional[str] = None,
    auth_url: Optional[str] = None,
    realm: Optional[str] = None,
) -> Dict[str, Any]:
    return await _token_client.obtain_token(
        grant_type=grant_type,
        username=username,
        password=password,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
        auth_url=auth_url,
        realm=realm,
    )


async def register_user(
    actor: AuthenticatedUser,
    username: str,
    password: str,
    role: str,
) -> Dict[str, Any]:
    try:
        manager = _get_user_manager()
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Keycloak user registration is not configured on the controller.",
        ) from exc
    return await manager.register_user(
        username=username,
        password=password,
        role=role,
        actor_token=actor.token,
    )


async def delete_user(
    actor: AuthenticatedUser,
    username: str,
) -> Dict[str, Any]:
    try:
        manager = _get_user_manager()
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Keycloak user deletion is not configured on the controller.",
        ) from exc
    return await manager.delete_user(
        username=username,
        actor_token=actor.token,
    )


async def update_user(
    actor: AuthenticatedUser,
    username: str,
    password: Optional[str],
    role: Optional[str],
) -> Dict[str, Any]:
    try:
        manager = _get_user_manager()
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Keycloak user update is not configured on the controller.",
        ) from exc
    return await manager.update_user(
        username=username,
        password=password,
        role=role,
        actor_token=actor.token,
    )


async def list_users(
    actor: AuthenticatedUser,
    *,
    all_info: bool = False,
    search: Optional[str] = None,
    first: Optional[int] = None,
    max_results: Optional[int] = None,
) -> list[Dict[str, Any]]:
    try:
        manager = _get_user_manager()
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Keycloak user listing is not configured on the controller.",
        ) from exc
    return await manager.list_users(
        actor_token=actor.token,
        all_info=all_info,
        search=search,
        first=first,
        max_results=max_results,
    )


def require_scope(required_scope: str):
    async def dependency(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not user.has_scope(required_scope):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"Missing scope: {required_scope}")
        return user

    return dependency


def require_roles(*roles: str):
    expected = set(roles)

    async def dependency(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not expected.intersection(user.roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency


async def authenticate_token(token: str) -> AuthenticatedUser:
    """Utility wrapper for modules that cannot use FastAPI dependencies (e.g. WebSockets)."""
    return await _authenticator.authenticate(token)

from __future__ import annotations

import abc
import os
from typing import Any, Dict, Optional

from nebula.auth.api import (
    AuthenticatedUser,
    authenticate_token as keycloak_authenticate_token,
    obtain_token as keycloak_obtain_token,
    list_users as keycloak_list_users,
    register_user as keycloak_register_user,
    delete_user as keycloak_delete_user,
    update_user as keycloak_update_user,
    logout as keycloak_logout,
)


class AuthClient(abc.ABC):
    """Defines the contract for the hub authentication client."""

    @abc.abstractmethod
    async def authenticate(self, token: str) -> AuthenticatedUser:
        """Validate the provided token and return the authenticated identity."""

    @abc.abstractmethod
    async def obtain_token(
        self,
        *,
        grant_type: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        refresh_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        auth_url: Optional[str] = None,
        realm: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Obtain a token from the upstream identity provider."""

    @abc.abstractmethod
    async def register_user(
        self,
        actor: AuthenticatedUser,
        username: str,
        password: str,
        role: str,
    ) -> Dict[str, Any]:
        """Provision a new user in the upstream identity provider."""

    @abc.abstractmethod
    async def update_user(
        self,
        actor: AuthenticatedUser,
        username: str,
        password: Optional[str],
        role: Optional[str],
    ) -> Dict[str, Any]:
        """Update an existing user in the upstream identity provider."""

    @abc.abstractmethod
    async def list_users(
        self,
        actor: AuthenticatedUser,
        *,
        all_info: bool = False,
        search: Optional[str] = None,
        first: Optional[int] = None,
        max_results: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        """Return users visible to the provided actor."""

    @abc.abstractmethod
    async def delete_user(self, actor: AuthenticatedUser, username: str) -> Dict[str, Any]:
        """Delete a user from the upstream identity provider."""

    @abc.abstractmethod
    async def logout(
        self,
        *,
        refresh_token: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        auth_url: Optional[str] = None,
        realm: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Revoke a refresh token in the upstream identity provider."""


class KeycloakAuthClient(AuthClient):
    """Auth client implementation backed by the Keycloak helper module."""

    async def authenticate(self, token: str) -> AuthenticatedUser:
        return await keycloak_authenticate_token(token)

    async def obtain_token(
        self,
        *,
        grant_type: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        refresh_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        auth_url: Optional[str] = None,
        realm: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await keycloak_obtain_token(
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
        self,
        actor: AuthenticatedUser,
        username: str,
        password: str,
        role: str,
    ) -> Dict[str, Any]:
        return await keycloak_register_user(actor=actor, username=username, password=password, role=role)

    async def update_user(
        self,
        actor: AuthenticatedUser,
        username: str,
        password: Optional[str],
        role: Optional[str],
    ) -> Dict[str, Any]:
        return await keycloak_update_user(actor=actor, username=username, password=password, role=role)

    async def delete_user(self, actor: AuthenticatedUser, username: str) -> Dict[str, Any]:
        return await keycloak_delete_user(actor=actor, username=username)

    async def logout(
        self,
        *,
        refresh_token: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        auth_url: Optional[str] = None,
        realm: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await keycloak_logout(
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            auth_url=auth_url,
            realm=realm,
        )
    async def list_users(
        self,
        actor: AuthenticatedUser,
        *,
        all_info: bool = False,
        search: Optional[str] = None,
        first: Optional[int] = None,
        max_results: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        return await keycloak_list_users(
            actor,
            all_info=all_info,
            search=search,
            first=first,
            max_results=max_results,
        )


def build_auth_client() -> AuthClient:
    """Factory used by the hub to decide which auth backend to use."""
    provider = (os.environ.get("NEBULA_HUB_AUTH_PROVIDER") or "keycloak").strip().lower()
    if provider == "keycloak":
        return KeycloakAuthClient()
    raise RuntimeError(f"Unsupported authentication provider '{provider}'")

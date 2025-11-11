from __future__ import annotations

import abc
import os
from typing import Any, Dict, Optional

from nebula.auth import (
    AuthenticatedUser,
    authenticate_token as keycloak_authenticate_token,
    obtain_token as keycloak_obtain_token,
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


def build_auth_client() -> AuthClient:
    """Factory used by the hub to decide which auth backend to use."""
    provider = (os.environ.get("NEBULA_HUB_AUTH_PROVIDER") or "keycloak").strip().lower()
    if provider == "keycloak":
        return KeycloakAuthClient()
    raise RuntimeError(f"Unsupported authentication provider '{provider}'")

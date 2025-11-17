from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from keycloak import KeycloakOpenID
from keycloak.exceptions import (
    KeycloakAuthenticationError,
    KeycloakConnectionError,
    KeycloakError,
)

from .utils import describe_keycloak_exception

logger = logging.getLogger(__name__)


class KeycloakTokenClient:
    """Handles token exchanges against Keycloak's OpenID Connect endpoints."""

    def __init__(
        self,
        base_url: str,
        realm: str,
        default_client_id: Optional[str] = None,
        default_client_secret: Optional[str] = None,
        default_scope: Optional[str] = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        if not base_url or not realm:
            raise ValueError("Keycloak token client requires both base_url and realm")

        self._base_url = base_url.rstrip("/")
        self._realm = realm
        self._default_client_id = default_client_id
        self._default_client_secret = default_client_secret
        self._default_scope = default_scope
        self._timeout = request_timeout_seconds

    def _build_openid_client(
        self,
        override_base_url: Optional[str],
        override_realm: Optional[str],
        client_id: str,
        client_secret: Optional[str],
    ) -> KeycloakOpenID:
        base_url = (override_base_url or self._base_url or "").rstrip("/")
        realm = (override_realm or self._realm or "").strip()
        if not base_url or not realm:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Keycloak login is not configured on the controller.",
            )

        server_url = f"{base_url}/" if not base_url.endswith("/") else base_url
        client = KeycloakOpenID(
            server_url=server_url,
            realm_name=realm,
            client_id=client_id,
            client_secret_key=client_secret,
        )
        client.connection.timeout = self._timeout
        return client

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
        resolved_client_id = client_id or self._default_client_id
        if not resolved_client_id:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Keycloak client_id is not configured for login.",
            )

        keycloak = self._build_openid_client(auth_url, realm, resolved_client_id, client_secret or self._default_client_secret)
        try:
            if grant_type == "password":
                if not username or not password:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        detail="username and password are required for password grant.",
                    )
                requested_scope = scope or self._default_scope
                result = await asyncio.to_thread(
                    keycloak.token,
                    username,
                    password,
                    "password",
                    requested_scope or "openid",
                )
            elif grant_type == "refresh_token":
                if not refresh_token:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        detail="refresh_token is required for refresh_token grant.",
                    )
                result = await asyncio.to_thread(keycloak.refresh_token, refresh_token, "refresh_token")
            else:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported grant type '{grant_type}'.",
                )
        except HTTPException:
            raise
        except KeycloakAuthenticationError as exc:
            detail = describe_keycloak_exception(exc) or "Keycloak rejected the credentials."
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakConnectionError as exc:
            logger.exception("Connection error while contacting Keycloak token endpoint: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to reach Keycloak token endpoint.",
            ) from exc
        except KeycloakError as exc:
            detail = describe_keycloak_exception(exc)
            logger.exception("Unexpected Keycloak error during token exchange: %s", detail)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Keycloak token request failed.") from exc

        if grant_type == "refresh_token" and refresh_token and "refresh_token" not in result:
            result["refresh_token"] = refresh_token

        return result

    async def logout(
        self,
        *,
        refresh_token: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        auth_url: Optional[str] = None,
        realm: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not refresh_token:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="refresh_token is required for logout.")

        resolved_client_id = client_id or self._default_client_id
        if not resolved_client_id:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Keycloak client_id is not configured for logout.",
            )

        keycloak = self._build_openid_client(auth_url, realm, resolved_client_id, client_secret or self._default_client_secret)
        try:
            await asyncio.to_thread(keycloak.logout, refresh_token)
        except KeycloakAuthenticationError as exc:
            detail = describe_keycloak_exception(exc) or "Keycloak rejected the logout request."
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakConnectionError as exc:
            logger.exception("Connection error while contacting Keycloak logout endpoint: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to reach Keycloak logout endpoint.",
            ) from exc
        except KeycloakError as exc:
            detail = describe_keycloak_exception(exc)
            logger.exception("Unexpected Keycloak error during logout: %s", detail)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Keycloak logout failed.") from exc

        return {"revoked": True}

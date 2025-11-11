"""Keycloak-backed authentication utilities for the FastAPI hub."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Set

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwcrypto import jwk
from keycloak import KeycloakOpenID
from keycloak.exceptions import (
    KeycloakAuthenticationError,
    KeycloakConnectionError,
    KeycloakError,
    KeycloakInvalidTokenError,
)

from nebula.auth.models import AuthenticatedUser

logger = logging.getLogger(__name__)


def _ensure_pem_format(public_key: str) -> str:
    key = (public_key or "").strip()
    if key.startswith("-----BEGIN "):
        return key
    return f"-----BEGIN PUBLIC KEY-----\n{key}\n-----END PUBLIC KEY-----"


def _extract_error_detail(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="ignore")
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return payload
    else:
        data = payload

    if isinstance(data, dict):
        for key in ("error_description", "error", "message", "detail"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return json.dumps(data)
    return str(payload)


def _describe_keycloak_exception(exc: KeycloakError) -> str:
    detail = _extract_error_detail(getattr(exc, "response_body", None))
    if detail:
        return detail
    message = getattr(exc, "error_message", None)
    if isinstance(message, str) and message:
        return message
    return str(exc)


class KeycloakAuthenticator:
    """Validates JWT access tokens issued by Keycloak using python-keycloak."""

    def __init__(
        self,
        server_url: str,
        realm: str,
        audience: Optional[str] = None,
        required_scope: Optional[str] = None,
        jwks_cache_seconds: int = 300,
        client_id: Optional[str] = None,
    ) -> None:
        if not server_url or not realm:
            raise ValueError("Both server_url and realm must be provided for Keycloak authentication")

        self._server_url = server_url.rstrip("/")
        self._realm = realm
        self._audience = audience
        self._required_scope = required_scope
        self._public_key_ttl = jwks_cache_seconds
        self._client_id = client_id or audience or os.environ.get("NEBULA_KEYCLOAK_CLIENT_ID") or "account"

        self._openid_client = KeycloakOpenID(
            server_url=self._server_url,
            realm_name=self._realm,
            client_id=self._client_id,
        )

        self._public_key: Optional[str] = None
        self._public_jwk: Optional[jwk.JWK] = None
        self._public_key_fetched_at: float = 0.0
        self._public_key_lock = asyncio.Lock()

    @property
    def issuer(self) -> str:
        return f"{self._server_url}/realms/{self._realm}"

    async def _get_public_key(self) -> jwk.JWK:
        async with self._public_key_lock:
            if (
                self._public_jwk
                and (time.time() - self._public_key_fetched_at) < self._public_key_ttl
            ):
                return self._public_jwk
            try:
                raw_key = await asyncio.to_thread(self._openid_client.public_key)
            except KeycloakConnectionError as exc:
                logger.exception("Unable to contact Keycloak to fetch the public key: %s", exc)
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch Keycloak signing key.",
                ) from exc
            except KeycloakError as exc:
                logger.exception("Unexpected error while retrieving Keycloak public key: %s", exc)
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    detail="Keycloak public key request failed.",
                ) from exc

            formatted_key = _ensure_pem_format(raw_key)
            try:
                self._public_jwk = jwk.JWK.from_pem(formatted_key.encode("utf-8"))
            except Exception as exc:  # jwcrypto raises custom exceptions that do not share a base class
                logger.exception("Unable to parse Keycloak public key: %s", exc)
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    detail="Invalid Keycloak public key returned by the identity provider.",
                ) from exc
            self._public_key = formatted_key
            self._public_key_fetched_at = time.time()
            return self._public_jwk

    async def authenticate(self, token: str) -> AuthenticatedUser:
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

        key = await self._get_public_key()
        try:
            claims = await asyncio.to_thread(
                self._openid_client.decode_token,
                token,
                key=key,
            )
        except KeycloakInvalidTokenError as exc:
            detail = _describe_keycloak_exception(exc) or "Token signature validation failed."
            logger.warning("Keycloak rejected token as invalid: %s", detail)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakAuthenticationError as exc:
            detail = _describe_keycloak_exception(exc) or "Token validation failed."
            logger.warning("Keycloak authentication error during token validation: %s", detail)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakConnectionError as exc:
            logger.exception("Connection error while validating Keycloak token: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to validate token with Keycloak.",
            ) from exc
        except KeycloakError as exc:
            detail = _describe_keycloak_exception(exc)
            logger.exception("Unexpected Keycloak error during token validation: %s", detail)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Keycloak token validation failed.") from exc

        audience = self._extract_audience(claims)
        if self._audience and self._audience not in audience:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token audience.")
        scope = self._extract_scope(claims)
        roles = self._extract_roles(claims)

        if self._required_scope and self._required_scope not in scope:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Missing required scope")

        return AuthenticatedUser(
            subject=claims.get("sub"),
            issuer=claims.get("iss", self.issuer),
            token=token,
            username=claims.get("preferred_username") or claims.get("email"),
            email=claims.get("email"),
            audience=audience,
            scope=scope,
            roles=roles,
            claims=claims,
        )

    @staticmethod
    def _extract_audience(claims: Dict[str, Any]) -> Set[str]:
        aud_claim = claims.get("aud")
        if isinstance(aud_claim, str):
            return {aud_claim}
        if isinstance(aud_claim, list):
            return {str(value) for value in aud_claim}
        return set()

    @staticmethod
    def _extract_scope(claims: Dict[str, Any]) -> Set[str]:
        scope_claim = claims.get("scope")
        if isinstance(scope_claim, str):
            return {item for item in scope_claim.split() if item}
        return set()

    def _extract_roles(self, claims: Dict[str, Any]) -> Set[str]:
        roles: Set[str] = set()
        realm_access = claims.get("realm_access") or {}
        if isinstance(realm_access, dict):
            roles.update(realm_access.get("roles", []) or [])

        resource_access = claims.get("resource_access") or {}
        if isinstance(resource_access, dict):
            for value in resource_access.values():
                if isinstance(value, dict):
                    roles.update(value.get("roles", []) or [])

        custom_roles = claims.get("roles")
        if isinstance(custom_roles, list):
            roles.update(str(role) for role in custom_roles if role)
        elif isinstance(custom_roles, str):
            roles.update(role for role in custom_roles.split() if role)

        return roles


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
            detail = _describe_keycloak_exception(exc) or "Keycloak rejected the credentials."
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakConnectionError as exc:
            logger.exception("Connection error while contacting Keycloak token endpoint: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to reach Keycloak token endpoint.",
            ) from exc
        except KeycloakError as exc:
            detail = _describe_keycloak_exception(exc)
            logger.exception("Unexpected Keycloak error during token exchange: %s", detail)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Keycloak token request failed.") from exc

        if grant_type == "refresh_token" and refresh_token and "refresh_token" not in result:
            result["refresh_token"] = refresh_token

        return result


def _build_authenticator() -> KeycloakAuthenticator:
    server_url = os.environ.get("NEBULA_KEYCLOAK_SERVER")
    realm = os.environ.get("NEBULA_KEYCLOAK_REALM")
    audience = os.environ.get("NEBULA_KEYCLOAK_AUDIENCE")
    scope = os.environ.get("NEBULA_KEYCLOAK_SCOPE")
    cache_seconds = int(os.environ.get("NEBULA_KEYCLOAK_JWKS_CACHE_SECONDS", "300"))
    client_id = os.environ.get("NEBULA_KEYCLOAK_CLIENT_ID") or audience

    return KeycloakAuthenticator(
        server_url=server_url,
        realm=realm,
        audience=audience,
        required_scope=scope,
        jwks_cache_seconds=cache_seconds,
        client_id=client_id,
    )


def _build_token_client() -> KeycloakTokenClient:
    token_url = (
        os.environ.get("NEBULA_KEYCLOAK_TOKEN_URL")
        or os.environ.get("NEBULA_KEYCLOAK_SERVER")
        or os.environ.get("NEBULA_KEYCLOAK_PUBLIC_URL")
    )
    if not token_url:
        raise ValueError(
            "Keycloak token client requires NEBULA_KEYCLOAK_TOKEN_URL, "
            "NEBULA_KEYCLOAK_SERVER or NEBULA_KEYCLOAK_PUBLIC_URL to be set."
        )

    realm = os.environ.get("NEBULA_KEYCLOAK_REALM")
    if not realm:
        raise ValueError("Keycloak token client requires NEBULA_KEYCLOAK_REALM to be set.")

    return KeycloakTokenClient(
        base_url=token_url,
        realm=realm,
        default_client_id=os.environ.get("NEBULA_KEYCLOAK_CLIENT_ID"),
        default_client_secret=os.environ.get("NEBULA_KEYCLOAK_CLIENT_SECRET"),
        default_scope=os.environ.get("NEBULA_KEYCLOAK_SCOPE") or os.environ.get("NEBULA_KEYCLOAK_AUDIENCE_SCOPE"),
    )


try:
    _authenticator = _build_authenticator()
except ValueError as exc:
    raise RuntimeError(
        "Keycloak authentication is not configured. Ensure NEBULA_KEYCLOAK_SERVER and "
        "NEBULA_KEYCLOAK_REALM environment variables are set."
    ) from exc

try:
    _token_client = _build_token_client()
except ValueError as exc:
    raise RuntimeError(
        "Keycloak login integration is not configured. Ensure NEBULA_KEYCLOAK_REALM and either "
        "NEBULA_KEYCLOAK_TOKEN_URL, NEBULA_KEYCLOAK_SERVER or NEBULA_KEYCLOAK_PUBLIC_URL are set."
    ) from exc

_bearer_dependency = HTTPBearer(auto_error=False)


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

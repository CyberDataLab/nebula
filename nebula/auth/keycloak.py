"""Keycloak-backed authentication utilities for the FastAPI hub."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

import aiohttp
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identity information extracted from a validated access token."""

    subject: str
    issuer: str
    token: str
    username: Optional[str]
    email: Optional[str]
    audience: Set[str]
    scope: Set[str]
    roles: Set[str]
    claims: Dict[str, Any]

    def has_scope(self, scope: str) -> bool:
        return scope in self.scope

    def has_role(self, role: str) -> bool:
        return role in self.roles


class KeycloakAuthenticator:
    """Validates JWT access tokens issued by Keycloak."""

    def __init__(
        self,
        server_url: str,
        realm: str,
        audience: Optional[str] = None,
        required_scope: Optional[str] = None,
        jwks_cache_seconds: int = 300,
    ) -> None:
        if not server_url or not realm:
            raise ValueError("Both server_url and realm must be provided for Keycloak authentication")

        self._server_url = server_url.rstrip("/")
        self._realm = realm
        self._audience = audience
        self._required_scope = required_scope
        self._jwks_cache_seconds = jwks_cache_seconds

        self._jwks: Optional[Dict[str, Any]] = None
        self._jwks_fetched_at: float = 0.0
        self._jwks_lock = asyncio.Lock()

    @property
    def issuer(self) -> str:
        return f"{self._server_url}/realms/{self._realm}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/certs"

    async def _fetch_jwks(self, force: bool = False) -> Dict[str, Any]:
        async with self._jwks_lock:
            if (
                not force
                and self._jwks is not None
                and (time.time() - self._jwks_fetched_at) < self._jwks_cache_seconds
            ):
                return self._jwks

            async with aiohttp.ClientSession() as session:
                async with session.get(self.jwks_url, timeout=10) as response:
                    if response.status != 200:
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Unable to fetch Keycloak signing keys",
                        )
                    data = await response.json()

            self._jwks = data
            self._jwks_fetched_at = time.time()
            return data

    async def authenticate(self, token: str) -> AuthenticatedUser:
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

        jwks = await self._fetch_jwks()
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        key = self._select_key(jwks, kid)
        if key is None:
            jwks = await self._fetch_jwks(force=True)
            key = self._select_key(jwks, kid)
            if key is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Unknown token signing key")

        options = {"verify_aud": self._audience is not None, "verify_at_hash": False}
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[key.get("alg", "RS256")],
                audience=self._audience,
                issuer=self.issuer,
                options=options,
            )
        except ExpiredSignatureError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
        except JWTClaimsError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token claims: {exc} self._audience {self.issuer}") from exc
        except JWTError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token signature validation failed") from exc

        audience = self._extract_audience(claims)
        scope = self._extract_scope(claims)
        roles = self._extract_roles(claims)

        if self._required_scope and self._required_scope not in scope:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Missing required scope")

        return AuthenticatedUser(
            subject=claims.get("sub"),
            issuer=claims.get("iss"),
            token=token,
            username=claims.get("preferred_username") or claims.get("email"),
            email=claims.get("email"),
            audience=audience,
            scope=scope,
            roles=roles,
            claims=claims,
        )

    def _select_key(self, jwks: Dict[str, Any], kid: Optional[str]) -> Optional[Dict[str, Any]]:
        keys = jwks.get("keys", [])
        if kid:
            for entry in keys:
                if entry.get("kid") == kid:
                    return entry
        # Fall back to first key for backward compatibility
        return keys[0] if keys else None

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
        roles.update(realm_access.get("roles", []))

        resource_access = claims.get("resource_access") or {}
        if isinstance(resource_access, dict):
            for value in resource_access.values():
                if isinstance(value, dict):
                    roles.update(value.get("roles", []) or [])

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
    ) -> None:
        if not base_url or not realm:
            raise ValueError("Keycloak token client requires both base_url and realm")

        self._base_url = base_url.rstrip("/")
        self._realm = realm
        self._default_client_id = default_client_id
        self._default_client_secret = default_client_secret
        self._default_scope = default_scope

    def _build_endpoint(self, override_base_url: Optional[str], override_realm: Optional[str]) -> str:
        base_url = (override_base_url or self._base_url or "").rstrip("/")
        realm = (override_realm or self._realm or "").strip()
        if not base_url or not realm:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Keycloak login is not configured on the controller.",
            )
        return f"{base_url}/realms/{realm}/protocol/openid-connect/token"

    @staticmethod
    def _extract_error_detail(payload: str) -> str:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return payload

        for key in ("error_description", "error", "message", "detail"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return payload

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
        endpoint = self._build_endpoint(auth_url, realm)
        resolved_client_id = client_id or self._default_client_id
        if not resolved_client_id:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Keycloak client_id is not configured for login.",
            )

        payload: Dict[str, Any] = {"grant_type": grant_type, "client_id": resolved_client_id}
        resolved_secret = client_secret or self._default_client_secret
        if resolved_secret:
            payload["client_secret"] = resolved_secret

        if grant_type == "password":
            if not username or not password:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="username and password are required for password grant.",
                )
            payload["username"] = username
            payload["password"] = password
            resolved_scope = scope or self._default_scope
            if resolved_scope:
                payload["scope"] = resolved_scope
        elif grant_type == "refresh_token":
            if not refresh_token:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="refresh_token is required for refresh_token grant.",
                )
            payload["refresh_token"] = refresh_token
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported grant type '{grant_type}'.",
            )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, data=payload, timeout=30) as response:
                    text = await response.text()
                    if response.status >= 400:
                        detail = self._extract_error_detail(text) or "Keycloak rejected the credentials."
                        if response.status in (400, 401):
                            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)
                        if response.status == 403:
                            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)
                        logger.error(
                            "Keycloak token request failed with unexpected status %s: %s",
                            response.status,
                            detail,
                        )
                        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Keycloak token request failed.")
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError as exc:
                        logger.error("Invalid JSON payload received from Keycloak token endpoint: %s", text)
                        raise HTTPException(
                            status.HTTP_502_BAD_GATEWAY,
                            detail="Invalid response from Keycloak token endpoint.",
                        ) from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timed out while contacting Keycloak for a token.",
            ) from exc
        except aiohttp.ClientError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to reach Keycloak token endpoint.",
            ) from exc

        if grant_type == "refresh_token" and refresh_token and "refresh_token" not in data:
            data["refresh_token"] = refresh_token

        return data


def _build_authenticator() -> KeycloakAuthenticator:
    server_url = os.environ.get("NEBULA_KEYCLOAK_SERVER")
    realm = os.environ.get("NEBULA_KEYCLOAK_REALM")
    audience = os.environ.get("NEBULA_KEYCLOAK_AUDIENCE")
    scope = os.environ.get("NEBULA_KEYCLOAK_SCOPE")
    cache_seconds = int(os.environ.get("NEBULA_KEYCLOAK_JWKS_CACHE_SECONDS", "300"))

    return KeycloakAuthenticator(
        server_url=server_url,
        realm=realm,
        audience=audience,
        required_scope=scope,
        jwks_cache_seconds=cache_seconds,
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

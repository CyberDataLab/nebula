from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException, status
from jwcrypto import jwk
from keycloak import KeycloakOpenID
from keycloak.exceptions import (
    KeycloakAuthenticationError,
    KeycloakConnectionError,
    KeycloakError,
    KeycloakInvalidTokenError,
)

from nebula.auth.models import AuthenticatedUser
from .utils import describe_keycloak_exception, ensure_pem_format


logger = logging.getLogger(__name__)


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

            formatted_key = ensure_pem_format(raw_key)
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
            detail = describe_keycloak_exception(exc) or "Token signature validation failed."
            logger.warning("Keycloak rejected token as invalid: %s", detail)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakAuthenticationError as exc:
            detail = describe_keycloak_exception(exc) or "Token validation failed."
            logger.warning("Keycloak authentication error during token validation: %s", detail)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakConnectionError as exc:
            logger.exception("Connection error while validating Keycloak token: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to validate token with Keycloak.",
            ) from exc
        except KeycloakError as exc:
            detail = describe_keycloak_exception(exc)
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

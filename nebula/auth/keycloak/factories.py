from __future__ import annotations

import os
from typing import Optional

from .authenticator import KeycloakAuthenticator
from .token_client import KeycloakTokenClient
from .user_manager import KeycloakUserManager


class KeycloakComponentFactory:
    """Centralized builder that lazily instantiates Keycloak helpers (Singleton style)."""

    def __init__(self) -> None:
        self._authenticator: Optional[KeycloakAuthenticator] = None
        self._token_client: Optional[KeycloakTokenClient] = None
        self._user_manager: Optional[KeycloakUserManager] = None

    def authenticator(self) -> KeycloakAuthenticator:
        if self._authenticator is None:
            self._authenticator = self._build_authenticator()
        return self._authenticator

    def token_client(self) -> KeycloakTokenClient:
        if self._token_client is None:
            self._token_client = self._build_token_client()
        return self._token_client

    def user_manager(self) -> KeycloakUserManager:
        if self._user_manager is None:
            self._user_manager = self._build_user_manager()
        return self._user_manager

    def _build_authenticator(self) -> KeycloakAuthenticator:
        server_url = os.environ.get("NEBULA_KEYCLOAK_SERVER")
        realm = os.environ.get("NEBULA_KEYCLOAK_REALM")
        audience = os.environ.get("NEBULA_KEYCLOAK_AUDIENCE")
        scope = os.environ.get("NEBULA_KEYCLOAK_SCOPE")
        cache_seconds = int(os.environ.get("NEBULA_KEYCLOAK_JWKS_CACHE_SECONDS", "300"))
        client_id = os.environ.get("NEBULA_KEYCLOAK_CLIENT_ID") or audience

        if not server_url or not realm:
            raise RuntimeError(
                "Keycloak authentication is not configured. Ensure NEBULA_KEYCLOAK_SERVER and "
                "NEBULA_KEYCLOAK_REALM environment variables are set."
            )

        return KeycloakAuthenticator(
            server_url=server_url,
            realm=realm,
            audience=audience,
            required_scope=scope,
            jwks_cache_seconds=cache_seconds,
            client_id=client_id,
        )

    def _build_token_client(self) -> KeycloakTokenClient:
        token_url = (
            os.environ.get("NEBULA_KEYCLOAK_TOKEN_URL")
            or os.environ.get("NEBULA_KEYCLOAK_SERVER")
            or os.environ.get("NEBULA_KEYCLOAK_PUBLIC_URL")
        )
        if not token_url:
            raise RuntimeError(
                "Keycloak login integration is not configured. Ensure NEBULA_KEYCLOAK_REALM and either "
                "NEBULA_KEYCLOAK_TOKEN_URL, NEBULA_KEYCLOAK_SERVER or NEBULA_KEYCLOAK_PUBLIC_URL are set."
            )

        realm = os.environ.get("NEBULA_KEYCLOAK_REALM")
        if not realm:
            raise RuntimeError("Keycloak token client requires NEBULA_KEYCLOAK_REALM to be set.")

        return KeycloakTokenClient(
            base_url=token_url,
            realm=realm,
            default_client_id=os.environ.get("NEBULA_KEYCLOAK_CLIENT_ID"),
            default_client_secret=os.environ.get("NEBULA_KEYCLOAK_CLIENT_SECRET"),
            default_scope=os.environ.get("NEBULA_KEYCLOAK_SCOPE") or os.environ.get("NEBULA_KEYCLOAK_AUDIENCE_SCOPE"),
        )

    def _build_user_manager(self) -> KeycloakUserManager:
        base_url = (
            os.environ.get("NEBULA_KEYCLOAK_ADMIN_URL")
            or os.environ.get("NEBULA_KEYCLOAK_SERVER")
            or os.environ.get("NEBULA_KEYCLOAK_PUBLIC_URL")
        )
        if not base_url:
            raise RuntimeError(
                "Keycloak user registration requires NEBULA_KEYCLOAK_ADMIN_URL, "
                "NEBULA_KEYCLOAK_SERVER or NEBULA_KEYCLOAK_PUBLIC_URL to be set."
            )

        realm = os.environ.get("NEBULA_KEYCLOAK_REALM")
        if not realm:
            raise RuntimeError("Keycloak user registration requires NEBULA_KEYCLOAK_REALM to be set.")

        admin_username = os.environ.get("NEBULA_KEYCLOAK_ADMIN_USER")
        admin_password = os.environ.get("NEBULA_KEYCLOAK_ADMIN_PASSWORD")
        admin_realm = os.environ.get("NEBULA_KEYCLOAK_ADMIN_REALM") or "master"
        timeout = float(os.environ.get("NEBULA_KEYCLOAK_ADMIN_TIMEOUT_SECONDS", "30"))
        client_role_client_id = os.environ.get("NEBULA_KEYCLOAK_CLI_CLIENT_ID") or os.environ.get(
            "NEBULA_KEYCLOAK_CLIENT_ID"
        )

        verify_env = (os.environ.get("NEBULA_KEYCLOAK_VERIFY_TLS") or "true").strip().lower()
        verify_tls = verify_env not in {"false", "0", "no"}

        return KeycloakUserManager(
            server_url=base_url,
            realm=realm,
            admin_username=admin_username,
            admin_password=admin_password,
            admin_realm=admin_realm,
            verify_tls=verify_tls,
            request_timeout_seconds=timeout,
            client_role_client_id=client_role_client_id,
        )

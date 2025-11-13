from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Set

from fastapi import HTTPException, status
from keycloak import KeycloakAdmin
from keycloak.exceptions import (
    KeycloakAuthenticationError,
    KeycloakConnectionError,
    KeycloakError,
    KeycloakGetError,
)

from .utils import describe_keycloak_exception

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoleDefinition:
    client_role: Optional[str] = None


class KeycloakUserManager:
    """Provides administrative helpers for managing users in Keycloak."""

    _ROLE_DEFINITIONS: Dict[str, RoleDefinition] = {
        "admin": RoleDefinition(client_role="admin"),
        "user": RoleDefinition(client_role="user"),
    }
    _MANAGED_CLIENT_ROLES: Set[str] = {
        definition.client_role for definition in _ROLE_DEFINITIONS.values() if definition.client_role
    }
    _FALLBACK_ACTOR_TOKEN_TTL_SECONDS = 300
    _MIN_ACTOR_TOKEN_TTL_SECONDS = 5
    _DEFAULT_LIST_LIMIT = 500

    def __init__(
        self,
        *,
        server_url: str,
        realm: str,
        admin_username: Optional[str] = None,
        admin_password: Optional[str] = None,
        admin_realm: Optional[str] = None,
        verify_tls: bool = True,
        request_timeout_seconds: float = 30.0,
        client_role_client_id: Optional[str] = None,
    ) -> None:
        if not server_url or not realm:
            raise ValueError("Keycloak user manager requires server_url and realm to be configured.")

        self._server_url = server_url.rstrip("/")
        self._realm = realm
        self._admin_username = admin_username
        self._admin_password = admin_password
        self._admin_realm = (admin_realm or "master").strip()
        self._verify_tls = verify_tls
        self._timeout = request_timeout_seconds
        self._client_role_client_id = client_role_client_id
        self._client_role_internal_id: Optional[str] = None

    def _new_admin_client(self, token: Optional[str]) -> KeycloakAdmin:
        client_kwargs: Dict[str, Any] = {
            "server_url": self._server_url,
            "realm_name": self._realm,
            "verify": self._verify_tls,
        }
        if self._admin_username and self._admin_password:
            client_kwargs.update(
                {
                    "user_realm_name": self._admin_realm,
                    "username": self._admin_username,
                    "password": self._admin_password,
                }
            )
        elif token:
            client_kwargs["token"] = self._build_actor_token_payload(token)
        else:
            raise RuntimeError("Keycloak admin credentials are not configured.")

        admin = KeycloakAdmin(**client_kwargs)
        admin.connection.timeout = self._timeout
        return admin

    def _register_user_sync(
        self,
        username: str,
        password: str,
        role_definition: RoleDefinition,
        actor_token: Optional[str],
    ) -> Dict[str, Any]:
        admin = self._new_admin_client(actor_token)
        user_payload = {
            "username": username,
            "enabled": True,
            "firstName": username,
            "lastName": username,
            "email" : f"{username}@gmail.com",
            "emailVerified": True
        }
        user_id = admin.create_user(user_payload)
        if not isinstance(user_id, str) or not user_id:
            user_id = admin.get_user_id(username)
        if not user_id:
            raise RuntimeError("Keycloak did not return an identifier for the newly created user.")

        admin.set_user_password(user_id=user_id, password=password, temporary=False)
        if role_definition.client_role:
            try:
                self._set_managed_client_role(admin, user_id, role_definition.client_role)
            except KeycloakGetError as exc:
                if exc.response_code == status.HTTP_404_NOT_FOUND:
                    logger.warning(
                        "Client role '%s' not found in Keycloak; skipping assignment.",
                        role_definition.client_role,
                    )
                else:
                    raise
        return {
            "id": user_id,
            "username": username,
            "role": role_definition.client_role,
        }

    def _assign_client_role(self, admin: KeycloakAdmin, user_id: str, role_name: str) -> None:
        client_internal_id = self._resolve_client_role_internal_id(admin)
        role_representation = admin.get_client_role(client_internal_id, role_name)
        admin.assign_client_role(user_id=user_id, client_id=client_internal_id, roles=[role_representation])

    def _remove_client_role(self, admin: KeycloakAdmin, user_id: str, role_name: str) -> None:
        client_internal_id = self._resolve_client_role_internal_id(admin)
        try:
            role_representation = admin.get_client_role(client_internal_id, role_name)
        except KeycloakGetError as exc:
            if exc.response_code == status.HTTP_404_NOT_FOUND:
                return
            raise
        admin.delete_client_roles_of_user(
            user_id=user_id,
            client_id=client_internal_id,
            roles=[role_representation],
        )

    async def register_user(
        self,
        *,
        username: str,
        password: str,
        role: str,
        actor_token: Optional[str],
    ) -> Dict[str, Any]:
        normalized_username = (username or "").strip()
        if not normalized_username:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Username must be provided.")
        if not password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Password must be provided.")

        role_key = (role or "").strip().lower()
        role_definition = self._ROLE_DEFINITIONS.get(role_key)
        if not role_definition:
            available = ", ".join(sorted(self._ROLE_DEFINITIONS))
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported role '{role}'. Available roles: {available}",
            )

        try:
            result = await asyncio.to_thread(
                self._register_user_sync,
                normalized_username,
                password,
                role_definition,
                actor_token,
            )
            result["role"] = role_key
            return result
        except KeycloakGetError as exc:
            if exc.response_code == status.HTTP_409_CONFLICT:
                raise HTTPException(status.HTTP_409_CONFLICT, detail="User already exists.") from exc
            if exc.response_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Requested role not found in Keycloak.") from exc
            logger.exception("Keycloak returned error during user registration: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail=describe_keycloak_exception(exc) or "Keycloak user registration failed.",
            ) from exc
        except KeycloakAuthenticationError as exc:
            detail = describe_keycloak_exception(exc) or "Failed to authenticate against Keycloak admin API."
            logger.exception("Keycloak admin authentication error: %s", detail)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakConnectionError as exc:
            logger.exception("Unable to reach Keycloak admin API: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to reach Keycloak admin API.",
            ) from exc
        except RuntimeError as exc:
            logger.error("Keycloak user manager misconfiguration: %s", exc)
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Keycloak user registration is not configured on the controller.",
            ) from exc
        except KeycloakError as exc:
            detail = describe_keycloak_exception(exc) or "Keycloak user registration failed."
            logger.exception("Unexpected Keycloak error during user registration: %s", detail)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Unexpected error during Keycloak user registration: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected error during Keycloak user registration.",
            ) from exc

    async def update_user(
        self,
        *,
        username: str,
        password: Optional[str],
        role: Optional[str],
        actor_token: Optional[str],
    ) -> Dict[str, Any]:
        normalized_username = (username or "").strip()
        if not normalized_username:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Username must be provided.")

        normalized_role = (role or "").strip().lower()
        role_definition: Optional[RoleDefinition] = None
        if normalized_role:
            role_definition = self._ROLE_DEFINITIONS.get(normalized_role)
            if not role_definition:
                available = ", ".join(sorted(self._ROLE_DEFINITIONS))
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported role '{role}'. Available roles: {available}",
                )

        try:
            return await asyncio.to_thread(
                self._update_user_sync,
                normalized_username,
                password,
                normalized_role or None,
                role_definition,
                actor_token,
            )
        except KeycloakGetError as exc:
            if exc.response_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.") from exc
            logger.exception("Keycloak returned error during user update: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail=describe_keycloak_exception(exc) or "Keycloak user update failed.",
            ) from exc
        except KeycloakAuthenticationError as exc:
            detail = describe_keycloak_exception(exc) or "Failed to authenticate against Keycloak admin API."
            logger.exception("Keycloak admin authentication error: %s", detail)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakConnectionError as exc:
            logger.exception("Unable to reach Keycloak admin API: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to reach Keycloak admin API.",
            ) from exc
        except RuntimeError as exc:
            logger.error("Keycloak user manager misconfiguration: %s", exc)
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Keycloak user update is not configured on the controller.",
            ) from exc
        except HTTPException:
            raise
        except KeycloakError as exc:
            detail = describe_keycloak_exception(exc) or "Keycloak user update failed."
            logger.exception("Unexpected Keycloak error during user update: %s", detail)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected error during Keycloak user update: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected error during Keycloak user update.",
            ) from exc

    async def list_users(
        self,
        *,
        actor_token: Optional[str],
        all_info: bool = False,
        search: Optional[str] = None,
        first: Optional[int] = None,
        max_results: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(
                self._list_users_sync,
                actor_token,
                all_info,
                search,
                first,
                max_results,
            )
        except KeycloakAuthenticationError as exc:
            detail = describe_keycloak_exception(exc) or "Failed to authenticate against Keycloak admin API."
            logger.exception("Keycloak admin authentication error: %s", detail)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
        except KeycloakConnectionError as exc:
            logger.exception("Unable to reach Keycloak admin API: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to reach Keycloak admin API.",
            ) from exc
        except KeycloakError as exc:
            detail = describe_keycloak_exception(exc) or "Keycloak user listing failed."
            logger.exception("Unexpected Keycloak error during user listing: %s", detail)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
        except RuntimeError as exc:
            logger.error("Keycloak user manager misconfiguration: %s", exc)
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Keycloak user listing is not configured on the controller.",
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected error during Keycloak user listing: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected error during Keycloak user listing.",
            ) from exc

    def _build_actor_token_payload(self, access_token: str) -> Dict[str, Any]:
        return {
            "access_token": access_token,
            "expires_in": self._predict_token_ttl(access_token),
        }

    def _predict_token_ttl(self, access_token: str) -> int:
        lifetime = self._remaining_token_lifetime(access_token)
        if lifetime is None:
            return self._FALLBACK_ACTOR_TOKEN_TTL_SECONDS
        return max(lifetime, self._MIN_ACTOR_TOKEN_TTL_SECONDS)

    def _remaining_token_lifetime(self, access_token: str) -> Optional[int]:
        try:
            payload = self._decode_jwt_payload(access_token)
        except ValueError:
            return None

        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            remaining = int(exp - time.time())
            if remaining > 0:
                return remaining
        return None

    def _list_users_sync(
        self,
        actor_token: Optional[str],
        all_info: bool,
        search: Optional[str],
        first: Optional[int],
        max_results: Optional[int],
    ) -> list[Dict[str, Any]]:
        admin = self._new_admin_client(actor_token)
        params: Dict[str, Any] = {
            "briefRepresentation": False,
            "first": first if first is not None else 0,
            "max": max_results if max_results is not None else self._DEFAULT_LIST_LIMIT,
        }
        if search:
            params["search"] = search

        raw_users = admin.get_users(params) or []
        serialized: list[Dict[str, Any]] = []
        for user in raw_users:
            if isinstance(user, dict):
                serialized.append(self._serialize_user(admin, user, all_info))
        return serialized

    def _update_user_sync(
        self,
        username: str,
        password: Optional[str],
        normalized_role: Optional[str],
        role_definition: Optional[RoleDefinition],
        actor_token: Optional[str],
    ) -> Dict[str, Any]:
        admin = self._new_admin_client(actor_token)
        user_id = admin.get_user_id(username)
        if not user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.")

        if password:
            admin.set_user_password(user_id=user_id, password=password, temporary=False)

        assigned_role = normalized_role
        if role_definition and role_definition.client_role:
            self._set_managed_client_role(admin, user_id, role_definition.client_role)
            assigned_role = normalized_role
        elif not assigned_role:
            assigned_role = self._resolve_primary_role(admin, user_id)

        return {
            "id": user_id,
            "username": username,
            "role": assigned_role,
        }

    def _set_managed_client_role(self, admin: KeycloakAdmin, user_id: str, client_role: str) -> None:
        if not self._MANAGED_CLIENT_ROLES:
            raise RuntimeError("No managed client roles configured for user manager.")
        if not self._client_role_client_id:
            raise RuntimeError("Keycloak client for CLI role assignment is not configured.")
        for existing in self._MANAGED_CLIENT_ROLES:
            if existing == client_role:
                continue
            self._remove_client_role(admin, user_id, existing)
        self._assign_client_role(admin, user_id, client_role)

    def _serialize_user(self, admin: KeycloakAdmin, user: Dict[str, Any], all_info: bool) -> Dict[str, Any]:
        username = user.get("username")
        user_id = user.get("id")
        payload: Dict[str, Any] = {
            "user": username,
            "role": self._resolve_primary_role(admin, user_id),
        }
        if all_info:
            payload.update(
                {
                    "id": user_id,
                    "email": user.get("email"),
                    "first_name": user.get("firstName"),
                    "last_name": user.get("lastName"),
                    "enabled": user.get("enabled"),
                    "attributes": user.get("attributes") or {},
                }
            )
        return payload

    def _resolve_primary_role(self, admin: KeycloakAdmin, user_id: Optional[str]) -> str:
        if not user_id:
            return "user"
        if not self._client_role_client_id:
            return "user"
        try:
            client_internal_id = self._resolve_client_role_internal_id(admin)
            client_roles = self._extract_role_names(admin.get_client_roles_of_user(user_id, client_internal_id))
        except KeycloakError:
            client_roles = set()

        return self._map_roles(client_roles)

    @staticmethod
    def _extract_role_names(entries: Optional[Sequence[Dict[str, Any]]]) -> Set[str]:
        names: Set[str] = set()
        if not entries:
            return names
        for entry in entries:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str) and name:
                    names.add(name.lower())
        return names

    @staticmethod
    def _map_roles(client_roles: Set[str]) -> str:
        normalized = {role.lower() for role in client_roles}
        if "admin" in normalized:
            return "admin"
        if "user" in normalized:
            return "user"
        return "user"

    def _resolve_client_role_internal_id(self, admin: KeycloakAdmin) -> str:
        if self._client_role_internal_id:
            return self._client_role_internal_id
        if not self._client_role_client_id:
            raise RuntimeError("Keycloak client for CLI role assignment is not configured.")
        client_internal_id = admin.get_client_id(self._client_role_client_id)
        if not client_internal_id:
            raise RuntimeError(f"Client '{self._client_role_client_id}' not found in Keycloak.")
        self._client_role_internal_id = client_internal_id
        return client_internal_id

    @staticmethod
    def _decode_jwt_payload(token: str) -> Dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Access token is not a JWT.")

        payload_segment = parts[1]
        padding = "=" * (-len(payload_segment) % 4)
        try:
            decoded = base64.urlsafe_b64decode(f"{payload_segment}{padding}")
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("Unable to decode JWT payload") from exc

        try:
            return json.loads(decoded.decode("utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("Unable to parse JWT payload") from exc

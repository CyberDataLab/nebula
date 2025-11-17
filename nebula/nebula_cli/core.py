"""Core utilities for the NEBULA CLI.

Contains configuration, shared helpers, token cache management, HTTP client,
and a small singleton context to reuse the client across commands.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from requests import Response

from nebula.controller.hub.utils_requests import Routes

# ---------------------------------------------------------------------------
# Configuration and context
# ---------------------------------------------------------------------------

DEFAULT_TOKEN_CACHE = Path.home() / ".cache" / "nebula-cli" / "token.json"
TOKEN_CACHE = Path(os.environ.get("NEBULA_CLI_TOKEN_PATH") or DEFAULT_TOKEN_CACHE)
LOGIN_ENDPOINT = Routes.LOGIN


@dataclass
class CLIConfig:
    """Centralized configuration for the CLI runtime."""

    hub_url: str
    client_id: str
    client_secret: Optional[str]
    scope: Optional[str]
    timeout: int = 30
    verify_tls: bool = True


def set_token_cache_path(path: Optional[str]) -> None:
    global TOKEN_CACHE
    if path:
        TOKEN_CACHE = Path(path).expanduser()


class CLIContext:
    """Singleton to keep shared CLI state (config + client)."""

    _instance: Optional["CLIContext"] = None

    def __init__(self) -> None:
        self.config: Optional[CLIConfig] = None
        self._client: Optional[NebulaClient] = None

    @classmethod
    def instance(cls) -> "CLIContext":
        if cls._instance is None:
            cls._instance = CLIContext()
        return cls._instance

    def configure(self, config: CLIConfig) -> None:
        self.config = config
        self._client = NebulaClient(config)

    def client(self) -> "NebulaClient":
        if self._client is None:
            raise RuntimeError("CLI client not configured. Build the parser and parse args first.")
        return self._client


# ---------------------------------------------------------------------------
# Token cache helpers
# ---------------------------------------------------------------------------

def _ensure_cache_dir() -> None:
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)


def load_token() -> Optional[Dict[str, Any]]:
    try:
        with TOKEN_CACHE.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def save_token(payload: Dict[str, Any]) -> None:
    _ensure_cache_dir()
    expires_in = max(int(payload.get("expires_in", 0)) - 5, 0)
    payload["expires_at"] = time.time() + expires_in
    with TOKEN_CACHE.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)


def clear_token() -> bool:
    try:
        TOKEN_CACHE.unlink()
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Output and payload helpers
# ---------------------------------------------------------------------------

def extract_error_detail(response: Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text.strip() or "unknown error"

    for key in ("detail", "error_description", "error", "message"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value

    return response.text.strip() or "unknown error"


def coerce_body(response: Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text.strip() or None


def print_output(data: Any, output_format: str) -> None:
    if data is None:
        print("OK")
        return

    if isinstance(data, (dict, list)):
        if output_format == "pretty":
            print(json.dumps(data, indent=2, sort_keys=True))
        elif output_format == "json":
            print(json.dumps(data, separators=(",", ":")))
        else:
            print(json.dumps(data))
        return

    print(str(data))


def bool_param(value: bool) -> str:
    return "true" if value else "false"


def load_json_payload(*, file_path: Optional[str], inline_json: Optional[str], use_stdin: bool) -> Any:
    if use_stdin:
        raw = sys.stdin.read()
        if not raw.strip():
            raise RuntimeError("No JSON payload received from stdin")
        return json.loads(raw)

    if file_path:
        with Path(file_path).expanduser().open("r", encoding="utf-8") as fp:
            return json.load(fp)

    if inline_json:
        return json.loads(inline_json)

    raise RuntimeError("Provide --file, --json, or --stdin with a JSON payload")


def load_text_payload(*, file_path: Optional[str], inline_text: Optional[str], use_stdin: bool) -> str:
    if use_stdin:
        data = sys.stdin.read()
        if not data:
            raise RuntimeError("No text payload received from stdin")
        return data

    if inline_text is not None:
        return inline_text

    if file_path:
        with Path(file_path).expanduser().open("r", encoding="utf-8") as fp:
            return fp.read()

    raise RuntimeError("Provide --file, --text, or --stdin with the note contents")


def preview_token(value: Optional[str], length: int = 12) -> str:
    if not isinstance(value, str):
        return "<missing>"
    if len(value) <= length:
        return value
    return f"{value[:length]}..."


# ---------------------------------------------------------------------------
# HTTP client and token exchange
# ---------------------------------------------------------------------------


class NebulaClient:
    """Thin HTTP client wrapper that reuses a session and cached tokens."""

    def __init__(self, config: CLIConfig):
        self.config = config
        self.session = requests.Session()
        self.session.verify = config.verify_tls

    def _url(self, path: str) -> str:
        base = self.config.hub_url.rstrip("/")
        return f"{base}{path}"

    def login(self, username: str, password: str) -> Dict[str, Any]:
        return obtain_token(self.config, username, password, self.session)

    def logout(self, refresh_token: Optional[str]) -> None:
        if not refresh_token:
            return
        payload: Dict[str, Any] = {
            "refresh_token": refresh_token,
            "client_id": self.config.client_id,
        }
        if self.config.client_secret:
            payload["client_secret"] = self.config.client_secret
        url = self._url(Routes.LOGOUT)
        try:
            response = self.session.post(
                url,
                json=payload,
                timeout=self.config.timeout,
                verify=self.config.verify_tls,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to revoke session with hub: {exc}") from exc

    def _get_access_token(self) -> str:
        token = load_token()
        if token is None:
            raise RuntimeError(
                "No cached token found. Run 'nebula-cli auth login' (or 'nebula-cli login') first."
            )
        if token.get("expires_at", 0) <= time.time():
            refresh_token = token.get("refresh_token")
            if not refresh_token:
                raise RuntimeError("Cached token expired and no refresh token is available")
            token = refresh_token_flow(self.config, refresh_token, self.session)
        access_token = token.get("access_token")
        if not isinstance(access_token, str):
            raise RuntimeError("Cached token does not contain an access_token")
        return access_token

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Any = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> Response:
        url = self._url(path)
        headers = headers or {}
        headers.setdefault("Accept", "application/json")
        if files is None and json_body is not None:
            headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Authorization", f"Bearer {self._get_access_token()}")

        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                files=files,
                headers=headers,
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to contact hub: {exc}") from exc

        if response.status_code >= 400:
            detail = extract_error_detail(response)
            if response.status_code == 401:
                hint = "Token missing, expired, or revoked. Run 'nebula-cli auth login' to obtain a new session."
                if detail and detail.lower() != "unknown error":
                    detail = f"{detail}\n{hint}"
                else:
                    detail = hint
            raise RuntimeError(f"{method.upper()} {path} failed {detail}")

        return response

    def request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.request(method, path, **kwargs)
        return coerce_body(response)


def _hub_token_exchange(
    config: CLIConfig,
    payload: Dict[str, Any],
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    if not config.hub_url:
        raise RuntimeError("Hub URL is not configured. Provide --hub-url or NEBULA_HUB_URL.")

    url = f"{config.hub_url.rstrip('/')}{LOGIN_ENDPOINT}"
    http_post = session.post if session else requests.post
    response = http_post(
        url,
        json=payload,
        timeout=config.timeout,
        verify=config.verify_tls,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = extract_error_detail(response)
        hint = _login_error_hint(response.status_code, detail, config, payload)
        if hint:
            detail = f"{detail} ({hint})"
        raise RuntimeError(f"Hub login failed ({response.status_code}): {detail}") from exc

    try:
        token_payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Hub login returned an invalid JSON response") from exc

    if payload.get("grant_type") == "refresh_token" and "refresh_token" not in token_payload:
        token_payload["refresh_token"] = payload.get("refresh_token")

    save_token(token_payload)
    return token_payload


def refresh_token_flow(
    config: CLIConfig, refresh_token: str, session: Optional[requests.Session] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.client_id,
    }
    if config.client_secret:
        payload["client_secret"] = config.client_secret
    return _hub_token_exchange(config, payload, session=session)


def obtain_token(
    config: CLIConfig,
    username: str,
    password: str,
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "grant_type": "password",
        "username": username,
        "password": password,
        "client_id": config.client_id,
    }
    if config.client_secret:
        payload["client_secret"] = config.client_secret
    scope = (config.scope or "").strip()
    if scope:
        payload["scope"] = scope

    return _hub_token_exchange(config, payload, session=session)


def _login_error_hint(
    status_code: int,
    detail: str,
    config: CLIConfig,
    payload: Dict[str, Any],
) -> str:
    normalized = detail.lower()
    if status_code == 401:
        client_msg = f"client_id='{config.client_id or '<missing>'}'"
        return f"{client_msg} rejected; verify NEBULA_KEYCLOAK_CLIENT_ID/SECRET and that the client exists"
    if status_code == 400 and "invalid_grant" in normalized:
        grant = payload.get("grant_type") or "password"
        if grant == "password":
            return "check username/password and that the user is allowed to use this client"
        if grant == "refresh_token":
            return "refresh token expired or revoked; run 'auth login' again"
    if status_code in {404, 502, 503}:
        return "hub could not reach Keycloak; confirm NEBULA_KEYCLOAK_SERVER/REALM URLs"
    return ""

"""Simple NEBULA command-line client.

This is a minimal example that obtains Keycloak tokens through the Hub API
using the Resource Owner Password grant (recommended only for trusted clients)
and then performs requests against the Hub API.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

TOKEN_CACHE = Path.home() / ".cache" / "nebula-cli" / "token.json"
LOGIN_ENDPOINT = "/auth/login"


def _ensure_cache_dir() -> None:
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)


def _load_token() -> Optional[Dict[str, Any]]:
    try:
        with TOKEN_CACHE.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        if data.get("expires_at", 0) <= time.time():
            return None
        return data
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def _save_token(payload: Dict[str, Any]) -> None:
    _ensure_cache_dir()
    payload["expires_at"] = time.time() + int(payload.get("expires_in", 0)) - 5
    with TOKEN_CACHE.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)


def _extract_error_detail(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text.strip() or "unknown error"

    for key in ("detail", "error_description", "error", "message"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value

    return response.text.strip() or "unknown error"


def _hub_token_exchange(config: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    hub_url = config.get("hub_url")
    if not hub_url:
        raise RuntimeError("Hub URL is not configured. Provide --hub-url or NEBULA_HUB_URL.")

    url = f"{hub_url.rstrip('/')}{LOGIN_ENDPOINT}"
    response = requests.post(url, json=payload, timeout=30)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = _extract_error_detail(response)
        raise RuntimeError(f"Hub login failed ({response.status_code}): {detail}") from exc

    try:
        token_payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Hub login returned an invalid JSON response") from exc

    if payload.get("grant_type") == "refresh_token" and "refresh_token" not in token_payload:
        token_payload["refresh_token"] = payload.get("refresh_token")

    _save_token(token_payload)
    return token_payload


def _refresh_token(config: Dict[str, str], refresh_token: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config["client_id"],
    }
    if config.get("client_secret"):
        payload["client_secret"] = config["client_secret"]
    return _hub_token_exchange(config, payload)


def _obtain_token(config: Dict[str, str], username: str, password: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "grant_type": "password",
        "username": username,
        "password": password,
        "client_id": config["client_id"],
    }
    if config.get("client_secret"):
        payload["client_secret"] = config["client_secret"]
    scope = (config.get("scope") or "").strip()
    if scope:
        payload["scope"] = scope

    return _hub_token_exchange(config, payload)


def _get_access_token(config: Dict[str, str]) -> str:
    token = _load_token()
    if token is None:
        raise RuntimeError(
            "No cached token found. Run `nebula-cli login` first or provide credentials."
        )
    if token.get("expires_at", 0) <= time.time():
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Cached token expired and no refresh token available")
        token = _refresh_token(config, refresh_token)
    return token["access_token"]


def cmd_login(args: argparse.Namespace) -> None:
    config = {
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "scope": "nebula-hub",
        "hub_url": args.hub_url,
    }
    _obtain_token(config, args.username, args.password)
    print("Login successful. Token cached.")


def _authorized_request(
    config: Dict[str, str], method: str, url: str, **kwargs: Any
) -> requests.Response:
    access_token = _get_access_token(config)
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {access_token}"
    headers.setdefault("Content-Type", "application/json")
    return requests.request(method, url, headers=headers, timeout=30, **kwargs)


def cmd_running(args: argparse.Namespace) -> None:
    config = {
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "hub_url": args.hub_url,
    }
    url = f"{args.hub_url}/scenarios/running"
    response = _authorized_request(
        config, "GET", url, params={"get_all": str(args.all).lower()}
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))


def cmd_scenarios(args: argparse.Namespace) -> None:
    config = {
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "hub_url": args.hub_url,
    }
    url = f"{args.hub_url}/scenarios/{args.username}/{args.role}"
    response = _authorized_request(config, "GET", url)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nebula-cli", description="NEBULA CLI example")
    parser.add_argument(
        "--client-id",
        default=os.environ.get("NEBULA_KEYCLOAK_CLIENT_ID", "nebula-cli"),
        help=(
            "Keycloak client ID to authenticate with "
            "(defaults to NEBULA_KEYCLOAK_CLIENT_ID or 'nebula-cli')"
        ),
    )
    parser.add_argument(
        "--client-secret",
        default=os.environ.get("NEBULA_KEYCLOAK_CLIENT_SECRET"),
        help="Optional client secret (defaults to NEBULA_KEYCLOAK_CLIENT_SECRET)",
    )
    parser.add_argument(
        "--hub-url",
        default=os.environ.get("NEBULA_HUB_URL", "http://localhost:5050"),
        help="Base URL for the Hub API",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Authenticate and cache a token")
    login_parser.add_argument("username")
    login_parser.add_argument("password")
    login_parser.set_defaults(func=cmd_login)

    running_parser = subparsers.add_parser(
        "running", help="List running scenarios"
    )
    running_parser.add_argument(
        "--all",
        action="store_true",
        help="Request all running scenarios instead of just the current user's",
    )
    running_parser.set_defaults(func=cmd_running)

    scenarios_parser = subparsers.add_parser(
        "scenarios", help="List scenarios for a specific user/role"
    )
    scenarios_parser.add_argument("username", help="Username whose scenarios should be fetched")
    scenarios_parser.add_argument("role", help="Role to use in the query (e.g. hub-admin)")
    scenarios_parser.set_defaults(func=cmd_scenarios)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except requests.HTTPError as exc:
        print(f"HTTP error: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

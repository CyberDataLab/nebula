from __future__ import annotations

import argparse
import time
from datetime import datetime
from getpass import getpass
from typing import Any

from nebula.nebula_cli.core import (
    NebulaClient,
    TOKEN_CACHE,
    clear_token,
    load_token,
    preview_token,
    print_output,
)


def cmd_auth_login(args: argparse.Namespace, client: NebulaClient) -> None:
    password = args.password or getpass("Password: ")
    if not password:
        raise RuntimeError("Password is required for login")
    token = client.login(args.username, password)
    expires = token.get("expires_in")
    if isinstance(expires, (int, float)) and expires > 0:
        print(f"Login successful. Token cached for ~{int(expires)}s.")
    else:
        print("Login successful. Token cached.")


def cmd_auth_logout(_: argparse.Namespace, __: NebulaClient) -> None:
    if clear_token():
        print(f"Removed cached token at {TOKEN_CACHE}")
    else:
        print("No cached token found.")


def cmd_auth_show(args: argparse.Namespace, _: NebulaClient) -> None:
    token = load_token()
    if not token:
        print("No cached token found.")
        return
    expires_at = token.get("expires_at")
    remaining = max(int(expires_at - time.time()), 0) if isinstance(expires_at, (int, float)) else None
    payload: dict[str, Any] = {
        "cache_path": str(TOKEN_CACHE),
        "expires_at": datetime.fromtimestamp(expires_at).isoformat() if isinstance(expires_at, (int, float)) else None,
        "seconds_remaining": remaining,
        "access_token_preview": preview_token(token.get("access_token")),
        "refresh_token_preview": preview_token(token.get("refresh_token")),
        "scope": token.get("scope"),
    }
    print_output(payload, args.output)


def add_login_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("username", help="Keycloak username")
    parser.add_argument("password", nargs="?", help="Keycloak password (will prompt if omitted)")


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    auth = subparsers.add_parser("auth", help="Authentication helpers")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)

    login = auth_sub.add_parser("login", help="Log in via Keycloak and cache a token")
    add_login_arguments(login)
    login.set_defaults(func=cmd_auth_login)

    logout = auth_sub.add_parser("logout", help="Remove the cached token")
    logout.set_defaults(func=cmd_auth_logout)

    show = auth_sub.add_parser("token", help="Show information about the cached token")
    show.set_defaults(func=cmd_auth_show)

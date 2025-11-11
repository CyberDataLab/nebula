from __future__ import annotations

import argparse
import os
from typing import Callable, Iterable


class ParserFactory:
    """Factory to compose the CLI parser from command modules."""

    def __init__(self) -> None:
        self._registrars: list[Callable[[argparse._SubParsersAction[argparse.ArgumentParser]], None]] = []

    def register(self, registrar: Callable[[argparse._SubParsersAction[argparse.ArgumentParser]], None]) -> None:
        self._registrars.append(registrar)

    def build(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="nebula-cli", description="NEBULA Hub CLI")
        parser.add_argument(
            "--hub-url",
            default=os.environ.get("NEBULA_HUB_URL", "http://localhost:5050"),
            help="Base URL for the Hub API",
        )
        parser.add_argument(
            "--client-id",
            default=os.environ.get("NEBULA_KEYCLOAK_CLIENT_ID", "nebula-cli"),
            help="Keycloak client ID",
        )
        parser.add_argument(
            "--client-secret",
            default=os.environ.get("NEBULA_KEYCLOAK_CLIENT_SECRET"),
            help="Optional Keycloak client secret",
        )
        parser.add_argument(
            "--scope",
            default=os.environ.get("NEBULA_KEYCLOAK_SCOPE", "nebula-hub"),
            help="OAuth scope to request during login",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=int(os.environ.get("NEBULA_HTTP_TIMEOUT", 30)),
            help="Request timeout in seconds",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="Disable TLS certificate verification",
        )
        parser.add_argument(
            "--output",
            choices=("pretty", "json", "raw"),
            default=os.environ.get("NEBULA_CLI_OUTPUT", "pretty"),
            help="Select how responses are rendered",
        )
        parser.add_argument(
            "--token-cache",
            help="Custom path for the cached token (defaults to ~/.cache/nebula-cli/token.json)",
        )
        parser.add_argument(
            "--interactive",
            "-i",
            action="store_true",
            help="Start the interactive shell instead of executing a single command",
        )

        subparsers = parser.add_subparsers(dest="command", required=False)

        for registrar in self._registrars:
            registrar(subparsers)

        return parser

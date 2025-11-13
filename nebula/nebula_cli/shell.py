from __future__ import annotations

import os
import shlex
import sys
from typing import Optional

from nebula.nebula_cli.core import CLIContext, load_token


BANNER_FULL = """
                    ███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗
                    ████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗
                    ██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║
                    ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║
                    ██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║
                    ╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
                      A Platform for Decentralized Federated Learning

                      Developed by:
                       • Enrique Tomás Martínez Beltrán
                       • Alberto Huertas Celdrán
                       • Alejandro Avilés Serrano
                       • Fernando Torres Vega

                      https://nebula-dfl.com / https://nebula-dfl.eu

                      [{mode} mode] [{prefix} prefix]
                """

BANNER_SHORT = """
                    ███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗
                    ████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗
                    ██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║
                    ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║
                    ██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║
                    ╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
                      A Platform for Decentralized Federated Learning
                """


class NebulaInteractiveShell:
    """Simple REPL that wraps the argparse-based CLI handlers."""

    PRE_AUTH_COMMANDS = {"auth", "login", "register"}

    def __init__(self, parser, ctx: CLIContext) -> None:
        self.parser = parser
        self.ctx = ctx
        self.client = ctx.client()
        self.authenticated = bool(load_token())
        self.mode = self._detect_mode()
        self.prefix = self._detect_prefix()

    def run(self) -> int:
        self._clear_screen()
        self._print_banner(full=not self.authenticated)
        self._print_intro()

        while True:
            try:
                raw = input("nebula> ").strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                break

            if not raw:
                continue

            lowered = raw.lower()
            if lowered in {"exit", "quit"}:
                print("See you soon.")
                break
            if lowered in {"help", "?"}:
                self._print_help()
                continue
            if lowered == "banner":
                self._clear_screen()
                self._print_banner(full=not self.authenticated)
                continue
            if lowered == "clear":
                self._clear_screen()
                self._print_banner(full=not self.authenticated)
                continue

            tokens = self._tokenize(raw)
            if not tokens:
                continue

            try:
                args = self.parser.parse_args(tokens)
            except SystemExit:
                # argparse already printed the error/help message
                continue

            command = getattr(args, "command", None)
            if command is None:
                print("Type 'help' to see available commands.")
                continue

            if not self.authenticated and command not in self.PRE_AUTH_COMMANDS:
                print("Please login first (e.g. 'auth login <user>').")
                continue

            if not hasattr(args, "func"):
                print("Unknown command. Type 'help'.")
                continue

            self._prepare_command_view()

            try:
                result = args.func(args, self.client)
            except RuntimeError as exc:
                print(f"Error: {exc}")
                continue
            except Exception as exc:  # pragma: no cover - safety
                print(f"Unexpected error: {exc}")
                continue

            if isinstance(result, int) and result != 0:
                print(f"Command completed with exit code {result}")

            self._update_auth_state(args)

        return 0

    def _print_intro(self) -> None:
        if self.authenticated:
            print("Session detected from cached token. Use 'auth logout' to switch users.")
        else:
            print("Please login or register before running other commands.")
        print("Type 'help' to list commands, 'banner' to reprint the banner, or 'exit' to quit.\n")

    def _print_help(self) -> None:
        print("\nExamples:")
        print("  auth login alice")
        print("  scenario list alice hub-admin")
        print("  register bob s3cret user")
        print("  nodes list <federation_id>")
        print("Use '--help' after any command for detailed options.\n")

    def _tokenize(self, raw: str) -> Optional[list[str]]:
        try:
            return shlex.split(raw)
        except ValueError as exc:
            print(f"Invalid command: {exc}")
            return None

    def _update_auth_state(self, args) -> None:
        command = getattr(args, "command", None)
        if command == "auth":
            sub = getattr(args, "auth_command", None)
            if sub == "login":
                self.authenticated = True
                self._clear_screen()
                self._print_banner(full=False)
                print("Authentication successful. You can now run NEBULA commands.")
            elif sub == "logout":
                self.authenticated = False
                self._clear_screen()
                self._print_banner(full=True)
                print("Logged out. Login again to continue.")
        elif command == "login":
            self.authenticated = True
            self._clear_screen()
            self._print_banner(full=False)
            print("Authentication successful. You can now run NEBULA commands.")
        elif command == "logout":
            self.authenticated = False
            self._clear_screen()
            self._print_banner(full=True)
            print("Logged out. Login again to continue.")

    def _print_banner(self, *, full: bool = False) -> None:
        banner = BANNER_FULL if full else BANNER_SHORT
        colored = "\033[0;36m" + banner.format(mode=self.mode, prefix=self.prefix) + "\033[0m"
        print(colored)

    def _prepare_command_view(self) -> None:
        self._clear_screen()
        self._print_banner(full=not self.authenticated)

    def _clear_screen(self) -> None:
        if os.name == "nt":
            os.system("cls")
        else:
            os.system("clear")

    def _detect_mode(self) -> str:
        env_tag = os.environ.get("NEBULA_ENV_TAG") or os.environ.get("NEBULA_ENV") or "dev"
        lowered = env_tag.lower()
        return "Production" if lowered in {"prod", "production"} else "Development"

    def _detect_prefix(self) -> str:
        prefix = (
            os.environ.get("NEBULA_PREFIX_TAG")
            or os.environ.get("NEBULA_DEPLOYMENT_PREFIX")
            or os.environ.get("NEBULA_CLI_PREFIX")
            or "dev"
        )
        return prefix

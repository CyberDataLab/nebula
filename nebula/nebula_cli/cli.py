"""NEBULA command-line client orchestrator.

This thin wrapper wires the parser factory and command modules, and dispatches
to handlers using a shared NebulaClient from a singleton context.
"""
from __future__ import annotations

from pathlib import Path
import os
import sys

if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

import argparse
from typing import Optional

from nebula.nebula_cli.core import CLIConfig, CLIContext, set_token_cache_path
from nebula.nebula_cli.parser_factory import ParserFactory
from nebula.nebula_cli.commands import auth, scenario, nodes, notes, users, legacy
from nebula.nebula_cli.shell import NebulaInteractiveShell


def build_parser() -> argparse.ArgumentParser:
    factory = ParserFactory()
    # Register command groups
    factory.register(auth.register)
    factory.register(scenario.register)
    factory.register(nodes.register)
    factory.register(notes.register)
    factory.register(users.register)
    factory.register(legacy.register)
    return factory.build()


def _apply_runtime_defaults(args: argparse.Namespace) -> None:
    overrides = {
        "NEBULA_HUB_URL": args.hub_url,
        "NEBULA_KEYCLOAK_CLIENT_ID": args.client_id,
        "NEBULA_KEYCLOAK_CLIENT_SECRET": args.client_secret,
        "NEBULA_KEYCLOAK_SCOPE": args.scope,
        "NEBULA_HTTP_TIMEOUT": str(args.timeout) if args.timeout is not None else None,
        "NEBULA_CLI_OUTPUT": args.output,
    }
    for key, value in overrides.items():
        if value is not None:
            os.environ[key] = str(value)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    set_token_cache_path(args.token_cache)

    config = CLIConfig(
        hub_url=args.hub_url,
        client_id=args.client_id,
        client_secret=args.client_secret,
        scope=args.scope,
        timeout=args.timeout,
        verify_tls=not args.insecure,
    )
    ctx = CLIContext.instance()
    ctx.configure(config)

    _apply_runtime_defaults(args)

    if args.interactive or args.command is None:
        shell = NebulaInteractiveShell(parser, ctx)
        return shell.run()

    client = ctx.client()

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    try:
        result = args.func(args, client)
    except KeyboardInterrupt:
        print("Aborted by user.", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if isinstance(result, int):
        return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

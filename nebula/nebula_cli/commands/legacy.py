from __future__ import annotations

import argparse

from nebula.nebula_cli.core import NebulaClient
from . import scenario as scenario_cmds
from . import auth as auth_cmds
from . import users as users_cmds


def cmd_legacy_scenarios(args: argparse.Namespace, client: NebulaClient) -> None:
    setattr(args, "user", args.username)
    scenario_cmds.cmd_scenario_list(args, client)


def cmd_register(args: argparse.Namespace, client: NebulaClient) -> None:
    users_cmds.cmd_users_add(args, client)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    # Backwards compatibility aliases
    legacy_login = subparsers.add_parser("login", help="Alias for 'auth login'")
    auth_cmds.add_login_arguments(legacy_login)
    legacy_login.set_defaults(func=auth_cmds.cmd_auth_login)

    legacy_running = subparsers.add_parser("running", help="Alias for 'scenario running'")
    legacy_running.add_argument(
        "--all",
        action="store_true",
        help="Return all running scenarios instead of the authenticated user's",
    )
    legacy_running.set_defaults(func=scenario_cmds.cmd_scenario_running)

    legacy_scenarios = subparsers.add_parser(
        "scenarios", help="Alias for 'scenario list <user> <role>'"
    )
    legacy_scenarios.add_argument("username", help="Username whose scenarios should be fetched")
    legacy_scenarios.add_argument("role", help="Role to use in the query (e.g. hub-admin)")
    legacy_scenarios.set_defaults(func=cmd_legacy_scenarios)

    register_cmd = subparsers.add_parser(
        "register", help="Alias for 'users add <user> <password> <role>'"
    )
    register_cmd.add_argument("user", help="Username to create")
    register_cmd.add_argument("password", help="Password for the new user")
    register_cmd.add_argument("role", help="Role to assign (e.g. viewer, operator, admin)")
    register_cmd.set_defaults(func=cmd_register)

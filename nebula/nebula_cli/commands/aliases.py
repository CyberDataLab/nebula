from __future__ import annotations

import argparse

from nebula.nebula_cli.core import NebulaClient
from . import scenario as scenario_cmds
from . import auth as auth_cmds
from . import users as users_cmds


def cmd_alias_scenarios(args: argparse.Namespace, client: NebulaClient) -> None:
    setattr(args, "user", args.username)
    scenario_cmds.cmd_scenario_list(args, client)


def cmd_alias_register(args: argparse.Namespace, client: NebulaClient) -> None:
    users_cmds.cmd_users_add(args, client)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    login_alias = subparsers.add_parser("login", help="Alias for 'auth login'")
    auth_cmds.add_login_arguments(login_alias)
    login_alias.set_defaults(func=auth_cmds.cmd_auth_login)

    logout_alias = subparsers.add_parser("logout", help="Alias for 'auth logout'")
    logout_alias.set_defaults(func=auth_cmds.cmd_auth_logout)

    running_alias = subparsers.add_parser("running", help="Alias for 'scenario running'")
    running_alias.add_argument(
        "--all",
        action="store_true",
        help="Return all running scenarios instead of the authenticated user's",
    )
    running_alias.set_defaults(func=scenario_cmds.cmd_scenario_running)

    scenarios_alias = subparsers.add_parser(
        "scenarios", help="Alias for 'scenario list <user> <role>'"
    )
    scenarios_alias.add_argument("username", help="Username whose scenarios should be fetched")
    scenarios_alias.add_argument("role", help="Role to use in the query (e.g. hub-admin)")
    scenarios_alias.set_defaults(func=cmd_alias_scenarios)

    register_alias = subparsers.add_parser(
        "register", help="Alias for 'users add <user> <password> <role>'"
    )
    register_alias.add_argument("user", help="Username to create")
    register_alias.add_argument("password", help="Password for the new user")
    register_alias.add_argument(
        "role",
        choices=("admin", "user"),
        help="Role to assign (admin or user)",
    )
    register_alias.set_defaults(func=cmd_alias_register)

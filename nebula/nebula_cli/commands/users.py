from __future__ import annotations

import argparse

from nebula.controller.hub.utils_requests import Routes
from nebula.nebula_cli.core import NebulaClient, bool_param, print_output


def cmd_users_list(args: argparse.Namespace, client: NebulaClient) -> None:
    params = {"all_info": bool_param(args.all_info)}
    data = client.request_json("GET", Routes.USER_LIST, params=params)
    print_output(data, args.output)


def cmd_users_add(args: argparse.Namespace, client: NebulaClient) -> None:
    body = {"user": args.user, "password": args.password, "role": args.role}
    data = client.request_json("POST", Routes.USER_ADD, json_body=body)
    print_output(data, args.output)


def cmd_users_delete(args: argparse.Namespace, client: NebulaClient) -> None:
    data = client.request_json("POST", Routes.USER_DELETE, json_body={"user": args.user})
    print_output(data, args.output)


def cmd_users_update(args: argparse.Namespace, client: NebulaClient) -> None:
    body = {"user": args.user, "password": args.password, "role": args.role}
    data = client.request_json("POST", Routes.USER_UPDATE, json_body=body)
    print_output(data, args.output)


def cmd_users_verify(args: argparse.Namespace, client: NebulaClient) -> None:
    body = {"user": args.user, "password": args.password}
    data = client.request_json("POST", Routes.USER_VERIFY, json_body=body)
    print_output(data, args.output)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    users = subparsers.add_parser("users", help="User management helpers")
    users_sub = users.add_subparsers(dest="users_command", required=True)

    list_parser = users_sub.add_parser("list", help="List users")
    list_parser.add_argument("--all-info", action="store_true", help="Include full user details")
    list_parser.set_defaults(func=cmd_users_list)

    add_parser = users_sub.add_parser("add", help="Add a new user")
    add_parser.add_argument("user")
    add_parser.add_argument("password")
    add_parser.add_argument("role", choices=("admin", "user"), help="Role to assign (admin or user)")
    add_parser.set_defaults(func=cmd_users_add)

    delete_parser = users_sub.add_parser("delete", help="Remove a user")
    delete_parser.add_argument("user")
    delete_parser.set_defaults(func=cmd_users_delete)

    update_parser = users_sub.add_parser("update", help="Update a user's password and role")
    update_parser.add_argument("user")
    update_parser.add_argument("password")
    update_parser.add_argument("role", choices=("admin", "user"), help="Role to assign (admin or user)")
    update_parser.set_defaults(func=cmd_users_update)

    verify_parser = users_sub.add_parser("verify", help="Verify a user's credentials")
    verify_parser.add_argument("user")
    verify_parser.add_argument("password")
    verify_parser.set_defaults(func=cmd_users_verify)

from __future__ import annotations

import argparse
from typing import Any

from nebula.controller.hub.utils_requests import Routes
from nebula.nebula_cli.core import NebulaClient, load_json_payload, print_output


def cmd_nodes_list(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.NODES_LIST.format(federation_id=args.federation_id)
    data = client.request_json("GET", path)
    print_output(data, args.output)


def cmd_nodes_update(args: argparse.Namespace, client: NebulaClient) -> None:
    payload = load_json_payload(
        file_path=args.payload_file,
        inline_json=args.payload_json,
        use_stdin=args.payload_stdin,
    )
    path = Routes.NODES_UPDATE.format(federation_id=args.federation_id)
    body = {"config": payload}
    data = client.request_json("POST", path, json_body=body)
    print_output(data, args.output)


def cmd_nodes_done(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.NODES_DONE.format(federation_id=args.federation_id)
    body = {"idx": args.idx}
    data = client.request_json("POST", path, json_body=body)
    print_output(data, args.output)


def cmd_nodes_remove(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.NODES_REMOVE.format(federation_id=args.federation_id)
    data = client.request_json("POST", path)
    print_output(data, args.output)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    nodes = subparsers.add_parser("nodes", help="Node management helpers")
    nodes_sub = nodes.add_subparsers(dest="nodes_command", required=True)

    list_parser = nodes_sub.add_parser("list", help="List nodes by federation ID")
    list_parser.add_argument("federation_id")
    list_parser.set_defaults(func=cmd_nodes_list)

    update_parser = nodes_sub.add_parser("update", help="Send a node update payload")
    update_parser.add_argument("federation_id")
    update_parser.add_argument("--file", "-f", dest="payload_file", help="Path to the JSON payload")
    update_parser.add_argument("--json", dest="payload_json", help="Inline JSON payload")
    update_parser.add_argument(
        "--stdin",
        dest="payload_stdin",
        action="store_true",
        help="Read the payload from stdin",
    )
    update_parser.set_defaults(func=cmd_nodes_update)

    done_parser = nodes_sub.add_parser("done", help="Report a node as finished")
    done_parser.add_argument("federation_id")
    done_parser.add_argument("idx", type=int, help="Index of the node")
    done_parser.set_defaults(func=cmd_nodes_done)

    remove_parser = nodes_sub.add_parser("remove", help="Remove node metadata for a federation")
    remove_parser.add_argument("federation_id")
    remove_parser.set_defaults(func=cmd_nodes_remove)

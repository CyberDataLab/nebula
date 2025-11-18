from __future__ import annotations

import argparse
from typing import Any, Dict

from nebula.controller.hub.utils_requests import Routes
from nebula.nebula_cli.core import (
    NebulaClient,
    bool_param,
    load_json_payload,
    print_output,
)


def cmd_scenario_list(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.GET_SCENARIOS_BY_USER.format(user=args.user, role=args.role)
    data = client.request_json("GET", path)
    print_output(data, args.output)


def cmd_scenario_running(args: argparse.Namespace, client: NebulaClient) -> None:
    params = {"get_all": bool_param(args.all)}
    data = client.request_json("GET", Routes.RUNNING, params=params)
    print_output(data, args.output)


def cmd_scenario_run(args: argparse.Namespace, client: NebulaClient) -> None:
    scenario_data = load_json_payload(
        file_path=args.config_file,
        inline_json=args.config_json,
        use_stdin=args.config_stdin,
    )
    body: Dict[str, Any] = {"scenario_data": scenario_data}
    data = client.request_json("POST", Routes.RUN, json_body=body)
    print_output(data, args.output)


def cmd_scenario_stop(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.STOP.format(federation_id=args.federation_id)
    body = {"experiment_type": args.experiment_type, "all": args.all}
    data = client.request_json("POST", path, json_body=body)
    print_output(data, args.output)


def cmd_scenario_remove(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.REMOVE.format(federation_id=args.federation_id)
    body = {
        "experiment_type": args.experiment_type,
        "scenario_name": args.scenario_name,
    }
    if args.user:
        body["user"] = args.user
    data = client.request_json("POST", path, json_body=body)
    print_output(data, args.output)


def cmd_scenario_finish(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.FINISH.format(federation_id=args.federation_id)
    body = {"all": args.all}
    data = client.request_json("POST", path, json_body=body)
    print_output(data, args.output)


def cmd_scenario_get(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.GET_SCENARIO_BY_FEDERATION_ID.format(federation_id=args.federation_id)
    data = client.request_json("GET", path)
    print_output(data, args.output)


def cmd_scenario_check(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.CHECK_SCENARIO.format(
        user=args.user,
        role=args.role,
        federation_id=args.federation_id,
    )
    data = client.request_json("GET", path)
    print_output(data, args.output)


def cmd_scenario_resources_stop(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.RESOURCES_STOP.format(federation_id=args.federation_id)
    data = client.request_json("POST", path)
    print_output(data, args.output)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    scenario = subparsers.add_parser("scenario", help="Scenario lifecycle operations")
    scenario_sub = scenario.add_subparsers(dest="scenario_command", required=True)

    list_parser = scenario_sub.add_parser("list", help="List scenarios for a user and role")
    list_parser.add_argument("user", help="Username to query")
    list_parser.add_argument("role", help="Role to use during the lookup (e.g. hub-admin)")
    list_parser.set_defaults(func=cmd_scenario_list)

    running_parser = scenario_sub.add_parser("running", help="List running scenarios")
    running_parser.add_argument(
        "--all",
        action="store_true",
        help="Return all running scenarios instead of just the authenticated user",
    )
    running_parser.set_defaults(func=cmd_scenario_running)

    run_parser = scenario_sub.add_parser("run", help="Run a scenario from a JSON definition")
    run_parser.add_argument("--file", "-f", dest="config_file", help="Path to a scenario JSON file")
    run_parser.add_argument("--json", dest="config_json", help="Inline scenario JSON")
    run_parser.add_argument(
        "--stdin",
        dest="config_stdin",
        action="store_true",
        help="Read the scenario JSON from stdin",
    )
    run_parser.set_defaults(func=cmd_scenario_run)

    stop_parser = scenario_sub.add_parser("stop", help="Stop a scenario")
    stop_parser.add_argument("federation_id")
    stop_parser.add_argument("--experiment-type", required=True, help="Experiment type to stop")
    stop_parser.add_argument("--all", action="store_true", help="Stop all queued scenarios as well")
    stop_parser.set_defaults(func=cmd_scenario_stop)

    remove_parser = scenario_sub.add_parser("remove", help="Remove scenario artifacts")
    remove_parser.add_argument("federation_id")
    remove_parser.add_argument("--experiment-type", required=True)
    remove_parser.add_argument("--scenario-name", required=True)
    remove_parser.add_argument("--user", help="User that owns the scenario")
    remove_parser.set_defaults(func=cmd_scenario_remove)

    finish_parser = scenario_sub.add_parser("finish", help="Mark a scenario as finished")
    finish_parser.add_argument("federation_id")
    finish_parser.add_argument("--all", action="store_true", help="Apply to all running scenarios")
    finish_parser.set_defaults(func=cmd_scenario_finish)

    get_parser = scenario_sub.add_parser("get", help="Retrieve a scenario by federation ID")
    get_parser.add_argument("federation_id")
    get_parser.set_defaults(func=cmd_scenario_get)

    check_parser = scenario_sub.add_parser("check", help="Check access to a scenario")
    check_parser.add_argument("user")
    check_parser.add_argument("role")
    check_parser.add_argument("federation_id")
    check_parser.set_defaults(func=cmd_scenario_check)

    resources_stop_parser = scenario_sub.add_parser(
        "resources-stop", help="Mark a scenario as stopped from a resources perspective"
    )
    resources_stop_parser.add_argument("federation_id")
    resources_stop_parser.set_defaults(func=cmd_scenario_resources_stop)

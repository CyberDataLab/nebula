from __future__ import annotations

import argparse

from nebula.controller.hub.utils_requests import Routes
from nebula.nebula_cli.core import NebulaClient, load_text_payload, print_output


def cmd_notes_get(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.NOTES_BY_FEDERATION_ID.format(federation_id=args.federation_id)
    data = client.request_json("GET", path)
    print_output(data, args.output)


def cmd_notes_update(args: argparse.Namespace, client: NebulaClient) -> None:
    notes = load_text_payload(
        file_path=args.note_file,
        inline_text=args.note_text,
        use_stdin=args.note_stdin,
    )
    path = Routes.NOTES_UPDATE.format(federation_id=args.federation_id)
    data = client.request_json("POST", path, json_body={"notes": notes})
    print_output(data, args.output)


def cmd_notes_remove(args: argparse.Namespace, client: NebulaClient) -> None:
    path = Routes.NOTES_REMOVE.format(federation_id=args.federation_id)
    data = client.request_json("POST", path)
    print_output(data, args.output)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    notes = subparsers.add_parser("notes", help="Attach free-form notes to federations")
    notes_sub = notes.add_subparsers(dest="notes_command", required=True)

    get_parser = notes_sub.add_parser("get", help="Retrieve notes for a federation")
    get_parser.add_argument("federation_id")
    get_parser.set_defaults(func=cmd_notes_get)

    update_parser = notes_sub.add_parser("update", help="Update notes")
    update_parser.add_argument("federation_id")
    update_parser.add_argument("--text", dest="note_text", help="Inline text for the note")
    update_parser.add_argument("--file", dest="note_file", help="File with the note contents")
    update_parser.add_argument(
        "--stdin",
        dest="note_stdin",
        action="store_true",
        help="Read the note contents from stdin",
    )
    update_parser.set_defaults(func=cmd_notes_update)

    remove_parser = notes_sub.add_parser("remove", help="Delete notes for a federation")
    remove_parser.add_argument("federation_id")
    remove_parser.set_defaults(func=cmd_notes_remove)

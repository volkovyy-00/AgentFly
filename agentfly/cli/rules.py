"""`agentfly rules`: check a rules file and run its inline tests (SPEC section 5, D12)."""

from __future__ import annotations

import argparse

from agentfly.cli import rules_check, rules_test


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "rules",
        help="check a rules file, or run its inline tests",
        description=(
            "Both commands read FILE, or, with no FILE, the file the recorder would load: the "
            "active rules file when it exists, else the packaged default. They change nothing."
        ),
    )
    # Not `dest="command"`: `agentfly.cli.main` prints that name when a command fails.
    sub = parser.add_subparsers(dest="rules_command", metavar="<command>", required=True)
    rules_check.add_parser(sub)
    rules_test.add_parser(sub)

"""`agentfly stop`: stop the recorder service and keep it down, also at the next login."""

from __future__ import annotations

import argparse

from agentfly.install import service


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "stop",
        help="stop the recorder service (until `agentfly start`)",
        description=(
            "Unloads the service and removes its file. While it is stopped only the offline "
            "guard protects Cursor; run `agentfly start` to bring the recorder back."
        ),
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    for line in service.stop():
        print(line)
    return 0

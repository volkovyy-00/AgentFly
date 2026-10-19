"""`agentfly stop`: stop the recorder service and keep it down, also at the next login."""

from __future__ import annotations

import argparse
import sys

from agentfly.install import InstallError, service


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
    try:
        for line in service.stop():
            print(line)
    except InstallError as exc:
        print(f"agentfly stop: {exc}", file=sys.stderr)
        return 1
    return 0

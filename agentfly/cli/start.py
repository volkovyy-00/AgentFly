"""`agentfly start`: run the recorder as a service that starts at login and restarts itself."""

from __future__ import annotations

import argparse
import sys

from agentfly.install import InstallError, service


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "start",
        help="run the recorder as a background service (restarts itself, starts at login)",
        description=(
            "Starts the recorder through `brew services` for a Homebrew install, and through a "
            "LaunchAgent AgentFly writes in ~/Library/LaunchAgents otherwise."
        ),
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    try:
        manager = service.detect_manager()
        for line in service.start(manager):
            print(line)
        if service.wait_for_health() is not None:
            print(f"recorder answers on 127.0.0.1:{service.HEALTH_PORT}")
            return 0
    except InstallError as exc:
        print(f"agentfly start: {exc}", file=sys.stderr)
        return 1
    where = "" if manager.brew else f"; see {service.log_path()}"
    print(
        f"agentfly start: the recorder did not answer on 127.0.0.1:{service.HEALTH_PORT} "
        f"within {service.START_TIMEOUT:g} s{where}",
        file=sys.stderr,
    )
    return 1

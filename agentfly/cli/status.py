"""`agentfly status`: who runs the recorder, whether it runs, and what `/health` answers."""

from __future__ import annotations

import argparse
import sys

from agentfly.install import InstallError, service


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "status",
        help="show whether the recorder service runs and answers",
        description="Exits 0 when the recorder answers on 127.0.0.1:8787, 1 otherwise.",
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    try:
        state = service.inspect()
    except InstallError as exc:
        print(f"agentfly status: {exc}", file=sys.stderr)
        return 1
    label = "brew services " + service.BREW_FORMULA if state.manager.brew else service.LABEL
    print(f"manager:  {state.manager.name} ({label})")
    print(f"service:  {state.summary}")
    answer = service.health()
    port = f"127.0.0.1:{service.HEALTH_PORT}"
    if answer is None:
        print(f"recorder: no answer on {port}")
        if not state.running:
            print("          run `agentfly start`")
        return 1
    note = "" if state.running else " (not through the service: was it started by hand?)"
    print(f"recorder: answers on {port}{note}")
    return 0

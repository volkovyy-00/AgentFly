"""`agentfly status`: who runs the recorder, whether it runs, and what `/health` answers."""

from __future__ import annotations

import argparse

from agentfly.install import service


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "status",
        help="show whether the recorder service runs and answers",
        description="Exits 0 when the recorder answers on 127.0.0.1:8787, 1 otherwise.",
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    state = service.inspect()
    print(f"manager:  {state.manager.name} ({state.manager.label})")
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
    problem = answer.get("rules_problem")
    if problem:
        print(f"rules:    {' '.join(str(problem).split())}")
    return 0

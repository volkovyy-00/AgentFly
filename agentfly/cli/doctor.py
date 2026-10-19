"""`agentfly doctor`: is AgentFly installed, intact and running? One line per check (SPEC 7)."""

from __future__ import annotations

import argparse

from agentfly.install import checks, installer, pythons
from agentfly.install.layout import SYSTEM


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "doctor",
        help="check that AgentFly is installed, intact and running",
        description=(
            "Compares the installed files with the hashes recorded at install, checks the hooks "
            "file, the service, the `agentfly` on PATH and Cursor's Hooks log. Prints one line "
            "per check (ok, warn, fail) and exits 1 if any check fails. Needs no password."
        ),
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    if not installer.is_installed(SYSTEM):
        print("fail  install          AgentFly is not installed; run `agentfly init -g`")
        return 1
    ctx = checks.build_context(SYSTEM, pythons.select_build(), installer.client_source())
    results = checks.run_all(ctx)
    for check in results:
        print(f"{check.level:<5} {check.id:<16} {check.text}")
    return 1 if any(check.level == "fail" for check in results) else 0

"""`agentfly uninstall`: take AgentFly's hook entries out, then its system folder (SPEC 7)."""

from __future__ import annotations

import argparse
import os
import sys

from agentfly.install import InstallError, elevate, installer
from agentfly.install.layout import SYSTEM


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "uninstall",
        help="remove AgentFly's system hooks and files (needs sudo once)",
        description="Removes AgentFly's entries from Cursor's system hooks file, then its folder.",
    )
    parser.set_defaults(run=run)


RESTART_HINT = (
    "Quit and reopen Cursor. Until it restarts it keeps calling the removed hook client; "
    "those calls fail (exit 127) and let every action through."
)


def run(args: argparse.Namespace) -> int:
    try:
        if os.geteuid() != 0:
            if not installer.is_installed(SYSTEM):
                print("nothing of AgentFly's is installed")
                return 0
            print("AgentFly will ask for your password once, to remove its system files.")
            code = elevate.run_elevated(["uninstall"])
            if code == 0:
                print(RESTART_HINT)
            return code
        outcome = installer.uninstall(SYSTEM)
        for line in outcome.messages:
            print(line)
        if outcome.changed:
            print(RESTART_HINT)
        return 0
    except InstallError as exc:
        print(f"agentfly uninstall: {exc}", file=sys.stderr)
        return 1

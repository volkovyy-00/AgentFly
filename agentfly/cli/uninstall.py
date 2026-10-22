"""`agentfly uninstall`: hook entries out first, then the system folder and the service (SPEC 7)."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from agentfly.install import InstallError, elevate, installer, packages, records, service
from agentfly.install.layout import SYSTEM


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "uninstall",
        help="remove AgentFly's system hooks and files (needs sudo once)",
        description=(
            "Keeps a copy of an edited rules file next to the hooks.json backups, removes "
            "AgentFly's entries from Cursor's system hooks file, then its folder, and stops and "
            "removes the recorder service. Run it without sudo: it asks for the password."
        ),
    )
    parser.set_defaults(run=run)


RESTART_HINT = (
    "Quit and reopen Cursor. Until it restarts it keeps calling the removed hook client; "
    "those calls fail (exit 127) and let every action through."
)


SERVICE_NOT_TOUCHED = (
    "The recorder service was not touched: sudo cannot reach your login session. If it is "
    "running, run `agentfly uninstall` as your own user, without sudo, to stop and remove it."
)


def _elevated_child(flags: Any = sys.flags) -> bool:
    """True in the root process `_as_user` started: `elevate.sudo_command` runs it as `-I -S`.

    A `sudo agentfly uninstall` typed by hand runs the entry script's Python with `site` on (SPEC
    section 10), so the two differ in how Python started, not in anything on the command line.
    """
    return bool(flags.isolated and flags.no_site)


def _as_root() -> int:
    outcome = installer.uninstall(SYSTEM)
    for line in outcome.messages:
        print(line)
    if _elevated_child():
        return 0  # the user's process goes on: it removes the service and prints the hint once
    if outcome.changed:  # typed by hand: nothing else will say these
        print(RESTART_HINT)
    print(SERVICE_NOT_TOUCHED)
    return 0


def _as_user() -> int:
    installed = installer.is_installed(SYSTEM)
    if installed:
        # The package is checked here, before anything asks for a password (V3c, SPEC section 10).
        current = packages.require(records.read(SYSTEM), "agentfly uninstall")
        packages.ensure_confirmed(current)
        print("AgentFly will ask for your password once, to remove its system files.")
        python = SYSTEM.interpreter if installer.python_intact(SYSTEM) else None
        code = elevate.run_elevated(["uninstall"], python=python)
        if code != 0:
            print(
                f"agentfly uninstall: the sudo part failed (exit {code}); the service was not "
                "touched; run `agentfly uninstall` again",
                file=sys.stderr,
            )
            return code
    try:
        messages = service.remove()  # the user's login session owns it: no sudo
        failure = ""
    except InstallError as exc:
        messages, failure = [], str(exc)
    for line in messages:
        print(line)
    if failure:
        what = (
            "the system files are removed, but the service is not"
            if installed
            else "cannot remove the service"
        )
        print(
            f"agentfly uninstall: {what} ({failure}); run `agentfly uninstall` again",
            file=sys.stderr,
        )
    elif not installed and not messages:
        print("nothing of AgentFly's is installed")
    if installed:
        print(RESTART_HINT)
    return 1 if failure else 0


def run(args: argparse.Namespace) -> int:
    try:
        if os.geteuid() != 0:
            return _as_user()
        return _as_root()
    except InstallError as exc:
        print(f"agentfly uninstall: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:  # a filesystem error outside the installer: one line, not a traceback
        reason = installer.describe_oserror(exc)
        print(f"agentfly uninstall: {reason}; run `agentfly uninstall` again", file=sys.stderr)
        return 1

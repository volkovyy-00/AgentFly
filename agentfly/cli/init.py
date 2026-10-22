"""`agentfly init -g`: install the hook client, a bundled Python and the system hooks (SPEC 7)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agentfly.install import InstallError, cursor, elevate, installer, packages, pythons, records
from agentfly.install.layout import SYSTEM


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "init",
        help="install AgentFly into Cursor for every project (needs sudo once)",
        description=(
            "Installs a pinned Python and the hook client in /Library/Application Support/AgentFly "
            "and registers them in Cursor's system hooks file. Asks for your password once."
        ),
    )
    parser.add_argument(
        "-g", "--global", dest="system", action="store_true", help="install for the whole machine"
    )
    parser.set_defaults(run=run)


def _stdin_archive() -> Path | None:
    """The archive the unprivileged run piped in, copied to a file; None on a terminal."""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as handle:
        while chunk := sys.stdin.buffer.read(1 << 20):
            handle.write(chunk)
    path = Path(handle.name)
    if path.stat().st_size == 0:
        path.unlink()
        return None
    return path


def _run_as() -> tuple[int, int] | None:
    """The user who ran sudo, so the hook command is tried the way Cursor will run it."""
    try:
        return int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])
    except (KeyError, ValueError):
        return None


def _warn_if_unchecked(version: str) -> None:
    """D32: said once per run, by whichever process ends it (the root child, or the user's run
    when it has nothing to elevate); the user's run that does elevate says nothing itself."""
    note = cursor.warning(version)
    if note:
        print(note)


def _as_root(version: str, build: pythons.PythonBuild) -> int:
    archive = _stdin_archive()
    try:
        outcome = installer.install(
            SYSTEM,
            build,
            cursor_version=version,
            source=installer.client_source(),
            archive=archive,
            run_as=_run_as(),
        )
    finally:
        if archive is not None:
            archive.unlink(missing_ok=True)
    for line in outcome.messages:
        print(line)
    if outcome.changed:
        if outcome.cursor_reload:  # a rules-only refresh changes nothing Cursor reads
            print(
                "Quit and reopen Cursor so it loads the hooks (its Hooks panel does not list them)."
            )
        print("Next: `agentfly start` (or `agentfly serve` in a terminal) runs the recorder.")
    _warn_if_unchecked(version)
    return 0


def _as_user(version: str, build: pythons.PythonBuild) -> int:
    # The package is checked here, before anything asks for a password (V3c, SPEC section 10).
    current = packages.require(records.read(SYSTEM), "agentfly init -g")
    bad = installer.status(SYSTEM, build, installer.client_source(), current)
    wanted = packages.recorded_hash(current, installer.DEFAULT_RECORD_PATH)
    if not bad:
        print("already installed and intact; nothing changed")
        # An edited rules file is the owner's, and a readable one needs no password to be said.
        notice = installer.rules_notice(SYSTEM, wanted)
        if notice:
            print(notice)
        _warn_if_unchecked(version)
        return 0
    # A rules file this user cannot open, by its owner and mode one the recorder cannot read
    # either (the system user's 0600): root would only say so, or refuse it with other work to do.
    unread = installer.unreadable_notice(SYSTEM, installer.current_reader())
    if unread is not None and installer.rules_state(SYSTEM, wanted) == "unknown":
        if bad - {"rules"}:
            raise InstallError(f"{unread}; nothing was changed")
        print("already installed and intact; nothing changed")
        print(unread)
        _warn_if_unchecked(version)
        return 0
    # A damaged default, or a link or folder at the rules path, stops before the password.
    installer.check_packaged_default(SYSTEM, current)
    packages.ensure_confirmed(current)
    print("AgentFly will ask for your password once, to write into /Library/Application Support.")
    if "python" not in bad:
        # The bundled Python is intact: no need to fetch it again, and root runs on it.
        return elevate.run_elevated(
            ["init", "-g"], stdin=subprocess.DEVNULL, python=SYSTEM.interpreter
        )
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / build.name
        print(f"downloading {build.name} ...")
        pythons.download(build, archive)  # checked against the pinned SHA-256
        with archive.open("rb") as handle:
            # No intact bundled Python to trust (a first install, or a new pin): root runs on the
            # tool environment's base interpreter.
            return elevate.run_elevated(["init", "-g"], stdin=handle)


def run(args: argparse.Namespace) -> int:
    if not args.system:
        print(
            "agentfly init: only `agentfly init -g` exists in this version "
            "(per-project init comes later)",
            file=sys.stderr,
        )
        return 2
    try:
        version = cursor.check(SYSTEM.cursor_app)
        build = pythons.select_build()
        return _as_root(version, build) if os.geteuid() == 0 else _as_user(version, build)
    except InstallError as exc:
        print(f"agentfly init: {exc}", file=sys.stderr)
        return 1

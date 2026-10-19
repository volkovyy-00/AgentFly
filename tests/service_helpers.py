"""Stub `launchctl` and `brew` for the service tests: real executables, state in a JSON file.

The service code runs them as subprocesses exactly as it runs the real tools, so the argument lists
it builds are what the stubs see. `tests/conftest.py` points every test at a fresh stub
launchctl, so no test can load a job into the real launchd.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

LAUNCHCTL_STUB = Path(__file__).with_name("launchctl_stub.py")
BREW_STUB = Path(__file__).with_name("brew_stub.py")


class Stub:
    """An executable at `path` that runs `script` on a JSON state file kept beside it."""

    def __init__(self, directory: Path, name: str, script: Path, state: dict[str, Any]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.state_path = directory / f"{name}.json"
        self.state_path.write_text(json.dumps({"calls": [], **state}), encoding="utf-8")
        self.path = directory / name
        self.path.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "{self.state_path}" "$@"\n',
            encoding="utf-8",
        )
        self.path.chmod(0o755)

    def state(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.state_path.read_text(encoding="utf-8"))
        return data

    def update(self, **values: Any) -> None:
        self.state_path.write_text(json.dumps({**self.state(), **values}), encoding="utf-8")

    def calls(self) -> list[list[str]]:
        calls: list[list[str]] = self.state()["calls"]
        return calls

    def verbs(self) -> list[str]:
        """The first word of every call, in order (`enable`, `bootstrap`, ...)."""
        return [call[0] for call in self.calls() if call]

    def forget_calls(self) -> None:
        self.update(calls=[])


class Launchd(Stub):
    def __init__(self, directory: Path) -> None:
        super().__init__(
            directory,
            "launchctl",
            LAUNCHCTL_STUB,
            {
                "jobs": {},
                "next_pid": 4000,
                "start_ok": True,
                "bootout_lag": 0,
                "bootout_code": 0,
                "bootstrap_code": 0,
                "disabled": [],
            },
        )

    def loaded(self) -> list[str]:
        jobs: dict[str, Any] = self.state()["jobs"]
        return sorted(jobs)

    def stop_job(self, label: str) -> None:
        """The job stays loaded but its process is gone (a crash, before launchd restarts it)."""
        jobs = self.state()["jobs"]
        jobs[label]["pid"] = None
        self.update(jobs=jobs)


class Brew(Stub):
    def __init__(self, prefix: Path, home: Path) -> None:
        plist = home / "Library" / "LaunchAgents" / "sh.brew.agentfly.plist"
        super().__init__(
            prefix / "bin",
            "brew",
            BREW_STUB,
            {"started": False, "keepalive": True, "plist": str(plist)},
        )
        self.plist = plist


def homebrew_package(prefix: Path) -> Path:
    """A fake keg: `<prefix>/Cellar/agentfly/0.1.0/libexec/.../agentfly/__init__.py`."""
    package = (
        prefix
        / "Cellar"
        / "agentfly"
        / "0.1.0"
        / "libexec"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "agentfly"
    )
    package.mkdir(parents=True)
    init = package / "__init__.py"
    init.write_text("", encoding="utf-8")
    return init

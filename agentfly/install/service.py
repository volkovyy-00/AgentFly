"""The recorder as a launchd service: `agentfly start`, `stop`, `status` (SPEC section 7, D4, D8).

A Homebrew install hands all of it to `brew services`. Any other install writes its own LaunchAgent
into ~/Library/LaunchAgents and loads it into the user's `gui/<uid>` domain. Both set `KeepAlive`,
so launchd brings a killed recorder back; the offline guard (SPEC section 9) covers the seconds it
is down. `stop` unloads the job and deletes the file, as `brew services stop` does, so a stopped
recorder stays down at the next login too.

Where the tools and files are is fixed in this module; nothing is read from the user's settings (D25
for the port). Every outside call goes through `_run`; tests point `LAUNCHCTL` and `PACKAGE_FILE`
at stub executables.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import plistlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.parsers.expat import ExpatError

import agentfly
from agentfly.install import InstallError
from agentfly.install.installer import describe_oserror
from agentfly.recorder import DEFAULT_PORT
from agentfly.recorder.paths import data_dir, private_dir

LABEL: str = "dev.agentfly.recorder"
BREW_FORMULA: str = "agentfly"
# Homebrew 7 names a formula's launchd job `sh.brew.<name>`; `homebrew.mxcl.<name>` is its old name.
BREW_LABELS: tuple[str, ...] = ("sh.brew.agentfly", "homebrew.mxcl.agentfly")
LAUNCHCTL: str = "/bin/launchctl"
PACKAGE_FILE: Path = Path(agentfly.__file__)
HEALTH_PORT: int = DEFAULT_PORT
POLL_INTERVAL: float = 0.25
UNLOAD_TIMEOUT: float = 10.0
START_TIMEOUT: float = 10.0
# `bootout` of a job that is gone exits 3; 36 and 37 are "teardown in progress" (Homebrew loops on
# them too); `print` of a job that is not loaded exits 113 (3 on some releases).
_BOOTOUT_OK: frozenset[int] = frozenset({0, 3, 36, 37})
_NOT_LOADED: frozenset[int] = frozenset({3, 113})


@dataclass(frozen=True)
class Manager:
    """Who runs the recorder: `brew services` when `brew` is set, else our own LaunchAgent."""

    brew: Path | None = None

    @property
    def name(self) -> str:
        return "brew services" if self.brew else "launchd LaunchAgent"

    @property
    def label(self) -> str:
        return f"brew services {BREW_FORMULA}" if self.brew else LABEL


@dataclass(frozen=True)
class State:
    manager: Manager
    plist_path: Path | None  # the service file that exists, if any
    plist: dict[str, Any] | None  # its content, None when missing or unreadable
    loaded: bool
    running: bool
    pid: int | None
    live_keepalive: bool | None  # what launchd says about the loaded job; None when unknown
    agent_loaded: bool = False  # Homebrew install only: a LaunchAgent of ours is loaded as well

    @property
    def keepalive(self) -> bool:
        """`KeepAlive` is set in the service file (D4)."""
        return bool(self.plist and self.plist.get("KeepAlive"))

    @property
    def summary(self) -> str:
        if self.running:
            text = f"running, pid {self.pid}" if self.pid else "running"
        elif self.loaded:
            text = "loaded, not running"
        elif self.plist_path is not None:
            text = "not loaded (a service file exists)"
        else:
            text = "stopped (not installed)"
        return f"{text}; {LABEL} is loaded too" if self.agent_loaded else text


# ---------------------------------------------------------------- where things are


def plist_path(label: str = LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def log_path() -> Path:
    return data_dir() / "logs" / "recorder.log"


def detect_manager(package_file: Path | None = None) -> Manager:
    """Homebrew when AgentFly's package lives in `<prefix>/Cellar/agentfly/` next to `bin/brew`."""
    parts = (package_file or PACKAGE_FILE).resolve().parts
    for index in range(len(parts) - 2):
        if parts[index] == "Cellar" and parts[index + 1] == BREW_FORMULA:
            brew = Path(*parts[:index]) / "bin" / "brew"
            if brew.is_file():
                return Manager(brew=brew)
    return Manager()


def expected_plist() -> dict[str, Any]:
    """The service file `start` writes: `serve` from this install, restarted whenever it dies."""
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-I", "-m", "agentfly.cli", "serve"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 5,
        # uvicorn writes its access log (a line per hook) to stdout and its errors to stderr.
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": str(log_path()),
    }


def plist_drift(actual: dict[str, Any] | None) -> list[str]:
    """The keys in which a service file differs from what `start` writes (all of them if none)."""
    wanted, actual = expected_plist(), actual or {}
    return sorted(
        key for key in wanted.keys() | actual.keys() if wanted.get(key) != actual.get(key)
    )


# ---------------------------------------------------------------- running the tools


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(f"cannot run {argv[0]} ({type(exc).__name__})") from exc


def _tail(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no message"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _target() -> str:
    return f"{_domain()}/{LABEL}"


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return _run([LAUNCHCTL, *args])


def _fail(verb: str, result: subprocess.CompletedProcess[str]) -> InstallError:
    return InstallError(f"launchctl {verb} failed ({result.returncode}): {_tail(result.stderr)}")


def _launchctl_ok(*args: str) -> None:
    result = _launchctl(*args)
    if result.returncode != 0:
        raise _fail(args[0], result)


def _print_job() -> str | None:
    """`launchctl print` of our job: its text, or None when launchd does not have it loaded."""
    result = _launchctl("print", _target())
    if result.returncode in _NOT_LOADED:
        return None
    if result.returncode != 0:
        raise _fail("print", result)
    return result.stdout


def _require_user(verb: str) -> None:
    if os.geteuid() == 0:
        raise InstallError(
            f"run `agentfly {verb}` as your own user, not with sudo: "
            "the service belongs to your login session"
        )


# ---------------------------------------------------------------- reading the state


def read_plist(path: Path) -> dict[str, Any] | None:
    """The file as data (XML or binary, `defaults write` makes either), or None."""
    try:
        data = plistlib.loads(path.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException, ExpatError):
        return None
    return data if isinstance(data, dict) else None


def inspect() -> State:
    manager = detect_manager()
    return _inspect_brew(manager) if manager.brew else _inspect_agent()


def _existing(path: Path) -> Path | None:
    return path if path.exists() or path.is_symlink() else None


def _inspect_agent() -> State:
    manager, path = Manager(), plist_path()
    plist = read_plist(path)
    out = _print_job()
    if out is None:
        return State(manager, _existing(path), plist, False, False, None, None)
    pid = re.search(r"^\s*pid = (\d+)\s*$", out, re.MULTILINE)
    running = re.search(r"^\s*state = running\s*$", out, re.MULTILINE) is not None
    properties = re.search(r"^\s*properties = (.*)$", out, re.MULTILINE)
    live = "keepalive" in properties[1].split(" | ") if properties else None
    return State(manager, _existing(path), plist, True, running, int(pid[1]) if pid else None, live)


def _inspect_brew(manager: Manager) -> State:
    assert manager.brew is not None
    result = _run([str(manager.brew), "services", "info", BREW_FORMULA, "--json"])
    if result.returncode != 0:
        raise InstallError(f"brew services info {BREW_FORMULA} failed: {_tail(result.stderr)}")
    try:
        info = json.loads(result.stdout)[0]
        loaded_file = info.get("loaded_file")
        pid = info.get("pid")
        loaded, running = bool(info["loaded"]), bool(info["running"])
    except (ValueError, IndexError, KeyError, TypeError, AttributeError) as exc:
        raise InstallError("cannot read the output of `brew services info --json`") from exc
    path = Path(loaded_file) if isinstance(loaded_file, str) else None
    if path is None:  # stopped: a file left behind under either of Homebrew's names
        path = next((p for p in map(plist_path, BREW_LABELS) if _existing(p)), None)
    plist = read_plist(path) if path else None
    return State(
        manager,
        path,
        plist,
        loaded,
        running,
        pid if isinstance(pid, int) else None,
        None,
        agent_loaded=_print_job() is not None,
    )


def health(timeout: float = 2.0) -> dict[str, Any] | None:
    """What `GET /health` answers on the hooks' port (D25), or None when nothing sensible does."""
    connection = http.client.HTTPConnection("127.0.0.1", HEALTH_PORT, timeout=timeout)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        if response.status != 200:
            return None
        data = json.loads(response.read(65536))
    except (OSError, http.client.HTTPException, ValueError):
        return None
    finally:
        connection.close()
    return data if isinstance(data, dict) else None


def wait_for_health(timeout: float | None = None) -> dict[str, Any] | None:
    deadline = time.monotonic() + (START_TIMEOUT if timeout is None else timeout)
    while True:
        answer = health()
        if answer is not None or time.monotonic() >= deadline:
            return answer
        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------- start


def start() -> list[str]:
    _require_user("start")
    manager = detect_manager()
    if manager.brew:
        return _retire_agent() + _brew_services(manager, "start")
    state = _inspect_agent()
    # A job loaded without KeepAlive although its file has it is what `doctor` warns about.
    if state.loaded and not plist_drift(state.plist) and state.live_keepalive is not False:
        if state.running:
            return [f"already running (pid {state.pid})"]
        _launchctl_ok("kickstart", _target())
        return [f"{LABEL} was loaded but not running; started it"]
    messages: list[str] = []
    if not state.loaded and health() is not None:
        messages.append(
            f"warning: something already answers on 127.0.0.1:{HEALTH_PORT} (a recorder started "
            "by hand?); stop it, or the service will fail to bind the port and restart in a loop"
        )
    if state.loaded:
        _unload()
        messages.append("the loaded job differs from its service file; reloaded it")
    _write_plist(plist_path(), expected_plist())
    _enable_if_disabled()
    _launchctl_ok("bootstrap", _domain(), str(plist_path()))
    messages.append(f"loaded {LABEL} (restarts itself, starts at login)")
    return messages


def _enable_if_disabled() -> None:
    """A label switched off (Login Items) cannot be loaded. `enable` writes launchd's override
    database for good, with no way to take the entry out again, so it runs only when needed."""
    result = _launchctl("print-disabled", _domain())
    if result.returncode == 0 and re.search(
        rf'"{re.escape(LABEL)}"\s*=>\s*disabled', result.stdout
    ):
        _launchctl("enable", _target())


def _write_plist(path: Path, data: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        private_dir(log_path().parent)  # launchd opens the log file but does not make its folder
        temp.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_XML))
        os.chmod(temp, 0o644)  # launchd refuses a plist others can write
        os.replace(temp, path)
    except OSError as exc:
        raise InstallError(f"cannot write {path} ({describe_oserror(exc)})") from exc
    finally:
        with contextlib.suppress(OSError):  # best effort: the error above is the one to report
            temp.unlink(missing_ok=True)


def _brew_services(manager: Manager, verb: str) -> list[str]:
    assert manager.brew is not None
    result = _run([str(manager.brew), "services", verb, BREW_FORMULA])
    if result.returncode != 0:
        raise InstallError(f"brew services {verb} {BREW_FORMULA} failed: {_tail(result.stderr)}")
    return [f"brew services {verb} {BREW_FORMULA}: {_tail(result.stdout)}"]


# ---------------------------------------------------------------- stop and remove


def _unload() -> None:
    """`bootout`, then wait until launchd really has let go: the teardown is not instant."""
    result = _launchctl("bootout", _target())
    if result.returncode not in _BOOTOUT_OK:
        raise _fail("bootout", result)
    deadline = time.monotonic() + UNLOAD_TIMEOUT
    while _print_job() is not None:
        if time.monotonic() >= deadline:
            raise InstallError(
                f"launchd still has {LABEL} loaded after {UNLOAD_TIMEOUT:g} s; run it again"
            )
        time.sleep(POLL_INTERVAL)


def _remove_file(path: Path) -> list[str]:
    if not _existing(path):
        return []
    try:
        path.unlink()
    except OSError as exc:
        raise InstallError(f"cannot remove {path} ({describe_oserror(exc)})") from exc
    return [f"removed {path}"]


def _teardown_agent() -> list[str]:
    """Unload our own job and delete its file; an empty list means there was nothing to do."""
    messages: list[str] = []
    if _print_job() is not None:
        _unload()
        messages.append(f"unloaded {LABEL}")
    return messages + _remove_file(plist_path())


def _retire_agent() -> list[str]:
    """Homebrew's service takes over from a LaunchAgent of ours (an earlier install's `start`).

    Two KeepAlive jobs on one port would fight: the older recorder keeps the port and answers, and
    the other restarts in a loop."""
    messages = _teardown_agent()
    if not messages:
        return []
    return [
        "replacing the LaunchAgent of an earlier install (two recorders cannot share the port):",
        *messages,
    ]


def _teardown_brew(manager: Manager) -> list[str]:
    messages: list[str] = []
    state = _inspect_brew(manager)
    if state.loaded or state.plist_path is not None:
        messages += _brew_services(manager, "stop")
    for label in BREW_LABELS:  # `brew uninstall` leaves these behind (D8)
        messages += _remove_file(plist_path(label))
    return messages


def stop() -> list[str]:
    _require_user("stop")
    manager = detect_manager()
    messages = _teardown_brew(manager) if manager.brew else _teardown_agent()
    return messages or ["already stopped"]


def remove() -> list[str]:
    """What `uninstall` runs: stop everything of ours, whichever way it was started."""
    _require_user("uninstall")
    manager = detect_manager()
    messages = _teardown_agent()
    if manager.brew:
        messages += _teardown_brew(manager)
    return messages

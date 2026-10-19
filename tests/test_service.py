"""`agentfly start`, `stop` and `status`: the LaunchAgent, `brew services`, and the CLI around them.

Every test runs against a stub `launchctl` (tests/conftest.py), so none can reach the real launchd.
"""

from __future__ import annotations

import os
import plistlib
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from agentfly.cli import main
from agentfly.install import InstallError, service
from tests.service_helpers import Brew, Launchd, homebrew_package

LABEL = service.LABEL


def plist_file(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_on_disk(home: Path) -> dict[str, Any]:
    data: dict[str, Any] = plistlib.loads(plist_file(home).read_bytes())
    return data


@pytest.fixture
def healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recorder answers `/health` (the commands wait for that after starting it)."""
    monkeypatch.setattr(service, "health", lambda timeout=2.0: {"ok": True})


@pytest.fixture
def brewed(tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Brew:
    """AgentFly installed in a fake Homebrew keg, with a stub `brew` next to it."""
    prefix = tmp_path / "homebrew"
    brew = Brew(prefix, isolated_home)
    monkeypatch.setattr(service, "PACKAGE_FILE", homebrew_package(prefix))
    return brew


# ---------------------------------------------------------------- which manager


def test_a_normal_install_uses_its_own_launch_agent() -> None:
    assert service.detect_manager().brew is None


def test_a_package_inside_a_homebrew_keg_uses_brew_services(tmp_path: Path) -> None:
    prefix = tmp_path / "homebrew"
    Brew(prefix, tmp_path)
    manager = service.detect_manager(homebrew_package(prefix))
    assert manager.brew == (prefix / "bin" / "brew").resolve()


def test_a_cellar_path_without_a_brew_next_to_it_is_not_homebrew(tmp_path: Path) -> None:
    assert service.detect_manager(homebrew_package(tmp_path / "elsewhere")).brew is None


# ---------------------------------------------------------------- start (own LaunchAgent)


def test_start_writes_a_keepalive_plist_and_loads_it(isolated_home: Path, launchd: Launchd) -> None:
    messages = service.start()
    plist = plist_on_disk(isolated_home)
    assert plist["Label"] == LABEL
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True
    assert plist["ProgramArguments"] == [sys.executable, "-I", "-m", "agentfly.cli", "serve"]
    assert plist["StandardOutPath"] == "/dev/null"  # the access log is one line per hook
    assert plist["StandardErrorPath"].endswith(".local/share/agentfly/logs/recorder.log")
    assert stat.S_IMODE(plist_file(isolated_home).stat().st_mode) == 0o644
    assert launchd.verbs() == ["print", "enable", "bootstrap"]
    assert launchd.loaded() == [LABEL]
    assert any("loaded" in line for line in messages)


def test_the_service_log_folder_is_private(isolated_home: Path) -> None:
    service.start()
    logs = isolated_home / ".local" / "share" / "agentfly" / "logs"
    assert stat.S_IMODE(logs.stat().st_mode) == 0o700


def test_start_on_a_running_service_changes_nothing(isolated_home: Path, launchd: Launchd) -> None:
    service.start()
    before = plist_file(isolated_home).read_bytes()
    launchd.forget_calls()
    messages = service.start()
    assert launchd.verbs() == ["print"]
    assert plist_file(isolated_home).read_bytes() == before
    assert "already running" in messages[0]


def test_start_with_a_changed_plist_reloads_it(isolated_home: Path, launchd: Launchd) -> None:
    service.start()
    path = plist_file(isolated_home)
    path.write_bytes(plistlib.dumps({**plist_on_disk(isolated_home), "KeepAlive": False}))
    launchd.forget_calls()
    service.start()
    assert launchd.verbs()[:2] == ["print", "bootout"]
    assert launchd.verbs()[-2:] == ["enable", "bootstrap"]
    assert plist_on_disk(isolated_home)["KeepAlive"] is True
    assert launchd.loaded() == [LABEL]


def test_start_waits_while_launchd_tears_the_old_job_down(
    isolated_home: Path, launchd: Launchd
) -> None:
    service.start()
    path = plist_file(isolated_home)
    path.write_bytes(plistlib.dumps({**plist_on_disk(isolated_home), "ThrottleInterval": 9}))
    launchd.update(bootout_lag=3, bootout_code=36)  # `bootout` says "in progress" first
    service.start()  # a bootstrap before the teardown ends would fail with "5: Input/output error"
    assert launchd.loaded() == [LABEL]
    assert plist_on_disk(isolated_home)["ThrottleInterval"] == 5


def test_start_on_a_loaded_job_without_a_process_kickstarts_it(launchd: Launchd) -> None:
    service.start()
    launchd.stop_job(LABEL)
    launchd.forget_calls()
    service.start()
    assert launchd.verbs() == ["print", "kickstart"]
    assert launchd.state()["jobs"][LABEL]["pid"]


def test_start_warns_when_something_else_already_answers_on_the_port(
    monkeypatch: pytest.MonkeyPatch, launchd: Launchd
) -> None:
    monkeypatch.setattr(service, "health", lambda timeout=2.0: {"ok": True})
    messages = service.start()
    port = str(service.HEALTH_PORT)
    assert any("already answers" in line and port in line for line in messages)
    assert launchd.loaded() == [LABEL]  # it still loads the service


def test_start_reports_a_bootstrap_failure_with_launchds_code(launchd: Launchd) -> None:
    launchd.update(bootstrap_code=5)
    with pytest.raises(InstallError) as caught:
        service.start()
    assert "launchctl bootstrap failed (5)" in str(caught.value)


@pytest.mark.parametrize("verb", ["start", "stop"])
def test_start_and_stop_refuse_to_run_as_root(
    verb: str, monkeypatch: pytest.MonkeyPatch, launchd: Launchd
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(InstallError, match="not with sudo"):
        getattr(service, verb)()
    assert launchd.calls() == []


# ---------------------------------------------------------------- stop


def test_stop_unloads_the_job_and_removes_the_plist(isolated_home: Path, launchd: Launchd) -> None:
    service.start()
    messages = service.stop()
    assert launchd.loaded() == []
    assert not plist_file(isolated_home).exists()  # so it stays down at the next login too
    assert any("unloaded" in line for line in messages)


def test_stop_waits_until_launchd_has_finished_the_teardown(
    isolated_home: Path, launchd: Launchd
) -> None:
    service.start()
    launchd.update(bootout_lag=4)
    service.stop()
    assert launchd.loaded() == []  # `launchctl list | grep agentfly` is empty right away
    assert not plist_file(isolated_home).exists()
    assert launchd.verbs().count("print") >= 4


def test_stop_gives_up_and_keeps_the_plist_if_launchd_never_lets_go(
    isolated_home: Path, launchd: Launchd, monkeypatch: pytest.MonkeyPatch
) -> None:
    service.start()
    launchd.update(bootout_lag=10_000)
    monkeypatch.setattr(service, "UNLOAD_TIMEOUT", 0.05)
    with pytest.raises(InstallError, match="still has"):
        service.stop()
    assert plist_file(isolated_home).exists()  # nothing is half-removed


def test_stop_when_nothing_runs_says_so(launchd: Launchd) -> None:
    assert service.stop() == ["already stopped"]
    assert launchd.verbs() == ["print"]


def test_stop_removes_a_plist_that_was_never_loaded(isolated_home: Path) -> None:
    path = plist_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(plistlib.dumps(service.expected_plist()))
    service.stop()
    assert not path.exists()


# ---------------------------------------------------------------- inspect


def test_inspect_reports_every_state(launchd: Launchd) -> None:
    state = service.inspect()
    assert (state.loaded, state.running, state.plist_path) == (False, False, None)
    assert state.summary == "stopped (not installed)"

    service.start()
    state = service.inspect()
    assert (state.loaded, state.running) == (True, True)
    assert (state.keepalive, state.live_keepalive, state.program_exists) == (True, True, True)
    assert state.pid and state.summary == f"running, pid {state.pid}"

    launchd.stop_job(LABEL)
    state = service.inspect()
    assert (state.loaded, state.running, state.pid) == (True, False, None)
    assert state.summary == "loaded, not running"

    launchd.update(jobs={})  # the plist is on disk but launchd does not have it
    state = service.inspect()
    assert (state.loaded, state.plist_path is not None) == (False, True)
    assert state.summary == "not loaded (a service file exists)"


def test_inspect_turns_a_launchctl_failure_into_an_error(launchd: Launchd) -> None:
    launchd.path.write_text("#!/bin/sh\necho 'boom' >&2\nexit 125\n", encoding="utf-8")
    with pytest.raises(InstallError, match="125"):
        service.inspect()


def test_a_missing_launchctl_is_an_error_not_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "LAUNCHCTL", "/nonexistent/launchctl")
    with pytest.raises(InstallError, match="cannot run"):
        service.inspect()


# ---------------------------------------------------------------- health


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status, self._body = status, body

    def read(self, amount: int = -1) -> bytes:
        return self._body


class FakeConnection:
    def __init__(self, response: FakeResponse | OSError) -> None:
        self.response = response

    def request(self, method: str, path: str) -> None:
        assert (method, path) == ("GET", "/health")

    def getresponse(self) -> FakeResponse:
        if isinstance(self.response, OSError):
            raise self.response
        return self.response

    def close(self) -> None:
        pass


def test_health_reads_the_recorders_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int]] = []

    def connect(host: str, port: int, timeout: float) -> FakeConnection:
        seen.append((host, port))
        return FakeConnection(FakeResponse(200, b'{"ok": true, "offline_guard_count": 3}'))

    monkeypatch.setattr(service, "HEALTH_PORT", 8787)
    monkeypatch.setattr(service.http.client, "HTTPConnection", connect)
    assert service.health() == {"ok": True, "offline_guard_count": 3}
    assert seen == [("127.0.0.1", 8787)]  # the hooks' port (D25), not a variable


@pytest.mark.parametrize(
    "response",
    [
        OSError("refused"),
        FakeResponse(500, b"{}"),
        FakeResponse(200, b"not json"),
        FakeResponse(200, b"[]"),
    ],
)
def test_health_is_none_when_nothing_sensible_answers(
    monkeypatch: pytest.MonkeyPatch, response: FakeResponse | OSError
) -> None:
    monkeypatch.setattr(
        service.http.client, "HTTPConnection", lambda *a, **k: FakeConnection(response)
    )
    assert service.health() is None


def test_wait_for_health_returns_as_soon_as_it_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([None, None, {"ok": True}])
    monkeypatch.setattr(service, "health", lambda timeout=2.0: next(answers))
    assert service.wait_for_health(5.0) == {"ok": True}


# ---------------------------------------------------------------- Homebrew


def test_a_homebrew_install_starts_and_stops_through_brew_services(
    brewed: Brew, launchd: Launchd, isolated_home: Path
) -> None:
    service.start()
    service.stop()
    assert brewed.calls() == [
        ["services", "start", "agentfly"],
        ["services", "info", "agentfly", "--json"],
        ["services", "stop", "agentfly"],
    ]
    assert launchd.calls() == []  # no LaunchAgent of ours
    assert not plist_file(isolated_home).exists()


def test_a_homebrew_status_comes_from_brew_services_info(brewed: Brew) -> None:
    assert service.inspect().summary == "stopped (not installed)"
    service.start()
    state = service.inspect()
    assert (state.loaded, state.running, state.pid) == (True, True, 4242)
    assert state.plist_path == brewed.plist and state.keepalive  # read from `loaded_file`
    assert state.live_keepalive is None  # nothing to cross-check against


def test_a_failing_brew_is_one_line(brewed: Brew) -> None:
    brewed.path.write_text("#!/bin/sh\necho 'no such formula' >&2\nexit 1\n", encoding="utf-8")
    with pytest.raises(InstallError, match="no such formula"):
        service.start()


def test_remove_in_a_homebrew_install_stops_it_and_clears_the_leftover_plists(
    brewed: Brew, isolated_home: Path
) -> None:
    service.start()
    leftover = isolated_home / "Library" / "LaunchAgents" / "homebrew.mxcl.agentfly.plist"
    leftover.write_bytes(plistlib.dumps({"Label": "homebrew.mxcl.agentfly"}))
    assert service.remove()
    assert ["services", "stop", "agentfly"] in brewed.calls()
    assert not leftover.exists() and not brewed.plist.exists()


# ---------------------------------------------------------------- remove (used by uninstall)


def test_remove_with_nothing_installed_is_silent(launchd: Launchd) -> None:
    assert service.remove() == []


def test_remove_stops_and_deletes_our_service(isolated_home: Path, launchd: Launchd) -> None:
    service.start()
    assert service.remove()
    assert launchd.loaded() == [] and not plist_file(isolated_home).exists()
    assert service.remove() == []


# ---------------------------------------------------------------- the commands


def test_the_start_command_says_when_the_recorder_answers(
    capsys: pytest.CaptureFixture[str], healthy: None
) -> None:
    assert main(["start"]) == 0
    assert f"recorder answers on 127.0.0.1:{service.HEALTH_PORT}" in capsys.readouterr().out


def test_the_start_command_fails_loudly_when_nothing_answers(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "wait_for_health", lambda timeout=10.0: None)
    assert main(["start"]) == 1
    err = capsys.readouterr().err
    assert "did not answer" in err and "recorder.log" in err


def test_the_start_command_prints_a_refusal_as_one_line(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert main(["start"]) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith("agentfly start:") and len(err.splitlines()) == 1


def test_the_stop_command(capsys: pytest.CaptureFixture[str], healthy: None) -> None:
    main(["start"])
    capsys.readouterr()
    assert main(["stop"]) == 0
    assert "unloaded" in capsys.readouterr().out
    assert main(["stop"]) == 0
    assert "already stopped" in capsys.readouterr().out


def test_the_status_command_in_each_state(
    capsys: pytest.CaptureFixture[str], launchd: Launchd, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer: list[dict[str, Any] | None] = [None]
    monkeypatch.setattr(service, "health", lambda timeout=2.0: answer[0])

    assert main(["status"]) == 1  # not installed, no recorder
    out = capsys.readouterr().out
    assert "launchd LaunchAgent" in out and LABEL in out
    port = f"127.0.0.1:{service.HEALTH_PORT}"
    assert "stopped (not installed)" in out and f"no answer on {port}" in out
    assert "agentfly start" in out

    answer[0] = {"ok": True}
    main(["start"])
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "running, pid" in out and f"answers on {port}" in out

    launchd.stop_job(LABEL)
    answer[0] = None
    assert main(["status"]) == 1
    assert "loaded, not running" in capsys.readouterr().out

    answer[0] = {"ok": True}  # something answers, but not through our service
    launchd.update(jobs={})
    assert main(["status"]) == 0
    assert "not through the service" in capsys.readouterr().out


def test_the_status_command_names_brew_services_for_a_homebrew_install(
    brewed: Brew, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 1
    out = capsys.readouterr().out
    assert "brew services" in out and "agentfly" in out

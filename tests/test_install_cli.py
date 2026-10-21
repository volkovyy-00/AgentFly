"""`agentfly init -g` and `agentfly uninstall` as commands: arguments, sudo, fixed paths."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import IO

import pytest

from agentfly.cli import build_parser, init, main, uninstall
from agentfly.install import (
    InstallError,
    elevate,
    installer,
    packages,
    pythons,
    records,
    service,
)
from agentfly.install.layout import SYSTEM, Layout
from agentfly.recorder import rulefile
from tests.helpers import REPO
from tests.install_helpers import (
    DIRECT_URL_KINDS,
    MODULE,
    NEW_AGENTFLY,
    REBUILDS,
    TOOL_DISTS,
    call_unless_it_hangs,
    fake_python_tar,
    install_system,
    make_cursor_app,
    make_layout,
    plant_direct_url,
    upgrade,
    write_archive,
)
from tests.service_helpers import Launchd
from tests.test_install_packages import (
    BAD,
    REAL_TOOL_ENVIRONMENT,
    SHOWN,
    assert_plain,
    fake_agentfly,
)


def test_the_system_paths_are_the_ones_in_the_spec() -> None:
    assert str(SYSTEM.system_root) == "/Library/Application Support/AgentFly"
    assert str(SYSTEM.hooks_file) == "/Library/Application Support/Cursor/hooks.json"
    assert str(SYSTEM.cursor_app) == "/Applications/Cursor.app"


def test_no_flag_or_variable_can_move_the_system_paths() -> None:
    parser = build_parser()
    commands = next(a for a in parser._actions if hasattr(a, "choices") and a.choices)
    for name in ("init", "uninstall"):
        options = {s for a in commands.choices[name]._actions for s in a.option_strings}
        assert options <= {"-h", "--help", "-g", "--global"}, options
    for source in (REPO / "agentfly" / "install").glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"\benviron\b|getenv", text), source.name
    init_text = (REPO / "agentfly/cli/init.py").read_text(encoding="utf-8")
    assert init_text.count("os.environ") == 2  # SUDO_UID and SUDO_GID, to try the hook as the user
    assert not re.search(
        r"\benviron\b|getenv", (REPO / "agentfly/cli/uninstall.py").read_text(encoding="utf-8")
    )


def test_init_without_g_says_so_and_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init"]) == 2
    assert "init -g" in capsys.readouterr().err


@pytest.fixture
def system(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Layout:
    """The CLI modules pointed at a temporary root (a test patch; the CLI has no flag)."""
    layout = make_layout(tmp_path)
    make_cursor_app(layout)
    monkeypatch.setattr(init, "SYSTEM", layout)
    monkeypatch.setattr(uninstall, "SYSTEM", layout)
    return layout


def test_init_as_a_user_downloads_then_pipes_the_archive_to_sudo(
    system: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = fake_python_tar()
    _, build = write_archive(tmp_path / "unused", data)
    seen: dict[str, object] = {}

    def fake_download(wanted: pythons.PythonBuild, target: Path) -> None:
        target.write_bytes(data)

    def fake_sudo(tail: list[str], stdin: IO[bytes] | None = None, **kwargs: object) -> int:
        assert stdin is not None
        seen.update(tail=tail, body=stdin.read())
        return 0

    monkeypatch.setattr(pythons, "download", fake_download)
    monkeypatch.setattr(pythons, "select_build", lambda *a: build)
    monkeypatch.setattr(elevate, "run_elevated", fake_sudo)
    assert main(["init", "-g"]) == 0
    assert seen == {"tail": ["init", "-g"], "body": data}


def test_init_as_a_user_on_an_intact_install_asks_for_no_password(
    system: Layout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    installer.install(
        system, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )
    monkeypatch.setattr(pythons, "select_build", lambda *a: build)
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert main(["init", "-g"]) == 0
    assert "already installed" in capsys.readouterr().out


def test_init_refuses_an_unknown_cursor_before_asking_for_a_password(
    system: Layout, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.rmtree(system.cursor_app)
    make_cursor_app(system, "1.0.0")
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert main(["init", "-g"]) == 1
    err = capsys.readouterr().err
    assert "Cursor 1.0.0" in err and "nothing was written" in err
    assert not system.system_root.exists()


def test_init_as_root_installs_from_the_piped_archive(
    system: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    monkeypatch.setattr(init, "_stdin_archive", lambda: path)
    assert init._as_root("3.24.12", build) == 0
    assert system.interpreter.is_file() and system.hooks_file.is_file()


def test_uninstall_with_nothing_installed_asks_for_no_password(
    system: Layout, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert main(["uninstall"]) == 0
    assert "nothing of AgentFly's is installed" in capsys.readouterr().out


def test_uninstall_as_a_user_runs_itself_under_sudo(
    system: Layout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    installer.install(
        system, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        elevate, "run_elevated", lambda tail, stdin=None, **kw: calls.append(tail) or 0
    )
    assert main(["uninstall"]) == 0
    assert calls == [["uninstall"]]
    assert uninstall.RESTART_HINT in capsys.readouterr().out


def test_init_repairing_only_the_client_does_not_download_the_python_again(
    system: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    installer.install(
        system, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )
    system.client.write_text("tampered\n")
    calls: list[tuple[list[str], object]] = []
    monkeypatch.setattr(pythons, "select_build", lambda *a: build)
    monkeypatch.setattr(pythons, "download", lambda *a: pytest.fail("downloaded the Python"))
    monkeypatch.setattr(
        elevate, "run_elevated", lambda tail, stdin=None, **kw: calls.append((tail, stdin)) or 0
    )
    assert main(["init", "-g"]) == 0
    assert calls == [(["init", "-g"], subprocess.DEVNULL)]


def test_a_filesystem_error_during_uninstall_is_one_line_and_a_failure(
    system: Layout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    installer.install(
        system, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )

    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError(1, "Operation not permitted", str(system.system_root))

    monkeypatch.setattr(uninstall.os, "geteuid", lambda: 0)  # take the root branch, no sudo
    monkeypatch.setattr(shutil, "rmtree", refuse)
    assert main(["uninstall"]) == 1
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1 and err.startswith("agentfly uninstall:")
    assert "Operation not permitted" in err and "Traceback" not in err


def test_an_oserror_that_escapes_the_installer_is_still_one_line(
    system: Layout, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(layout: Layout) -> bool:
        raise OSError(13, "Permission denied", "/Library/Application Support/AgentFly")

    monkeypatch.setattr(installer, "is_installed", broken)
    assert main(["uninstall"]) == 1
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1 and "Permission denied" in err and "Traceback" not in err


# ---------------------------------------------------------------- the service goes too (V3b)


def install_and_start(system: Layout, tmp_path: Path) -> None:
    install_system(system, tmp_path)
    service.start()


def uninstall_through_a_fake_sudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the sudo: the child is the real root path, as `-I -S` Python runs it."""

    def fake_sudo(tail: list[str], stdin: IO[bytes] | None = None, **kwargs: object) -> int:
        with monkeypatch.context() as child:  # only while it runs: the parent is the user's
            child.setattr(uninstall.os, "geteuid", lambda: 0)
            child.setattr(uninstall, "_elevated_child", lambda: True)
            return main(tail)

    monkeypatch.setattr(elevate, "run_elevated", fake_sudo)


def test_uninstall_also_stops_and_removes_the_service(
    system: Layout,
    tmp_path: Path,
    launchd: Launchd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_and_start(system, tmp_path)
    plist = service.plist_path()
    assert launchd.loaded() == [service.LABEL] and plist.exists()
    uninstall_through_a_fake_sudo(monkeypatch)
    assert main(["uninstall"]) == 0
    assert (
        launchd.loaded() == [] and not plist.exists()
    )  # `launchctl list | grep agentfly` is empty
    out = capsys.readouterr().out
    assert out.count(uninstall.RESTART_HINT) == 1  # the child leaves it to the user's process
    assert "unloaded" in out and out.rstrip().endswith(uninstall.RESTART_HINT)


def test_uninstall_leaves_the_service_alone_when_the_system_part_fails(
    system: Layout,
    tmp_path: Path,
    launchd: Launchd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_and_start(system, tmp_path)
    monkeypatch.setattr(elevate, "run_elevated", lambda tail, stdin=None, **kw: 1)
    assert main(["uninstall"]) == 1
    assert launchd.loaded() == [service.LABEL]  # the service part never ran
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "sudo part failed" in err and "exit 1" in err
    assert "service was not touched" in err and "agentfly uninstall" in err


def test_a_failed_system_part_does_not_claim_what_it_cannot_know(
    system: Layout,
    tmp_path: Path,
    launchd: Launchd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The elevated part removed the hook entries, then failed on the folder: the hooks are gone."""
    install_and_start(system, tmp_path)

    def removes_the_entries_then_fails(
        tail: list[str], stdin: IO[bytes] | None = None, **kwargs: object
    ) -> int:
        installer.uninstall(system)
        return 1

    monkeypatch.setattr(elevate, "run_elevated", removes_the_entries_then_fails)
    assert main(["uninstall"]) == 1
    err = capsys.readouterr().err
    assert "still registered" not in err and "left running" not in err
    assert launchd.loaded() == [service.LABEL]  # untouched, as the message says


def test_a_cancelled_password_prompt_with_no_service_installed_says_the_same(
    system: Layout,
    tmp_path: Path,
    launchd: Launchd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_system(system, tmp_path)
    assert launchd.loaded() == []
    monkeypatch.setattr(elevate, "run_elevated", lambda tail, stdin=None, **kw: 1)
    assert main(["uninstall"]) == 1
    err = capsys.readouterr().err
    assert "sudo part failed" in err and "service was not touched" in err
    assert "left running" not in err and "still registered" not in err


def test_uninstall_removes_a_service_even_when_nothing_else_is_installed(
    system: Layout,
    launchd: Launchd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.start()  # `start` without `init -g`
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert main(["uninstall"]) == 0
    out = capsys.readouterr().out
    assert launchd.loaded() == [] and "unloaded" in out
    assert "nothing of AgentFly's is installed" not in out


def test_a_service_that_will_not_unload_is_one_line_and_a_second_run_finishes_it(
    system: Layout,
    tmp_path: Path,
    launchd: Launchd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_and_start(system, tmp_path)
    uninstall_through_a_fake_sudo(monkeypatch)
    launchd.update(bootout_lag=10_000)
    monkeypatch.setattr(service, "UNLOAD_TIMEOUT", 0.05)
    assert main(["uninstall"]) == 1
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1 and "service" in err and "agentfly uninstall" in err
    launchd.update(bootout_lag=0, jobs={})
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert main(["uninstall"]) == 0
    assert not service.plist_path().exists()


# ---------------------------------------------------------------- the package check (V3c)


class Sudo:
    """Stands in for `elevate.run_elevated`: records the call and, if asked, does the root work."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], object, Path | None]] = []
        self.then: object = None

    def __call__(
        self, tail: list[str], stdin: IO[bytes] | None = None, *, python: Path | None = None
    ) -> int:
        self.calls.append((tail, stdin, python))
        if callable(self.then):
            self.then()
        return 0

    def installs(self, system: Layout, build: pythons.PythonBuild, tmp_path: Path) -> None:
        """When called, do what root would: `installer.install` into `system`."""
        self.then = lambda: installer.install(
            system,
            build,
            cursor_version="3.24.12",
            source=installer.client_source(),
            archive=tmp_path / "dl" / "fake-python.tar.gz",
        )


def owner_answers(monkeypatch: pytest.MonkeyPatch, yes: bool) -> list[list[str]]:
    """The owner's reply to the prompt; the returned list collects what was asked."""
    asked: list[list[str]] = []
    monkeypatch.setattr(packages, "confirm", lambda changes, ask=None: asked.append(changes) or yes)
    return asked


@pytest.fixture
def sudo(monkeypatch: pytest.MonkeyPatch) -> Sudo:
    fake = Sudo()
    monkeypatch.setattr(elevate, "run_elevated", fake)
    return fake


@pytest.fixture
def installed(
    system: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> pythons.PythonBuild:
    build = install_system(system, tmp_path)
    monkeypatch.setattr(pythons, "select_build", lambda *a: build)
    return build


@pytest.mark.parametrize("command", [["init", "-g"], ["uninstall"]])
def test_a_changed_package_file_stops_before_any_password_prompt(
    command: list[str],
    system: Layout,
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    capsys: pytest.CaptureFixture[str],
) -> None:
    changed = tool_env.site / "agentfly" / "module.py"
    changed.write_text("import os\n")
    assert main(command) == 1
    err = capsys.readouterr().err
    assert str(changed) in err and f"run `agentfly {' '.join(command)}` again" in err
    assert "reinstall AgentFly" in err and "Traceback" not in err
    assert sudo.calls == [] and system.system_root.exists()  # nothing was asked, nothing removed


@pytest.mark.parametrize("command", [["init", "-g"], ["uninstall"]])
def test_an_extra_file_in_site_packages_stops_it_too(
    command: list[str],
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tool_env.site / "agentfly" / "_native.so").write_bytes(b"\x7fELF")
    assert main(command) == 1
    assert "_native.so is not listed in any RECORD" in capsys.readouterr().err
    assert sudo.calls == []


@pytest.mark.parametrize("command", [["init", "-g"], ["uninstall"]])
def test_a_file_with_control_characters_in_its_name_stops_with_one_plain_line(
    command: list[str],
    system: Layout,
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tool_env.site / "agentfly" / f"x{BAD}y.py").write_text("x = 1\n")
    assert main(command) == 1
    err = capsys.readouterr().err
    assert f"/agentfly/x{SHOWN}y.py is not listed in any RECORD" in err
    assert err.endswith("\n") and err[:-1].isprintable()  # one line; nothing a terminal acts on
    assert sudo.calls == [] and system.system_root.exists()


def test_a_version_with_a_control_character_is_escaped_in_the_question_before_the_password(
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    upgrade(tool_env, "agentfly-recorder", "0.2.0\x1b[2K", NEW_AGENTFLY)
    asked: list[str] = []
    monkeypatch.setattr(packages.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "n")
    assert main(["init", "-g"]) == 1
    out = capsys.readouterr().out
    assert "agentfly-recorder: changed from 0.1.0 to 0.2.0\\x1b[2K" in out
    assert_plain(out)  # everything printed before "Go on? [y/N]"
    assert asked == ["Go on? [y/N] "] and sudo.calls == []


def test_a_clean_install_is_checked_and_init_asks_for_no_password(
    installed: pythons.PythonBuild, sudo: Sudo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "-g"]) == 0
    assert "already installed" in capsys.readouterr().out and sudo.calls == []


def test_root_runs_on_the_bundled_python_when_it_is_installed_and_unchanged(
    system: Layout, installed: pythons.PythonBuild, sudo: Sudo
) -> None:
    system.client.write_text("tampered\n")  # a repair that leaves the Python alone
    assert main(["init", "-g"]) == 0
    assert sudo.calls == [(["init", "-g"], subprocess.DEVNULL, system.interpreter)]
    sudo.calls.clear()
    assert main(["uninstall"]) == 0
    assert sudo.calls == [(["uninstall"], None, system.interpreter)]


def test_root_runs_on_the_tool_environments_python_when_the_bundled_one_is_not_to_be_trusted(
    system: Layout,
    tmp_path: Path,
    installed: pythons.PythonBuild,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system.interpreter.write_text("#!/bin/sh\nexit 0\n")  # the bundled Python was changed
    monkeypatch.setattr(pythons, "download", lambda build, target: target.write_bytes(b"x"))
    assert main(["init", "-g"]) == 0
    assert sudo.calls[0][2] is None  # a repair that replaces it: the base interpreter
    sudo.calls.clear()
    assert main(["uninstall"]) == 0
    assert sudo.calls == [(["uninstall"], None, None)]


def test_a_first_install_runs_root_on_the_tool_environments_python(
    system: Layout, tmp_path: Path, sudo: Sudo, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = fake_python_tar()
    _, build = write_archive(tmp_path / "unused", data)
    monkeypatch.setattr(pythons, "select_build", lambda *a: build)
    monkeypatch.setattr(pythons, "download", lambda wanted, target: target.write_bytes(data))
    assert main(["init", "-g"]) == 0
    assert [call[2] for call in sudo.calls] == [None]


def test_an_upgrade_shows_old_and_new_versions_and_stops_unless_the_owner_confirms(
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    upgrade(tool_env, "agentfly-recorder", "0.2.0", NEW_AGENTFLY)
    monkeypatch.setattr(packages.sys, "stdin", None)  # no terminal: nobody can say yes
    assert main(["init", "-g"]) == 1
    captured = capsys.readouterr()
    assert "agentfly-recorder: changed from 0.1.0 to 0.2.0" in captured.out
    assert "not confirmed; nothing was changed" in captured.err and sudo.calls == []
    owner_answers(monkeypatch, False)
    assert main(["uninstall"]) == 1
    assert "uninstall: not confirmed" in capsys.readouterr().err and sudo.calls == []


def test_a_confirmed_upgrade_goes_ahead_and_the_record_holds_the_new_hashes(
    system: Layout,
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    upgrade(tool_env, "agentfly-recorder", "0.2.0", NEW_AGENTFLY)
    seen = owner_answers(monkeypatch, True)
    sudo.installs(system, installed, tmp_path)
    assert main(["init", "-g"]) == 0
    assert seen == [["agentfly-recorder: changed from 0.1.0 to 0.2.0"]]
    assert sudo.calls == [(["init", "-g"], subprocess.DEVNULL, system.interpreter)]
    stored = records.read(system)["packages"]  # type: ignore[index]
    assert stored["agentfly-recorder"]["version"] == "0.2.0"
    assert stored["agentfly-recorder"]["files"][MODULE] != ""
    sudo.calls.clear()
    assert main(["init", "-g"]) == 0  # now it is the recorded state: no prompt, no sudo
    assert sudo.calls == [] and "already installed" in capsys.readouterr().out


def test_an_upgrade_with_a_file_changed_against_its_own_record_is_stopped(
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    upgrade(tool_env, "agentfly-recorder", "0.2.0", NEW_AGENTFLY)
    (tool_env.site / MODULE).write_text("import os\n")
    monkeypatch.setattr(packages, "confirm", lambda *a, **k: pytest.fail("asked the owner"))
    assert main(["init", "-g"]) == 1
    assert "does not match its RECORD" in capsys.readouterr().err and sudo.calls == []


def test_a_dependency_upgrade_alone_goes_ahead_after_confirmation(
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upgrade(tool_env, "fakedep", "1.1", {"fakedep/__init__.py": b"X = 2\n"})
    seen = owner_answers(monkeypatch, True)
    assert main(["uninstall"]) == 0
    assert seen == [["fakedep: changed from 1.0 to 1.1"]] and len(sudo.calls) == 1


def test_a_new_homebrew_or_uv_python_does_not_stop_init_or_uninstall(
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tool_env.prefix / "pyvenv.cfg").write_text("home = /opt/homebrew/Cellar/python@3.12/3.12.99\n")
    (tool_env.prefix / "bin" / "python").write_text("a newer interpreter\n")
    assert main(["init", "-g"]) == 0
    assert "already installed" in capsys.readouterr().out
    assert main(["uninstall"]) == 0
    assert len(sudo.calls) == 1


def test_a_source_checkout_is_refused_with_the_wheel_hint_before_any_password(
    installed: pythons.PythonBuild,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refused() -> packages.Environment:
        raise packages.InstallError(
            f"running from a source checkout or an editable install. {packages.WHEEL_HINT}"
        )

    monkeypatch.setattr(packages, "tool_environment", refused)
    for command in (["init", "-g"], ["uninstall"]):
        assert main(command) == 1
    assert capsys.readouterr().err.count(packages.WHEEL_HINT) == 2 and sudo.calls == []


def test_uninstall_with_nothing_installed_checks_no_package(
    system: Layout, sudo: Sudo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(packages, "tool_environment", lambda: pytest.fail("looked at the package"))
    assert main(["uninstall"]) == 0 and sudo.calls == []


# ---------------------------------------------------------------- a rebuild at the same version

REBUILD_CASES = [
    pytest.param(*REBUILDS[0], id="AgentFly rebuilt"),
    pytest.param(*REBUILDS[1], id="a dependency under another Python"),
]


def rebuild(env: packages.Environment, name: str, files: dict[str, bytes]) -> None:
    """Reinstall one distribution at the version it has: other files, a RECORD that agrees."""
    upgrade(env, name, TOOL_DISTS[name][0], files)


@pytest.mark.parametrize(("name", "files"), REBUILD_CASES)
@pytest.mark.parametrize("command", [["init", "-g"], ["uninstall"]], ids=["init", "uninstall"])
def test_a_rebuild_at_the_same_version_asks_and_stops_after_a_no(
    command: list[str],
    name: str,
    files: dict[str, bytes],
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rebuild(tool_env, name, files)
    asked = owner_answers(monkeypatch, False)
    assert main(command) == 1
    assert len(asked) == 1 and asked[0][0].startswith(f"{name}: same version ")
    assert "files differ from install but match RECORD" in asked[0][0]
    assert "expected only if you reinstalled or rebuilt" in asked[0][0]
    err = capsys.readouterr().err
    assert "not confirmed; nothing was changed" in err and "hashes.json" not in err
    assert sudo.calls == []  # no password was asked for


@pytest.mark.parametrize(("name", "files"), REBUILD_CASES)
def test_a_rebuild_at_the_same_version_goes_on_after_a_yes_and_writes_the_new_hashes(
    name: str,
    files: dict[str, bytes],
    system: Layout,
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    rebuild(tool_env, name, files)
    owner_answers(monkeypatch, True)
    sudo.installs(system, installed, tmp_path)
    assert main(["init", "-g"]) == 0
    assert len(sudo.calls) == 1
    stored = (records.read(system) or {})["packages"][name]["files"]
    on_disk = packages.inspect(tool_env, None).distributions[name].files
    assert stored == on_disk  # the record now holds what was rebuilt
    sudo.calls.clear()
    assert main(["init", "-g"]) == 0  # and the next run is plain again
    assert sudo.calls == [] and "already installed" in capsys.readouterr().out


def test_uninstall_goes_on_after_a_yes_for_a_rebuild(
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rebuild(tool_env, *REBUILDS[0])
    owner_answers(monkeypatch, True)
    assert main(["uninstall"]) == 0 and len(sudo.calls) == 1


def test_a_rebuild_with_a_file_that_fails_its_own_record_never_asks(
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rebuild(tool_env, *REBUILDS[0])
    (tool_env.site / MODULE).write_text("import os\n")
    monkeypatch.setattr(packages, "confirm", lambda *a, **k: pytest.fail("asked the owner"))
    assert main(["init", "-g"]) == 1
    assert "does not match its RECORD" in capsys.readouterr().err and sudo.calls == []


def test_a_damaged_package_section_in_the_record_asks_instead_of_going_quiet(
    system: Layout,
    installed: pythons.PythonBuild,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Found by the audit: a section the code could not read once meant "no record", no prompt."""
    record = records.read(system) or {}
    record["packages"] = "garbage"
    system.record.write_text(records.dumps(record), encoding="utf-8")
    asked = owner_answers(monkeypatch, True)
    assert main(["init", "-g"]) == 0
    assert len(asked) == 1 and len(sudo.calls) == 1  # asked first, then the password


# ---------------------------------------------------------------- a direct_url.json that is no file


@pytest.mark.parametrize("kind", DIRECT_URL_KINDS[:2])  # the two that hung; the unit tests have all
def test_uninstall_stops_before_the_password_on_a_direct_url_that_is_not_a_plain_file(
    kind: str,
    installed: pythons.PythonBuild,
    tool_env: packages.Environment,
    sudo: Sudo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    info = next(tool_env.site.glob("agentfly_recorder-*.dist-info"))
    target, fifo = plant_direct_url(info, kind, tmp_path / "scratch", listed=False)
    fake_agentfly(monkeypatch, tool_env.site / "agentfly" / "__init__.py")
    monkeypatch.setattr(packages, "tool_environment", REAL_TOOL_ENVIRONMENT)  # the real lookup
    assert call_unless_it_hangs(lambda: main(["uninstall"]), fifo) == 1
    err = capsys.readouterr().err
    assert str(target) in err and "No password was asked for" in err
    assert sudo.calls == []  # nothing was asked, nothing removed


# ---------------------------------------------------------------- uninstall as root: sudo or hand


def test_a_hand_typed_sudo_uninstall_leaves_the_service_running_and_says_so(
    system: Layout,
    tmp_path: Path,
    launchd: Launchd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_and_start(system, tmp_path)
    user = os.geteuid
    monkeypatch.setattr(uninstall.os, "geteuid", lambda: 0)  # `sudo agentfly uninstall`: site is on
    assert main(["uninstall"]) == 0
    out = capsys.readouterr().out
    assert launchd.loaded() == [service.LABEL] and service.plist_path().exists()  # still running
    assert not system.system_root.exists()  # the system part is done
    assert out.count(uninstall.RESTART_HINT) == 1
    assert "service was not touched" in out and "without sudo" in out
    assert "`agentfly uninstall`" in out
    monkeypatch.setattr(uninstall.os, "geteuid", user)  # now as the user, as the message says
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert main(["uninstall"]) == 0
    assert launchd.loaded() == [] and not service.plist_path().exists()


def test_the_root_child_is_told_from_a_hand_typed_sudo_by_how_python_started() -> None:
    assert uninstall._elevated_child() is False  # the test run has site on and no -I
    assert uninstall._elevated_child(SimpleNamespace(isolated=1, no_site=1)) is True
    for one in (SimpleNamespace(isolated=1, no_site=0), SimpleNamespace(isolated=0, no_site=1)):
        assert uninstall._elevated_child(one) is False


def test_the_flags_sudo_starts_python_with_are_the_ones_the_child_looks_for() -> None:
    command = elevate.sudo_command(["uninstall"], site=Path("/site"), python=Path(sys.executable))
    flags = command[2 : command.index("-c")]  # what follows the interpreter: -I -S -B -X ...
    probe = "import sys; print(int(bool(sys.flags.isolated and sys.flags.no_site)))"

    def started(*args: str) -> str:
        run = subprocess.run(
            [sys.executable, *args, "-c", probe], capture_output=True, text=True, check=False
        )
        return run.stdout.strip()

    assert (started(*flags), started()) == ("1", "0")


# ---------------------------------------------------------------- the rules file (V5b-fix2)

OLDER_DEFAULT = sorted((REPO / "tests/fixtures/shipped_defaults").glob("*.toml"))[0]


def test_a_damaged_packaged_default_stops_init_before_the_password(
    system: Layout,
    installed: pythons.PythonBuild,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    system.rules.unlink()  # `init -g` would write the packaged default again
    monkeypatch.setattr(rulefile, "default_path", lambda: tmp_path / "gone.toml")
    monkeypatch.setattr(packages, "confirm", lambda *a, **k: pytest.fail("asked the owner"))
    assert main(["init", "-g"]) == 1
    captured = capsys.readouterr()
    assert "cannot read the packaged default rules" in captured.err
    assert "ask for your password" not in captured.out and sudo.calls == []


def test_a_damaged_packaged_default_does_not_stop_init_when_no_default_is_to_be_written(
    system: Layout,
    installed: pythons.PythonBuild,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    system.rules.write_text("# edited by the owner\n" + rulefile.default_text(), encoding="utf-8")
    system.client.write_text("tampered\n")  # a repair that has nothing to do with the rules
    monkeypatch.setattr(rulefile, "default_path", lambda: tmp_path / "gone.toml")
    assert main(["init", "-g"]) == 0
    assert len(sudo.calls) == 1  # the owner's file is never written: the default is not needed


def test_a_rules_only_refresh_does_not_ask_for_a_cursor_restart(
    system: Layout,
    installed: pythons.PythonBuild,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(init, "_stdin_archive", lambda: None)
    system.rules.write_bytes(
        OLDER_DEFAULT.read_bytes()
    )  # an unedited default of an earlier version
    assert init._as_root("3.24.12", installed) == 0
    out = capsys.readouterr().out
    assert "restart the recorder" in out and "Quit and reopen Cursor" not in out
    assert system.rules.read_bytes() == rulefile.default_path().read_bytes()


def test_a_refresh_that_changes_more_than_the_rules_still_asks_for_a_cursor_restart(
    system: Layout,
    installed: pythons.PythonBuild,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(init, "_stdin_archive", lambda: None)
    system.rules.write_bytes(OLDER_DEFAULT.read_bytes())
    system.client.write_text("tampered\n")
    assert init._as_root("3.24.12", installed) == 0
    out = capsys.readouterr().out
    assert "restart the recorder" in out and "Quit and reopen Cursor" in out


@pytest.mark.parametrize("what", ["link", "folder"])
def test_a_link_or_folder_at_the_rules_path_stops_init_before_the_password(
    what: str,
    system: Layout,
    installed: pythons.PythonBuild,
    sudo: Sudo,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CR7: the unprivileged run refuses with root's own words, and asks for no password."""
    system.rules.unlink()
    if what == "link":
        target = tmp_path / "elsewhere.toml"
        target.write_text(rulefile.default_text(), encoding="utf-8")
        system.rules.symlink_to(target)
    else:
        system.rules.mkdir()
    expected = str(installer._blocked(system))
    monkeypatch.setattr(packages, "confirm", lambda *a, **k: pytest.fail("asked the owner"))
    assert main(["init", "-g"]) == 1
    captured = capsys.readouterr()
    assert captured.err == f"agentfly init: {expected}\n"
    assert "ask for your password" not in captured.out and sudo.calls == []
    with pytest.raises(InstallError, match="remove it first"):  # root says the same
        installer.install(
            system, installed, cursor_version="3.24.12", source=installer.client_source()
        )

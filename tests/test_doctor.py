"""`agentfly doctor` (V3b): a clean install is all ok; each fault fails exactly its own line.

The install is a real `installer.install` into a temporary root with a fake Python build, the
service is the stub launchctl of tests/conftest.py, and Cursor's Hooks log is a file written here.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from agentfly.cli import doctor, main
from agentfly.install import (
    InstallError,
    checks,
    cursor,
    installer,
    packages,
    pythons,
    records,
    service,
)
from agentfly.install.layout import Layout
from agentfly.install.pythons import PythonBuild
from agentfly.recorder import rulefile
from tests.install_helpers import (
    TOOL_DISTS,
    fake_python_tar,
    make_cursor_app,
    make_layout,
    make_tool_env,
    upgrade,
    write_archive,
)
from tests.rules_helpers import BROKEN_TOML, R0_ENTRY
from tests.service_helpers import Brew, Launchd, homebrew_package
from tests.test_install_packages import (
    BAD,
    REAL_TOOL_ENVIRONMENT,
    SHOWN,
    assert_plain,
    fake_agentfly,
)

IDS = [
    "record",
    "python",
    "lock",
    "client",
    "rules",
    "package",
    "hooks",
    "events",
    "service",
    "service-file",
    "keepalive",
    "path",
    "hooks-log",
    "claude-settings",
]
STEPS = ", ".join(cursor.EVENTS)
LOADED = (
    f"[2026-10-19T10:00:00.100Z] Loaded {len(cursor.EVENTS)} enterprise hook(s) for steps: {STEPS}"
)
# Lines Cursor writes about the other hook files; common, and not about ours.
OTHER_FILES = [
    "[2026-10-19T10:00:00.200Z] ERROR: Invalid user config: Unknown hook type: afBogusEvent.",
    "[2026-10-19T10:00:00.300Z] ERROR: Failed to parse user hooks configuration",
    "[2026-10-19T10:00:00.400Z] ERROR: Failed to parse project hooks configuration",
]


@dataclass
class World:
    layout: Layout
    build: PythonBuild
    home: Path
    launchd: Launchd
    bin: Path
    log: Path
    search_path: list[str] = field(default_factory=list)

    def context(self) -> checks.Context:
        return checks.build_context(
            self.layout,
            self.build,
            installer.client_source(),
            home=self.home,
            search_path=self.search_path,
            own_script=self.bin / "agentfly",
        )

    def results(self) -> dict[str, checks.Check]:
        return {check.id: check for check in checks.run_all(self.context())}

    def levels(self, level: str) -> set[str]:
        return {id_ for id_, check in self.results().items() if check.level == level}

    def hooks(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.layout.hooks_file.read_text(encoding="utf-8"))
        return data

    def save_hooks(self, data: dict[str, Any]) -> None:
        self.layout.hooks_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def plist(self) -> dict[str, Any]:
        data: dict[str, Any] = plistlib.loads(service.plist_path().read_bytes())
        return data

    def save_plist(self, data: dict[str, Any]) -> None:
        service.plist_path().write_bytes(plistlib.dumps(data))

    def write_log(self, *lines: str) -> None:
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fake_command(folder: Path, text: str = "#!/bin/sh\nexit 0\n") -> Path:
    """An executable `agentfly` in `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "agentfly"
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    return script


def claude_settings(home: Path, content: str | dict[str, Any]) -> None:
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(exist_ok=True)
    settings.write_text(content if isinstance(content, str) else json.dumps(content))


def seed_service(launchd: Launchd) -> None:
    """The files and the job `agentfly start` leaves, without the subprocess calls it costs."""
    wanted = service.expected_plist()
    service._write_plist(service.plist_path(), wanted)
    job = {
        "plist": str(service.plist_path()),
        "keepalive": True,
        "args": wanted["ProgramArguments"],
        "pid": 4001,
        "dying": 0,
    }
    launchd.update(jobs={service.LABEL: job})


def make_world(
    tmp_path: Path,
    home: Path,
    launchd: Launchd,
    monkeypatch: pytest.MonkeyPatch,
    source: Path | None = None,
    *,
    via_start: bool = False,
) -> World:
    # The install's own checks (a smoke run of every hook command, byte-compiling the Python) are
    # tests/test_install_*.py's business; here they only cost two seconds a test.
    monkeypatch.setattr(installer, "smoke", lambda *args, **kwargs: None)
    monkeypatch.setattr(pythons, "compile_stdlib", lambda *args, **kwargs: None)
    layout = make_layout(tmp_path)
    make_cursor_app(layout)
    archive, build = write_archive(tmp_path / "dl", fake_python_tar())
    installer.install(
        layout,
        build,
        cursor_version="3.24.12",
        source=source or installer.client_source(),
        archive=archive,
    )
    if via_start:
        service.start()
    else:  # three stub launchctl runs a test, over fifty tests; test_a_clean_install covers both
        seed_service(launchd)
    bin_dir = tmp_path / "bin"
    fake_command(bin_dir)
    log = (
        home
        / "Library/Application Support/Cursor/logs/20261019T100000"
        / "window1_wb0/output_20261019T100001/cursor.hooks.workspaceId-a.log"
    )
    log.parent.mkdir(parents=True)
    world = World(layout, build, home, launchd, bin_dir, log, [str(bin_dir)])
    world.write_log(LOADED, *OTHER_FILES)
    return world


@pytest.fixture
def world(
    tmp_path: Path, isolated_home: Path, launchd: Launchd, monkeypatch: pytest.MonkeyPatch
) -> World:
    return make_world(tmp_path, isolated_home, launchd, monkeypatch)


# ---------------------------------------------------------------- a clean install


@pytest.mark.parametrize("via_start", [False, True], ids=["seeded", "agentfly start"])
def test_a_clean_install_is_all_ok(
    via_start: bool,
    tmp_path: Path,
    isolated_home: Path,
    launchd: Launchd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = make_world(tmp_path, isolated_home, launchd, monkeypatch, via_start=via_start)
    results = world.results()
    assert list(results) == IDS
    assert {id_: check.level for id_, check in results.items()} == dict.fromkeys(IDS, "ok")


def test_every_line_says_what_it_found(world: World) -> None:
    assert all(check.text and "\n" not in check.text for check in world.results().values())


# ---------------------------------------------------------------- the rules file (V5b)


def serve_health(monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any] | None) -> None:
    monkeypatch.setattr(service, "health", lambda timeout=2.0: answer)


HEALTHY = {"ok": True, "offline_guard_count": 0, "last_hook_at": None}


def test_the_rules_line_is_ok_for_the_file_init_wrote(world: World) -> None:
    check = world.results()["rules"]
    assert check.level == "ok" and str(world.layout.rules) in check.text


def test_a_recorder_that_does_not_answer_never_fails_the_rules_line(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve_health(monkeypatch, None)
    assert world.results()["rules"].level == "ok"


def test_a_missing_rules_file_is_a_warning_that_names_init(world: World) -> None:
    world.layout.rules.unlink()
    check = world.results()["rules"]
    assert check.level == "warn" and "agentfly init -g" in check.text and "default" in check.text
    assert world.levels("fail") == set(), "one fault turns one line"


@pytest.mark.parametrize(
    "text",
    [BROKEN_TOML, "not toml", "", "schema = 2\n"],
)
def test_an_invalid_rules_file_fails_only_the_rules_line_and_says_the_default_runs(
    world: World, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    world.layout.rules.write_text(text, encoding="utf-8")
    serve_health(monkeypatch, {**HEALTHY, "rules_problem": "rules.toml: not valid TOML"})
    check = world.results()["rules"]
    assert check.level == "fail" and "default rules are in force" in check.text
    assert world.levels("fail") == {"rules"}


def test_an_entry_for_r0_fails_the_rules_line(world: World) -> None:
    text = world.layout.rules.read_text(encoding="utf-8") + R0_ENTRY
    world.layout.rules.write_text(text, encoding="utf-8")
    check = world.results()["rules"]
    assert check.level == "fail" and "R0" in check.text


def test_an_invalid_file_that_a_running_recorder_has_not_read_yet_still_fails(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.layout.rules.write_text("garbage", encoding="utf-8")
    serve_health(monkeypatch, HEALTHY)
    check = world.results()["rules"]
    assert check.level == "fail" and "restart" in check.text and "next start" in check.text


def test_an_invalid_file_with_the_recorder_down_says_what_will_happen_at_its_start(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.layout.rules.write_text("garbage", encoding="utf-8")
    serve_health(monkeypatch, None)
    check = world.results()["rules"]
    assert check.level == "fail" and "default" in check.text


def test_a_fixed_file_with_a_recorder_still_on_the_default_asks_for_a_restart(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve_health(monkeypatch, {**HEALTHY, "rules_problem": "rules.toml: not valid TOML"})
    check = world.results()["rules"]
    assert check.level == "fail" and "restart" in check.text and "agentfly start" in check.text


def test_an_unedited_older_default_is_only_a_warning_that_names_init(world: World) -> None:
    older = sorted((Path(__file__).parent / "fixtures" / "shipped_defaults").glob("*.toml"))[0]
    world.layout.rules.write_bytes(older.read_bytes())
    check = world.results()["rules"]
    assert check.level == "warn" and "agentfly init -g" in check.text and "restart" in check.text
    assert world.levels("fail") == set()


def test_an_edited_file_is_fine_even_if_it_started_from_an_older_default(world: World) -> None:
    older = sorted((Path(__file__).parent / "fixtures" / "shipped_defaults").glob("*.toml"))[0]
    world.layout.rules.write_text("# mine\n" + older.read_text(encoding="utf-8"), encoding="utf-8")
    check = world.results()["rules"]
    assert check.level == "ok" and "all valid" in check.text


def test_a_rules_file_the_recorder_would_refuse_for_its_owner_fails_the_rules_line_only(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`doctor` reads the file as the recorder does: who owns it counts (V5b-fix)."""
    monkeypatch.setattr(rulefile, "ACTIVE_OWNER_UID", os.getuid() + 1)
    check = world.results()["rules"]
    assert check.level == "fail" and "is owned by" in check.text
    assert world.levels("fail") == {"rules"}


def test_a_rules_file_others_can_write_fails_the_rules_line(world: World) -> None:
    world.layout.rules.chmod(0o666)
    check = world.results()["rules"]
    assert check.level == "fail" and "written by group or others" in check.text
    assert "rules" in world.levels("fail")


def test_a_link_in_place_of_the_rules_file_fails_the_rules_line(
    world: World, tmp_path: Path
) -> None:
    target = tmp_path / "elsewhere.toml"
    target.write_text(world.layout.rules.read_text(encoding="utf-8"), encoding="utf-8")
    world.layout.rules.unlink()
    world.layout.rules.symlink_to(target)
    check = world.results()["rules"]
    assert check.level == "fail" and "symbolic link" in check.text


def test_a_file_without_r1_fails_the_rules_line_and_names_r1(world: World) -> None:
    default = world.layout.rules.read_text(encoding="utf-8")
    world.layout.rules.write_text(default[: default.index('[[rule]]\nid = "R1"')], encoding="utf-8")
    check = world.results()["rules"]
    assert check.level == "fail" and "rule R1: missing" in check.text
    assert world.levels("fail") == {"rules"}


def test_the_rules_line_is_one_line_however_many_problems_there_are(world: World) -> None:
    world.layout.rules.write_text(
        "schema = 1\n[[rule]]\nid = 1\n[[rule]]\nid = 2\n[[rule]]\nid = 3\n", encoding="utf-8"
    )
    check = world.results()["rules"]
    assert check.level == "fail" and "\n" not in check.text and "more" in check.text


def test_a_rules_file_the_user_could_not_read_is_a_lock_fault_not_a_rules_crash(
    world: World,
) -> None:
    world.layout.rules.chmod(0o000)
    try:
        results = world.results()
    finally:
        world.layout.rules.chmod(0o644)
    assert results["lock"].level == "fail"
    assert results["rules"].level == "fail"


# ---------------------------------------------------------------- one fault, one failing line


def change_client(w: World) -> None:
    w.layout.client.write_text(w.layout.client.read_text() + "# changed\n")


def change_package_file(w: World) -> None:
    (packages.tool_environment().site / "agentfly" / "module.py").write_text("import os\n")


def add_extra_file(w: World) -> None:
    (packages.tool_environment().site / "agentfly" / "_native.so").write_bytes(b"\x7fELF")


def forget_the_package_hashes(w: World) -> None:
    """An install from before V3c: the record has no `packages` section."""
    record = records.read(w.layout)
    assert record is not None
    del record["packages"]
    w.layout.record.write_text(records.dumps(record), encoding="utf-8")


def change_python(w: World) -> None:
    helper = w.layout.python_dir / "lib" / "python3.12" / "helper.py"
    helper.write_text(helper.read_text() + "VALUE = 2\n")


def change_entry(w: World) -> None:
    data = w.hooks()
    data["hooks"]["preToolUse"][0]["timeout"] = 99
    w.save_hooks(data)


def drop_entry(w: World) -> None:
    data = w.hooks()
    del data["hooks"]["afterFileEdit"]
    w.save_hooks(data)


def add_unknown_event(w: World) -> None:
    data = w.hooks()
    data["hooks"]["afBogusEvent"] = [dict(data["hooks"]["preToolUse"][0])]
    w.save_hooks(data)


def make_python_group_writable(w: World) -> None:
    os.chmod(w.layout.interpreter, 0o775)


def expect_another_owner(w: World) -> None:
    w.layout = replace(w.layout, owner=(0, 0))  # the temporary tree belongs to this user


def keepalive_off(w: World) -> None:
    w.save_plist({**w.plist(), "KeepAlive": False})


def edit_program(w: World) -> None:
    w.save_plist({**w.plist(), "ProgramArguments": ["/bin/sh", "-c", "sleep 1000"]})


def put_another_agentfly_first(w: World) -> None:
    other = w.bin.parent / "other"
    fake_command(other)
    w.search_path = [str(other), *w.search_path]


# The line each fault turns to fail. "a file the system user does not own" is two: the temporary
# tree belongs to this user, so the rules file in it is not root's either, and `rules` says so.
FAULTS: dict[str, tuple[str | set[str], Callable[[World], None]]] = {
    "a changed hook client": ("client", change_client),
    "a changed bundled Python": ("python", change_python),
    "a changed file of the package": ("package", change_package_file),
    "an extra file in site-packages": ("package", add_extra_file),
    "no package hashes in the record": ("package", forget_the_package_hashes),
    "a changed entry in hooks.json": ("hooks", change_entry),
    "a missing entry in hooks.json": ("hooks", drop_entry),
    "no hooks.json": ("hooks", lambda w: w.layout.hooks_file.unlink()),
    "no hash record": ("record", lambda w: w.layout.record.unlink()),
    "a group-writable bundled Python": ("lock", make_python_group_writable),
    "a file the system user does not own": ({"lock", "rules"}, expect_another_owner),
    "a missing hook client": ("client", lambda w: w.layout.client.unlink()),
    "KeepAlive off in the service file": ("keepalive", keepalive_off),
    "the service not loaded": ("service", lambda w: w.launchd.update(jobs={})),
    "the service stopped by `agentfly stop`": ("service", lambda w: service.stop()),
    "an edited service program": ("service-file", edit_program),
    "another agentfly first on PATH": ("path", put_another_agentfly_first),
    "an event Cursor does not know": ("events", add_unknown_event),
    "no enterprise hooks in the Hooks log": (
        "hooks-log",
        lambda w: w.write_log("[t] No enterprise hooks configuration found", *OTHER_FILES),
    ),
    "a parse error about the system file": (
        "hooks-log",
        lambda w: w.write_log(LOADED, "[t] ERROR: Failed to parse enterprise hooks configuration"),
    ),
    "an invalid-config line about the system file": (
        "hooks-log",
        lambda w: w.write_log(LOADED, "[t] ERROR: Invalid enterprise config: Unknown hook type"),
    ),
    "a Hooks-log line about an unnamed source": (
        "hooks-log",
        lambda w: w.write_log(LOADED, "[t] ERROR: Invalid config: Unknown hook type"),
    ),
    "Cursor loaded only some of the hooks": (
        "hooks-log",
        lambda w: w.write_log("[t] Loaded 2 enterprise hook(s) for steps: preToolUse, stop"),
    ),
}


@pytest.mark.parametrize("name", FAULTS)
def test_each_fault_turns_only_its_own_line_to_fail(name: str, world: World) -> None:
    expected, inject = FAULTS[name]
    inject(world)
    assert world.levels("fail") == ({expected} if isinstance(expected, str) else expected), (
        world.results()
    )


def test_a_missing_record_leaves_what_needs_it_unchecked(world: World) -> None:
    world.layout.record.unlink()
    results = world.results()
    assert results["python"].level == results["client"].level == "warn"
    assert "not checked" in results["python"].text and "no hash record" in results["client"].text
    assert results["package"].level == "warn" and "no hash record" in results["package"].text


def test_after_stop_the_service_file_and_keepalive_lines_only_warn(world: World) -> None:
    service.stop()
    results = world.results()
    assert (results["service-file"].level, results["keepalive"].level) == ("warn", "warn")
    assert "stopped" in results["keepalive"].text


def test_a_service_file_that_cannot_be_read_fails_only_its_own_line(world: World) -> None:
    service.plist_path().write_text("this is not a property list")
    results = world.results()
    assert world.levels("fail") == {"service-file"}
    assert results["keepalive"].level == "warn" and "not checked" in results["keepalive"].text


def test_a_loaded_job_that_lost_its_file_fails_keepalive(world: World) -> None:
    service.plist_path().unlink()
    assert "keepalive" in world.levels("fail")


def test_keepalive_that_launchd_does_not_know_about_is_a_warning(world: World) -> None:
    jobs = world.launchd.state()["jobs"]
    jobs[service.LABEL]["keepalive"] = False  # edited after it was loaded
    world.launchd.update(jobs=jobs)
    assert world.levels("fail") == set() and world.levels("warn") == {"keepalive"}


def test_a_client_that_matches_the_record_but_is_older_than_this_agentfly_warns(
    tmp_path: Path, isolated_home: Path, launchd: Launchd, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old_client.py"
    old.write_text(installer.client_source().read_text() + "\n# an earlier release\n")
    stale = make_world(tmp_path, isolated_home, launchd, monkeypatch, source=old)
    assert stale.levels("fail") == set() and stale.levels("warn") == {"client"}
    assert "agentfly init -g" in stale.results()["client"].text


def test_an_unknown_cursor_version_only_warns_about_the_events(world: World) -> None:
    plist = world.layout.cursor_app / "Contents" / "Info.plist"
    plist.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "9.9.9"}))
    results = world.results()
    assert results["events"].level == "warn" and "9.9.9" in results["events"].text
    assert world.levels("fail") == set()


def test_an_unreadable_cursor_version_only_warns(world: World) -> None:
    (world.layout.cursor_app / "Contents" / "Info.plist").unlink()
    assert world.results()["events"].level == "warn" and world.levels("fail") == set()


def test_an_entry_on_an_unknown_event_does_not_fail_the_hooks_line_too(world: World) -> None:
    add_unknown_event(world)
    results = world.results()
    assert results["hooks"].level == "ok" and results["events"].level == "fail"
    assert "afBogusEvent" in results["events"].text


def test_a_hooks_file_that_is_not_json_fails_hooks_and_leaves_events_unchecked(
    world: World,
) -> None:
    world.layout.hooks_file.write_text("{not json", encoding="utf-8")
    results = world.results()
    assert results["hooks"].level == "fail" and results["events"].level == "warn"


def test_other_tools_entries_in_the_hooks_file_do_not_matter(world: World) -> None:
    data = world.hooks()
    data["hooks"].setdefault("stop", []).append({"command": "/opt/other/audit.sh", "timeout": 5})
    data["hooks"]["preToolUse"].append({"command": "/opt/other/gate.sh"})
    world.save_hooks(data)
    assert world.levels("fail") == set() and world.levels("warn") == set()


# ---------------------------------------------------------------- the Hooks log


def test_an_old_error_followed_by_a_good_load_is_ok(world: World) -> None:
    world.write_log("[t] ERROR: Failed to parse enterprise hooks configuration", LOADED)
    assert world.results()["hooks-log"].level == "ok"


def test_errors_about_the_user_and_project_files_are_not_ours(world: World) -> None:
    world.write_log(LOADED, *OTHER_FILES, "[t] ERROR: Invalid claude user config: x")
    assert world.results()["hooks-log"].level == "ok"


def test_the_newest_start_folder_is_the_one_that_counts(world: World) -> None:
    older = world.log.parents[3] / "20261018T090000/window1_wb0/output_x"
    older.mkdir(parents=True)
    (older / "cursor.hooks.workspaceId-a.log").write_text(
        "[t] No enterprise hooks configuration found\n"
    )
    assert world.results()["hooks-log"].level == "ok"
    newer = world.log.parents[3] / "20261020T090000/window1_wb0/output_y"
    newer.mkdir(parents=True)
    (newer / "cursor.hooks.workspaceId-a.log").write_text(
        "[t] No enterprise hooks configuration found\n"
    )
    assert world.results()["hooks-log"].level == "fail"


def test_one_window_that_failed_is_enough_to_fail(world: World) -> None:
    second = world.log.parents[2] / "window2_wb1/output_z"
    second.mkdir(parents=True)
    (second / "cursor.hooks.workspaceId-b.log").write_text(
        "[t] No enterprise hooks configuration found\n"
    )
    assert world.results()["hooks-log"].level == "fail"


@pytest.mark.parametrize("setup", ["no logs", "no hooks log", "no status line"])
def test_a_hooks_log_that_says_nothing_only_warns(world: World, setup: str) -> None:
    if setup == "no logs":
        shutil.rmtree(world.log.parents[3])
    elif setup == "no hooks log":
        world.log.unlink()
    else:
        world.write_log("[t] Reloading hooks configuration...")
    assert world.results()["hooks-log"].level == "warn" and world.levels("fail") == set()


# ---------------------------------------------------------------- ~/.claude/settings.json (D24)


def test_a_gate_hook_in_claude_settings_is_a_warning(world: World) -> None:
    claude_settings(world.home, {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": []}]}})
    results = world.results()
    assert (
        results["claude-settings"].level == "warn"
        and "PreToolUse" in results["claude-settings"].text
    )
    assert world.levels("fail") == set()


@pytest.mark.parametrize(
    "content",
    [
        {"hooks": {"SessionStart": [{"hooks": []}], "PostToolUse": [{"hooks": []}]}},
        {"hooks": {"PreToolUse": []}},
        {"hooks": {}},
        {"permissions": {}},
    ],
)
def test_other_claude_hooks_are_fine(world: World, content: dict[str, Any]) -> None:
    claude_settings(world.home, content)
    assert world.results()["claude-settings"].level == "ok"


@pytest.mark.parametrize("content", ["{", "[" * 200_000], ids=["broken", "nested too deep"])
def test_claude_settings_that_are_not_json_only_warn(world: World, content: str) -> None:
    claude_settings(world.home, content)  # the second is nested deeper than json.loads allows
    assert world.results()["claude-settings"].level == "warn"


# ---------------------------------------------------------------- PATH


def test_no_agentfly_on_path_is_a_warning(world: World) -> None:
    world.search_path = [str(world.bin.parent / "empty")]
    assert world.results()["path"].level == "warn"


def test_a_command_that_runs_this_installs_python_is_ours(world: World, tmp_path: Path) -> None:
    other = tmp_path / "wrapper"
    fake_command(other, f"#!{sys.executable}\nprint('ours')\n")
    world.search_path = [str(other)]
    assert world.results()["path"].level == "ok"


def test_a_wrapper_script_that_runs_our_command_is_ours(world: World, tmp_path: Path) -> None:
    # what `write_exec_script` makes for a Homebrew formula: a shell script that execs the venv's
    wrapper = tmp_path / "wrapper"
    fake_command(wrapper, f'#!/bin/bash\nexec "{world.bin / "agentfly"}" "$@"\n')
    world.search_path = [str(wrapper)]
    assert world.results()["path"].level == "ok"


def test_a_python_script_of_another_install_is_not_ours(world: World, tmp_path: Path) -> None:
    other = tmp_path / "pypi"
    fake_command(other, "#!/usr/bin/env python3\nprint('another agentfly')\n")
    world.search_path = [str(other)]
    assert world.levels("fail") == {"path"}


def make_venv(root: Path, base: Path) -> Path:
    """A venv the way `python -m venv` and `uv` make one: `bin/python` is a symlink to `base`."""
    (root / "bin").mkdir(parents=True)
    (root / "pyvenv.cfg").write_text(f"home = {base.parent}\n", encoding="utf-8")
    (root / "bin" / "python").symlink_to(base)
    fake_command(root / "bin", f"#!{root / 'bin' / 'python'}\nprint('agentfly')\n")
    return root / "bin"


@pytest.fixture
def venvs(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Two venvs on one base Python; this run is from the first. Returns their `bin` folders."""
    base = tmp_path / "base" / "python3.12"
    base.parent.mkdir()
    base.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ours, other = make_venv(tmp_path / "ours", base), make_venv(tmp_path / "other", base)
    monkeypatch.setattr(sys, "executable", str(ours / "python"))
    seed_service(world.launchd)  # the service file names the interpreter that runs this
    return ours, other


def test_an_agentfly_of_another_venv_on_the_same_base_python_is_not_ours(
    world: World, venvs: tuple[Path, Path]
) -> None:
    ours, other = venvs
    assert os.path.realpath(ours / "python") == os.path.realpath(other / "python")
    world.search_path = [str(other), str(ours)]
    assert world.levels("fail") == {"path"}


def test_an_agentfly_of_this_venv_is_ours_even_when_it_is_not_the_recorded_script(
    world: World, venvs: tuple[Path, Path]
) -> None:
    ours, other = venvs
    world.search_path = [str(ours), str(other)]
    assert world.results()["path"].level == "ok"


def test_two_commands_on_a_python_without_a_venv_share_its_environment(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base" / "python3.12"
    base.parent.mkdir()
    base.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tmp_path / "usr_bin").mkdir()
    (tmp_path / "usr_bin" / "python3").symlink_to(base)
    monkeypatch.setattr(sys, "executable", str(base))
    command = tmp_path / "global"
    fake_command(command, f"#!{tmp_path / 'usr_bin' / 'python3'}\nprint('agentfly')\n")
    world.search_path = [str(command)]
    assert world.results()["path"].level == "ok"


def test_a_symlink_to_our_command_is_ours(world: World, tmp_path: Path) -> None:
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    (link_dir / "agentfly").symlink_to(world.bin / "agentfly")
    world.search_path = [str(link_dir)]
    assert world.results()["path"].level == "ok"


# ---------------------------------------------------------------- Homebrew and our own LaunchAgent


def become_a_homebrew_install(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Brew:
    """`brew services` runs the recorder; the world's LaunchAgent of ours is still loaded."""
    prefix = tmp_path / "homebrew"
    brew = Brew(prefix, world.home)
    monkeypatch.setattr(service, "PACKAGE_FILE", homebrew_package(prefix))
    subprocess.run([str(brew.path), "services", "start", "agentfly"], check=True)
    return brew


def test_a_homebrew_service_alone_is_ok(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    become_a_homebrew_install(world, tmp_path, monkeypatch)
    world.launchd.update(jobs={})
    service.plist_path().unlink()
    assert world.levels("fail") == set()
    assert world.results()["service"].level == "ok"


def test_a_homebrew_service_and_our_own_launch_agent_together_fail_the_service_line(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    become_a_homebrew_install(world, tmp_path, monkeypatch)
    assert service.LABEL in world.launchd.loaded()
    assert world.levels("fail") == {"service"}, world.results()
    text = world.results()["service"].text
    assert service.LABEL in text and "agentfly start" in text


# ---------------------------------------------------------------- a check cannot stop doctor


def test_a_check_that_blows_up_is_a_failed_line_not_a_traceback(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def check_boom(ctx: checks.Context) -> checks.Finding:
        raise PermissionError(13, "Permission denied", "/Library/Application Support/AgentFly")

    monkeypatch.setattr(checks, "CHECKS", [check_boom, checks.check_record])
    results = checks.run_all(world.context())
    assert [c.id for c in results] == ["boom", "record"]
    assert results[0].level == "fail" and "PermissionError" in results[0].text
    assert results[1].level == "ok"


def test_a_record_without_the_python_archive_name_does_not_stop_doctor(world: World) -> None:
    record = json.loads(world.layout.record.read_text())
    del record["python"]["archive"]
    world.layout.record.write_text(json.dumps(record))
    assert world.levels("fail") == set()


def test_any_exception_in_a_check_is_a_failed_line(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def check_boom(ctx: checks.Context) -> checks.Finding:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(checks, "CHECKS", [check_boom])
    assert [c.level for c in checks.run_all(world.context())] == ["fail"]


def test_an_unreadable_service_state_fails_the_service_line_only(world: World) -> None:
    world.launchd.path.write_text("#!/bin/sh\necho boom >&2\nexit 125\n", encoding="utf-8")
    assert world.levels("fail") == {"service"}
    assert "125" in world.results()["service"].text


# ---------------------------------------------------------------- the command


@pytest.fixture
def command(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.setattr(doctor, "SYSTEM", world.layout)
    monkeypatch.setattr(pythons, "select_build", lambda *a: world.build)
    monkeypatch.setattr(checks, "default_own_script", lambda: world.bin / "agentfly")
    monkeypatch.setenv("PATH", f"{world.bin}:/usr/bin:/bin")
    return world


def test_the_command_prints_one_line_per_check_and_exits_0_when_nothing_fails(
    command: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["doctor"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in lines] == IDS
    assert {line.split()[0] for line in lines} == {"ok"}


def test_a_warning_alone_does_not_fail_the_command(
    command: World, capsys: pytest.CaptureFixture[str]
) -> None:
    claude_settings(command.home, {"hooks": {"beforeShellExecution": [{"command": "x"}]}})
    assert main(["doctor"]) == 0
    assert "warn  claude-settings" in capsys.readouterr().out


def test_a_failure_makes_the_command_exit_1(
    command: World, capsys: pytest.CaptureFixture[str]
) -> None:
    change_client(command)
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert [line.split()[0] for line in out.splitlines()].count("fail") == 1
    assert out.count("fail  client") == 1


def test_the_command_on_a_machine_without_agentfly_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(doctor, "SYSTEM", make_layout(tmp_path))
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 1 and "agentfly init -g" in out


def test_doctor_reads_and_changes_nothing(command: World) -> None:
    def snapshot() -> dict[str, tuple[int, float]]:
        root = command.layout.system_root.parent
        return {
            str(p): (stat.S_IMODE(p.lstat().st_mode), p.lstat().st_mtime) for p in root.rglob("*")
        }

    before = snapshot()
    main(["doctor"])
    assert snapshot() == before


# ---------------------------------------------------------------- the package line (V3c)


def test_the_package_line_fails_after_one_changed_file_and_passes_after_a_reinstall(
    world: World,
) -> None:
    env = packages.tool_environment()
    module = env.site / "agentfly" / "module.py"
    original = module.read_bytes()
    module.write_bytes(b"import os\n")
    line = world.results()["package"]
    assert line.level == "fail" and str(module) in line.text
    assert "does not match its RECORD" in line.text and "init -g" in line.text
    module.write_bytes(original)  # reinstalling the same wheel puts the same bytes back
    assert world.results()["package"].level == "ok"


def test_an_extra_file_is_named_on_the_package_line(world: World) -> None:
    add_extra_file(world)
    text = world.results()["package"].text
    assert "_native.so is not listed in any RECORD" in text
    assert "delete each extra file or uninstall AgentFly's package" in text  # a reinstall keeps it


def test_the_package_line_counts_what_it_checked(world: World) -> None:
    assert world.results()["package"].text == (
        "AgentFly and its 1 dependencies match the record"  # the fake environment has two
    )


def test_an_upgrade_since_install_only_warns_and_says_to_run_init_again(world: World) -> None:
    upgrade(packages.tool_environment(), "fakedep", "1.1", {"fakedep/__init__.py": b"X = 2\n"})
    line = world.results()["package"]
    assert line.level == "warn" and "fakedep: changed from 1.0 to 1.1" in line.text
    assert "agentfly init -g" in line.text
    assert world.levels("fail") == set()


def test_run_from_a_source_checkout_the_package_line_is_not_checked(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused() -> packages.Environment:
        raise InstallError("AgentFly is running from a source checkout")

    monkeypatch.setattr(packages, "tool_environment", refused)
    line = world.results()["package"]
    assert line.level == "warn" and "not checked" in line.text and "source checkout" in line.text
    assert world.levels("fail") == set()


def test_the_package_line_lists_the_installed_versions_it_compared(world: World) -> None:
    record = records.read(world.layout)
    assert record is not None
    assert {n: v["version"] for n, v in record["packages"].items()} == {
        name: version for name, (version, _files) in TOOL_DISTS.items()
    }


def test_a_rebuild_at_the_same_version_only_warns(world: World) -> None:
    upgrade(packages.tool_environment(), "fakedep", "1.0", {"fakedep/__init__.py": b"X = 3\n"})
    line = world.results()["package"]
    assert line.level == "warn" and "fakedep: same version 1.0" in line.text
    assert "match RECORD" in line.text and "agentfly init -g" in line.text
    assert world.levels("fail") == set()


# ---------------------------------------------------------------- the package line, names (F13)


def test_the_package_line_shows_a_version_with_a_control_character_escaped(world: World) -> None:
    upgrade(
        packages.tool_environment(), "fakedep", "1.1\x1b[2K", {"fakedep/__init__.py": b"X = 2\n"}
    )
    line = world.results()["package"]
    assert line.level == "warn" and "fakedep: changed from 1.0 to 1.1\\x1b[2K" in line.text
    assert_plain(line.text)


def test_the_package_line_shows_an_environment_path_with_control_characters_escaped(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_tool_env(tmp_path / f"other{BAD}")
    (made.prefix / "pyvenv.cfg").unlink()
    fake_agentfly(monkeypatch, made.site / "agentfly" / "__init__.py")
    monkeypatch.setattr(packages, "tool_environment", REAL_TOOL_ENVIRONMENT)
    line = world.results()["package"]
    assert line.level == "warn" and f"({str(made.site).replace(BAD, SHOWN)})" in line.text
    assert_plain(line.text)


def test_the_command_prints_a_package_name_with_control_characters_as_one_plain_line(
    command: World, capsys: pytest.CaptureFixture[str]
) -> None:
    (packages.tool_environment().site / "agentfly" / f"x{BAD}y.py").write_text("x = 1\n")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert_plain(out)
    [line] = [line for line in out.split("\n") if line.startswith("fail  package")]
    assert f"x{SHOWN}y.py is not listed in any RECORD" in line

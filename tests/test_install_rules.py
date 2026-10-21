"""V5b, V5b-fix (D28): `init -g` puts the rules file in place, and never touches an edit.

Against a temporary root, like test_install_flow.py: the file is written when missing, as the
system user's, readable by everybody and writable by nobody else; a file that is byte for byte a
default the package once carried (the owner never edited it) is replaced by this version's; a
repair, a second `init -g` and an upgrade leave an edited copy alone; `uninstall` takes it away with
the folder. What is written is the packaged default as read once, checked against the wheel's
RECORD hash and parsed cleanly. Known bytes in a file that is not exactly what `init -g` writes
(the owner's, mode 0644) are rewritten; an edited file is never written, chowned or chmodded, and
an edited one the recorder would not read gets a notice that says so (V5b-fix2).
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agentfly.cli import init
from agentfly.install import InstallError, elevate, installer, packages, pythons, records
from agentfly.install.layout import SYSTEM, Layout
from agentfly.install.pythons import PythonBuild
from agentfly.recorder import rulefile
from tests.install_helpers import (
    TOOL_DISTS,
    fake_python_tar,
    make_layout,
    make_tool_env,
    status_of,
    write_archive,
)
from tests.rules_helpers import BROKEN_TOML, default_as

EDITED = "# edited by the owner\n" + rulefile.default_text()
SHIPPED = sorted((Path(__file__).parent / "fixtures" / "shipped_defaults").glob("*.toml"))
RECORD_PATH = installer.DEFAULT_RECORD_PATH


@pytest.fixture(autouse=True)
def quick_install(monkeypatch: pytest.MonkeyPatch) -> None:
    # The install's own checks (a smoke run of every hook command, byte-compiling the Python) are
    # tests/test_install_flow.py's business; none of these tests looks at them (~1.5 s each).
    monkeypatch.setattr(installer, "smoke", lambda *args, **kwargs: None)
    monkeypatch.setattr(pythons, "compile_stdlib", lambda *args, **kwargs: None)


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    return make_layout(tmp_path)


@pytest.fixture
def archive(tmp_path: Path) -> tuple[Path, PythonBuild]:
    return write_archive(tmp_path / "download", fake_python_tar())


def do_install(
    layout: Layout, archive: tuple[Path, PythonBuild], run_as: tuple[int, int] | None = None
) -> installer.Outcome:
    path, build = archive
    return installer.install(
        layout,
        build,
        cursor_version="3.24.12",
        source=installer.client_source(),
        archive=path,
        run_as=run_as,
    )


def fingerprint(path: Path) -> tuple[int, int, int]:
    info = path.lstat()
    return info.st_ino, info.st_mtime_ns, info.st_size


# ---------------------------------------------------------------- a first install


def test_the_rules_file_is_where_the_spec_says(layout: Layout) -> None:
    assert layout.rules == layout.system_root / "rules.toml"
    assert SYSTEM.rules == Path("/Library/Application Support/AgentFly/rules.toml")
    assert rulefile.ACTIVE_RULES != SYSTEM.rules, "the conftest keeps tests off the real file"


def test_install_writes_the_packaged_default_as_a_readable_unwritable_file(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    old = os.umask(0o077)  # a strict umask must not make the file unreadable for the user
    try:
        outcome = do_install(layout, archive)
    finally:
        os.umask(old)
    assert layout.rules.read_text(encoding="utf-8") == rulefile.default_text()
    assert stat.S_IMODE(layout.rules.stat().st_mode) == 0o644
    assert any("rules" in message for message in outcome.messages)
    assert rulefile.load_file(layout.rules).errors == ()


def test_the_file_is_written_with_the_layouts_owner_in_one_atomic_step(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, int]] = []
    real = installer._write_atomic

    def spy(path: Path, data: bytes, lay: Layout, mode: int = 0o644) -> None:
        calls.append((path, mode))
        real(path, data, lay, mode)

    monkeypatch.setattr(installer, "_write_atomic", spy)
    do_install(layout, archive)
    assert (layout.rules, 0o644) in calls, "the same helper that chowns and renames every file"


def test_the_folder_listing_has_the_rules_file_and_no_leftovers(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    assert sorted(p.name for p in layout.system_root.iterdir()) == [
        "hashes.json",
        "hook_client.py",
        "python",
        "rules.toml",
    ]
    assert installer.lock_problems(layout, check_owner=False) == []


def test_the_record_does_not_hash_the_rules_file(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    record = records.read(layout)
    # The packaged default is a file of the package, so its hash is among the package's; the
    # active file is the owner's and is neither named nor hashed on its own.
    assert record is not None and "rules.toml" not in json.dumps(record)


# ---------------------------------------------------------------- an edit is the owner's


def test_a_second_init_leaves_an_edited_copy_alone(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    before = fingerprint(layout.rules)
    assert status_of(layout, archive[1]) == set(), "an edit is not drift"
    outcome = do_install(layout, archive)
    assert not outcome.changed
    assert fingerprint(layout.rules) == before and layout.rules.read_text() == EDITED


def test_a_repair_of_something_else_never_overwrites_the_edit(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    layout.client.chmod(0o644)
    layout.client.write_text("tampered\n")
    assert status_of(layout, archive[1]) == {"client"}
    assert do_install(layout, archive).changed
    assert layout.client.read_bytes() == installer.client_source().read_bytes()
    assert layout.rules.read_text() == EDITED


def test_an_edit_that_is_not_valid_is_still_left_alone(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(BROKEN_TOML, encoding="utf-8")
    do_install(layout, archive)
    assert layout.rules.read_text() == BROKEN_TOML, "doctor reports it; init does not"


# ---------------------------------------------------------------- an install from before this card


def test_an_install_from_before_the_card_gets_the_file_on_its_next_init(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.unlink()
    assert status_of(layout, archive[1]) == {"rules"}
    client, interpreter = fingerprint(layout.client), fingerprint(layout.interpreter)
    outcome = do_install(layout, archive)
    assert outcome.changed and any("rules" in message for message in outcome.messages)
    assert layout.rules.read_text() == rulefile.default_text()
    assert status_of(layout, archive[1]) == set()
    assert (fingerprint(layout.client), fingerprint(layout.interpreter)) == (client, interpreter)


def test_a_missing_record_counts_the_rules_file_as_missing_too(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    assert "rules" in status_of(layout, archive[1])


# ---------------------------------------------------------------- what stands in the way


def test_a_symbolic_link_in_its_place_is_refused_and_its_target_is_not_written(
    layout: Layout, archive: tuple[Path, PythonBuild], tmp_path: Path
) -> None:
    do_install(layout, archive)
    target = tmp_path / "elsewhere.toml"
    target.write_text("mine\n")
    layout.rules.unlink()
    layout.rules.symlink_to(target)
    assert "rules" in status_of(layout, archive[1])
    with pytest.raises(InstallError, match="symbolic link"):
        do_install(layout, archive)
    assert target.read_text() == "mine\n" and layout.rules.is_symlink()


def test_a_folder_in_its_place_is_refused(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.unlink()
    layout.rules.mkdir()
    with pytest.raises(InstallError, match="not a regular file"):
        do_install(layout, archive)


def test_a_packaged_default_that_cannot_be_read_stops_the_install_with_a_message(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(rulefile, "default_path", lambda: tmp_path / "gone.toml")
    with pytest.raises(InstallError, match="cannot read the packaged default rules"):
        do_install(layout, archive)
    assert not layout.system_root.exists(), "a failed first install leaves nothing behind"


# ---------------------------------------------------------------- uninstall


def test_uninstall_takes_the_rules_file_away_with_the_folder(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    installer.uninstall(layout)
    assert not layout.system_root.exists()
    assert not layout.rules.exists()


def test_the_status_lists_only_the_known_parts(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.unlink()
    layout.client.write_text("tampered\n")
    found: Any = status_of(layout, archive[1])
    assert found == {"rules", "client"}


# ---------------------------------------------------------------- an unedited older default (D28)


def tamper_with_the_client(layout: Layout) -> None:
    """Something else to repair, so that `init -g` has work to do besides the rules."""
    layout.client.chmod(0o644)
    layout.client.write_text("tampered\n")


@pytest.mark.parametrize("old", SHIPPED, ids=[f.stem for f in SHIPPED])
def test_an_unedited_older_default_is_replaced_and_the_restart_is_asked_for(
    old: Path, layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_bytes(old.read_bytes())
    assert status_of(layout, archive[1]) == {"rules"}, "an older default is drift"
    client, interpreter = fingerprint(layout.client), fingerprint(layout.interpreter)
    outcome = do_install(layout, archive)
    assert outcome.changed
    (said,) = [m for m in outcome.messages if "replaced" in m]
    assert "unedited default rules" in said and "restart the recorder" in said
    assert layout.rules.read_bytes() == rulefile.default_path().read_bytes()
    assert stat.S_IMODE(layout.rules.stat().st_mode) == 0o644
    assert status_of(layout, archive[1]) == set()
    assert (fingerprint(layout.client), fingerprint(layout.interpreter)) == (client, interpreter)


def test_the_current_default_is_left_alone(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    before = fingerprint(layout.rules)
    tamper_with_the_client(layout)
    outcome = do_install(layout, archive)
    assert fingerprint(layout.rules) == before
    assert not any("rules" in message for message in outcome.messages)


def test_an_edit_is_kept_with_one_notice_line_when_init_has_other_work(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    tamper_with_the_client(layout)
    outcome = do_install(layout, archive)
    notices = [m for m in outcome.messages if "kept your edited rules file" in m]
    assert len(notices) == 1 and str(layout.rules) in notices[0]
    assert layout.rules.read_text() == EDITED


def test_an_edit_that_is_not_valid_is_kept_too(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(BROKEN_TOML, encoding="utf-8")
    tamper_with_the_client(layout)
    outcome = do_install(layout, archive)
    assert any("kept your edited rules file" in m for m in outcome.messages)
    assert layout.rules.read_text() == BROKEN_TOML


def kept(layout: Layout) -> str:
    return (
        f"kept your edited rules file {layout.rules}; this version's default rules were not applied"
    )


def test_an_intact_install_with_an_edit_prints_the_kept_notice_after_the_pinned_line(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    outcome = do_install(layout, archive)
    assert (outcome.changed, outcome.messages) == (
        False,
        ["already installed and intact; nothing changed", kept(layout)],
    )


def test_an_intact_install_with_no_edit_prints_only_the_pinned_line(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    outcome = do_install(layout, archive)
    assert (outcome.changed, outcome.messages) == (
        False,
        ["already installed and intact; nothing changed"],
    )


def test_an_oversized_file_in_its_place_counts_as_an_edit(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_bytes(b"#" * (rulefile.MAX_FILE_BYTES + 10))
    assert status_of(layout, archive[1]) == set()


def test_the_states_of_the_rules_file(layout: Layout, archive: tuple[Path, PythonBuild]) -> None:
    wanted = rulefile.sha256_of(rulefile.default_path().read_bytes())
    state = installer.rules_state
    assert state(layout, wanted) == "missing"
    do_install(layout, archive)
    assert state(layout, wanted) == "current"
    layout.rules.write_bytes(SHIPPED[0].read_bytes())
    assert state(layout, wanted) == "older"
    layout.rules.write_text(EDITED, encoding="utf-8")
    assert state(layout, wanted) == "edited"
    layout.rules.unlink()
    layout.rules.mkdir()
    assert state(layout, wanted) == "blocked"


# ------------------------------------------------------- what is written is what was checked


def test_a_default_changed_after_the_package_was_hashed_is_refused_and_nothing_is_written(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    swapped = tmp_path / "swapped.toml"
    swapped.write_text(default_as("warn"), encoding="utf-8")  # a valid file, but not the hashed one
    monkeypatch.setattr(rulefile, "default_path", lambda: swapped)
    with pytest.raises(InstallError, match="not the file that was checked"):
        do_install(layout, archive)
    assert not layout.system_root.exists()


def hashed_package_holding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, data: bytes | None
) -> Path:
    """A tool environment whose RECORD lists `data` as the default (none: lists no default)."""
    version, files = TOOL_DISTS["agentfly-recorder"]
    files = {k: v for k, v in files.items() if k != RECORD_PATH}
    path = tmp_path / "default.toml"
    if data is not None:
        files[RECORD_PATH] = data
        path.write_bytes(data)
    env = make_tool_env(tmp_path / "env2", {**TOOL_DISTS, "agentfly-recorder": (version, files)})
    monkeypatch.setattr(packages, "tool_environment", lambda: env)
    monkeypatch.setattr(rulefile, "default_path", lambda: path)
    return path


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        (BROKEN_TOML, "cannot be used"),
        (default_as("warn"), "rule R1"),  # a default that D27 would refuse is not installed
        ("schema = 1\n", "rule R1: missing"),
    ],
    ids=["not toml", "weak R1", "no R1"],
)
def test_a_packaged_default_that_does_not_parse_cleanly_is_never_written(
    text: str,
    complaint: str,
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hashed_package_holding(monkeypatch, tmp_path, text.encode())
    with pytest.raises(InstallError, match=complaint):
        do_install(layout, archive)
    assert not layout.system_root.exists()


def test_a_default_that_the_record_does_not_list_is_refused(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hashed_package_holding(monkeypatch, tmp_path, None)
    with pytest.raises(InstallError, match="not listed in AgentFly's RECORD"):
        do_install(layout, archive)
    assert not layout.system_root.exists()


def test_a_link_in_its_place_is_refused_before_anything_else_is_repaired(
    layout: Layout, archive: tuple[Path, PythonBuild], tmp_path: Path
) -> None:
    do_install(layout, archive)
    target = tmp_path / "elsewhere.toml"
    target.write_text("mine\n")
    layout.rules.unlink()
    layout.rules.symlink_to(target)
    tamper_with_the_client(layout)
    with pytest.raises(InstallError, match="symbolic link"):
        do_install(layout, archive)
    assert layout.client.read_text() == "tampered\n", "refused before the repair started"
    assert target.read_text() == "mine\n"


def test_recorded_hash_is_the_hash_the_check_made() -> None:
    check = packages.inspect(packages.tool_environment(), None)
    digest = packages.recorded_hash(check, RECORD_PATH)
    assert digest == rulefile.sha256_of(rulefile.default_path().read_bytes())
    assert packages.recorded_hash(check, "agentfly/nothing.toml") is None
    assert packages.recorded_hash(check, RECORD_PATH, "no-such-package") is None


# ------------------------------------------- known bytes in a file that is not exactly ours


def wanted_hash() -> str:
    return rulefile.sha256_of(rulefile.default_path().read_bytes())


def make_untrusted(fault: str, layout: Layout, monkeypatch: pytest.MonkeyPatch) -> str:
    """Spoil the file or who is expected to own it; return a word the reason must hold."""
    if fault == "owner":  # the layout's owner is root in production; here a user who is not us
        monkeypatch.setattr(installer, "rules_owner_uid", lambda lay: os.getuid() + 1)
        return "is owned by"
    mode = 0o664 if fault == "group-writable" else 0o600
    layout.rules.chmod(mode)
    return f"{mode:04o}"


FAULTS = ["group-writable", "owner-only", "owner"]


@pytest.mark.parametrize("fault", FAULTS)
def test_current_bytes_that_are_not_exactly_ours_are_rewritten(
    fault: str, layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    do_install(layout, archive)
    reason = make_untrusted(fault, layout, monkeypatch)
    assert installer.rules_state(layout, wanted_hash()) == "untrusted"
    assert status_of(layout, archive[1]) == {"rules"}, "the same bytes, but not an intact file"
    before = fingerprint(layout.rules)
    outcome = do_install(layout, archive)
    after = fingerprint(layout.rules)
    assert after != before and after[0] != before[0], "a fresh inode, not a chmod of the old file"
    assert layout.rules.read_bytes() == rulefile.default_path().read_bytes()
    assert outcome.changed
    (said,) = [m for m in outcome.messages if "rules" in m]
    assert reason in said and "rewrote the default rules" in said
    assert "`agentfly stop`" in said and "`agentfly start`" in said


def test_a_rewritten_file_is_exactly_ours_again(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.chmod(0o600)
    do_install(layout, archive)
    assert stat.S_IMODE(layout.rules.stat().st_mode) == 0o644
    assert installer.rules_state(layout, wanted_hash()) == "current"
    assert status_of(layout, archive[1]) == set()
    again = do_install(layout, archive)
    assert (again.changed, again.messages) == (
        False,
        ["already installed and intact; nothing changed"],
    )


def test_a_mode_the_recorder_would_load_is_still_not_exactly_ours(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.chmod(0o600)  # the recorder loads it (D3 asks only that others cannot write)
    assert rulefile.trust_problem(layout.rules, os.getuid()) is None
    assert installer.rules_state(layout, wanted_hash()) == "untrusted"


def test_an_older_default_is_rewritten_whatever_its_mode(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_bytes(SHIPPED[0].read_bytes())
    layout.rules.chmod(0o664)
    assert installer.rules_state(layout, wanted_hash()) == "older"
    do_install(layout, archive)
    assert layout.rules.read_bytes() == rulefile.default_path().read_bytes()
    assert stat.S_IMODE(layout.rules.stat().st_mode) == 0o644


def test_an_edited_untrusted_file_keeps_its_bytes_and_mode_with_a_notice(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    layout.rules.chmod(0o664)
    before, owner = fingerprint(layout.rules), layout.rules.stat().st_uid
    assert status_of(layout, archive[1]) == set(), "an edit is not drift, trusted or not"
    outcome = do_install(layout, archive)
    assert fingerprint(layout.rules) == before and layout.rules.read_text() == EDITED
    assert stat.S_IMODE(layout.rules.stat().st_mode) == 0o664
    assert layout.rules.stat().st_uid == owner
    assert not outcome.changed
    line, notice = outcome.messages
    assert line == "already installed and intact; nothing changed"
    assert notice.startswith(f"kept your edited rules file {layout.rules}, but the recorder will")
    assert "written by group or others" in notice and notice.endswith(rulefile.DEFAULT_IN_FORCE)


def test_the_notice_is_the_recorders_own_reason_for_an_edit_it_would_refuse(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    monkeypatch.setattr(installer, "rules_owner_uid", lambda lay: os.getuid() + 1)
    reason = rulefile.trust_problem(layout.rules, os.getuid() + 1)
    assert reason is not None and "is owned by" in reason
    assert installer.rules_notice(layout, wanted_hash()) == (
        f"kept your edited rules file {layout.rules}, but the recorder will not read it: "
        f"{reason}; {rulefile.DEFAULT_IN_FORCE}"
    )


def test_an_edit_with_other_work_to_do_gets_the_notice_in_the_changed_messages(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    before = fingerprint(layout.rules)
    monkeypatch.setattr(installer, "rules_owner_uid", lambda lay: os.getuid() + 1)
    tamper_with_the_client(layout)
    outcome = do_install(layout, archive)
    assert outcome.changed
    (notice,) = [m for m in outcome.messages if "kept your edited rules file" in m]
    assert "but the recorder will not read it: is owned by" in notice
    assert notice.endswith(rulefile.DEFAULT_IN_FORCE)
    assert fingerprint(layout.rules) == before and layout.rules.read_text() == EDITED


def test_a_group_writable_edit_with_other_work_to_do_stops_the_repair_and_is_not_touched(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    # The lock check (`assert_locked`) has always refused a folder with a file others can write.
    # The edit is not chmodded to get past it: the repair is undone and the file stays as it was.
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    layout.rules.chmod(0o664)
    before = fingerprint(layout.rules)
    tamper_with_the_client(layout)
    with pytest.raises(InstallError, match="can be written by group or others"):
        do_install(layout, archive)
    assert fingerprint(layout.rules) == before
    assert stat.S_IMODE(layout.rules.stat().st_mode) == 0o664


@pytest.mark.parametrize("state", ["missing", "current", "older", "untrusted", "blocked"])
def test_only_an_edited_file_has_a_notice(
    state: str, layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    assert installer.rules_notice(layout, wanted_hash()) is None  # nothing installed: missing
    do_install(layout, archive)
    if state == "older":
        layout.rules.write_bytes(SHIPPED[0].read_bytes())
    elif state == "untrusted":
        layout.rules.chmod(0o600)
    elif state == "blocked":
        layout.rules.unlink()
        layout.rules.mkdir()
    elif state == "missing":
        layout.rules.unlink()
    assert installer.rules_state(layout, wanted_hash()) == state
    assert installer.rules_notice(layout, wanted_hash()) is None


def test_the_owner_who_must_hold_the_file(layout: Layout) -> None:
    assert layout.owner is None and installer.rules_owner_uid(layout) == os.getuid()
    assert installer.rules_owner_uid(replace(layout, owner=(0, 0))) == 0
    assert installer.rules_owner_uid(replace(layout, owner=(501, 20))) == 501
    assert installer.rules_owner_uid(SYSTEM) == 0


def test_init_as_the_user_prints_the_notice_without_a_password(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    monkeypatch.setattr(init, "SYSTEM", layout)
    monkeypatch.setattr(installer, "status", lambda *args, **kwargs: set())
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert init._as_user("3.24.12", archive[1]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "already installed and intact; nothing changed",
        kept(layout),
    ]


def test_init_as_the_user_prints_nothing_more_without_an_edit(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    do_install(layout, archive)
    monkeypatch.setattr(init, "SYSTEM", layout)
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert init._as_user("3.24.12", archive[1]) == 0
    assert capsys.readouterr().out == "already installed and intact; nothing changed\n"


# ------------------------------------------------------------------ a file that cannot be read


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every file")
def test_an_unreadable_file_is_unknown_and_counts_as_work_for_root(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.chmod(0)
    try:
        assert installer.rules_state(layout, wanted_hash()) == "unknown"
        assert "rules" in status_of(layout, archive[1])
        assert installer.rules_notice(layout, wanted_hash()) is None
    finally:
        layout.rules.chmod(0o644)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every file")
def test_root_that_cannot_read_a_file_calls_it_edited_as_before(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    do_install(layout, archive)
    layout.rules.chmod(0)
    try:
        monkeypatch.setattr(os, "geteuid", lambda: 0)
        assert installer.rules_state(layout, wanted_hash()) == "edited"
        assert "rules" not in status_of(layout, archive[1])
    finally:
        layout.rules.chmod(0o644)


# ---------------------------------------------------------------- who can read the rules file (V5d)

# The tests run as the file's owner, so the group clause is tried through a `Reader` of another
# user. No such user exists (`pwd` has no entry), so `reader_for` knows only the group it is given.
NOBODY = 2_000_000_000


def edited_rules(layout: Layout, archive: tuple[Path, PythonBuild], mode: int) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    os.chown(layout.rules, -1, os.getegid())  # a group the user is in
    layout.rules.chmod(mode)


def another_user(*groups: int) -> installer.Reader:
    return installer.Reader(NOBODY, frozenset(groups))


def test_a_rules_file_the_user_reads_through_its_group_is_no_lock_fault(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    edited_rules(layout, archive, 0o640)
    reader = another_user(os.getegid())
    assert installer.lock_problems(layout, check_owner=False, reader=reader) == []
    lonely = another_user(os.getegid() + 1)
    assert installer.lock_problems(layout, check_owner=False, reader=lonely) == [
        f"{layout.rules} cannot be read by the user, so the recorder could not load it"
    ]


@pytest.mark.parametrize("mode", [0o660, 0o664, 0o646, 0o620])
def test_a_group_writable_rules_file_is_refused_in_a_group_the_user_is_in(
    mode: int, layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    edited_rules(layout, archive, mode)
    problems = installer.lock_problems(layout, check_owner=False, reader=another_user(os.getegid()))
    assert any("can be written by group or others" in problem for problem in problems)


def test_the_owner_bit_counts_for_the_owner_and_root_reads_nothing_by_owner_or_group(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    edited_rules(layout, archive, 0o600)
    unread = f"{layout.rules} cannot be read by the user, so the recorder could not load it"
    mine = installer.Reader(os.getuid(), frozenset())
    assert installer.lock_problems(layout, check_owner=False, reader=mine) == []
    assert installer.lock_problems(layout, check_owner=False, reader=another_user()) == [unread]
    layout.rules.chmod(0o640)  # root could read it, which says nothing about the user
    root = installer.Reader(0, frozenset({os.getegid()}))
    assert installer.lock_problems(layout, check_owner=False, reader=root) == [unread]
    layout.rules.chmod(0o644)
    assert installer.lock_problems(layout, check_owner=False, reader=root) == []
    layout.rules.chmod(0o000)
    assert installer.lock_problems(layout, check_owner=False, reader=mine) == [unread]


def test_the_other_files_still_have_to_be_readable_by_others(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    os.chown(layout.client, -1, os.getegid())
    layout.client.chmod(0o640)
    problems = installer.lock_problems(layout, check_owner=False, reader=another_user(os.getegid()))
    assert problems == [f"{layout.client} cannot be read by the user, so the hook would fail"]


def test_a_repair_goes_on_past_a_rules_file_the_user_reads_through_its_group(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    edited_rules(layout, archive, 0o640)
    before = fingerprint(layout.rules)
    tamper_with_the_client(layout)
    outcome = do_install(layout, archive, (NOBODY, os.getegid()))
    assert outcome.changed
    assert fingerprint(layout.rules) == before and layout.rules.read_text() == EDITED
    assert stat.S_IMODE(layout.rules.stat().st_mode) == 0o640


def test_a_repair_stops_when_the_user_the_installer_serves_is_not_in_the_group(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    edited_rules(layout, archive, 0o640)
    before = fingerprint(layout.rules)
    tamper_with_the_client(layout)
    with pytest.raises(InstallError, match="could not load it"):
        do_install(layout, archive, (NOBODY, os.getegid() + 1))
    assert fingerprint(layout.rules) == before and layout.rules.read_text() == EDITED


def test_the_reader_of_a_sudo_user_is_their_group_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer.pwd, "getpwuid", lambda uid: type("P", (), {"pw_name": "u"})())
    seen: list[tuple[str, int]] = []

    def groups(name: str, gid: int) -> list[int]:
        seen.append((name, gid))
        return [gid, 80, 12]

    monkeypatch.setattr(os, "getgrouplist", groups)
    assert installer.reader_for((501, 20)) == installer.Reader(501, frozenset({20, 80, 12}))
    assert seen == [("u", 20)]
    monkeypatch.setattr(os, "getgrouplist", lambda *a: (_ for _ in ()).throw(OSError("no")))
    assert installer.reader_for((501, 20)) == installer.Reader(501, frozenset({20}))
    assert installer.reader_for(None) == installer.current_reader()
    assert installer.current_reader().uid == os.geteuid()

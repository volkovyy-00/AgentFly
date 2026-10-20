"""V5b: which rules the recorder runs. The active file when it is valid, else the packaged default.

The recorder reads `rulefile.ACTIVE_RULES` once, at start. A missing file is normal (a developer
`serve`); a file that cannot be used is reported, and the default runs instead. A damaged
*default* must not stop `uninstall` from importing the engine, and must stop the recorder.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.rules as rules_mod
from agentfly.recorder import rulefile
from agentfly.recorder.names import is_sensitive
from tests.rules_helpers import BROKEN_TOML, R0_ENTRY, default_as, default_with, ruleset_of

GOOD_DEFAULT = rulefile.default_text()  # read before any test damages the path
WITH_P12 = re.sub(
    r"^secret_names = \[(.*)\]$",
    r'secret_names = [\1, "*.p12"]',
    GOOD_DEFAULT,
    count=1,
    flags=re.M,
)


def test_a_missing_active_file_means_the_default_and_no_complaint() -> None:
    loaded = rules_mod.load_active()
    assert loaded is rules_mod.DEFAULT
    assert loaded.problem is None and loaded.source == "default"
    assert [r.id for r in loaded.rules][:2] == ["R0", "R1"]


def test_a_valid_active_file_is_the_rules_in_force(active_rules: Path) -> None:
    active_rules.write_text(WITH_P12, encoding="utf-8")
    loaded = rules_mod.load_active()
    assert (loaded.source, loaded.path, loaded.problem) == ("active", str(active_rules), None)
    assert loaded is not rules_mod.DEFAULT


@pytest.mark.parametrize(
    "text",
    [
        BROKEN_TOML,
        "not toml at all",
        default_with("", R0_ENTRY),
        GOOD_DEFAULT.replace("R1", "R1\nx"),
        "",
    ],
)
def test_an_active_file_with_errors_is_not_used_and_says_why(active_rules: Path, text: str) -> None:
    active_rules.write_text(text, encoding="utf-8")
    loaded = rules_mod.load_active()
    assert loaded.source == "default" and loaded.rules == rules_mod.DEFAULT.rules
    assert loaded.problem and str(active_rules) in loaded.problem
    assert "\n" not in loaded.problem and len(loaded.problem) < 600


def test_an_unreadable_active_file_never_raises(active_rules: Path) -> None:
    active_rules.mkdir()  # a folder where the file should be
    loaded = rules_mod.load_active()
    assert loaded.source == "default" and loaded.problem
    active_rules.rmdir()
    active_rules.write_bytes(b"\xff\xfe\x00\x00" * 100)
    assert rules_mod.load_active().problem


def test_activate_swaps_the_list_in_place_so_importers_see_it() -> None:
    imported = rules_mod.RULES
    rs = ruleset_of(default_as("warn"))
    rules_mod.activate(rs)
    assert imported is rules_mod.RULES and imported[1].severity == "warn"
    assert rules_mod.current() is rs
    rules_mod.activate(rules_mod.DEFAULT)
    assert imported[1].severity == "block" and rules_mod.current() is rules_mod.DEFAULT


def test_find_rule_answers_from_the_rules_in_force() -> None:
    assert rules_mod.find_rule("R0") is rules_mod.RULES[0]
    assert rules_mod.find_rule("R1") is rules_mod.RULES[1]
    assert rules_mod.find_rule("nope") is None and rules_mod.find_rule(None) is None


def test_find_rule_reads_the_rules_in_force_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rs = ruleset_of(default_as("warn"))
    monkeypatch.setattr(rules_mod, "_active", rs)  # not through `activate`: RULES is not touched
    assert rules_mod.find_rule("R1") is rs.rules[1] and rs.rules[1].severity == "warn"


def test_the_deny_messages_come_from_the_rule_and_a_gone_rule_falls_back_to_r1() -> None:
    user, agent = rules_mod.deny_messages("R0")
    assert user == rules_mod.R0_MESSAGE and agent == user + rules_mod.BLOCK_TAIL
    assert rules_mod.deny_messages("gone")[0] == rules_mod.R1_MESSAGE


def test_the_engine_knows_exactly_the_command_classes_a_rules_file_may_name() -> None:
    assert set(rules_mod.CLASSES) == rulefile.COMMAND_CLASSES


def test_reads_secret_is_the_marking_test_of_the_rules_in_force() -> None:
    read = {"hook_event_name": "beforeReadFile", "file_path": "/w/.env"}
    shell = {"hook_event_name": "beforeShellExecution", "command": "cat .env.example"}
    assert rules_mod.reads_secret(read) is True and rules_mod.reads_secret(shell) is False


def test_the_names_the_page_flags_as_sensitive_follow_the_rules_in_force() -> None:
    assert is_sensitive("cert.p12") is False
    rules_mod.activate(ruleset_of(WITH_P12))
    assert is_sensitive("dir/Cert.P12") is True
    assert is_sensitive(".env") is True and is_sensitive(".env.example") is False


# ---------------------------------------------------------------- the recorder's start


def start() -> TestClient:
    return TestClient(app_module.app, base_url="http://127.0.0.1:8787")


def test_the_recorder_starts_on_an_invalid_file_with_the_default_and_logs_the_reason(
    active_rules: Path, caplog: pytest.LogCaptureFixture
) -> None:
    active_rules.write_text(BROKEN_TOML, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="agentfly"), start():
        assert rules_mod.current().source == "default"
        assert rules_mod.current().problem
    assert any("packaged default rules are in force" in r.getMessage() for r in caplog.records)


def test_the_recorder_reads_the_file_once_at_start(active_rules: Path) -> None:
    active_rules.write_text(WITH_P12, encoding="utf-8")
    with start():
        assert rules_mod.current().source == "active"
        active_rules.write_text("garbage", encoding="utf-8")
        assert rules_mod.current().source == "active", "a later edit waits for the next start"


# ---------------------------------------------------------------- a damaged default


@pytest.fixture
def damaged_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "default.toml"
    path.write_text("schema = 1\n[[rule]\n", encoding="utf-8")
    monkeypatch.setattr(rulefile, "default_path", lambda: path)
    return path


def test_a_damaged_default_leaves_r0_alone_and_does_not_stop_the_import(
    damaged_default: Path,
) -> None:
    broken = rules_mod._load_default()
    assert broken.broken and [r.id for r in broken.rules] == ["R0"]
    assert "packaged default" in (broken.problem or "")
    assert broken.secret({"hook_event_name": "beforeReadFile", "file_path": ".env"}) is False


def test_a_missing_default_is_the_same_damage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rulefile, "default_path", lambda: tmp_path / "gone.toml")
    assert rules_mod._load_default().broken


def test_the_recorder_refuses_to_start_on_a_damaged_default(
    damaged_default: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rules_mod, "DEFAULT", rules_mod._load_default())
    with pytest.raises(RuntimeError, match="packaged default"), start():
        pass


def test_a_good_active_file_still_runs_when_the_packaged_default_is_damaged(
    damaged_default: Path, active_rules: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rules_mod, "DEFAULT", rules_mod._load_default())
    active_rules.write_text(GOOD_DEFAULT, encoding="utf-8")
    with start():
        assert rules_mod.current().source == "active" and not rules_mod.current().broken

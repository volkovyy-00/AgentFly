"""Which Cursor versions and events `init -g` accepts (D23)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentfly.install import InstallError, cursor
from tests.install_helpers import make_cursor_app, make_layout


def test_a_known_version_and_its_events_pass(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    make_cursor_app(layout, "3.24.12")
    assert cursor.check(layout.cursor_app) == "3.24.12"


def test_an_unknown_version_is_refused_and_named(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    make_cursor_app(layout, "9.9.9")
    with pytest.raises(InstallError, match=r"Cursor 9\.9\.9 .*nothing was written"):
        cursor.check(layout.cursor_app)


def test_an_event_the_cursor_does_not_accept_is_refused_and_named(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    make_cursor_app(layout)
    with pytest.raises(InstallError, match="afBogusEvent"):
        cursor.check(layout.cursor_app, (*cursor.EVENTS, "afBogusEvent"))


def test_a_missing_cursor_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match="cannot read the Cursor version"):
        cursor.check(tmp_path / "Cursor.app")


def test_the_registered_events_are_the_d9_list_and_all_in_the_s5_dump() -> None:
    assert set(cursor.EVENTS) == {
        "beforeShellExecution",
        "beforeReadFile",
        "beforeMCPExecution",
        "preToolUse",
        "afterFileEdit",
        "sessionStart",
        "sessionEnd",
        "subagentStart",
    }
    assert set(cursor.EVENTS) <= cursor.KNOWN_VERSIONS["3.24.12"]
    for never in ("beforeSubmitPrompt", "afterAgentResponse", "afterAgentThought"):
        assert never not in cursor.EVENTS  # they carry prompts and replies

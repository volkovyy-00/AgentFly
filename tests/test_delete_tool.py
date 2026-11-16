"""P2: Cursor's Delete tool is a `write` event for every rule (owner 2026-11-16).

Cursor 3.27.22's Delete fires `preToolUse` only, `tool_name` "Delete", `tool_input`
`{"file_path": <absolute path>}`, with a `tool_use_id` like other tools (HOOKS.md "Observed on
Cursor"). Example rule 8 blocks a write outside the workspace and rule 7 warns on one under
`.github/workflows/`; a Delete is judged the same way.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
from agentfly.recorder import rulefile
from agentfly.recorder.rules import Session, decide
from tests.test_rule_bypass import EXAMPLE, RULESET
from tests.test_step_fields import deny, post_raw
from tests.test_step_merge import pre

RULE8_TEXT = "Blocked: writes outside the open workspace folder are not allowed."


def delete(path: str, tool: str = "Delete") -> dict[str, Any]:
    """A Delete as the hook client passes it on (the brief's observed input), root `/work/app`."""
    return {**pre(tool, "toolu_del_1", path=path), "workspace_roots": ["/work/app"]}


def example_verdict(action: dict[str, Any]) -> tuple[str, str | None]:
    return decide(action, Session(id="c", marked=False, start_time="", next_step=0), RULESET)


@pytest.mark.parametrize("tool", ["Delete", "dElEtE"])
def test_a_delete_is_a_write_event(tool: str) -> None:
    assert rulefile.event_of(delete("/etc/hosts", tool)) == "write"


def test_rule8_blocks_a_delete_outside_the_workspace() -> None:
    assert example_verdict(delete("/etc/hosts")) == ("blocked", "s08-write-outside-workspace")


def test_rule8_allows_a_delete_inside_the_workspace() -> None:
    assert example_verdict(delete("/work/app/src/a.py")) == ("allow", None)


def test_rule7_warns_on_a_delete_of_a_workflow() -> None:
    verdict = example_verdict(delete("/work/app/.github/workflows/ci.yml"))
    assert verdict == ("warned", "s07-workflow-edit")


@pytest.fixture
def example_client(active_rules: Path) -> Iterator[TestClient]:
    shutil.copyfile(EXAMPLE, active_rules)
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as client:
        yield client


def test_the_recorder_denies_a_delete_outside_the_workspace(example_client: TestClient) -> None:
    assert post_raw(example_client, delete("/etc/hosts")).json() == deny(RULE8_TEXT)

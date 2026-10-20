"""V5b: `GET /api/rules`, and `/health` saying when the active rules file was not used."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.rules as rules_mod
from agentfly.recorder import rulefile
from tests.helpers import free_port, start_recorder, stop_recorder, wait_for_health

BROKEN = "schema = 1\n[[rule]\n"
EXTRA = """
[[rule]]
id = "warn-push"
kind = "match"
severity = "warn"
message = "A push needs a look."
event = ["shell"]
command = "push_cmds"
  [[rule.test]]
  steps = ["shell: git push"]
  expect = "warn"
"""


def custom_rules() -> str:
    text = rulefile.default_text().replace("[lists]\n", '[lists]\npush_cmds = ["git push"]\n', 1)
    return text + EXTRA


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        yield test_client


def started(active_rules: Path, text: str | None) -> TestClient:
    if text is not None:
        active_rules.write_text(text, encoding="utf-8")
    return TestClient(app_module.app, base_url="http://127.0.0.1:8787")


# ---------------------------------------------------------------- GET /api/rules


def test_the_default_rules_are_listed_r0_first_with_the_file_in_use(client: TestClient) -> None:
    body = client.get("/api/rules").json()
    assert set(body) == {"file", "source", "problem", "rules"}
    assert body["source"] == "default" and body["problem"] is None
    assert body["file"] == str(rulefile.default_path())
    assert [r["id"] for r in body["rules"]][:2] == ["R0", "R1"]
    r0, r1 = body["rules"][:2]
    assert r0 == {
        "id": "R0",
        "kind": "builtin",
        "severity": "block",
        "message": rules_mod.R0_MESSAGE,
    }
    assert r1 == {
        "id": "R1",
        "kind": "after_then",
        "severity": "block",
        "message": rules_mod.R1_MESSAGE,
    }
    assert all(set(r) == {"id", "kind", "severity", "message"} for r in body["rules"])


def test_a_valid_active_file_is_listed_in_its_own_order(active_rules: Path) -> None:
    with started(active_rules, custom_rules()) as client:
        body = client.get("/api/rules").json()
    assert (body["source"], body["file"], body["problem"]) == ("active", str(active_rules), None)
    shipped = [spec.id for spec in rulefile.load_default().rules]
    assert [r["id"] for r in body["rules"]] == ["R0", *shipped, "warn-push"]
    assert body["rules"][0]["kind"] == "builtin" and body["rules"][1]["id"] == "R1"
    assert body["rules"][-1] == {
        "id": "warn-push",
        "kind": "match",
        "severity": "warn",
        "message": "A push needs a look.",
    }


def test_an_invalid_active_file_shows_the_default_and_says_why(active_rules: Path) -> None:
    with started(active_rules, BROKEN) as client:
        body = client.get("/api/rules").json()
    assert body["source"] == "default" and body["file"] == str(rulefile.default_path())
    assert str(active_rules) in body["problem"] and "TOML" in body["problem"]
    assert [r["id"] for r in body["rules"]][:2] == ["R0", "R1"]


def test_the_rules_need_no_token_but_the_host_must_be_local() -> None:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as ok:
        assert ok.get("/api/rules").status_code == 200
    with TestClient(app_module.app, base_url="http://example.com:8787") as bad:
        assert bad.get("/api/rules").status_code == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def test_every_other_method_on_the_rules_is_refused(client: TestClient, method: str) -> None:
    assert client.request(method, "/api/rules").status_code == 405
    assert client.request(method, "/api/rules", json={"id": "x"}).status_code == 405


def test_listing_the_rules_changes_nothing(client: TestClient) -> None:
    before = [r.id for r in rules_mod.RULES]
    client.get("/api/rules")
    client.get("/api/rules?file=/etc/passwd&source=active")
    assert [r.id for r in rules_mod.RULES] == before
    assert rules_mod.current().source == "default"


# ---------------------------------------------------------------- /health


def test_health_stays_as_it_was_when_the_rules_are_fine(client: TestClient) -> None:
    assert client.get("/health").json() == {
        "ok": True,
        "offline_guard_count": 0,
        "last_hook_at": None,
    }


def test_health_says_so_when_the_active_file_was_not_used(active_rules: Path) -> None:
    with started(active_rules, BROKEN) as client:
        body = client.get("/health").json()
    assert set(body) == {"ok", "offline_guard_count", "last_hook_at", "rules_problem"}
    assert str(active_rules) in body["rules_problem"]
    assert "\n" not in body["rules_problem"] and len(body["rules_problem"]) <= 400


def test_health_says_nothing_about_a_valid_active_file(active_rules: Path) -> None:
    with started(active_rules, custom_rules()) as client:
        assert "rules_problem" not in client.get("/health").json()


# ---------------------------------------------------------------- a real recorder process


def fetch(port: int, path: str) -> Any:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return json.loads(response.read())


def run_recorder(home: Path, text: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Start a child recorder whose rules file is `<home>/test-rules.toml` (see RECORDER_CODE)."""
    if text is not None:
        (home / "test-rules.toml").write_text(text, encoding="utf-8")
    port = free_port()
    process = start_recorder(home, port)
    try:
        health = wait_for_health(port, process)
        return health, fetch(port, "/api/rules")
    finally:
        stop_recorder(process)


def test_a_child_recorder_with_no_file_runs_the_default(isolated_home: Path) -> None:
    health, listing = run_recorder(isolated_home, None)
    assert "rules_problem" not in health
    assert listing["source"] == "default" and listing["problem"] is None


def test_a_child_recorder_with_a_valid_file_runs_it(isolated_home: Path) -> None:
    health, listing = run_recorder(isolated_home, custom_rules())
    assert "rules_problem" not in health
    assert listing["source"] == "active"
    shipped = [spec.id for spec in rulefile.load_default().rules]
    assert [r["id"] for r in listing["rules"]] == ["R0", *shipped, "warn-push"]


def test_a_child_recorder_with_a_planted_invalid_file_runs_the_default_and_says_so(
    isolated_home: Path,
) -> None:
    health, listing = run_recorder(isolated_home, BROKEN)
    assert "test-rules.toml" in health["rules_problem"]
    assert listing["source"] == "default" and listing["problem"] == health["rules_problem"]

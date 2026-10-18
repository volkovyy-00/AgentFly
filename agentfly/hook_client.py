#!/usr/bin/env python3
"""Hook client (`agentfly-hook <agent> <event>`): strip, ask the local recorder, print the answer.

Standard library only, one file, run with `python -I -S`. Stdout holds ONLY the JSON answer and the
exit code is always 0 (exit 2 would block the action); diagnostics go to stderr and never carry
payload text. If the recorder does not answer, the offline guard (SPEC section 9, D4) answers.
"""

from __future__ import annotations

import json
import os
import sys
import time

TYPE_CHECKING = False  # `import typing` alone costs ~5 ms per call
if TYPE_CHECKING:
    from typing import Any

try:  # the C module alone is enough here, and importing `socket` costs ~12 ms at start-up
    import _socket as _net
except ImportError:  # pragma: no cover
    import socket as _net  # type: ignore[no-redef]

# D25: the client always talks to the recorder on this address. No env var and no
# port file may change it; tests set these module attributes from inside their own harness.
_HOST: str = "127.0.0.1"
_PORT: int = 8787
_BUDGET_S: float = 0.5  # total wait for the recorder, connect and answer together
_MAX_STDIN: int = 64 * 1024 * 1024
_MAX_GUARD_TEXT: int = 1024 * 1024
_MAX_ANSWER: int = 1024 * 1024
_MAX_DEPTH: int = 24  # nested containers deeper than this are cut before they reach the body

_STRIP_KEYS: frozenset[str] = frozenset(
    {"content", "output", "edits", "tool_output", "tool_response", "prompt", "text"}
)
# Events whose `command` is not a shell command line (an MCP server launch) or which carry none.
_NOT_SHELL: frozenset[str] = frozenset(
    {"beforeReadFile", "afterFileEdit", "beforeMCPExecution", "preToolUse", "afterShellExecution"}
)
_MCP_KEEP: tuple[str, ...] = (
    "hook_event_name",
    "conversation_id",
    "session_id",
    "generation_id",
    "model",
    "cwd",
    "workspace_roots",
    "tool_use_id",
    "parent_tool_call_id",  # a subagent's link to its parent's Task call (D21 A)
    "parent_conversation_id",
    "tool_name",
    "mcp_server_name",
    "server",
    "server_name",
)
# Session events (the subagent's `task` is its prompt text): only the common fields, ids and names.
_SESSION_EVENTS: frozenset[str] = frozenset({"sessionStart", "sessionEnd", "subagentStart"})
_SESSION_KEEP: tuple[str, ...] = (
    *_MCP_KEEP,
    "cursor_version",
    "user_email",
    "transcript_path",
    "tool_call_id",
    "subagent_id",
    "subagent_type",
    "is_parallel_worker",
)
_AGENT_SUFFIX: str = "Do not retry with another tool or language. Stop and tell the user."

# Offline guard (SPEC section 9): a word-level copy of what agentfly/recorder/rules.py treats as
# outbound, plus R0's guard paths. tests/test_offline_guard.py runs both over the same cases.
_ALWAYS_OUTBOUND: frozenset[str] = frozenset({"gh", "aws"})
_HOSTED_OUTBOUND: frozenset[str] = frozenset({"curl", "wget", "nc", "scp", "ssh", "rsync"})
_INTERPRETERS: tuple[str, ...] = ("python", "node")  # name prefixes: python3.12, nodejs
_GUARD_PATHS: tuple[str, ...] = (
    ".config/agentfly",
    ".local/share/agentfly",
    "/library/application support/agentfly",
    "hooks.json",
)


def say(message: str) -> None:
    """One line on stderr, never raising (stderr may be closed or broken)."""
    try:
        sys.stderr.write(f"agentfly: {message}\n")
    except Exception:  # noqa: BLE001, S110
        pass


# ---------------------------------------------------------------- paths (computed on use)


def _home() -> str | None:
    home: str = os.path.expanduser("~")
    return home if home.startswith("/") else None  # unset HOME and no passwd entry: no files


def _under_home(*parts: str) -> str | None:
    home: str | None = _home()
    return os.path.join(home, *parts) if home else None


def log_path() -> str | None:
    return _under_home(".local", "share", "agentfly", "logs", "events.jsonl")


def count_path() -> str | None:
    return _under_home(".local", "share", "agentfly", "logs", "offline-count")


def token_path() -> str | None:
    return _under_home(".config", "agentfly", "token")


# ---------------------------------------------------------------- stripping


def _scrub(text: str) -> str:
    """Replace lone surrogates, which neither UTF-8 nor the recorder's log can hold."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "".join("\ufffd" if "\ud800" <= char <= "\udfff" else char for char in text)
    return text


def strip_tree(root: Any, drop: frozenset[str]) -> None:
    """In place, with no recursion: drop `drop` keys at every depth, scrub strings, cut depth."""
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            for key in [k for k in node if k in drop]:
                del node[key]
            slots = list(node.items())
        else:
            slots = list(enumerate(node))
        for key, value in slots:
            if isinstance(value, str):
                node[key] = _scrub(value)
            elif isinstance(value, dict | list):
                if depth >= _MAX_DEPTH:
                    node[key] = None
                else:
                    stack.append((value, depth + 1))


def sanitize(payload: dict[str, Any], event: str) -> dict[str, Any]:
    """The copy sent to the recorder: no file, edit, output or tool-input text (SPEC section 8)."""
    out: dict[str, Any] = dict(payload)
    tool_input: Any = out.pop("tool_input", None)
    tool_name: str = str(out.get("tool_name", "")).lower()
    if event in _SESSION_EVENTS:
        out = {key: out[key] for key in _SESSION_KEEP if key in out}
        out["hook_event_name"] = event
    elif event == "beforeMCPExecution" or (event == "preToolUse" and tool_name.startswith("mcp")):
        out = {key: out[key] for key in _MCP_KEEP if key in out}
        out["hook_event_name"] = event
    else:
        if event != "beforeShellExecution":
            out.pop("command", None)
        if isinstance(tool_input, dict) and isinstance(tool_input.get("file_path"), str):
            out["tool_input"] = {"file_path": tool_input["file_path"]}
    edits: Any = out.pop("edits", None)
    strip_tree(out, _STRIP_KEYS)
    if event == "afterFileEdit" and edits is not None:
        out["edits"] = f"<{len(edits) if isinstance(edits, list) else 0} edits>"
    if "agent_message" in out:
        out["agent_message"] = "<omitted>"
    return out


# ---------------------------------------------------------------- offline guard


# Shell operators, quotes and the punctuation of (possibly broken) JSON all separate words, so a
# quoted `bash -c 'curl x'` and a truncated `{"command": "curl x"` are scanned the same way.
_SEPARATORS = str.maketrans(dict.fromkeys(";|&()`$\n\r\t\"'{},\\", " "))


def words(text: str) -> list[str]:
    """Words of a shell command or of raw hook text. Never raises, and is fast on big input."""
    for escape in ("\\n", "\\r", "\\t"):  # `\n` written out inside JSON text
        text = text.replace(escape, " ")
    return text.translate(_SEPARATORS).split()


def _is_local_host(host: str) -> bool:
    if host.lower() == "localhost" or host == "::1":
        return True
    import ipaddress

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(addr.is_loopback or addr.is_private)


def _host_of_token(token: str) -> str | None:
    from urllib.parse import urlparse

    if "://" in token:  # also `--url=https://host` and `-d@https://host`
        try:
            return urlparse("//" + token.split("://", 1)[1]).hostname
        except ValueError:
            return None
    if token.startswith("-") and "=" in token:  # `--url=host`
        return _host_of_token(token.split("=", 1)[1])
    if ":" in token and not token.startswith("-"):
        left: str = token.split(":", 1)[0]
        if "@" in left:
            left = left.rsplit("@", 1)[-1]
        if left and not left.isdigit() and "/" not in left:
            return left
    if token.startswith("-") or "/" in token or "=" in token:
        return None
    if "." in token or token == "localhost" or ":" in token:
        if token.replace(".", "").isdigit():
            return token
        if any(c.isalpha() for c in token) or ":" in token:
            return token
    return None


def _interpreter(name: str) -> str | None:
    """'python' for python, python3, python3.12; 'node' for node, nodejs, node18; else None."""
    for family in _INTERPRETERS:
        rest: str = name.removeprefix(family)
        if rest != name and (not rest.strip("0123456789.") or (family == "node" and rest == "js")):
            return family
    return None


def _python_one_liner(args: list[str]) -> bool:
    """`-c` in python's own options, found letter by letter (`-Sc`, `-c1`, `-X dev -c`)."""
    options = iter(args)
    for arg in options:
        if arg == "--" or not arg.startswith("-") or arg.startswith("-m"):
            return False  # the script (first plain word), `--`, or `python -m module`
        if arg.startswith("--"):
            if arg == "--check-hash-based-pycs":
                next(options, None)
            continue
        for index, letter in enumerate(arg[1:], 1):
            if letter == "c":
                return True
            if letter == "m":
                return False
            if letter in "WXQ":  # the rest of the word, or the next word, is its value
                if index == len(arg) - 1:
                    next(options, None)
                break
    return False


def _node_one_liner(args: list[str]) -> bool:
    """`-e`, `-p`, `--eval[=]`, `--print[=]` before node's script.

    Node has too many options that take a value to walk past them, so the options end at the
    first word that names a script file or at `--`.
    """
    for arg in args:
        if arg == "--" or arg.endswith((".js", ".mjs", ".cjs", ".ts")):
            return False
        if arg.startswith(("--eval", "--print")):
            return True
        if arg.startswith("-") and not arg.startswith("--") and arg[1:].isalpha():
            if "e" in arg[1:] or "p" in arg[1:]:
                return True
    return False


def _inline_code(argv: list[str], names: list[str]) -> bool:
    """An inline one-liner: `python -c`, `node -e` (SPEC section 9 denies every one).

    Only the words after the interpreter are looked at, so the `-c` of `bash -c 'python3 x.py'`
    or of `python3 -m pytest -c cfg` is not taken for it.
    """
    for index, name in enumerate(names):
        family: str | None = _interpreter(name)
        if family == "python" and _python_one_liner(argv[index + 1 :]):
            return True
        if family == "node" and _node_one_liner(argv[index + 1 :]):
            return True
    return False


def _outbound_words(argv: list[str], text: str) -> bool:
    """`text` is the case-folded command, for the `http` test."""
    lower: list[str] = [a.lower() for a in argv]
    names: list[str] = [a.split("/")[-1].lower() for a in argv]
    if any(n in _ALWAYS_OUTBOUND for n in names) or ("git" in names and "push" in lower):
        return True
    if _inline_code(argv, names) or (any(map(_interpreter, names)) and "http" in text):
        return True
    if any(n in _HOSTED_OUTBOUND for n in names):
        hosts = [h for h in (_host_of_token(a) for a in argv) if h]
        return not hosts or any(not _is_local_host(h) for h in hosts)
    return False


def guard_reason(text: str) -> str | None:
    """'guard_path', 'outbound' or None. Wrapped commands are found by scanning every word."""
    folded: str = text.casefold()
    plain: str = folded.replace("\\", "")  # `Application\ Support`
    while "//" in plain:
        plain = plain.replace("//", "/")
    while "/./" in plain:  # `/././` needs more than one pass
        plain = plain.replace("/./", "/")
    if "/.." in plain:  # `~/.config/x/../agentfly`: resolve each word that has a `..`
        plain += " " + " ".join(os.path.normpath(w) for w in plain.split() if "/.." in w)
    if any(path in plain for path in _GUARD_PATHS):
        return "guard_path"
    return "outbound" if _outbound_words(words(text), folded) else None


# What a file tool names: `tool_input` of `preToolUse`, `file_path` and attachments of
# `beforeReadFile`, and the folder a call runs in (R0 checks `cwd` too). Values are a string or a
# list of strings; a relative target is also tried under each folder.
_PATH_KEYS: tuple[str, ...] = (
    "file_path",
    "path",
    "paths",
    "target_file",
    "target_directory",
    "target_directories",
    "target_notebook",
)
_DIR_KEYS: tuple[str, ...] = ("cwd", "working_directory")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def file_targets(payload: dict[str, Any]) -> list[str]:
    """Paths the action names, whatever the event. Only strings; other shapes are ignored."""
    tool_input: Any = payload.get("tool_input")
    sources: list[Any] = [payload, tool_input]
    found: list[str] = []
    attachments: Any = payload.get("attachments")
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, str):
                found.append(item)
            else:
                sources.append(item)
    folders: list[str] = []
    for source in sources:
        if isinstance(source, dict):
            for key in _PATH_KEYS:
                found += _strings(source.get(key))
            for key in _DIR_KEYS:
                folders += _strings(source.get(key))
    found += [os.path.join(f, t) for f in folders for t in found if not t.startswith("/")]
    return found + folders


def path_guard_reason(path: str) -> str | None:
    """'guard_path' if the path, with case, `\\`, `//`, `/./` and `..` resolved, is a guard path."""
    plain: str = path.casefold().replace("\\", "")
    try:
        forms: list[str] = [plain, os.path.normpath(plain)]
    except ValueError:  # a NUL byte
        forms = [plain]
    return "guard_path" if any(g in form for g in _GUARD_PATHS for form in forms) else None


def files_reason(payload: dict[str, Any]) -> str | None:
    return next((r for r in map(path_guard_reason, file_targets(payload)) if r), None)


def deny_answer(reason: str) -> dict[str, str]:
    what: str = (
        "touches AgentFly's own files" if reason == "guard_path" else "sends data off this computer"
    )
    message: str = (
        f"AgentFly's recorder is not running, so this action, which {what}, is blocked. "
        "Run `agentfly start`, then try again."
    )
    return {
        "permission": "deny",
        "user_message": message,
        "agent_message": f"{message} {_AGENT_SUFFIX}",
    }


def offline_answer(text: str) -> tuple[dict[str, str], str | None]:
    reason: str | None = guard_reason(text)
    if reason is None:
        return {"permission": "allow"}, None
    return deny_answer(reason), reason


# ---------------------------------------------------------------- recorder, log, output


def _recv_until_closed(sock: Any, deadline: float) -> bytes:
    chunks: list[bytes] = []
    total: int = 0
    while total <= _MAX_ANSWER:
        sock.settimeout(max(deadline - time.monotonic(), 0.001))
        chunk: bytes = sock.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def post_hook(body: bytes, token: str, deadline: float) -> dict[str, Any]:
    """POST to the recorder. Raises on any failure; the caller then applies the offline guard."""
    if not (token.isascii() and token.isprintable() and token):
        raise ValueError("bad token file")
    head: bytes = (
        f"POST /hook HTTP/1.1\r\nHost: {_HOST}:{_PORT}\r\nContent-Type: application/json\r\n"
        f"X-Recorder-Token: {token}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode("ascii")
    sock = _net.socket(_net.AF_INET, _net.SOCK_STREAM)
    try:
        sock.settimeout(max(deadline - time.monotonic(), 0.001))
        sock.connect((_HOST, _PORT))
        sock.sendall(head + body)
        raw: bytes = _recv_until_closed(sock, deadline)
    finally:
        sock.close()
    header, _, answer = raw.partition(b"\r\n\r\n")
    status: list[bytes] = header.split(b"\r\n", 1)[0].split()
    if len(status) < 2 or status[1] != b"200":
        raise ValueError("bad recorder status")
    if b"transfer-encoding" in header.lower():
        raise ValueError("unsupported recorder answer")
    parsed: Any = json.loads(answer)
    permission: Any = parsed.get("permission", "allow") if isinstance(parsed, dict) else None
    if permission not in {"allow", "deny", "ask"}:
        raise ValueError("recorder answer is not a permission object")
    out: dict[str, str] = {"permission": permission}
    for key in ("user_message", "agent_message"):
        if key in parsed:
            out[key] = str(parsed[key])
    return out


def _append(path: str | None, data: bytes) -> None:
    """Append to a private file (folder 700, file 600, never through a symlink). May raise."""
    if path is None:
        return
    folder: str = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    fd: int = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def append_log(record: dict[str, Any]) -> None:
    """One line per call in the hook log. Never raises."""
    try:
        _append(log_path(), (json.dumps(record, ensure_ascii=True) + "\n").encode("ascii"))
    except Exception as exc:  # noqa: BLE001
        say(f"could not write the hook log ({type(exc).__name__})")


def count_offline_answer() -> None:
    """One byte per guard answer made while the recorder was down; `/health` reports the size."""
    try:
        _append(count_path(), b"\n")
    except Exception:  # noqa: BLE001, S110
        pass


def emit(answer: dict[str, str]) -> None:
    """Print the answer. If stdout is broken, silence it so shutdown cannot exit non-zero."""
    try:
        sys.stdout.write(json.dumps(answer, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        try:
            fd: int = os.open(os.devnull, os.O_WRONLY)
            os.dup2(fd, 1)
            sys.stdout = open(os.devnull, "w")  # noqa: SIM115
        except Exception:  # noqa: BLE001, S110
            pass


# ---------------------------------------------------------------- one call


def read_stdin() -> bytes:
    chunks: list[bytes] = []
    total: int = 0
    try:
        while total <= _MAX_STDIN:
            chunk: bytes = os.read(0, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError:
        pass
    return b"".join(chunks)


def parse_payload(raw: bytes) -> dict[str, Any] | None:
    if len(raw) > _MAX_STDIN:
        return None
    try:
        parsed: Any = json.loads(raw)
    except Exception:  # noqa: BLE001 - RecursionError, ValueError (5000 digits), bad UTF-8, ...
        return None
    return parsed if isinstance(parsed, dict) else None


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def guard_raw(raw: bytes) -> tuple[dict[str, str], str | None]:
    """The offline guard on input that could not be read as a hook payload."""
    if len(raw) > _MAX_GUARD_TEXT:  # a tool name may sit at either end of a cut-off payload
        half: int = _MAX_GUARD_TEXT // 2
        raw = raw[:half] + b" " + raw[-half:]
    return offline_answer(raw.decode("utf-8", "replace"))


def unreadable(raw: bytes) -> dict[str, str]:
    answer, guard = guard_raw(raw)
    say("unreadable hook input; offline guard applied")
    append_log(
        {
            "ts": now(),
            "decision": answer["permission"],
            "offline": True,
            "reason": "unreadable_input",
            "guard": guard,
        }
    )
    return answer


def ask_recorder(payload: dict[str, Any], event: str, start: float) -> dict[str, str]:
    sanitized: dict[str, Any] = sanitize(payload, event)
    body: str = json.dumps(sanitized, ensure_ascii=True)
    logged: dict[str, Any] = json.loads(body)
    strip_tree(logged, frozenset({"command"}))
    record: dict[str, Any] = {"ts": now(), "event": logged}
    command: Any = payload.get("command")
    shell: bool = event not in _NOT_SHELL and command is not None
    try:
        path: str | None = token_path()
        if path is None:
            raise FileNotFoundError("no home folder")
        with open(path, encoding="ascii", errors="replace") as handle:
            token: str = handle.read(4096).strip()
        answer = post_hook(body.encode("ascii"), token, start + _BUDGET_S)
        record.update(decision=answer["permission"])
        append_log(record)
        return answer
    except Exception as exc:  # noqa: BLE001 - any failure means "recorder did not answer"
        say(f"recorder unreachable ({type(exc).__name__}); offline guard applied")
        text: str = ""
        if shell:  # a missing or odd event name, or a command that is not a string, still counts
            text = command if isinstance(command, str) else json.dumps(command, default=str)
        answer, guard = offline_answer(text)
        guard = guard or files_reason(payload)
        if guard:
            answer = deny_answer(guard)
        count_offline_answer()
        record.update(
            decision=answer["permission"], offline=True, reason="recorder_unreachable", guard=guard
        )
        append_log(record)
        return answer


def run(args: list[str], raw: bytes, start: float) -> dict[str, str]:
    if args and args[0] != "cursor":
        say(f"unknown agent {args[0][:40]!r}; allowing")
        return {"permission": "allow"}
    payload: dict[str, Any] | None = parse_payload(raw)
    if payload is None:
        return unreadable(raw)
    event: str = str(payload.get("hook_event_name", ""))
    given: str = args[1] if len(args) > 1 else ""
    if given and given != event:
        if event:
            say("event argument and payload event differ; using the argument")
        event = given
        payload["hook_event_name"] = given
    return ask_recorder(payload, event, start)


def main(argv: list[str] | None = None) -> int:
    start: float = time.monotonic()
    args: list[str] = list(sys.argv[1:] if argv is None else argv)
    raw: bytes = b""
    try:
        raw = read_stdin()
        answer: dict[str, str] = run(args, raw, start)
    except BaseException as exc:  # noqa: BLE001 - nothing may escape: no deny is ever lost
        say(f"internal error ({type(exc).__name__}); offline guard applied")
        try:
            answer, _ = guard_raw(raw)
        except BaseException:  # noqa: BLE001
            answer = {"permission": "allow"}
    emit(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Hook client (`agentfly-hook <agent> <event>`): strip, ask the local recorder, print the answer.

Standard library only, one file, run with `python -I -S`. Stdout holds ONLY the JSON answer and the
exit code is always 0 (exit 2 would block the action); diagnostics go to stderr and never carry
payload text. If the recorder does not answer, the offline guard (SPEC section 9, D4) answers.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

TYPE_CHECKING = False  # `import typing` alone costs ~5 ms per call
if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
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
# The Grep tool's `tool_input` fields that go to the recorder beside `file_path` (not `pattern`).
_SEARCH_KEEP: tuple[str, ...] = ("glob", "output_mode")
_AGENT_SUFFIX: str = "Do not retry with another tool or language. Stop and tell the user."

# Offline guard (SPEC section 9): a word-level copy of what agentfly/recorder/rules.py treats as
# outbound, plus R0's guard paths. tests/test_offline_guard.py runs both over the same cases.
_ALWAYS_OUTBOUND: frozenset[str] = frozenset({"gh", "aws"})
_HOSTED_OUTBOUND: frozenset[str] = frozenset({"curl", "wget", "nc", "scp", "ssh", "rsync"})
_INTERPRETERS: tuple[str, ...] = ("python", "node")  # name prefixes: python3.12, nodejs
_GUARD_PATHS: tuple[str, ...] = (  # the same list as `_R0_PATHS` in agentfly/recorder/rules.py
    ".config/agentfly",
    ".local/share/agentfly",
    "/library/application support/agentfly",
    "hooks.json",
    "dev.agentfly.recorder",
    "homebrew.mxcl.agentfly",
    "sh.brew.agentfly",
    "uv/tools/agentfly-recorder",
    "pipx/venvs/agentfly-recorder",
    "site-packages/agentfly",
    "/cellar/agentfly",
    "/homebrew/opt/agentfly",
    "/local/opt/agentfly",
    ".local/bin/agentfly",
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
        kept: dict[str, Any] = {}
        if isinstance(tool_input, dict):
            if isinstance(tool_input.get("file_path"), str):
                kept["file_path"] = tool_input["file_path"]
            # A search's file-name pattern and what it returns, never its search text. A value
            # that is not a string goes as null: present, so the recorder counts it as a read.
            for key in _SEARCH_KEEP if tool_name == "grep" else ():
                if key in tool_input:
                    value: Any = tool_input[key]
                    kept[key] = value if isinstance(value, str) else None
        if kept:
            out["tool_input"] = kept
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


# What a one-liner walk does at one word of an interpreter's options: CODE (inline code, yes),
# END (the options end here, no), or how many words it moves on (2 when the word's option takes
# the next word as its value). A walk is these steps from the word after the interpreter's name.
_CODE: int = -1
_END: int = 0


def _python_step(arg: str) -> int:
    """`-c` in python's own options, found letter by letter (`-Sc`, `-c1`, `-X dev -c`)."""
    if arg == "--" or not arg.startswith("-") or arg.startswith("-m"):
        return _END  # the script (first plain word), `--`, or `python -m module`
    if arg.startswith("--"):
        return 2 if arg == "--check-hash-based-pycs" else 1
    for index, letter in enumerate(arg[1:], 1):
        if letter == "c":
            return _CODE
        if letter == "m":
            return _END
        if letter in "WXQ":  # the rest of the word, or the next word, is its value
            return 2 if index == len(arg) - 1 else 1
    return 1


def _node_stop(arg: str) -> bool:
    """`--` or a word that names a script file: node's options end there."""
    return arg == "--" or arg.endswith((".js", ".mjs", ".cjs", ".ts"))


def _node_code(arg: str) -> bool:
    """`-e`, `-p` (alone or clustered), `--eval[=]`, `--print[=]`."""
    if arg.startswith(("--eval", "--print")):
        return True
    letters: str = arg[1:]
    return (
        arg.startswith("-")
        and not arg.startswith("--")
        and letters.isalpha()
        and ("e" in letters or "p" in letters)
    )


def _node_step(arg: str) -> int:
    """Node has too many options that take a value to walk past them, so its options end at the
    first word that names a script file or at `--`, and a `-e`, `-p`, `--eval` or `--print`
    before that is code."""
    return _END if _node_stop(arg) else _CODE if _node_code(arg) else 1


def _script_family(name: str) -> str | None:
    """'perl' for perl, perl5.34; 'ruby' for ruby, ruby3.2; else None (`perldoc` is neither)."""
    base: str = name.rstrip("0123456789.")
    return base if base in ("perl", "ruby") else None


# What `-M`, `-m`, `-d:` and `-dt:` may name in perl and still be a module (`Foo::Bar`, `-strict`,
# `Foo=a,b`); anything else is code perl runs (`-MIO::Socket;print 1`), V5c.
PERL_MODULE: str = "(?a)" r"-?[A-Za-z_]\w*(?:::\w+)*(?:=[\w:]+(?:,[\w:]+)*)?"


def _perl_value(arg: str, index: int) -> str | None:
    """The module a `-d:` or `-dt:` at `index` names, else None."""
    for lead in (":", "t:"):
        if arg.startswith(lead, index + 1):
            return arg[index + 1 + len(lead) :]
    return None


def _perl_step(arg: str) -> int:
    """`-e` or `-E` in perl's own options, found letter by letter (`-lane`, `-MIO::Socket -e`).

    `-M` and `-m` take the rest of their word (`-MIO::Socket` holds an `e`), as do `-d:` and
    `-dt:`, and that rest is code unless it is a module name (`PERL_MODULE`); `-I` takes the rest
    or, alone, the next word; a long option (`--version`) takes nothing. The script (the first
    plain word), `-` or `--` ends the options.
    """
    if arg in ("-", "--") or not arg.startswith("-"):
        return _END
    if arg.startswith("--"):
        return 1
    for index, letter in enumerate(arg[1:], 1):
        if letter in "eE":
            return _CODE
        if letter in "Mm":
            return 1 if re.compile(PERL_MODULE).fullmatch(arg[index + 1 :]) else _CODE
        if letter == "I":
            return 2 if index == len(arg) - 1 else 1
        value: str | None = _perl_value(arg, index) if letter == "d" else None
        if value is not None:
            return 1 if re.compile(PERL_MODULE).fullmatch(value) else _CODE
    return 1


# Ruby's long options that take the next word as their value (unless it is glued on with `=`).
_RUBY_VALUE_OPTIONS: frozenset[str] = frozenset(
    {
        "--enable",
        "--disable",
        "--dump",
        "--encoding",
        "--external-encoding",
        "--internal-encoding",
        "--backtrace-limit",
        "--parser",
        "--crash-report",
    }
)


def _ruby_step(arg: str) -> int:
    """`-e` in ruby's own options, found letter by letter (`-ne`, `-rnet/http -e`, `-We`).

    `-r`, `-I`, `-C`, `-X` and `-E` (an encoding, not code) take the rest of their word or, alone,
    the next word; `-x`, `-F`, `-i` and `-W:` take the rest of their word; `-K` takes one
    character (`-Ke` is a character set) and `-0`, `-T` and `-W` their digits, and the letters
    after those are options again (`-0e` is code). The script (the first plain word), `-` or `--`
    ends the options.
    """
    if arg in ("-", "--") or not arg.startswith("-"):
        return _END
    if arg.startswith("--"):
        return 2 if arg in _RUBY_VALUE_OPTIONS else 1
    index: int = 1
    while index < len(arg):
        letter: str = arg[index]
        index += 1
        if letter == "e":
            return _CODE
        if letter in "rICXE":
            return 2 if index == len(arg) else 1
        if letter in "xFi" or (letter == "W" and arg[index : index + 1] == ":"):
            return 1
        if letter == "K":
            index += 1
        elif letter in "0TW":
            while index < len(arg) and arg[index].isdigit():
                index += 1
    return 1


_STEPS: dict[str, Callable[[str], int]] = {
    "python": _python_step,
    "node": _node_step,
    "perl": _perl_step,
    "ruby": _ruby_step,
}


def _one_liner_table(args: Sequence[str], step: Callable[[str], int]) -> list[bool]:
    """For every position i: does a walk of these steps over `args[i:]` find code?

    Worked out once for the whole command, from the right, so each word is stepped on once
    however many interpreter names the command holds (`perl -I perl -I perl ...`, `-/ruby`): a
    walk from each name would read the rest again.
    """
    found: list[bool] = [False] * (len(args) + 2)
    for at in range(len(args) - 1, -1, -1):
        move: int = step(args[at])
        found[at] = move == _CODE or (move != _END and found[at + move])
    return found


def _inline_code(argv: list[str], names: list[str]) -> bool:
    """An inline one-liner: `python -c`, `node -e`, `perl -e`, `ruby -e` (SPEC section 9 denies
    every one).

    Only the words after the interpreter are looked at, so the `-c` of `bash -c 'python3 x.py'`
    or of `python3 -m pytest -c cfg` is not taken for it.
    """
    tables: dict[str, list[bool]] = {}  # `_one_liner_table`, one per family, made when needed
    for index, name in enumerate(names):
        family: str | None = _interpreter(name) or _script_family(name)
        if family is None:
            continue
        if family not in tables:
            tables[family] = _one_liner_table(argv, _STEPS[family])
        if tables[family][index + 1]:
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


# ---- piped code (V5c): the stdin walk of agentfly/recorder/normalize.py, at word level

_SHELLS: frozenset[str] = frozenset({"sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh"})
_SHELL_VALUE_OPTIONS: frozenset[str] = frozenset({"--rcfile", "--init-file"})
_RUNNERS: frozenset[str] = frozenset(  # `normalize.RUNNERS`
    {"uv", "uvx", "arch", "xcrun", "bundle", "poetry", "pipenv", "pdm", "hatch", "conda"}
    | {"pyenv", "rbenv", "nodenv", "mise", "asdf", "npx", "pnpm", "yarn"}
)
_RUNNER_VERBS: frozenset[str] = frozenset({"run", "exec", "x", "dlx", "tool"})
_WRAPPERS: frozenset[str] = _RUNNERS | frozenset(  # `normalize.WRAPPERS`, and `eval` (the
    {"sudo", "doas", "env", "xargs", "parallel", "timeout", "gtimeout", "nice", "nohup"}  # recorder
    | {"command", "builtin", "exec", "time", "stdbuf", "caffeinate", "script", "eval"}  # reads its
)  # words again as a command)
_DURATION: str = r"\d+(?:\.\d+)?[smhd]?"
_KEYWORDS: frozenset[str] = frozenset(
    {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "fi", "done", "esac"}
)
_HEADS: frozenset[str] = frozenset({"for", "select", "case"})
_ASSIGNMENT: str = r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?="
_NODE_VALUE_OPTIONS: frozenset[str] = frozenset(
    {"-r", "--require", "-C", "--conditions", "--import", "--loader", "--experimental-loader"}
    | {"--input-type", "--env-file", "--env-file-if-exists", "--title"}
)
_DEV_FD: str = r"/dev/fd/\d+"
_NODE_SCRIPT: str = r"/|\.[cm]?[jt]s$"
# A fed shell's `-c` script is read as a word (a stage) and as a command line, this many levels
# deep at most; deeper, it counts as reading code from the pipe.
_SCRIPT_DEPTH: int = 4
_STDIN: int = -1
_SCRIPT: int = 0
_SUB: str = "\x00"  # stands for a `$(`, a backtick, `<(` or `>(` in a stage's words
# A stage that may read piped code: a single `|` (`|&` too, never `||`) or `>(`, what may lead the
# command (blanks, a comment, `(`, `{`, `!`), then its text up to the first name of an interpreter
# or a shell in it. A stage ends where the next begins (`_CUT`); runs of characters that neither
# end it nor start a name are taken whole and never given back, so a try that finds no name fails
# at the stage's end, and the text is read about once, in C, however many stages it has. Each
# pattern starts with its operator, so `re` jumps from one to the next: measured, 1 MiB of `a | `
# costs about 150 ms (the rest of the guard about 250 ms), text with no `|` almost nothing.
_NAMES: str = r"(?i:python|node|perl|ruby|sh)"
_STAGE_TO_NAME: str = (
    r"(?:\s|[({!]|#[^\n]*)*+(?P<start>)"
    rf"(?:[^;&|\n)>\s#pnrsPNRS]++|\s(?!#)|>(?!\()|&(?=>)|(?<=[<>])&|#|(?!{_NAMES})[pnrsPNRS])*+"
    rf"{_NAMES}"
)
_FED_STAGES: tuple[str, ...] = (r"(?<!\|)\|(?!\|)&?" + _STAGE_TO_NAME, r">\(" + _STAGE_TO_NAME)
_CUT: str = r";|(?<![<>])&(?!>)|\||\n|\)|\s#|>\("
_STDIN_SUB: str = r"<[ \t]*<\("  # `python3 < <(cat x)`
_OWNER_START: str = ";|&\n(){}`'\""
_REDIRECT: str = r"(\d*)(<<<|<<-?|<>|<|>>|>)(.*)"
_DUPLICATE: str = r"(?:(?<!\S)\d+)?[<>]&[\d-]+"  # `2>&1`, `<&0`, `<&-`: no file, no word
# Past this many stages or `< <(`, the guard denies without reading more (as the recorder's limit
# rule does): each costs a walk in Python.
_PIPE_STAGES: int = 1000
# F18: the words the piped-code check reads in all: each fed stage's words and one more (a `-c`
# word read as a stage too), each stage read again with quotes kept whole (its words, and each
# quote and backslash in it: each a piece taken off in Python, F18-fix2), and the commands of
# each `-c` script. They are counted right after the C-speed split, before any walk in Python;
# past the count the text counts as piped code. A quoted word may be 1 MiB long, so the count
# alone does not bound the bytes read again: a stage that starts inside the last such read is not
# read again (`_fed_stage_reads`).
_PIPED_WORDS: int = 20_000
# F18-fix3: the bytes the quote-aware re-reads of one command take in all, whatever the text holds:
# each stage read again with quotes kept whole and each `-c` script read as a command line. Each
# is more passes in C over its text, and a nest of scripts is read once per depth; past this many
# bytes the text counts as piped code. F18's 256 KiB quoted word is read in about 263 KiB.
_REREAD_BYTES: int = 512 * 1024
# A stage read again with quotes kept whole: its text up to the first `_CUT` outside quotes and
# backslashes (an unclosed quote is read as a character).
_QUOTED_STAGE: str = (
    r"""(?s)(?:[^;&|\n)'"\\>\s]++|'[^']*+'|"(?:[^"\\]++|\\.)*+"|\\.|['"\\]"""
    r"""|[^\S\n](?!#)|>(?!\()|(?<=[<>])&|&(?=>))*+"""
)
# A word's pieces the shell does not expand (a backslash's character, a single-quoted run): what is
# left (`\1`: plain text and double-quoted runs) may hold a `$(` or a backtick.
_UNEXPANDED: str = r"""(?s)\\.|'[^']*+'|("(?:[^"\\]++|\\.)*+")"""
# The guard's patterns are kept as text and compiled on first use (`re` keeps them): the client
# starts on every hook, and the guard runs only when the recorder does not answer.


def _programs(argv: Sequence[str]) -> range | tuple[int, ...]:
    """`normalize.programs(narrow=True)`: the first word after assignments and keywords; after a
    wrapper, the program plainly next to it, down the chain, or every word if an option or
    `parallel` comes first."""
    assignment: re.Pattern[str] = re.compile(_ASSIGNMENT)
    for index, word in enumerate(argv):
        if word in _KEYWORDS or assignment.match(word):
            continue
        if word in _HEADS:
            return ()
        if word.split("/")[-1].lower() not in _WRAPPERS:
            return (index,)
        return _chain(argv, index, assignment)
    return ()


def _chain(argv: Sequence[str], at: int, assignment: re.Pattern[str]) -> range | tuple[int, ...]:
    """`normalize._chain`."""
    found: list[int] = [at]
    while (name := argv[at].split("/")[-1].lower()) in _WRAPPERS:
        if name == "parallel":
            return range(found[0], len(argv))
        at += 1
        duration: bool = at < len(argv) and re.compile(_DURATION).fullmatch(argv[at]) is not None
        if name in ("timeout", "gtimeout") and duration:
            at += 1
        while at < len(argv) and (
            (name in _RUNNERS and argv[at] in _RUNNER_VERBS)
            or (name in ("env", "sudo") and assignment.match(argv[at]))
        ):
            at += 1
        if at >= len(argv):
            break
        if argv[at].startswith("-"):
            return range(found[0], len(argv))
        found.append(at)
    return tuple(found)


def _is_stdin(word: str) -> bool:
    return word == "-" or _is_stdin_device(word)


def _is_stdin_device(word: str) -> bool:
    # D/F4: fold `//`→`/` and `/./`→`/` first (`/dev/./stdin`, `/dev/fd//0`, `//dev/stdin`).
    while "//" in word:
        word = word.replace("//", "/")
    while "/./" in word:  # `/././` needs more than one pass
        word = word.replace("/./", "/")
    if word == "/dev/stdin":
        return True
    return word.startswith("/dev/fd/") and re.compile(_DEV_FD).fullmatch(word) is not None


def _stdin_step(family: str, words: Sequence[str], at: int, count: _Count, depth: int) -> int:
    """`normalize._stdin_step`: _STDIN, _SCRIPT, or how many words the walk moves on. A shell's
    `-c` reads the pipe when its script holds a substitution (`bash -c "$(cat)"`) or its word,
    read as a stage, does (main's read: it covers what the quote-aware read skips or misreads);
    what the script runs is also read from the stage's text, quotes kept whole (`_scripts_read`)."""
    arg: str = words[at]
    if _is_stdin(arg):
        return _STDIN
    if arg == "--":
        return _STDIN if at + 1 >= len(words) or _is_stdin(words[at + 1]) else _SCRIPT
    if family == "shell":
        if not arg.startswith(("-", "+")):
            return _SCRIPT
        if arg.startswith("--"):
            return 2 if arg in _SHELL_VALUE_OPTIONS else 1
        if "c" in arg[1:]:
            if at + 1 >= len(words):
                return _SCRIPT
            script: str = words[at + 1]
            fed: bool = _SUB in script or _stage_reads_stdin(script, count, depth + 1)
            return _STDIN if fed else _SCRIPT
        if "s" in arg[1:]:
            return _STDIN
        return 2 if ("o" in arg[1:] or "O" in arg[1:]) else 1
    if not arg.startswith("-"):
        return _SCRIPT
    if family == "node":
        return _STDIN if _node_code(arg) else 2 if _node_takes_value(words, at) else 1
    move: int = _STEPS[family](arg)
    return _STDIN if move == _CODE else _SCRIPT if move == _END else move


def _node_takes_value(words: Sequence[str], at: int) -> bool:
    """`normalize._node_takes_value`."""
    arg: str = words[at]
    if arg in _NODE_VALUE_OPTIONS:
        return True
    if not arg.startswith("--") or "=" in arg or at + 1 >= len(words):
        return False
    return re.compile(_NODE_SCRIPT).search(words[at + 1]) is None


def _reads_stdin(words: Sequence[str], count: _Count, depth: int) -> bool:
    """`normalize.reads_stdin`: an interpreter or a shell at a program position that names no
    script, worked out from the right once per family (linear)."""
    tables: dict[str, list[bool]] = {}
    for at in _programs(words):
        name: str = words[at].split("/")[-1].lower()
        family: str | None = (
            ("shell" if name.rstrip("0123456789.") in _SHELLS else None)
            or _interpreter(name)
            or _script_family(name)
        )
        if family is None:
            continue
        if family not in tables:
            found: list[bool] = [True] * (len(words) + 2)
            for index in range(len(words) - 1, -1, -1):
                move: int = _stdin_step(family, words, index, count, depth)
                found[index] = move == _STDIN or (move > 0 and found[index + move])
            tables[family] = found
        if tables[family][at + 1]:
            return True
    return False


class _Count:
    """The words the piped-code check may still read (`_PIPED_WORDS`) and the bytes its
    quote-aware re-reads may still take (`_REREAD_BYTES`)."""

    def __init__(self) -> None:
        self.left: int = _PIPED_WORDS
        self.bytes_left: int = _REREAD_BYTES

    def spend(self, words: int) -> bool:
        """Count `words` more; True once past the count (the text then counts as piped code)."""
        self.left -= words
        return self.left < 0

    def reread(self, size: int) -> bool:
        """Count `size` more bytes read again; True once past the budget (piped code too)."""
        self.bytes_left -= size
        return self.bytes_left < 0


def _stage_reads_stdin(stage: str, count: _Count, depth: int = 0) -> bool:
    """One command of a pipe, as raw text: its redirects dropped (stdin from a file names the
    script; from `<(`, a herestring, a heredoc, `/dev/stdin` or another fd it is code; `3<` is not
    stdin), then the stdin walk. Its words are counted before the walk."""
    if depth > _SCRIPT_DEPTH:
        return True
    for start in ("$(", "`", "<(", ">("):
        stage = stage.replace(start, f" {_SUB} ")
    stage = re.compile(_DUPLICATE).sub(" ", stage)
    argv: list[str] = []
    found: list[str] = words(stage)
    if count.spend(len(found) + 1):
        return True
    redirect_word: re.Pattern[str] = re.compile(_REDIRECT)
    index: int = 0
    while index < len(found):
        redirect: re.Match[str] | None = redirect_word.fullmatch(found[index])
        if redirect is None:
            argv.append(found[index])
            index += 1
            continue
        fd, operator, target = redirect.groups()
        if not target:
            index += 1
            target = found[index] if index < len(found) else ""
        index += 1
        if operator not in ("<", "<>") or fd not in ("", "0") or target.startswith("&"):
            continue
        if _SUB not in target and not _is_stdin_device(target):
            return False  # `python3 < x.py`
    return _reads_stdin(argv, count, depth)


def _fed_stage_reads(
    text: str, start: int, end: int, count: _Count, depth: int, read_to: int
) -> tuple[bool, int]:
    """Whether the fed stage `text[start:end]` (cut at `_CUT`) reads code from the pipe: its stdin
    walk, then the stage read again with quotes kept whole (`_scripts_read`), unless it starts
    before `read_to`, where the last such read ended: its `|` sits in a quoted word that read
    took whole (its `-c` word is still read by the stdin walk). Returns that and where the reads
    have now reached, so they cover the text once."""
    if _stage_reads_stdin(text[start:end], count, depth):
        return True, read_to
    if start < read_to:
        return False, read_to
    return _scripts_read(text, start, count, depth)


def _scripts_read(text: str, start: int, count: _Count, depth: int) -> tuple[bool, int]:
    """The stage at `start` read as the recorder reads it, quotes kept whole, to its first `_CUT`
    outside quotes: whether a shell in it (any word; a versioned name too) runs a `-c` script that
    reads the pipe, and where the stage ends. A script reads it when it holds a `$(` or backtick
    the shell expands (`normalize._shell_stdin_step`), or when a command of it does: each is fed,
    as the recorder feeds every command of a fed shell's script (`_line_reads`)."""
    stage: re.Match[str] | None = re.compile(_QUOTED_STAGE).match(text, start)
    end: int = stage.end() if stage else start
    if count.reread(end - start):
        return True, end
    raw: list[str] = re.compile(_QUOTED_WORD).findall(text, start, end)
    # each piece `_unquoted` or `_UNEXPANDED` takes off holds a quote or a backslash (F18-fix2)
    pieces: int = sum(text.count(c, start, end) for c in "'\"\\")
    if count.spend(len(raw) + pieces):
        return True, end
    argv: list[str] = [_unquoted(w) if any(q in w for q in "'\"\\") else w for w in raw]
    found: dict[int, None] = {}  # each script once, however many shells find it
    table: list[int | None] = []  # `_script_indexes(argv)`, at the first shell
    for at, word in enumerate(argv):
        if word.split("/")[-1].lower().rstrip("0123456789.") not in _SHELLS:
            continue
        table = table or _script_indexes(argv)
        if (script := table[at + 1]) is not None:
            found[script] = None
    for script in found:
        expanded: str = re.compile(_UNEXPANDED).sub(r"\1", raw[script])
        if "$(" in expanded or "`" in expanded:
            return True, end
    scripts: dict[str, None] = dict.fromkeys(argv[script] for script in found)
    return any(_line_reads(script, count, depth + 1) for script in scripts), end


def _script_indexes(argv: Sequence[str]) -> list[int | None]:
    """`normalize.script_indexes`: for each index (and the two past the end), the index of the
    `-c` script a shell's option walk finds from there, or None; worked out from the right once."""
    found: list[int | None] = [None] * (len(argv) + 2)
    for index in range(len(argv) - 1, -1, -1):
        arg: str = argv[index]
        if arg == "--" or not arg.startswith(("-", "+")):
            continue
        if arg.startswith("--"):
            found[index] = found[index + (2 if arg in _SHELL_VALUE_OPTIONS else 1)]
        elif "c" in arg[1:]:
            found[index] = index + 1 if index + 1 < len(argv) else None
        else:
            found[index] = found[index + (2 if ("o" in arg[1:] or "O" in arg[1:]) else 1)]
    return found


def _line_reads(script: str, count: _Count, depth: int) -> bool:
    """A `-c` script read as a command line: each of its commands (cut at `_CUT`) a fed stage.
    Past _SCRIPT_DEPTH scripts deep, or past the re-read budget, it counts as reading the pipe."""
    if depth > _SCRIPT_DEPTH or count.reread(len(script)):
        return True
    start: int = 0
    read_to: int = 0
    for found in re.compile(_CUT).finditer(script):
        reads, read_to = _fed_stage_reads(script, start, found.start(), count, depth, read_to)
        if reads:
            return True
        start = found.end()
    return _fed_stage_reads(script, start, len(script), count, depth, read_to)[0]


def _piped_code(text: str) -> bool:
    """Code piped into an interpreter or a shell that names no script (SPEC section 9): the
    command after a `|` (`echo 'print(1)' | python3`), inside `>(` (`cat x > >(sh)`) or before
    `< <(` (`python3 < <(cat x)`), and a fed shell's `-c` script read as a command line (F18:
    `… | sh -c 'cd /tmp && python3'`). Stages with no interpreter or shell name are skipped in C
    (`_FED_STAGES`); past _PIPE_STAGES of either kind, or past _PIPED_WORDS words read, the text
    counts as piped code."""
    text = text.replace("\\\n", " ")  # a line continuation: `| \` and a newline go on
    cut: re.Pattern[str] = re.compile(_CUT)
    count: _Count = _Count()
    stages: int = 0
    for source in _FED_STAGES:
        read_to: int = 0
        for fed in re.compile(source).finditer(text):
            stages += 1
            if stages > _PIPE_STAGES:
                return True
            start: int = fed.start("start")
            end: re.Match[str] | None = cut.search(text, start)
            stop: int = end.start() if end else len(text)
            reads, read_to = _fed_stage_reads(text, start, stop, count, 0, read_to)
            if reads:
                return True
    # A `-c` word read past the count answers only for its place in a walk: the count spent decides
    if "<(" not in text:
        return count.left < 0
    after: int = 0  # where the last `< <(` ended: an owner starts no earlier
    for number, sub in enumerate(re.compile(_STDIN_SUB).finditer(text)):
        if number >= _PIPE_STAGES:
            return True
        start = max(after, *(text.rfind(c, after, sub.start()) + 1 for c in _OWNER_START))
        if _stage_reads_stdin(text[start : sub.start()] + " < " + _SUB, count):
            return True
        after = sub.end()
    return count.left < 0


# A perl module value with a `;` or a space in it is quoted (`perl '-MIO::Socket;print 1' x.pl`),
# which `words` splits: these words keep a quoted part whole. A word that still holds a space is
# a quoted command (`bash -c '...'`) and is read again, at most _QUOTED_DEPTH times.
_QUOTED_WORD: str = r"""(?s)(?:[^\s'"\\;|&()<>`]++|\\.|'[^']*+'|"(?:[^"\\]++|\\.)*+")++"""
_QUOTED_PART: str = r"(?s)\\(.)|'([^']*+)'|" + r'"((?:[^"\\]++|\\.)*+)"'
_QUOTED_DEPTH: int = 4
_QUOTED_WORDS: int = 20_000  # past this many quote-aware words in all, the text counts as code


def _unquoted(word: str) -> str:
    """The word with its quotes and backslashes taken off, as the shell would."""
    return re.compile(_QUOTED_PART).sub(lambda m: "".join(g or "" for g in m.groups()), word)


def _quoted_one_liner(text: str) -> bool:
    """A perl one-liner hidden in a quoted module value, read with quotes kept whole. Each pass
    reads at most the text once, and a word only comes back while it holds a space; past
    _QUOTED_WORDS words the text counts as one."""
    lists: list[str] = [text]
    quoted: re.Pattern[str] = re.compile(_QUOTED_WORD)
    space: re.Pattern[str] = re.compile(r"\s")  # what `str.isspace` takes, without a loop a letter
    read: int = 0
    for _ in range(_QUOTED_DEPTH):
        again: list[str] = []
        for chunk in lists:
            found: list[str] = quoted.findall(chunk)
            read += len(found)
            if read > _QUOTED_WORDS:
                return True
            argv: list[str] = [_unquoted(w) if any(q in w for q in "'\"\\") else w for w in found]
            names: list[str] = [a.split("/")[-1].lower() for a in argv]
            perls: list[int] = [i for i, name in enumerate(names) if _script_family(name) == "perl"]
            if perls:
                table: list[bool] = _one_liner_table(argv, _perl_step)
                if any(table[i + 1] for i in perls):
                    return True
            again += [word for word in argv if space.search(word)]
        lists = again
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
    if _outbound_words(words(text), folded) or _piped_code(text):
        return "outbound"
    quotes: bool = any(q in text for q in "'\"\\")
    return "outbound" if quotes and "perl" in folded and _quoted_one_liner(text) else None


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


def _json_strings(text: str) -> str:
    """Raw hook text with its JSON strings read (`\\\\`, `\\"`, `\\n`, `\\t`, `\\r`, `\\/`) and
    each bare `"` a new line, at C speed: a cut-off payload's command then ends where its string
    does (`"echo 1 | node", "cwd"` names no script `,`). A `\\u` escape is left as written."""
    text = text.replace("\\\\", "\x01").replace('\\"', "\x02").replace('"', "\n")
    for escape, plain in (("\\n", "\n"), ("\\t", "\t"), ("\\r", "\r"), ("\\/", "/")):
        text = text.replace(escape, plain)
    return text.replace("\x02", '"').replace("\x01", "\\")


def guard_raw(raw: bytes) -> tuple[dict[str, str], str | None]:
    """The offline guard on input that could not be read as a hook payload: on its raw text, and
    piped code on that text with its JSON strings read too (`_json_strings`)."""
    if len(raw) > _MAX_GUARD_TEXT:  # a tool name may sit at either end of a cut-off payload
        half: int = _MAX_GUARD_TEXT // 2
        raw = raw[:half] + b" " + raw[-half:]
    text: str = raw.decode("utf-8", "replace")
    answer, reason = offline_answer(text)
    if reason is None and _piped_code(_json_strings(text)):
        return deny_answer("outbound"), "outbound"
    return answer, reason


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

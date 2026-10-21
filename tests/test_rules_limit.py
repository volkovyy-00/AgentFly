"""V5b-fix2 §4.3: what a rule left unfinished by the hook's meter does.

A floating path pattern charges the hook's meter (`rules.one_hook`); once the budget is spent the
rule being run is unfinished. An unfinished block rule denies with the limit rule (unless R0 or R1
fires), an unfinished warn asks with the limit rule, an unfinished highlight is skipped, and an
unfinished trigger is never recorded. Outside a hook nothing is charged and the engine answers as
before.
"""

from __future__ import annotations

import itertools
import logging
import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.rules as rules_mod
from agentfly.cli.rules_test import run_tests
from agentfly.recorder import rulefile
from agentfly.recorder.memory import memory_steps
from agentfly.recorder.rules import (
    BLOCK_TAIL,
    DEFAULT,
    LIMIT_ID,
    LIMIT_MESSAGE,
    LIMIT_RULE,
    LIMIT_WARN_RULE,
    SKIP_TAIL,
    Rule,
    RuleSet,
    Session,
    find_rule,
    mark,
    one_hook,
    winning_rule,
)
from tests.recorder_harness import Recorder
from tests.rules_helpers import default_with, list_line, ruleset_of
from tests.test_rules_cost import BIPARTITE_LINE, bipartite_list, command, match_rule
from tests.test_severities import push
from tests.test_severities import rule as severity_rule
from tests.test_severities import ruleset as severity_ruleset
from tests.test_step_merge import event, live, post, pre

# Five floating patterns: every word of `command(20)` holds `d…` folders and no `zN` folder, so
# every middle walk runs to the end, none matches, and the budget runs out.
HEAVY_LIST = list_line("l", *[f"d*/d*/d*/z{n}/**" for n in range(5)])
CHEAP_LISTS = 'cat_cmds = ["cat"]\n'
MATCH_ID = "m0"
TRIGGER_ID = "t0"
R1_AT = '[[rule]]\nid = "R1"'


def heavy_rule(severity: str, kind: str = "match") -> str:
    if kind == "match":
        return match_rule(0, 'path = "l"', severity)
    return f"""
[[rule]]
id = "{TRIGGER_ID}"
kind = "after_then"
severity = "{severity}"
message = "x"
after = {{ event = ["shell"], path = "l" }}
then = {{ event = ["shell"], command = "cat_cmds" }}
"""


def heavy_id(kind: str) -> str:
    return MATCH_ID if kind == "match" else TRIGGER_ID


def heavy(severity: str, kind: str = "match") -> RuleSet:
    """The packaged default plus the heavy rule after it."""
    return ruleset_of(default_with(HEAVY_LIST + CHEAP_LISTS, heavy_rule(severity, kind)))


def cheap_block() -> str:
    return """
[[rule]]
id = "cheap"
kind = "match"
severity = "block"
message = "no cat"
event = ["shell"]
command = "cat_cmds"
"""


def shell(text: str) -> dict[str, Any]:
    return {"hook_event_name": "beforeShellExecution", "command": text}


def session(*, marked: bool = False, triggers: frozenset[str] = frozenset()) -> Session:
    return Session(id="s", marked=marked, start_time="t", next_step=1, triggers=triggers)


HEAVY = shell(command(20))


def test_the_heavy_command_runs_the_budget_out() -> None:
    """The premise of every test here: a fresh hook cannot finish the heavy rule."""
    with one_hook() as meter:
        assert winning_rule(HEAVY, session(), heavy("highlight")) is None
    assert meter.left < 0 and meter.unfinished == [MATCH_ID]


def test_outside_a_hook_the_engine_answers_as_before() -> None:
    assert rulefile.current_meter() is None
    ran, failures = run_tests(rulefile.load_default(), Path("default.toml"))
    assert ran > 0 and failures == []
    for order in itertools.permutations(["block", "warn", "highlight"]):
        rs = severity_ruleset(*(severity_rule(f"r-{sev}", sev, f"{sev} text") for sev in order))
        assert winning_rule(push(), session(), rs).id == "r-block"
    # The heavy rule itself, with no meter: it runs to the end and does not fire.
    assert winning_rule(HEAVY, session(), heavy("block")) is None


def test_r0_and_r1_answer_as_usual_at_the_limit() -> None:
    text = default_with(HEAVY_LIST)
    at = text.index(R1_AT)
    rs = ruleset_of(text[:at] + heavy_rule("block").lstrip("\n") + "\n" + text[at:])
    ids = [r.id for r in rs.rules]
    assert ids.index(MATCH_ID) < ids.index("R1")

    with one_hook() as meter:
        rule = winning_rule(shell(f"{command(20)}; curl https://x.com"), session(marked=True), rs)
    assert rule is not None and rule.id == "R1"
    assert MATCH_ID in meter.unfinished

    with one_hook():
        rule = winning_rule(shell(f"{command(20)} ~/.config/agentfly/token"), session(), rs)
    assert rule is not None and rule.id == "R0"


def test_an_unfinished_block_rule_gives_the_limit_rule() -> None:
    with one_hook() as meter:
        assert winning_rule(HEAVY, session(), heavy("block")) is LIMIT_RULE
    assert MATCH_ID in meter.unfinished


def test_a_fired_block_before_an_unfinished_one_wins_and_one_after_it_does_not() -> None:
    lists = HEAVY_LIST + CHEAP_LISTS
    before = ruleset_of(default_with(lists, cheap_block(), heavy_rule("block")))
    with one_hook():
        rule = winning_rule(HEAVY, session(), before)
    assert rule is not None and rule.id == "cheap"

    after = ruleset_of(default_with(lists, heavy_rule("block"), cheap_block()))
    with one_hook() as meter:
        assert winning_rule(HEAVY, session(), after) is LIMIT_RULE
    assert MATCH_ID in meter.unfinished


def test_an_unfinished_warn_gives_the_limit_warn_rule() -> None:
    with one_hook() as meter:
        assert winning_rule(HEAVY, session(), heavy("warn")) is LIMIT_WARN_RULE
    assert MATCH_ID in meter.unfinished


def test_an_unfinished_highlight_is_skipped() -> None:
    with one_hook() as meter:
        assert winning_rule(HEAVY, session(), heavy("highlight")) is None
    assert MATCH_ID in meter.unfinished


@pytest.mark.parametrize(("severity", "limit"), [("block", LIMIT_RULE), ("warn", LIMIT_WARN_RULE)])
def test_an_unfinished_trigger_is_never_recorded(severity: str, limit: Rule) -> None:
    rs = heavy(severity, "after_then")
    with one_hook() as meter:
        marked = mark(HEAVY, session(), rs)
        assert TRIGGER_ID not in marked.triggers
        assert TRIGGER_ID in meter.unfinished
        assert winning_rule(HEAVY, marked, rs) is limit


def test_a_trigger_the_chat_holds_is_not_evaluated_again() -> None:
    rs = heavy("block", "after_then")
    calls: list[dict[str, Any]] = []

    def counting(rule: Rule) -> Rule:
        if rule.id != TRIGGER_ID:
            return rule
        after = rule.after
        assert after is not None

        def count(action: dict[str, Any]) -> bool:
            calls.append(action)
            return after(action)

        return replace(rule, after=count)

    rs = replace(rs, rules=tuple(counting(r) for r in rs.rules))
    with one_hook() as meter:
        mark(HEAVY, session(triggers=frozenset({TRIGGER_ID})), rs)
    assert calls == [] and meter.unfinished == []


def test_r1s_mark_is_set_when_the_hook_is_limit_denied() -> None:
    rs = heavy("block")
    action = shell("cat .env " + command(20).removeprefix("cat "))
    with one_hook() as meter:
        marked = mark(action, session(), rs)
        assert marked.marked
        assert winning_rule(action, marked, rs) is LIMIT_RULE
    assert MATCH_ID in meter.unfinished


def test_a_full_size_name_list_gets_no_limit_deny() -> None:
    names = list_line("l", *[f"n{i}.secret" for i in range(167)])
    rs = ruleset_of(default_with(names, match_rule(0, 'path = "l"', "block")))
    words = " ".join(f"{'w' * 21}{i:05d}.txt" for i in range(300))
    assert all(len(w) == 30 for w in words.split())
    with one_hook() as meter:
        assert winning_rule(shell(f"cat {words}"), session(), rs) is None
    assert meter.unfinished == []


def test_the_limit_rules_are_not_listed_and_are_found_by_id() -> None:
    assert LIMIT_ID not in [r.id for r in DEFAULT.rules]
    assert find_rule(LIMIT_ID) is LIMIT_RULE
    assert rulefile._ID.fullmatch(LIMIT_ID) is None
    assert LIMIT_RULE.severity == "block" and LIMIT_WARN_RULE.severity == "warn"
    assert LIMIT_RULE.message == LIMIT_WARN_RULE.message and LIMIT_WARN_RULE.id == LIMIT_ID
    assert not LIMIT_RULE.check(HEAVY, session())


def test_one_hook_reads_the_budget_at_each_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rulefile, "FLOAT_STEPS", 10)
    with one_hook() as meter:
        assert meter.left == 10 and rulefile.current_meter() is meter
    assert rulefile.current_meter() is None


# ---------------------------------------------------------------- the recorder (V5b-fix2 §4.4)

HEALTHY_KEYS = {"ok", "offline_guard_count", "last_hook_at"}
LIMIT_LINE = re.compile(
    r"rules limit reached by (\d+) hook\(s\) since the recorder started; "
    r"last at \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00, rules (.+)"
)


@pytest.fixture()
def rec(tmp_path: Path) -> Iterator[Recorder]:
    previous = app_module._store
    app_module.graph_store.enabled = False
    yield Recorder(tmp_path / "data")
    app_module._store = previous


@pytest.fixture()
def app_client() -> Iterator[TestClient]:
    """The app with its `lifespan` run (a bare `TestClient(app)` does not run it)."""
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        yield test_client


def test_the_recorder_denies_with_the_limit_message_in_both_fields(rec: Recorder) -> None:
    rules_mod.activate(heavy("block"))
    assert rec.run("P", command(20)) == {
        "permission": "deny",
        "user_message": LIMIT_MESSAGE,
        "agent_message": LIMIT_MESSAGE + BLOCK_TAIL,
    }


def test_a_padded_shell_command_with_an_unfinished_warn_asks(rec: Recorder) -> None:
    rules_mod.activate(heavy("warn"))
    assert rec.run("P", command(20)) == {
        "permission": "ask",
        "user_message": LIMIT_MESSAGE,
        "agent_message": LIMIT_MESSAGE + SKIP_TAIL,
    }


def test_an_unfinished_warn_on_a_read_is_allowed_and_the_step_shows_the_limit(
    rec: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rulefile, "FLOAT_STEPS", 10)  # one path cannot spend the real budget
    warn_on_read = match_rule(0, 'path = "l"', "warn", event="read")
    rules_mod.activate(ruleset_of(default_with(HEAVY_LIST + CHEAP_LISTS, warn_on_read)))
    deep = "/w/" + "/".join(f"d{k}" for k in range(20)) + "/f.py"
    assert rec.read("P", deep) == {"permission": "allow"}
    [step] = memory_steps.snapshot(all_steps=True)["steps"]
    assert (step["rule"], step["verdict"]) == (LIMIT_ID, "warned")


def test_a_limit_deny_records_no_trigger_and_a_restart_judges_as_before(rec: Recorder) -> None:
    """Review focus 1: the denied action does not run, so the trigger it would set is not kept."""
    rules_mod.activate(heavy("block", "after_then"))
    # The control: a path a floating pattern does match records the trigger, and `cat` is denied.
    assert rec.run("K", "ls /w/d/d/d/z0/f.py")["permission"] == "allow"
    assert rec.run("K", "cat notes.txt")["permission"] == "deny"

    rec.task("P", "T1")
    answer = rec.run("C", command(20), parent_tool_call_id="T1")
    assert (answer["permission"], answer["user_message"]) == ("deny", LIMIT_MESSAGE)
    for chat in ("P", "C"):
        stored = rec.store.get(chat)
        assert stored is not None and TRIGGER_ID not in stored.triggers
        assert rec.run(chat, "cat notes.txt")["permission"] == "allow"

    rec.restart()
    for chat in ("P", "C"):
        assert rec.run(chat, "cat notes.txt")["permission"] == "allow"
    assert rec.run("K", "cat notes.txt")["permission"] == "deny"  # a trigger that was set stays


def test_health_says_rules_limit_only_after_a_hit(app_client: TestClient) -> None:
    rules_mod.activate(heavy("block"))  # `lifespan` activated the rules it loaded: after it
    assert set(app_client.get("/health").json()) == HEALTHY_KEYS
    post(app_client, event("beforeShellExecution", "c", command="ls"))
    assert set(app_client.get("/health").json()) == HEALTHY_KEYS  # a hook that finished: no hit

    answer = post(app_client, event("beforeShellExecution", "c", command=command(20)))
    assert answer["permission"] == "deny"
    body = app_client.get("/health").json()
    assert set(body) == HEALTHY_KEYS | {"rules_limit"}
    line = body["rules_limit"]
    assert len(line) <= rulefile.MAX_PROBLEM_CHARS
    match = LIMIT_LINE.fullmatch(line)
    assert match is not None, line
    assert match.groups() == ("1", MATCH_ID)

    post(app_client, event("beforeShellExecution", "c", command=command(20)))
    assert "reached by 2 hook(s)" in app_client.get("/health").json()["rules_limit"]


def test_the_health_line_is_cut_to_fit_and_says_how_many_rules_it_left_out() -> None:
    assert app_module.rules_limit_line() is None
    ids = [f"{'r' * 60}{n:03d}" for n in range(190)]
    app_module.report_rules_limit("c", ids, "none")
    line = app_module.rules_limit_line()
    assert line is not None and len(line) <= rulefile.MAX_PROBLEM_CHARS
    assert LIMIT_LINE.fullmatch(line) is not None
    assert ids[0] in line and ids[-1] not in line and re.search(r"and \d+ more$", line)


def test_the_log_line_holds_at_most_80_characters_of_the_chat_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Final review M4: a broken or hostile chat id does not bloat the warning line."""
    chat = "c" * 9_990 + "zz-tail-mark"
    with caplog.at_level(logging.WARNING, logger="agentfly"):
        app_module.report_rules_limit(chat, ["r1"], "deny")
    [record] = [r for r in caplog.records if "rules limit" in r.getMessage()]
    text = record.getMessage()
    assert text == f"rules limit: chat {chat[:80]!r}, unfinished r1, answer deny"
    assert "zz-tail-mark" not in caplog.text


@pytest.mark.parametrize(
    ("severity", "answer"), [("block", "deny"), ("warn", "ask"), ("highlight", "none")]
)
def test_the_log_line_names_the_chat_and_rules_and_no_command_text(
    rec: Recorder, caplog: pytest.LogCaptureFixture, severity: str, answer: str
) -> None:
    rules_mod.activate(heavy(severity))
    with caplog.at_level(logging.WARNING, logger="agentfly"):
        rec.run("chat-7", command(20) + " zz-secret-marker")
    [record] = [r for r in caplog.records if "rules limit" in r.getMessage()]
    text = record.getMessage()
    assert record.levelno == logging.WARNING
    assert "chat-7" in text and MATCH_ID in text and text.endswith(answer)
    assert "zz-secret-marker" not in caplog.text


def test_a_hook_that_finishes_is_neither_logged_nor_counted(
    rec: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    rules_mod.activate(heavy("block"))
    with caplog.at_level(logging.WARNING, logger="agentfly"):
        assert rec.run("P", "ls")["permission"] == "allow"
    assert "rules limit" not in caplog.text and app_module.rules_limit_line() is None


@pytest.mark.parametrize("shell_first", [True, False])
def test_a_merged_pair_with_a_limit_half_shows_the_limit_rule(
    app_client: TestClient, shell_first: bool
) -> None:
    """Review focus 2: the two halves of one action are one step, and the denied half's rule shows.
    (The client strips `tool_input`, so the preToolUse half carries no command.)"""
    rules_mod.activate(heavy("block"))
    halves = [
        event("beforeShellExecution", "c", "t1", command=command(20)),
        pre("Shell", "t1"),
    ]
    answers = [post(app_client, half) for half in (halves if shell_first else halves[::-1])]
    assert sorted(a["permission"] for a in answers) == ["allow", "deny"]
    [step] = live(app_client)
    assert (step["rule"], step["verdict"]) == (LIMIT_ID, "blocked")
    assert step["rule_text"] == step["user_message"] == LIMIT_MESSAGE
    assert step["agent_message"] == LIMIT_MESSAGE + BLOCK_TAIL


def test_a_fresh_start_forgets_the_limit_hit() -> None:
    """Review focus 5: `lifespan` zeroes the counter, as it does `last_hook_at`."""
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as first:
        rules_mod.activate(heavy("block"))
        post(first, event("beforeShellExecution", "c", command=command(20)))
        assert "rules_limit" in first.get("/health").json()
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as second:
        assert set(second.get("/health").json()) == HEALTHY_KEYS


def test_a_hit_in_one_test_is_not_seen_by_the_next(rec: Recorder) -> None:
    """The conftest zeroes the counter after each test: a hit here (no `lifespan` runs) must not
    show in a later test that pins the three `/health` keys."""
    rules_mod.activate(heavy("block"))
    rec.run("P", command(20))
    assert app_module.rules_limit_line() is not None


# ---------------------------------------------------------------- command lists (Task 6b)

# The 198 rules of `bipartite_list`: the first few finish and spend the budget, the next is left
# unfinished.
LIST_IDS = {f"m{i}" for i in range(rulefile.MAX_RULES - 2)}


def heavy_lists(severity: str, *, before_r1: bool = False) -> RuleSet:
    lists, rules = bipartite_list(severity)
    if not before_r1:
        return ruleset_of(default_with(lists, *rules))
    text = default_with(lists)
    at = text.index(R1_AT)
    return ruleset_of(text[:at] + "".join(rules).lstrip("\n") + "\n" + text[at:])


def test_a_heavy_command_list_stops_at_the_budget_and_the_count_proves_it(
    rec: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real work of the lists (each entry read, a step for it and one for each word it checks;
    each run of key probes, a step for four), counted beside the meter, not by it, stays within
    `FLOAT_STEPS` plus one bucket, and the hook is the limit deny. With the charge taken away the
    same hook reads more entries than the whole budget, so the test fails if the bound goes."""
    rules_mod.activate(heavy_lists("block"))
    steps = entries = 0
    real_keys, real_entry = rulefile._key_lookups, rulefile._entry_follows

    def keys(count: int) -> None:
        nonlocal steps
        steps += count // 4
        real_keys(count)

    def entry(last: dict[str, int], at: int, extras: tuple[str, ...]) -> bool:
        nonlocal steps, entries
        steps += 1 + len(extras)
        entries += 1
        return real_entry(last, at, extras)

    monkeypatch.setattr(rulefile, "_key_lookups", keys)
    monkeypatch.setattr(rulefile, "_entry_follows", entry)
    answer = rec.run("P", BIPARTITE_LINE)
    assert answer["permission"] == "deny" and answer["user_message"] == LIMIT_MESSAGE
    bucket = 10 * (1 + 1)  # ten entries of one word left each
    assert 0 < steps <= rulefile.FLOAT_STEPS + bucket, steps
    assert 0 < entries <= rulefile.FLOAT_STEPS + 10, entries

    steps = entries = 0
    monkeypatch.setattr(rulefile, "_charge", lambda cost: None)
    assert rec.run("Q", BIPARTITE_LINE)["permission"] == "allow"  # it runs to the end, no fire
    assert entries > rulefile.FLOAT_STEPS, entries


def test_a_heavy_command_list_warn_asks_with_the_limit_message(rec: Recorder) -> None:
    rules_mod.activate(heavy_lists("warn"))
    assert rec.run("P", BIPARTITE_LINE) == {
        "permission": "ask",
        "user_message": LIMIT_MESSAGE,
        "agent_message": LIMIT_MESSAGE + SKIP_TAIL,
    }


def test_a_heavy_command_list_highlight_is_skipped(rec: Recorder) -> None:
    rs = heavy_lists("highlight")
    with one_hook() as meter:
        assert winning_rule(shell(BIPARTITE_LINE), session(), rs) is None
    assert meter.unfinished and set(meter.unfinished) <= LIST_IDS
    rules_mod.activate(rs)
    assert rec.run("P", BIPARTITE_LINE) == {"permission": "allow"}


def test_r0_and_r1_answer_as_usual_with_a_heavy_command_list_before_r1() -> None:
    rs = heavy_lists("block", before_r1=True)
    ids = [r.id for r in rs.rules]
    assert max(ids.index(i) for i in LIST_IDS) < ids.index("R1")

    with one_hook() as meter:
        line = f"{BIPARTITE_LINE} ; curl https://x.com"
        rule = winning_rule(shell(line), session(marked=True), rs)
    assert rule is not None and rule.id == "R1"
    assert meter.unfinished and set(meter.unfinished) <= LIST_IDS

    with one_hook():
        rule = winning_rule(shell(f"{BIPARTITE_LINE} ~/.config/agentfly/token"), session(), rs)
    assert rule is not None and rule.id == "R0"

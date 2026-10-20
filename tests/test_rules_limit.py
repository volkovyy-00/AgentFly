"""V5b-fix2 §4.3: what a rule left unfinished by the hook's meter does.

A floating path pattern charges the hook's meter (`rules.one_hook`); once the budget is spent the
rule being run is unfinished. An unfinished block rule denies with the limit rule (unless R0 or R1
fires), an unfinished warn asks with the limit rule, an unfinished highlight is skipped, and an
unfinished trigger is never recorded. Outside a hook nothing is charged and the engine answers as
before.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agentfly.cli.rules_test import run_tests
from agentfly.recorder import rulefile
from agentfly.recorder.rules import (
    DEFAULT,
    LIMIT_ID,
    LIMIT_RULE,
    LIMIT_WARN_RULE,
    Rule,
    RuleSet,
    Session,
    find_rule,
    mark,
    one_hook,
    winning_rule,
)
from tests.rules_helpers import default_with, list_line, ruleset_of
from tests.test_rules_cost import command, match_rule
from tests.test_severities import push
from tests.test_severities import rule as severity_rule
from tests.test_severities import ruleset as severity_ruleset

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

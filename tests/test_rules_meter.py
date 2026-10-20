"""V5b-fix2: the meter, which bounds what floating patterns may cost in one hook (spec §4.2).

Only a floating pattern (a run of parts with `**` on both sides) walks the path, so only its tests
charge: each start tried for a middle block is a step, each compare made costs
`compare_cost(len(segment), len(part))` and a bare `*` costs 1. A charge that takes the meter below
0 raises `WorkLimit`. With no meter set, nothing is charged or raised.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentfly.recorder import rulefile
from agentfly.recorder.rulefile import Clause, Meter, WorkLimit, compile_pattern, metered
from tests.test_rules_cost import command

HOME = "/h/me"


def shell(line: str) -> dict[str, Any]:
    return {"hook_event_name": "beforeShellExecution", "command": line}


def clause_of(*patterns: str) -> Clause:
    return Clause(("shell",), tuple(compile_pattern(p) for p in patterns))


def r1_after() -> Clause:
    r1 = next(s for s in rulefile.load_default().rules if s.id == rulefile.MARK_RULE)
    assert r1.after is not None
    return r1.after


def test_a_compare_costs_one_step_below_256_and_more_above() -> None:
    assert rulefile.compare_cost(25, 10) == 1
    assert rulefile.compare_cost(64, 32) == 9
    assert rulefile.compare_cost(250, 200) == 196


def test_patterns_that_do_not_float_never_charge() -> None:
    clauses = [
        r1_after(),
        clause_of(*[f"*/*/*/*/*/*/*/k{i}.pem" for i in range(8)]),
        clause_of(*[f"*/*/secret{i}/*.json" for i in range(10)]),
        clause_of(*[f"p{i}*.pem" for i in range(167)]),
    ]
    for clause in clauses:
        assert not any(rulefile.floating(p) for p in (*clause.path, *clause.path_except))
    line = command(60)
    with metered(Meter(left=1)) as meter:
        for clause in clauses:
            clause.matches(shell(line), {})
    assert meter.left == 1 and meter.unfinished == []


def test_a_floating_pattern_charges_its_starts_and_compares() -> None:
    pattern = compile_pattern("x/**")
    assert rulefile.floating(pattern)
    with metered(Meter(left=100)) as meter:
        assert pattern.matches("p/q/x", None, HOME)
    assert meter.left == 94  # 3 starts and 3 one-step compares


def test_past_the_budget_every_floating_test_raises() -> None:
    pattern = compile_pattern("x/**")
    deep = "/".join(f"d{k}" for k in range(20))
    with metered(Meter(left=5)):
        with pytest.raises(WorkLimit):
            pattern.matches(deep, None, HOME)
        with pytest.raises(WorkLimit):
            pattern.matches("x", None, HOME)
        assert not compile_pattern("*.pem").matches(deep, None, HOME)


def test_without_a_meter_nothing_is_charged_or_raised() -> None:
    assert rulefile.current_meter() is None
    assert not clause_of("zz/**").matches(shell(command(60)), {})


def test_the_meter_is_unset_after_its_block() -> None:
    with metered(Meter(left=3)) as meter:
        assert rulefile.current_meter() is meter
    assert rulefile.current_meter() is None


def test_a_rule_is_noted_once() -> None:
    meter = Meter(left=0)
    meter.note("a")
    meter.note("b")
    meter.note("a")
    assert meter.unfinished == ["a", "b"]


def test_a_partly_parsed_command_is_walked_once_per_distinct_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line = "cat 'x ; cat a b"  # an unbalanced quote: the loose scan repeats the words
    rulefile.distinct_candidates.cache_clear()
    calls = 0
    real = rulefile.Pattern.matches

    def counting(
        self: rulefile.Pattern, path: str, name: str | None = None, home: str | None = None
    ) -> bool:
        nonlocal calls
        calls += 1
        return real(self, path, name, home)

    monkeypatch.setattr(rulefile.Pattern, "matches", counting)
    clause = clause_of("zz", "zz/**")
    assert not clause.matches(shell(line), {})
    parsed = rulefile.normalize(line)
    words = [w for argv in parsed.all_commands() for w in argv]
    distinct = rulefile.distinct_candidates(parsed)
    assert distinct == ("cat", "x ; cat a b", "x", "a", "b") and len(words) > len(distinct)
    assert calls == len(distinct) * len(clause.path)


def test_distinct_candidates_keep_the_first_seen_order_and_the_text_after_eq_and_at() -> None:
    parsed = rulefile.normalize("cat --f=.env b -d@k.pem b")
    assert rulefile.distinct_candidates(parsed) == (
        "cat",
        "--f=.env",
        ".env",
        "b",
        "-d@k.pem",
        "k.pem",
    )


def test_an_unparseable_command_naming_env_still_marks() -> None:
    assert r1_after().matches(shell("cat 'x .env"), {})

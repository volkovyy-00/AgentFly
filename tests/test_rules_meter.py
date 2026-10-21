"""V5b-fix2: the meter, which bounds what floating patterns and command lists may cost in one hook
(spec §4.2).

Of the path patterns only a floating one (a run of parts with `**` on both sides) walks the path, so
only its tests charge: each start tried for a middle block is a step, each compare made costs
`compare_cost(len(segment), len(part))` and a bare `*` costs 1. A command list charges a bucket of
its index before it is walked (one step an entry and one a word left in it) and a run of key probes
at one step for four (owner, 2026-10-21). A charge that takes the meter below 0 raises `WorkLimit`.
With no meter set, nothing is charged or raised.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

import agentfly.recorder.rules as rules_mod
from agentfly.recorder import rulefile
from agentfly.recorder.rulefile import Clause, Meter, WorkLimit, compile_pattern, metered
from tests.glob_oracle import old_command_hit
from tests.rules_helpers import default_with, list_line, ruleset_of
from tests.test_rules_cost import (
    command,
    command_list_on_one_program,
    match_rule,
    realistic_lists,
)

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


def test_a_walk_stops_once_it_has_spent_what_the_meter_has_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One floating test on a very deep path stops its walk at the budget (final audit A1): the
    meter ends at most one start's work below 0, however deep the path, and no more starts are
    tried than the budget pays for."""
    pattern = compile_pattern(".ssh/**")  # unanchored: `**/.ssh/**`, one middle block
    assert rulefile.floating(pattern)
    deep = "a/" * 50_000 + "f"
    starts: list[int] = []
    monkeypatch.setattr(rulefile, "_tally", lambda tried, stars: starts.append(tried))
    with metered(Meter(left=1_000)) as meter, pytest.raises(WorkLimit):
        pattern.matches(deep, None, HOME)
    assert 0 < -meter.left <= 2  # a start of `.ssh` costs 2: the start and one short compare
    assert sum(starts) <= 501
    with metered(Meter(left=10**9)) as meter:  # a budget that pays for the walk still walks it
        assert not pattern.matches(deep, None, HOME)
    assert meter.left == 10**9 - 2 * 50_001


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


# ---------------------------------------------------------------- command lists (spec §4.7)


def command_clause(*entries: tuple[str, ...]) -> Clause:
    return Clause(("shell",), command=entries)


class Counts:
    """What an index look-up did: key look-ups made, and entries whose extras were read."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.keys = 0
        self.entries = 0
        real_keys, real_entry = rulefile._key_lookups, rulefile._entry_follows

        def keys(count: int) -> None:
            self.keys += count
            real_keys(count)

        def entry(last: dict[str, int], at: int, extras: tuple[str, ...]) -> bool:
            self.entries += 1
            return real_entry(last, at, extras)

        monkeypatch.setattr(rulefile, "_key_lookups", keys)
        monkeypatch.setattr(rulefile, "_entry_follows", entry)


def test_the_index_answers_as_the_old_loop() -> None:
    rng = random.Random(20261020)
    vocabulary = "cat a b c npm publish x".split()
    answers = {True: 0, False: 0}
    for _ in range(3000):
        entries = tuple(
            tuple(rng.choice(vocabulary) for _ in range(rng.randint(1, 3)))
            for _ in range(rng.randint(1, 30))
        )
        line = " ; ".join(
            " ".join(rng.choice(vocabulary) for _ in range(rng.randint(1, 6)))
            for _ in range(rng.randint(1, 6))
        )
        parsed = rulefile.normalize(line)
        expected = old_command_hit(entries, parsed)
        assert command_clause(*entries)._command_hit(parsed) == expected, (entries, line)
        answers[expected] += 1
    assert min(answers.values()) > 200, answers  # both answers occur in numbers


def test_a_command_naming_200_programs_looks_up_the_smaller_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clause = command_clause(*[(f"p{i}", "x") for i in range(200)])
    counts = Counts(monkeypatch)
    line = " ".join([*(f"p{i}" for i in range(200)), "y"])
    assert not clause.matches(shell(line), {})
    assert counts.keys <= 200 + 1 and counts.entries == 0, (counts.keys, counts.entries)


def test_entries_that_share_a_first_word_are_keyed_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    many = command_clause(*[("cat", "w", f"a{i}") for i in range(200)])
    counts = Counts(monkeypatch)
    assert not many.matches(shell(" ; ".join(["cat w x"] * 100)), {})
    assert counts.entries == 0 and counts.keys <= 2, (counts.keys, counts.entries)
    one = command_clause(("cat", "w", "a7"))
    assert one.matches(shell("cat w x ; cat a7 w"), {})
    assert not one.matches(shell("cat w x ; cat a7 z"), {})


def test_a_long_command_on_a_short_list_looks_up_the_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    clause = command_clause(("cat", "k1"), ("cat", "k2"), ("cat", "k3"))
    counts = Counts(monkeypatch)
    assert not clause.matches(shell("cat " + " ".join(f"w{i}" for i in range(100))), {})
    assert counts.keys == 3 and counts.entries == 0, (counts.keys, counts.entries)
    assert clause.matches(shell("cat " + " ".join(f"w{i}" for i in range(100)) + " k2"), {})


def test_an_entry_is_keyed_by_its_rarest_extra_word(monkeypatch: pytest.MonkeyPatch) -> None:
    """`b` is in every entry, `c` only in the first: the first is looked at when `c` is there,
    the others (keyed by their own rare words) when theirs are."""
    clause = command_clause(("cat", "b", "c"), ("cat", "b", "d"), ("cat", "b", "e"))
    counts = Counts(monkeypatch)
    assert not clause.matches(shell("cat b"), {})
    assert counts.entries == 0
    assert clause.matches(shell("cat b e"), {})
    assert counts.entries == 1


def test_identical_entries_are_kept_once(monkeypatch: pytest.MonkeyPatch) -> None:
    clause = command_clause(*[("cat", "a", "b")] * 5, ("cat", "b", "a"))
    counts = Counts(monkeypatch)
    assert not clause.matches(shell("cat a"), {})
    assert counts.entries <= 2, counts.entries  # (cat a b) once, (cat b a) once
    assert clause.matches(shell("cat a b"), {})


def test_an_entry_with_no_extra_word_fires_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    clause = command_clause(*[("cat", f"w{i}") for i in range(50)], ("ls",))
    counts = Counts(monkeypatch)
    assert clause.matches(shell("ls -l"), {})
    assert not clause.matches(shell("cat x"), {})
    assert counts.entries == 0


def test_a_repeated_simple_command_is_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    clause = command_clause(("cat", "a"))
    counts = Counts(monkeypatch)
    assert not clause.matches(shell(" ; ".join(["cat x"] * 100)), {})
    assert counts.keys == 1
    assert clause.matches(shell(" ; ".join(["cat x"] * 100 + ["cat a"])), {})


@pytest.mark.parametrize("count", [150, 600, 2000])
def test_a_long_line_of_simple_commands_is_worked_out_once_for_all_clauses(
    count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The views of a line's simple commands are held for the hook, not in a memo of fixed size:
    however many distinct simple commands the line has, each is built once for all the clauses."""
    builds = 0
    real = rulefile._simple_view

    def counting(argv: tuple[str, ...]) -> rulefile._Simple:
        nonlocal builds
        builds += 1
        return real(argv)

    monkeypatch.setattr(rulefile, "_simple_view", counting)
    rulefile._simple_commands.cache_clear()
    line = " ; ".join(f"cat z{i} y" for i in range(count))
    for i in range(20):
        assert not command_clause(("cat", f"w{i}"), ("cat", f"v{i}")).matches(shell(line), {})
    assert builds == count


def test_a_line_that_repeats_a_simple_command_builds_its_view_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds = 0
    real = rulefile._simple_view

    def counting(argv: tuple[str, ...]) -> rulefile._Simple:
        nonlocal builds
        builds += 1
        return real(argv)

    monkeypatch.setattr(rulefile, "_simple_view", counting)
    rulefile._simple_commands.cache_clear()
    line = " ; ".join(["cat x y", "ls", "cat x y", "cat x y", "ls"])
    assert not command_clause(("cat", "w")).matches(shell(line), {})
    assert builds == 2


def test_the_index_is_not_part_of_the_clauses_identity() -> None:
    one = command_clause(("cat", "a"), ("cat", "b"))
    other = command_clause(("cat", "a"), ("cat", "b"))
    assert one == other and hash(one) == hash(other)
    assert "index" not in repr(one).casefold()
    assert command_clause() == Clause(("shell",))


def test_198_rules_of_200_cat_entries_on_150_cat_commands_check_few_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lists, rules = command_list_on_one_program()
    ruleset = ruleset_of(default_with(lists, *rules))
    action = shell(" ; ".join(f"cat z{i} y" for i in range(150)))
    counts = Counts(monkeypatch)
    session = rules_mod.Session(id="s", marked=False, start_time="t", next_step=1)
    verdict = rules_mod.decide(action, rules_mod.mark(action, session, ruleset), ruleset)
    assert verdict == ("allow", None)
    assert counts.entries == 0, counts.entries


# ---------------------------------------------------------------- command lists count (Task 6b)


def test_a_bucket_is_charged_its_weight_before_it_is_walked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bucket costs one step an entry and one a word left in it: ten one-word rests are 20,
    charged before the first entry is read, so a meter short of 20 reads none of them."""
    clause = command_clause(*[("cat", f"a{i}", f"b{j}") for i in range(20) for j in range(10)])
    events: list[object] = []
    real_charge, real_entry = rulefile._charge, rulefile._entry_follows

    def charge(steps: int) -> None:
        events.append(steps)
        real_charge(steps)

    def entry(last: dict[str, int], at: int, extras: tuple[str, ...]) -> bool:
        events.append("entry")
        return real_entry(last, at, extras)

    monkeypatch.setattr(rulefile, "_charge", charge)
    monkeypatch.setattr(rulefile, "_entry_follows", entry)
    with metered(Meter(left=100)) as meter:
        assert not clause.matches(shell("cat a0 z"), {})
    assert events == [20, *["entry"] * 10]  # two probes cost nothing, then the bucket of `a0`
    assert meter.left == 80 and meter.unfinished == []
    events.clear()
    with metered(Meter(left=19)), pytest.raises(WorkLimit):
        clause.matches(shell("cat a0 z"), {})
    assert events == [20]


def test_a_run_of_probes_is_charged_one_step_for_four(monkeypatch: pytest.MonkeyPatch) -> None:
    charged: list[int] = []
    real = rulefile._charge

    def charge(steps: int) -> None:
        charged.append(steps)
        real(steps)

    monkeypatch.setattr(rulefile, "_charge", charge)
    long_line = shell("cat " + " ".join(f"w{i}" for i in range(100)))
    with metered(Meter(left=100)) as meter:
        assert not command_clause(*[("cat", f"k{i}") for i in range(8)]).matches(long_line, {})
    assert charged == [2] and meter.left == 98  # eight keys looked up
    charged.clear()
    with metered(Meter(left=100)):  # eight words looked up among fifty keys
        many = command_clause(*[("cat", f"k{i}") for i in range(50)])
        assert not many.matches(shell("cat " + " ".join(f"w{i}" for i in range(8))), {})
    assert charged == [2]
    charged.clear()
    with metered(Meter(left=0)):  # fewer than four probes charge nothing, even on a spent meter
        assert not command_clause(*[("cat", f"k{i}") for i in range(3)]).matches(long_line, {})
    assert charged == []


def text_of_lists(shape: Any) -> str:
    lists, rules = shape()
    return default_with(lists, *rules)


def realistic_line() -> str:
    return " ; ".join(f"git push origin b{k}" for k in range(75))  # 300 words


@pytest.mark.parametrize(
    ("text", "line"),
    [
        (rulefile.default_text, lambda: command(60)),
        (
            lambda: text_of_lists(command_list_on_one_program),
            lambda: " ; ".join(f"cat z{i} y" for i in range(150)),
        ),
        (
            lambda: default_with(
                list_line("l", *[f"cat w a{i}" for i in range(200)]),
                *[match_rule(i, 'command = "l"') for i in range(rulefile.MAX_RULES - 2)],
            ),
            lambda: " ; ".join(["cat w x"] * 100),
        ),
        (lambda: text_of_lists(realistic_lists), realistic_line),
    ],
    ids=["the default on command(60)", "cat wN on cat zN y", "cat w aN on cat w x", "realistic"],
)
def test_command_lists_of_real_shapes_are_never_charged(text: Any, line: Any) -> None:
    ruleset = ruleset_of(text())
    action = shell(line())
    session = rules_mod.Session(id="s", marked=False, start_time="t", next_step=1)
    with rules_mod.one_hook() as meter:
        assert (
            rules_mod.winning_rule(action, rules_mod.mark(action, session, ruleset), ruleset)
            is None
        )
    assert meter.left == rulefile.FLOAT_STEPS and meter.unfinished == []


def test_a_long_command_on_198_lists_of_cat_wn_pays_only_its_probes() -> None:
    """`command(60)` has 300 words after `cat`, more than the 200 keys: each rule looks the keys
    up (50 steps), finds none, reads no entry and finishes."""
    ruleset = ruleset_of(text_of_lists(command_list_on_one_program))
    action = shell(command(60))
    session = rules_mod.Session(id="s", marked=False, start_time="t", next_step=1)
    with rules_mod.one_hook() as meter:
        assert (
            rules_mod.winning_rule(action, rules_mod.mark(action, session, ruleset), ruleset)
            is None
        )
    assert meter.unfinished == []
    assert meter.left == rulefile.FLOAT_STEPS - (rulefile.MAX_RULES - 2) * (200 // 4)

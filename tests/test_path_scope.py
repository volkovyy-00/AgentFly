"""V5c: `path_scope = "outside_workspace"` (SPEC section 5, owner 2026-10-16 and 2026-10-23).

A read or write is outside when its path, resolved through links and `..` by a bounded
`lstat`/`readlink` walk (`clean.Walker`), is under none of the event's `workspace_roots`. A missing
part is joined as text, a relative path is read against the first root, and every bound falls
toward firing: no roots, more than `MAX_ROOTS`, no steps left, too many links, a path too long. A
path outside every root as text is outside with no disk call. These run on real temporary folders.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from agentfly.cli.rules_test import action_for, run_tests
from agentfly.recorder import clean, rulefile, store
from agentfly.recorder import rules as rules_mod
from agentfly.recorder.rulefile import Clause, Meter, metered
from tests.rules_helpers import default_with, ruleset_of

RULE8 = """
[[rule]]
id = "s08-write-outside-workspace"
kind = "match"
severity = "block"
message = "Blocked: writes outside the open workspace folder are not allowed."
event = ["write"]
path_scope = "outside_workspace"
"""
TRIGGER = """
[[rule]]
id = "outside-then-push"
kind = "after_then"
severity = "block"
message = "m"
after = { event = ["read"], path_scope = "outside_workspace" }
then = { event = ["shell"], command = "pushes" }
"""
PUSHES = 'pushes = ["git push"]\n'


def clause_of(rule: str, rule_id: str, lists: str = "") -> Clause:
    parsed = rulefile.parse(default_with(lists, rule))
    assert parsed.errors == (), parsed.errors
    spec = next(spec for spec in parsed.rules if spec.id == rule_id)
    clause = spec.clause or spec.after
    assert clause is not None
    return clause


RULE8_CLAUSE = clause_of(RULE8, "s08-write-outside-workspace")


def write(path: str, roots: Any = None) -> dict[str, Any]:
    action: dict[str, Any] = {
        "hook_event_name": "preToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": path},
    }
    if roots is not None:
        action["workspace_roots"] = roots
    return action


def read(path: str, roots: Any = None) -> dict[str, Any]:
    action: dict[str, Any] = {"hook_event_name": "beforeReadFile", "file_path": path}
    if roots is not None:
        action["workspace_roots"] = roots
    return action


def fires(action: dict[str, Any]) -> bool:
    return RULE8_CLAUSE.matches(action, rules_mod.CLASSES)


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """`w` is the workspace (a file, a folder, a link out and a link in); `out` is outside it."""
    base = tmp_path.resolve()
    (base / "w" / "src").mkdir(parents=True)
    (base / "w" / "src" / "app.py").write_text("")
    (base / "out").mkdir()
    (base / "w" / "link").symlink_to(base / "out")
    (base / "w" / "inner").symlink_to(base / "w" / "src")
    (base / "alias").symlink_to(base / "w")
    return base


# ---------------------------------------------------------------- the brief's criteria


def test_rule8_fires_on_a_write_outside_every_root(tree: Path) -> None:
    roots = [str(tree / "w")]
    assert fires(write(str(tree / "out" / "f"), roots))
    assert fires(write("/etc/hosts", roots))
    assert fires(write("/etc/hosts"))  # S3's own test: no roots


def test_rule8_fires_through_a_link_inside_a_root(tree: Path) -> None:
    roots = [str(tree / "w")]
    assert fires(write(str(tree / "w" / "link" / "f"), roots))
    assert fires(write("link/f", roots))  # relative, against the first root
    assert fires(write(str(tree / "w" / "link" / "new" / "f"), roots))


def test_rule8_fires_on_dot_dot_out_of_a_root(tree: Path) -> None:
    roots = [str(tree / "w")]
    assert fires(write(str(tree / "w" / ".." / "x"), roots))
    assert fires(write("../x", roots))
    assert fires(write("src/../../x", roots))
    # `..` after a link climbs from where the link leads, and the text folded is checked too
    assert fires(write(str(tree / "w" / "link" / ".." / "w" / "src" / "f"), roots)) is False
    assert fires(write(str(tree / "w" / "link" / ".." / "out" / "f"), roots))


def test_rule8_fires_on_a_relative_path_with_no_roots() -> None:
    assert fires(write("src/app.py"))
    assert fires(write("src/app.py", []))
    assert fires(write("src/app.py", "not a list"))


def test_rule8_fires_past_max_roots(tree: Path) -> None:
    inside = str(tree / "w" / "src" / "app.py")
    filler = [f"/nowhere/{i}" for i in range(clean.MAX_ROOTS - 1)]
    assert clean.MAX_ROOTS == 32
    assert not fires(write(inside, [str(tree / "w"), *filler]))  # 32 roots: read
    assert fires(write(inside, [str(tree / "w"), *filler, "/nowhere/x"]))  # 33: outside


def test_rule8_is_quiet_on_a_write_inside_a_root(tree: Path) -> None:
    roots = [str(tree / "w")]
    assert not fires(write(str(tree / "w" / "src" / "app.py"), roots))
    assert not fires(write("src/app.py", roots))  # S3's own test, with a root
    assert not fires(write("./src/./app.py", roots))
    assert not fires(write(str(tree / "w" / "inner" / "app.py"), roots))  # a link that stays in
    assert not fires(write(str(tree / "w"), roots))  # the root itself


def test_rule8_is_quiet_on_a_new_file_in_a_new_folder(tree: Path) -> None:
    roots = [str(tree / "w")]
    assert not fires(write(str(tree / "w" / "new" / "deeper" / "f.py"), roots))
    assert not fires(write("new/deeper/f.py", roots))
    assert not fires(write(str(tree / "w" / "new" / ".." / "src" / "f.py"), roots))


@pytest.mark.skipif(
    os.path.realpath("/tmp") != "/private/tmp", reason="macOS: /tmp is a link to /private/tmp"
)
def test_rule8_is_quiet_on_the_resolved_form_of_a_root() -> None:
    assert not fires(write("/private/tmp/w/f", ["/tmp/w"]))
    # a path whose text is under no root as sent or as resolved is outside, links or not
    assert fires(write("/tmp/w/f", ["/private/tmp/w"]))
    assert not fires(write("/tmp/w/f", ["/tmp/w"]))
    assert fires(write("/private/tmp/x/f", ["/tmp/w"]))


def test_a_root_reached_through_a_link_holds_its_files(tree: Path) -> None:
    assert not fires(write(str(tree / "w" / "src" / "f"), [str(tree / "alias")]))
    assert not fires(write(str(tree / "alias" / "src" / "f"), [str(tree / "alias")]))
    # A path outside every root as text is outside with no disk call, even when a link from
    # outside leads in (as for the history's project files): toward firing.
    assert fires(write(str(tree / "alias" / "src" / "f"), [str(tree / "w")]))


def test_any_root_will_do(tree: Path) -> None:
    roots = ["/nowhere/a", str(tree / "w"), str(tree / "out")]
    assert not fires(write(str(tree / "out" / "f"), roots))
    assert not fires(write(str(tree / "w" / "f"), roots))
    assert fires(write("/etc/hosts", roots))


@pytest.mark.parametrize(
    "roots",
    [["/"], ["//"], ["/x/.."], ["relative/root"], [""], [5], [None], ["/" + "a" * 1100]],
    ids=["slash", "double-slash", "dot-dot", "relative", "empty", "number", "null", "long"],
)
def test_a_root_that_is_not_usable_holds_nothing(roots: list[Any]) -> None:
    assert fires(write("/etc/hosts", roots))
    assert fires(write("src/app.py", roots))


def test_a_root_that_resolves_to_the_top_holds_nothing(tree: Path) -> None:
    (tree / "top").symlink_to("/")
    assert fires(write("/etc/hosts", [str(tree / "top")]))


def test_home_in_a_path_is_the_home_folder(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tree / "w"))
    roots = [str(tree / "w")]
    for path in ("~/src/f", "$HOME/src/f", "${HOME}/src/f"):
        assert not fires(write(path, roots)), path
    assert fires(write("~/link/f", roots))
    assert fires(write("~/../out/f", roots))


def test_a_path_that_is_no_string_or_empty_is_outside(tree: Path) -> None:
    roots = [str(tree / "w")]
    assert fires({**write("", roots)})
    assert fires({**write("x", roots), "tool_input": {"file_path": 5}})
    assert fires({**write("x", roots), "tool_input": {}})


# ---------------------------------------------------------------- reads, triggers and searches


def test_a_trigger_with_path_scope_sets_on_a_read_outside_the_roots(tree: Path) -> None:
    ruleset = ruleset_of(default_with(PUSHES, TRIGGER))
    roots = [str(tree / "w")]
    blank = rules_mod.Session(id="s", marked=False, start_time="t", next_step=1)
    inside = rules_mod.mark(read(str(tree / "w" / "src" / "app.py"), roots), blank, ruleset)
    assert inside.triggers == frozenset()
    outside = rules_mod.mark(read(str(tree / "out" / "notes.txt"), roots), blank, ruleset)
    assert outside.triggers == {"outside-then-push"}
    push = {"hook_event_name": "beforeShellExecution", "command": "git push"}
    assert rules_mod.decide(push, outside, ruleset) == ("blocked", "outside-then-push")
    assert rules_mod.decide(push, inside, ruleset) == ("allow", None)


def search(tool_input: dict[str, Any], roots: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "preToolUse",
        "tool_name": "Grep",
        "tool_input": tool_input,
        "workspace_roots": roots,
    }


def test_a_search_is_judged_by_its_file_path_and_with_none_is_outside(tree: Path) -> None:
    clause = clause_of(TRIGGER, "outside-then-push", PUSHES)
    roots = [str(tree / "w")]
    assert not clause.matches(search({"file_path": str(tree / "w" / "src")}, roots), {})
    assert clause.matches(search({"file_path": str(tree / "out")}, roots), {})
    assert clause.matches(search({"glob": "*.py"}, roots), {})  # no file_path: outside
    assert clause.matches(search({"file_path": None}, roots), {})
    names_only = search({"glob": "*.py", "output_mode": "files_with_matches"}, roots)
    assert not clause.matches(names_only, {}), "a names-only search is no event at all"


def test_path_comes_before_the_scope_and_both_must_hold(tree: Path) -> None:
    rule = RULE8.replace('event = ["write"]', 'event = ["write"]\npath = "pys"').replace(
        "s08-write-outside-workspace", "py-outside"
    )
    clause = clause_of(rule, "py-outside", 'pys = ["*.py"]\n')
    roots = [str(tree / "w")]
    assert clause.matches(write(str(tree / "out" / "a.py"), roots), {})
    assert not clause.matches(write(str(tree / "out" / "a.txt"), roots), {})
    assert not clause.matches(write(str(tree / "w" / "a.py"), roots), {})


# ---------------------------------------------------------------- the bounds, each past its limit


def test_out_of_steps_counts_as_outside(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roots = [str(tree / "w")]
    inside = str(tree / "w" / "src" / "app.py")
    assert not fires(write(inside, roots))
    monkeypatch.setattr(clean, "LOOKUP_STEPS", 2)
    assert fires(write(inside, roots))


def test_too_many_links_count_as_outside(tree: Path) -> None:
    roots = [str(tree / "w")]
    chain = tree / "w" / "chain"
    chain.mkdir()
    (chain / "l0").symlink_to(tree / "w" / "src")
    for i in range(1, clean.MAX_LINK_HOPS + 1):
        (chain / f"l{i}").symlink_to(chain / f"l{i - 1}")
    assert not fires(write(str(chain / f"l{clean.MAX_LINK_HOPS - 1}" / "f"), roots))
    assert fires(write(str(chain / f"l{clean.MAX_LINK_HOPS}" / "f"), roots))


def test_a_path_past_the_word_limit_counts_as_outside(tree: Path) -> None:
    roots = [str(tree / "w")]
    room = clean.MAX_PATH_WORD - len(str(tree / "w")) - 1
    assert not fires(write(str(tree / "w" / ("a" * 200) / ("b" * (room - 201))), roots))
    assert fires(write(str(tree / "w" / ("a" * 200) / ("b" * (room - 200))), roots))


def test_a_link_loop_counts_as_outside(tree: Path) -> None:
    (tree / "w" / "loop").symlink_to(tree / "w" / "loop")
    assert fires(write(str(tree / "w" / "loop" / "f"), [str(tree / "w")]))


def test_a_file_where_a_folder_should_be_counts_as_outside(tree: Path) -> None:
    assert fires(write(str(tree / "w" / "src" / "app.py" / "x"), [str(tree / "w")]))


def test_a_missing_folder_cancelled_by_dot_dot_still_follows_the_next_link(tree: Path) -> None:
    roots = [str(tree / "w")]
    assert fires(write(str(tree / "w" / "new" / ".." / "link" / "f"), roots))
    assert fires(write("new/../link/f", roots))
    assert not fires(write("new/../inner/f", roots))


@pytest.fixture()
def lstat_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = os.lstat

    def counting(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        calls.append(str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(clean.os, "lstat", counting)
    return calls


def test_a_path_outside_as_text_is_never_looked_up(tree: Path, lstat_calls: list[str]) -> None:
    roots = [str(tree / "w")]
    assert fires(write(str(tree / "out" / "a" / "b" / "f"), roots))
    assert not [c for c in lstat_calls if c.startswith(str(tree / "out"))]
    assert fires(write("/etc/hosts", roots))
    assert not [c for c in lstat_calls if c.startswith("/etc")]


def test_the_lookups_are_counted_and_shared_by_one_hook(tree: Path, lstat_calls: list[str]) -> None:
    roots = [str(tree / "w")]
    action = write(str(tree / "w" / "src" / "new.py"), roots)
    with metered(Meter(left=rulefile.FLOAT_STEPS)) as meter:
        assert not fires(action)
        first = len(lstat_calls)
        assert not fires(action)
        assert not fires(action)
    assert first > 0 and len(lstat_calls) == first, "the second clause asks the disk nothing"
    assert meter.disk.left == clean.LOOKUP_STEPS - first
    lstat_calls.clear()
    assert not fires(action)  # no meter: a walker of its own
    assert len(lstat_calls) == first


def test_one_hook_spends_at_most_one_budget(
    tree: Path, monkeypatch: pytest.MonkeyPatch, lstat_calls: list[str]
) -> None:
    monkeypatch.setattr(clean, "LOOKUP_STEPS", 40)
    paths = [write(str(tree / "w" / "src" / f"d{i}" / "f"), [str(tree / "w")]) for i in range(30)]
    with metered(Meter(left=rulefile.FLOAT_STEPS)):
        results = [fires(action) for action in paths]
    assert len(lstat_calls) <= 40
    assert results[0] is False and results[-1] is True, "past the budget: outside"


@pytest.mark.parametrize(
    ("payload", "budgets"),
    [
        ({"hook_event_name": "beforeReadFile", "file_path": "/w/a.py"}, 0),
        (
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": "f"},
            },
            0,
        ),
        ({"hook_event_name": "preToolUse", "tool_name": "Grep", "tool_input": {"path": "src"}}, 0),
        ({"hook_event_name": "afterFileEdit", "file_path": "/w/a.py"}, 0),
        ({"hook_event_name": "beforeShellExecution", "command": "ls src"}, 1),
    ],
)
def test_the_step_record_makes_a_budget_only_where_path_scope_cannot_run(
    payload: dict[str, Any], budgets: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One budget a hook: a scope judges read, write and search hooks (`rules check` refuses it
    beside a shell event), and the step record's `Lookups` runs on shell hooks only."""
    made: list[Path] = []

    def counted(root: Path) -> clean.Lookups:
        made.append(root)
        return clean.Lookups(root)

    monkeypatch.setattr(store, "Lookups", counted)
    session = rules_mod.Session(id="s", marked=False, start_time="t", next_step=1)
    store.build_step_record({**payload, "workspace_roots": ["/w"]}, session, "allow", None, order=1)
    assert len(made) == budgets


# ---------------------------------------------------------------- the rules file


def file_with(rule: str, lists: str = "") -> rulefile.RuleFile:
    return rulefile.parse(default_with(lists, rule))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('event = ["write"]', 'event = ["write", "shell"]'), "path_scope"),
        (('event = ["write"]', 'event = ["shell"]'), "path_scope"),
        (('"outside_workspace"', '"inside_workspace"'), "path_scope"),
        (('"outside_workspace"', "true"), "path_scope"),
    ],
)
def test_rules_check_refuses_a_scope_it_cannot_judge(change: tuple[str, str], message: str) -> None:
    parsed = file_with(RULE8.replace(*change))
    assert any(message in error for error in parsed.errors), parsed.errors


def test_a_scope_is_refused_in_then() -> None:
    rule = TRIGGER.replace(
        'then = { event = ["shell"], command = "pushes" }',
        'then = { event = ["write"], path_scope = "outside_workspace" }',
    )
    parsed = file_with(rule, PUSHES)
    assert any("then" in e and "path_scope" in e for e in parsed.errors), parsed.errors


def test_r1_may_not_use_a_scope() -> None:
    text = rulefile.default_text().replace(
        'path_except = "secret_names_ok" }',
        'path_except = "secret_names_ok", path_scope = "outside_workspace" }',
        1,
    )
    loaded = rulefile.load_bytes(text.encode())
    assert any("R1" in e for e in loaded.errors), loaded.errors


def test_a_scope_alone_is_a_condition() -> None:
    assert file_with(RULE8).errors == ()
    parsed = file_with(RULE8.replace('path_scope = "outside_workspace"\n', ""))
    assert any("add a condition" in e for e in parsed.errors)


def test_a_scope_costs_a_fixed_amount_per_clause() -> None:
    assert rulefile.WORK_SCOPE == 2
    assert rulefile.clause_work(RULE8_CLAUSE) == rulefile.WORK_SCOPE
    with_path = clause_of(
        RULE8.replace('event = ["write"]', 'event = ["write"]\npath = "pys"'),
        "s08-write-outside-workspace",
        'pys = ["*.py"]\n',
    )
    plain = rulefile.WORK_CLAUSE + rulefile.WORK_NAME
    assert rulefile.clause_work(with_path) == plain + rulefile.WORK_SCOPE


# ---------------------------------------------------------------- inline tests take roots


def test_an_inline_test_sends_its_roots_as_workspace_roots() -> None:
    assert action_for("write", "src/app.py", ("/w",))["workspace_roots"] == ["/w"]
    assert action_for("read", "a", ("/w", "/v"))["workspace_roots"] == ["/w", "/v"]
    assert "workspace_roots" not in action_for("shell", "ls", ())


def test_rules_test_runs_a_scope_rule_with_roots(tmp_path: Path) -> None:
    rule = (
        RULE8
        + '  [[rule.test]]\n  steps = ["write: src/app.py"]\n  roots = ["/work/app"]\n'
        + '  expect = "allow"\n'
        + '  [[rule.test]]\n  steps = ["write: /etc/hosts"]\n  roots = ["/work/app"]\n'
        + '  expect = "block"\n'
        + '  [[rule.test]]\n  steps = ["write: src/app.py"]\n  expect = "block"\n'
    )
    loaded = file_with(rule)
    assert loaded.errors == ()
    spec = next(s for s in loaded.rules if s.id == "s08-write-outside-workspace")
    assert [t.roots for t in spec.tests] == [("/work/app",), ("/work/app",), ()]
    ran, failures = run_tests(loaded, tmp_path / "rules.toml")
    assert failures == [] and ran > 3


@pytest.mark.parametrize(
    "roots",
    ['"/w"', "[1]", "[" + ", ".join(['"/w"'] * 65) + "]", '["' + "a" * 2001 + '"]'],
    ids=["string", "number", "too-many", "too-long"],
)
def test_inline_roots_must_be_a_short_list_of_strings(roots: str) -> None:
    rule = RULE8 + f'  [[rule.test]]\n  steps = ["write: /etc/hosts"]\n  roots = {roots}\n'
    rule += '  expect = "block"\n'
    parsed = file_with(rule)
    assert any("roots" in e for e in parsed.errors), parsed.errors


def test_inline_roots_may_be_empty() -> None:
    rule = RULE8 + '  [[rule.test]]\n  steps = ["write: x"]\n  roots = []\n  expect = "block"\n'
    assert file_with(rule).errors == ()

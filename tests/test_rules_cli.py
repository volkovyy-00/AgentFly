"""V5b: `agentfly rules check [FILE]` and `agentfly rules test [FILE]`.

In-process, through `main`: the conftest points the recorder's active file at a path that does
not exist, so "no FILE" means the packaged default unless a test writes that path.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from agentfly.cli import main
from agentfly.recorder import rulefile
from tests.rules_helpers import BROKEN_TOML, default_with, list_line

DEFAULT = rulefile.default_text()

GOOD_RULE = """
[[rule]]
id = "no-push"
kind = "match"
severity = "warn"
message = "A push needs a look."
event = ["shell"]
command = "push_cmds"
  [[rule.test]]
  steps = ["shell: git push origin main"]
  expect = "warn"
  [[rule.test]]
  steps = ["shell: git status"]
  expect = "allow"
"""


EVERYTHING = """
[[rule]]
id = "no-push"
kind = "match"
severity = "warn"
message = "Every read."
event = ["read"]
path = "all"
"""


def with_rule(*rules: str) -> str:
    return default_with('push_cmds = ["git push"]\n', *rules)


@pytest.fixture
def rules_file(tmp_path: Path) -> Callable[..., Path]:
    def write(text: str, name: str = "mine.toml") -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return write


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(["rules", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


# ---------------------------------------------------------------- the default file


@pytest.mark.parametrize("command", ["check", "test"])
def test_both_commands_pass_on_the_packaged_default_when_there_is_no_active_file(
    capsys: pytest.CaptureFixture[str], command: str
) -> None:
    code, out, err = run(capsys, command)
    assert code == 0, err
    assert str(rulefile.default_path()) in out
    assert err == ""


def test_check_reports_how_many_rules_and_that_r0_is_built_in(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, out, _ = run(capsys, "check")
    count = len(rulefile.load_default().rules)
    assert f"ok: {count} rule" in out and "R0" in out


def test_test_reports_how_many_tests_passed(capsys: pytest.CaptureFixture[str]) -> None:
    _, out, _ = run(capsys, "test")
    expected = sum(len(spec.tests) for spec in rulefile.load_default().rules)
    assert f"{expected} tests passed" in out and expected >= 8


@pytest.mark.parametrize("command", ["check", "test"])
def test_the_default_for_no_file_is_the_file_the_recorder_would_load(
    capsys: pytest.CaptureFixture[str], active_rules: Path, command: str
) -> None:
    active_rules.write_text(with_rule(GOOD_RULE), encoding="utf-8")
    code, out, _ = run(capsys, command)
    assert code == 0 and str(active_rules) in out


def test_an_invalid_active_file_fails_even_though_the_recorder_would_use_the_default(
    capsys: pytest.CaptureFixture[str], active_rules: Path
) -> None:
    active_rules.write_text(BROKEN_TOML, encoding="utf-8")
    for command in ("check", "test"):
        code, _, err = run(capsys, command)
        assert code == 1 and str(active_rules) in err and "TOML" in err


# ---------------------------------------------------------------- a file named on the command line


def test_a_good_file_with_its_own_rule_passes_both(
    capsys: pytest.CaptureFixture[str], rules_file: Callable[..., Path]
) -> None:
    path = rules_file(with_rule(GOOD_RULE))
    assert run(capsys, "check", str(path))[0] == 0
    code, out, _ = run(capsys, "test", str(path))
    count = len(rulefile.load_default().rules) + 1
    assert code == 0 and "tests passed" in out and f"in {count} rules" in out


REFUSED = {
    "a schema error": (
        with_rule(GOOD_RULE.replace('severity = "warn"', 'severity = "fatal"')),
        "no-push",
    ),
    "an unknown field": (
        with_rule(GOOD_RULE.replace('event = ["shell"]', 'event = ["shell"]\ncolour = "red"')),
        "no-push",
    ),
    "an entry for R0": (
        with_rule(GOOD_RULE.replace('"no-push"', '"R0"')),
        "R0",
    ),
    "a pattern that matches everything": (
        DEFAULT.replace("[lists]\n", '[lists]\nall = ["**"]\n', 1) + EVERYTHING,
        "no-push",
    ),
}


@pytest.mark.parametrize("label", sorted(REFUSED))
def test_check_exits_1_and_names_the_rule_for_each_kind_of_fault(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
    label: str,
) -> None:
    text, needle = REFUSED[label]
    code, out, err = run(capsys, "check", str(rules_file(text)))
    assert code == 1, (out, err)
    assert needle in err, err
    assert "ok" not in out


@pytest.mark.parametrize("label", sorted(REFUSED))
def test_test_also_refuses_a_file_that_check_refuses(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
    label: str,
) -> None:
    text, needle = REFUSED[label]
    code, _, err = run(capsys, "test", str(rules_file(text)))
    assert code == 1 and needle in err


def test_every_problem_is_printed_not_only_the_first(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
) -> None:
    text = (
        with_rule(GOOD_RULE)
        .replace('severity = "warn"', 'severity = "fatal"')
        .replace('"git push"', '"git push --f*"')
    )
    _, _, err = run(capsys, "check", str(rules_file(text)))
    assert "severity" in err and "wildcard" in err


def test_a_failing_inline_test_exits_1_naming_the_rule_and_the_test(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
) -> None:
    text = with_rule(
        GOOD_RULE.replace('steps = ["shell: git status"]', 'steps = ["shell: git push"]')
    )
    path = rules_file(text)
    assert run(capsys, "check", str(path))[0] == 0, "the schema is fine: only a test is wrong"
    code, out, err = run(capsys, "test", str(path))
    assert code == 1
    assert "no-push" in err and "test #2" in err and "expected allow" in err and "warn" in err
    assert "tests passed" not in out


def test_a_test_whose_expected_severity_is_won_by_another_rule_fails_naming_both(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
) -> None:
    # R1 blocks the send after a secret read, so the warn rule's own test never gets its warn.
    shadowed = GOOD_RULE.replace(
        'steps = ["shell: git push origin main"]',
        'steps = ["read: .env", "shell: git push origin main"]',
    )
    code, _, err = run(capsys, "test", str(rules_file(with_rule(shadowed))))
    assert code == 1 and "no-push" in err and "R1" in err


def test_an_expected_allow_fails_when_any_rule_fires(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
) -> None:
    text = with_rule(
        GOOD_RULE.replace(
            'steps = ["shell: git status"]', 'steps = ["shell: cat ~/.config/agentfly/token"]'
        )
    )
    code, _, err = run(capsys, "test", str(rules_file(text)))
    assert code == 1 and "R0" in err, "R0 is part of the rules a test runs against"


def test_the_trigger_of_an_after_then_rule_is_set_by_the_earlier_steps(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
) -> None:
    text = (
        DEFAULT.replace("[lists]\n", '[lists]\ninstall = ["pip install"]\npush = ["git push"]\n', 1)
        + """
[[rule]]
id = "no-push-after-install"
kind = "after_then"
severity = "block"
message = "No pushing after an install."
after = { event = ["shell"], command = "install" }
then = { event = ["shell"], command = "push" }
  [[rule.test]]
  steps = ["shell: pip install x", "shell: git push"]
  expect = "block"
  [[rule.test]]
  steps = ["shell: git push"]
  expect = "allow"
  [[rule.test]]
  steps = ["shell: pip install x && git push"]
  expect = "block"
"""
    )
    code, out, err = run(capsys, "test", str(rules_file(text)))
    assert code == 0, err
    assert "tests passed" in out


def test_a_rule_without_a_test_is_a_warning_not_a_failure(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
) -> None:
    bare = GOOD_RULE.split("  [[rule.test]]")[0]
    code, out, _ = run(capsys, "check", str(rules_file(with_rule(bare))))
    assert code == 0
    assert "warn: rule no-push: no inline test" in out


FLOATING_RULE = """
[[rule]]
id = "gen"
kind = "match"
severity = "block"
message = "Generated code is not read."
event = ["read"]
path = "gen_paths"
  [[rule.test]]
  steps = ["read: /w/src/a/gen.py"]
  expect = "block"
"""


def test_rules_check_warns_about_floating_patterns(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
) -> None:
    """V5b-fix2 §4.4: a floating `path` pattern loads, with a `warn:` line that names it."""
    text = default_with('gen_paths = ["src/**/gen.py"]\n', FLOATING_RULE)
    code, out, err = run(capsys, "check", str(rules_file(text)))
    assert code == 0, err
    (line,) = [line for line in out.splitlines() if line.startswith("warn:")]
    assert line == (
        "warn: rule gen: pattern 'src/**/gen.py' is checked at every folder of a path; on long, "
        "deep commands it may reach the rules limit, which then blocks the action if gen is a "
        "block rule, asks if it is a warn, and skips it if it is a highlight; anchor it if you can"
    )


HEAVY_LIST_RULE = """
[[rule]]
id = "pairs"
kind = "after_then"
severity = "block"
message = "No pairs."
after = { event = ["shell"], command = "pairs" }
then = { event = ["shell"], command = "pairs" }
  [[rule.test]]
  steps = ["shell: cat a0 b0"]
  expect = "allow"
"""


def test_rules_check_warns_about_a_heavy_command_list_once_per_list(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
) -> None:
    """Task 6b: a list whose heaviest bucket weighs more than 20 loads, with one `warn:` line for
    the list in the rule, however many of its clauses name it. Eleven one-word entries under `a0`
    weigh 22; ten weigh 20 and pass without a line."""
    heavy = [f"cat a{i} b{j}" for i in range(18) for j in range(11)]
    text = default_with(list_line("pairs", *heavy), HEAVY_LIST_RULE)
    code, out, err = run(capsys, "check", str(rules_file(text)))
    assert code == 0, err
    (line,) = [line for line in out.splitlines() if line.startswith("warn:")]
    assert line == (
        "warn: rule pairs: 11 entries of list 'pairs' share the word 'a0' and are each checked "
        "when a command holds it; on long commands the rule may reach the rules limit"
    )
    light = [f"cat a{i} b{j}" for i in range(20) for j in range(10)]
    text = default_with(list_line("pairs", *light), HEAVY_LIST_RULE)
    code, out, err = run(capsys, "check", str(rules_file(text, "light.toml")))
    assert code == 0, err
    assert not [line for line in out.splitlines() if line.startswith("warn:")]
    assert rulefile.load_default().lint == ()


def without_tests(text: str) -> str:
    """The text with every [[rule.test]] table taken out (they are indented, unlike the rules)."""
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not re.match(r"\s+(\[\[rule\.test\]\]|steps = |expect = )", line)
    )


def test_test_on_a_file_with_no_tests_fails_because_all_passed_would_be_true_of_nothing(
    capsys: pytest.CaptureFixture[str], rules_file: Callable[..., Path]
) -> None:
    path = rules_file(without_tests(DEFAULT))
    assert not rulefile.load_file(path).errors and not any(
        spec.tests for spec in rulefile.load_file(path).rules
    )
    code, out, err = run(capsys, "test", str(path))
    assert code == 1 and "no tests to run" in err and "tests passed" not in out
    code, out, err = run(capsys, "check", str(path))
    assert code == 0, "check only advises: the file is usable"
    assert "warn: rule R1: no inline test" in out


def test_a_missing_file_is_a_message_not_a_traceback(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    for command in ("check", "test"):
        code, out, err = run(capsys, command, str(tmp_path / "nope.toml"))
        assert code == 1 and "nope.toml" in err and "Traceback" not in err + out


def test_the_steps_run_against_the_rule_set_not_against_the_rules_in_force(
    capsys: pytest.CaptureFixture[str],
    rules_file: Callable[..., Path],
) -> None:
    from agentfly.recorder import rules

    before = [r.id for r in rules.RULES]
    run(capsys, "test", str(rules_file(with_rule(GOOD_RULE))))
    assert [r.id for r in rules.RULES] == before


def test_rules_alone_asks_for_check_or_test() -> None:
    with pytest.raises(SystemExit) as stop:
        main(["rules"])
    assert stop.value.code == 2

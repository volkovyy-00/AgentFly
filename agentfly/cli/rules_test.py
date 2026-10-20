"""`agentfly rules test [FILE]`: run every inline test of a rules file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentfly.cli.rules_check import add_file_argument, choose_file, load, rules_word
from agentfly.recorder import rulefile


def action_for(event: str, value: str) -> dict[str, object]:
    """The hook payload a test step stands for."""
    if event == "read":
        return {"hook_event_name": "beforeReadFile", "file_path": value}
    if event == "write":
        return {
            "hook_event_name": "preToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": value},
        }
    return {"hook_event_name": "beforeShellExecution", "command": value}


def run_tests(loaded: rulefile.RuleFile, path: Path) -> tuple[int, list[str]]:
    """Run every inline test; return how many ran and one line for each that failed.

    A test is a fresh chat, the steps in order through the real `mark`, and the verdict of the
    last step through the real `decide` over R0 and the file's rules. Unless it expects "allow",
    the rule that wins must be the rule the test belongs to: a test that another rule answers
    does not prove its own rule fires.
    """
    from agentfly.recorder import rules  # the CLI imports the engine only when it runs a test

    ruleset = rules.build_ruleset(loaded, source="file", path=str(path))
    ran: int = 0
    failures: list[str] = []
    for spec in loaded.rules:
        for number, test in enumerate(spec.tests, 1):
            ran += 1
            session = rules.Session(id="test", marked=False, start_time="test", next_step=1)
            action: dict[str, object] = {}
            for event, value in test.steps:
                action = action_for(event, value)
                session = rules.mark(action, session, ruleset)
            winner = rules.winning_rule(action, session, ruleset)
            got: str = "allow" if winner is None else winner.severity
            steps: str = "; ".join(f"{event}: {value}" for event, value in test.steps)
            label: str = f"rule {spec.id} test #{number} ({steps})"
            by: str = f" by rule {winner.id}" if winner is not None else ""
            if got != test.expect:
                failures.append(f"{label}: expected {test.expect}, got {got}{by}")
            elif winner is not None and winner.id != spec.id:
                failures.append(
                    f"{label}: expected {test.expect} from {spec.id}, but {winner.id} wins"
                )
    return ran, failures


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "test",
        help="run the inline tests of a rules file",
        description=(
            "Each [[rule.test]] lists steps ('read: PATH', 'shell: COMMAND', 'write: PATH') and "
            "what the last one must get: block, warn, highlight or allow. Exit 0 if every test "
            "passes, 1 if not (each failure names the rule and the test)."
        ),
    )
    add_file_argument(parser)
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    path, what = choose_file(args.file)
    loaded = load("test", path)
    if loaded is None:
        return 1
    ran, failures = run_tests(loaded, path)
    if failures:
        for failure in failures:
            print(f"agentfly rules test: {path}: {failure}", file=sys.stderr)
        print(f"FAILED: {len(failures)} of {ran} tests", file=sys.stderr)
        return 1
    print(f"ok: {ran} tests passed in {rules_word(len(loaded.rules))} ({path}; {what})")
    for line in loaded.lint:
        print(f"warn: {line}")
    return 0

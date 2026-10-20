"""Rules files for tests: the packaged default with a change, and the rule set built from it."""

from __future__ import annotations

import re

from agentfly.recorder import rulefile
from agentfly.recorder.rules import RuleSet, build_ruleset

BROKEN_TOML = "schema = 1\n[[rule]\n"

# A rule named R0: a rules file may not list it.
R0_ENTRY = """
[[rule]]
id = "R0"
kind = "match"
severity = "warn"
message = "gentle"
event = ["shell"]
command_class = "outbound"
"""


def default_with(lists: str = "", *rules: str, drop_r1: bool = False) -> str:
    """The packaged default with more list lines and more rules (after R1, or instead of it)."""
    text = re.sub(
        r"^\[lists\]\n", "[lists]\n" + lists, rulefile.default_text(), count=1, flags=re.M
    )
    if drop_r1:
        text = text[: text.index('[[rule]]\nid = "R1"')]
    return text + "".join(rules)


def default_as(severity: str) -> str:
    """The packaged default with R1's severity changed: a file that makes R1 gentler."""
    return rulefile.default_text().replace('severity = "block"', f'severity = "{severity}"', 1)


def ruleset_of(text: str) -> RuleSet:
    """The rule set a valid rules file gives (the test fails if the file has errors)."""
    parsed = rulefile.parse(text)
    assert parsed.errors == (), parsed.errors
    return build_ruleset(parsed, source="test", path="rules.toml")

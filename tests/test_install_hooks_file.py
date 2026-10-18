"""Editing Cursor's system hooks.json: other tools' text stays as it was (D2)."""

from __future__ import annotations

import json
import random
from typing import Any

import pytest

from agentfly.install import InstallError, hooks_file
from agentfly.install.hooks_file import HookEntry
from tests.install_helpers import OTHER_TOOL_ENTRY

PREFIX = '"/Library/Application Support/AgentFly/python/bin/python3.12"'
ENTRIES = [
    HookEntry(
        event,
        f'{PREFIX} -I -S "/Library/Application Support/AgentFly/hook_client.py" cursor {event}',
        2,
    )
    for event in ("beforeShellExecution", "preToolUse", "sessionStart")
]

OTHER_FILE = f"""{{
  "version": 1,
  "hooks": {{
    "beforeShellExecution": [
      {OTHER_TOOL_ENTRY}
    ],
    "stop": [
      {OTHER_TOOL_ENTRY}
    ]
  }}
}}
"""


def test_a_missing_or_empty_file_gets_a_new_one() -> None:
    for text in (None, "", "  \n"):
        data = json.loads(hooks_file.merge(text, ENTRIES, PREFIX))
        assert data["version"] == 1
        assert [e["timeout"] for e in data["hooks"]["preToolUse"]] == [2]


def test_other_tools_entries_stay_byte_identical_and_ours_are_added_quoted() -> None:
    merged = hooks_file.merge(OTHER_FILE, ENTRIES, PREFIX)
    assert merged.count(OTHER_TOOL_ENTRY) == 2  # theirs, untouched, text for text
    data = json.loads(merged)
    ours = hooks_file.our_entries(merged, PREFIX)
    assert sorted(e.event for e in ours) == sorted(e.event for e in ENTRIES)
    for entry in ours:
        assert entry.command.startswith(PREFIX)  # a space in the path: quoted
        assert entry.timeout == 2
    assert data["hooks"]["stop"] == [json.loads(OTHER_TOOL_ENTRY)]
    assert data["hooks"]["beforeShellExecution"][0] == json.loads(OTHER_TOOL_ENTRY)


def test_a_second_merge_changes_nothing() -> None:
    once = hooks_file.merge(OTHER_FILE, ENTRIES, PREFIX)
    assert hooks_file.merge(once, ENTRIES, PREFIX) == once


def test_removing_ours_gives_back_the_original_bytes() -> None:
    merged = hooks_file.merge(OTHER_FILE, ENTRIES, PREFIX)
    assert hooks_file.remove_ours(merged, PREFIX) == OTHER_FILE


def test_a_changed_command_replaces_ours_without_duplicates() -> None:
    old = [HookEntry(e.event, e.command + " --old", e.timeout) for e in ENTRIES]
    merged = hooks_file.merge(hooks_file.merge(OTHER_FILE, old, PREFIX), ENTRIES, PREFIX)
    assert hooks_file.same_entries(hooks_file.our_entries(merged, PREFIX), ENTRIES)


@pytest.mark.parametrize(
    "text",
    [
        '{"version":1,"hooks":{}}',
        '{"version": 1, "hooks": { }}',
        '{\n\t"version": 1,\n\t"hooks": {\n\t}\n}\n',
        '{"version": 1}',
        '{"hooks": {"stop": []}}',
        "﻿" + OTHER_FILE,
        OTHER_FILE.replace("\n", "\r\n"),
        OTHER_FILE.replace("  ", "\t"),
        OTHER_FILE.replace("  ", "    "),
        '{"version":1,"hooks":{"stop":[{"command":"a [b],{c} \\"q\\"","timeout":1}]}}',
    ],
)
def test_odd_layouts_merge_and_remove_cleanly(text: str) -> None:
    merged = hooks_file.merge(text, ENTRIES, PREFIX)
    assert len(hooks_file.our_entries(merged, PREFIX)) == len(ENTRIES)
    assert hooks_file.merge(merged, ENTRIES, PREFIX) == merged
    back = hooks_file.remove_ours(merged, PREFIX)
    assert hooks_file.our_entries(back, PREFIX) == []
    expected = json.loads(text.removeprefix("﻿"))
    actual = json.loads(back.removeprefix("﻿"))
    if "hooks" in actual and "hooks" not in expected:
        del actual["hooks"]  # the empty object we added stays
    assert actual == expected or (expected.get("hooks") == {"stop": []})
    if "audit.sh" in text:
        assert back == text  # a file with real entries comes back byte for byte


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"hooks": []}',
        '{"hooks": {"stop": {}}}',
        '{"hooks": {}, "hooks": {}}',
        '{"hooks": {} // comment\n}',
    ],
)
def test_a_shape_we_do_not_understand_is_refused(text: str) -> None:
    with pytest.raises(InstallError, match="nothing was written"):
        hooks_file.merge(text, ENTRIES, PREFIX)


def test_only_a_file_we_emptied_counts_as_holding_nothing_else() -> None:
    assert hooks_file.holds_nothing_else(
        hooks_file.remove_ours(hooks_file.new_file(ENTRIES), PREFIX)
    )
    merged = hooks_file.merge(OTHER_FILE, ENTRIES, PREFIX)
    assert not hooks_file.holds_nothing_else(hooks_file.remove_ours(merged, PREFIX))


def _whitespace(rng: random.Random) -> str:
    return rng.choice(["", " ", "  ", "\n", "\n  ", "\r\n    ", "\t", "\n\t\t"])


def _dump(value: Any, rng: random.Random) -> str:
    if isinstance(value, dict):
        body = ",".join(
            f"{_whitespace(rng)}{json.dumps(k)}{_whitespace(rng)}:{_whitespace(rng)}{_dump(v, rng)}"
            for k, v in value.items()
        )
        return "{" + body + _whitespace(rng) + "}" if value else "{}"
    if isinstance(value, list):
        body = ",".join(f"{_whitespace(rng)}{_dump(v, rng)}" for v in value)
        return "[" + body + _whitespace(rng) + "]" if value else "[]"
    return json.dumps(value)


def test_random_whitespace_never_changes_what_is_not_ours() -> None:
    rng = random.Random(7)
    events = ["beforeShellExecution", "preToolUse", "stop", "afterFileEdit"]
    for _ in range(400):
        hooks = {
            event: [
                {"command": "/x [a],{b}", "timeout": 1, "n": n} for n in range(rng.randint(1, 2))
            ]
            for event in rng.sample(events, rng.randint(1, 3))
        }
        text = _dump({"version": 1, "hooks": hooks}, rng) + rng.choice(["", "\n"])
        merged = hooks_file.merge(text, ENTRIES, PREFIX)
        assert json.loads(merged)["hooks"].keys() >= set(hooks)
        assert hooks_file.remove_ours(merged, PREFIX) == text


def test_commands_are_read_parsed_so_escaped_slashes_are_decoded() -> None:
    text = (
        '{"hooks": {"stop": [{"command": "\\/opt\\/a b\\/run.sh"}, 3, {"timeout": 1}],'
        ' "preToolUse": [{"command": "x"}]}}'
    )
    assert hooks_file.commands(text) == ["/opt/a b/run.sh", "x"]
    assert hooks_file.commands('{"version": 1}') == []
    with pytest.raises(InstallError):
        hooks_file.commands("not json")

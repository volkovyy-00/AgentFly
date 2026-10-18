"""Edit Cursor's system hooks.json without touching other tools' entries (D2, D23).

Entries are added and removed by splicing text, not by loading and dumping the file, so every
byte that is not ours stays exactly as it was. Our entries are recognised by their command: it
starts with the quoted path of the bundled interpreter (no extra JSON key is added, because an
unknown key might make Cursor reject the whole file). Every result is parsed again and compared
with a plain-data model of the edit; a mismatch, or a file shape we do not understand, raises
`InstallError` and nothing is written.
"""

from __future__ import annotations

import json
from dataclasses import astuple, dataclass
from typing import Any

from agentfly.install import InstallError

_WS = " \t\r\n"
_DECODER = json.JSONDecoder()
_BOM = "﻿"


@dataclass(frozen=True)
class HookEntry:
    event: str
    command: str
    timeout: int

    def value(self) -> dict[str, Any]:
        return {"command": self.command, "timeout": self.timeout}


@dataclass(frozen=True)
class _Child:
    """One member of an object or element of an array: where it starts and ends in the text."""

    key: str | None
    start: int
    value_start: int
    end: int


@dataclass(frozen=True)
class _Container:
    open: int
    close: int
    children: list[_Child]


# ---------------------------------------------------------------- reading the structure


def _skip(text: str, i: int) -> int:
    while i < len(text) and text[i] in _WS:
        i += 1
    return i


def _scan(text: str, start: int) -> _Container:
    """The children of the object or array opening at `start` (the text is already valid JSON)."""
    is_object: bool = text[start] == "{"
    closer: str = "}" if is_object else "]"
    i: int = _skip(text, start + 1)
    children: list[_Child] = []
    while text[i] != closer:
        child_start: int = i
        key: str | None = None
        if is_object:
            key, i = _DECODER.raw_decode(text, i)
            i = _skip(text, _skip(text, i) + 1)  # past the colon
        value_start: int = i
        _, end = _DECODER.raw_decode(text, i)
        children.append(_Child(key, child_start, value_start, end))
        i = _skip(text, end)
        if text[i] == ",":
            i = _skip(text, i + 1)
    return _Container(start, i, children)


def _find(container: _Container, key: str) -> _Child | None:
    return next((c for c in container.children if c.key == key), None)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def _parse(text: str) -> dict[str, Any]:
    """The file as data, or InstallError for anything that is not the shape Cursor documents."""
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicates)
    except ValueError as exc:
        raise InstallError(
            f"the hooks file is not valid JSON ({exc}); nothing was written"
        ) from exc
    if not isinstance(data, dict):
        raise InstallError("the hooks file is not a JSON object; nothing was written")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict) or not all(isinstance(v, list) for v in hooks.values()):
        raise InstallError(
            'the hooks file has a "hooks" entry that is not an object of lists; nothing was written'
        )
    return data


def _is_ours(element: Any, prefix: str) -> bool:
    command = element.get("command") if isinstance(element, dict) else None
    return isinstance(command, str) and command.startswith(prefix)


def our_entries(text: str, prefix: str) -> list[HookEntry]:
    """Our entries in the file, in file order (for the idempotence check and `doctor`)."""
    found: list[HookEntry] = []
    for event, elements in _parse(text.removeprefix(_BOM)).get("hooks", {}).items():
        for element in elements:
            if _is_ours(element, prefix):
                found.append(HookEntry(event, element["command"], element.get("timeout", 0)))
    return found


def commands(text: str) -> list[str]:
    """Every entry's `command`, parsed (so escapes such as `\\/` are already decoded)."""
    found: list[str] = []
    for elements in _parse(text.removeprefix(_BOM)).get("hooks", {}).values():
        for element in elements:
            command = element.get("command") if isinstance(element, dict) else None
            if isinstance(command, str):
                found.append(command)
    return found


def same_entries(a: list[HookEntry], b: list[HookEntry]) -> bool:
    """Whether two lists hold the same entries, whatever their order."""
    return sorted(a, key=astuple) == sorted(b, key=astuple)


def holds_nothing_else(text: str) -> bool:
    """True when the file is only `version` and an empty `hooks`: nothing of any tool remains."""
    data = _parse(text.removeprefix(_BOM))
    hooks = data.get("hooks", {})
    return set(data) <= {"version", "hooks"} and not any(hooks.values())


# ---------------------------------------------------------------- rendering new text


class _Style:
    def __init__(self, text: str) -> None:
        self.nl: str = "\r\n" if "\r\n" in text else "\n"
        self.pretty: bool = "\n" in text
        self.unit: str = "  "
        for line in text.splitlines():
            stripped = line.lstrip(" \t")
            if stripped and stripped != line:
                self.unit = line[: len(line) - len(stripped)]
                break

    def render(self, value: Any, indent: str, pretty: bool) -> str:
        """`value` as JSON text; lines after the first start with `indent`."""
        if not pretty:
            return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        lines = json.dumps(value, indent=self.unit, ensure_ascii=False).split("\n")
        return (self.nl + indent).join(lines)


def _line_indent(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    line = text[start:pos]
    return line[: len(line) - len(line.lstrip(" \t"))]


def _member(key: str | None, rendered: str, pretty: bool) -> str:
    """`"key": value` for an object member, or just the value for an array element."""
    return rendered if key is None else json.dumps(key) + (": " if pretty else ":") + rendered


def _insert(text: str, container: _Container, key: str | None, value: Any, style: _Style) -> str:
    """Append a member (`key` given) or an element to the object or array at `container`."""
    if container.children:
        last = container.children[-1]
        j = last.start
        while text[j - 1] in _WS:
            j -= 1
        gap: str = text[j : last.start]
        pretty = "\n" in gap
        indent = gap.rsplit("\n", 1)[-1] if pretty else ""
        new = _member(key, style.render(value, indent, pretty), pretty)
        return text[: last.end] + "," + gap + new + text[last.end :]
    base: str = _line_indent(text, container.open)
    indent = base + style.unit
    new = _member(key, style.render(value, indent, style.pretty), style.pretty)
    inner = style.nl + indent + new + style.nl + base if style.pretty else new
    return text[: container.open + 1] + inner + text[container.close :]


def _delete(text: str, container: _Container, index: int) -> str:
    """Remove child `index` with the comma that separated it from its neighbour."""
    children = container.children
    if len(children) == 1:
        return text[: container.open + 1] + text[container.close :]
    if index == len(children) - 1:
        return text[: children[index - 1].end] + text[children[index].end :]
    return text[: children[index].start] + text[children[index + 1].start :]


# ---------------------------------------------------------------- the edits


def _hooks_container(text: str) -> _Container | None:
    top = _scan(text, _skip(text, 0))
    member = _find(top, "hooks")
    return _scan(text, member.value_start) if member else None


def _remove_ours(text: str, prefix: str) -> str:
    while True:
        hooks = _hooks_container(text)
        if hooks is None:
            return text
        for index, event in enumerate(hooks.children):
            array = _scan(text, event.value_start)
            ours = [
                i
                for i, element in enumerate(array.children)
                if _is_ours(json.loads(text[element.start : element.end]), prefix)
            ]
            if ours:
                if len(ours) == len(array.children):
                    text = _delete(text, hooks, index)
                else:
                    text = _delete(text, array, ours[0])
                break
        else:
            return text


def _add(text: str, entry: HookEntry, style: _Style) -> str:
    top = _scan(text, _skip(text, 0))
    if _find(top, "hooks") is None:
        text = _insert(text, top, "hooks", {}, style)
    hooks = _hooks_container(text)
    assert hooks is not None
    member = _find(hooks, entry.event)
    if member is None:
        return _insert(text, hooks, entry.event, [entry.value()], style)
    return _insert(text, _scan(text, member.value_start), None, entry.value(), style)


def _model(data: dict[str, Any], prefix: str, entries: list[HookEntry]) -> dict[str, Any]:
    """The edit done on plain data: what the spliced text must parse to."""
    if "hooks" not in data and not entries:
        return data
    hooks: dict[str, list[Any]] = {}
    for event, elements in data.get("hooks", {}).items():
        kept = [e for e in elements if not _is_ours(e, prefix)]
        if kept or len(kept) == len(elements):  # an array that held only ours goes away with them
            hooks[event] = kept
    for entry in entries:
        hooks.setdefault(entry.event, []).append(entry.value())
    return {**data, "hooks": hooks}


def new_file(entries: list[HookEntry]) -> str:
    """A hooks file that does not exist yet."""
    hooks: dict[str, list[Any]] = {}
    for entry in entries:
        hooks.setdefault(entry.event, []).append(entry.value())
    return json.dumps({"version": 1, "hooks": hooks}, indent=2, ensure_ascii=False) + "\n"


def merge(text: str | None, entries: list[HookEntry], prefix: str) -> str:
    """The file with exactly `entries` as ours and everything else untouched.

    Returns `text` itself when our entries are already there (a second run changes nothing).
    """
    if text is None or not text.strip():
        return new_file(entries)
    bom = _BOM if text.startswith(_BOM) else ""
    body = text.removeprefix(_BOM)
    data = _parse(body)
    if same_entries(our_entries(body, prefix), entries):
        return text
    style = _Style(body)
    result = _remove_ours(body, prefix)
    for entry in entries:
        result = _add(result, entry, style)
    _verify(result, _model(data, prefix, entries))
    return bom + result


def remove_ours(text: str, prefix: str) -> str:
    """The file with our entries taken out and every other byte as it was."""
    bom = _BOM if text.startswith(_BOM) else ""
    body = text.removeprefix(_BOM)
    data = _parse(body)
    result = _remove_ours(body, prefix)
    _verify(result, _model(data, prefix, []))
    return bom + result


def _verify(result: str, expected: dict[str, Any]) -> None:
    try:
        actual = _parse(result)
    except InstallError as exc:
        raise InstallError(f"internal check failed ({exc}); nothing was written") from exc
    if actual != expected:
        raise InstallError("internal check failed: the edited hooks file differs from the plan")

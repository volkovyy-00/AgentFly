"""Rule engine: R0 in code, the rules file's rules, and the decision (D10, D11).

`mark` records what a chat has done (R1's mark in `Session.marked`, every other `after_then`
rule's trigger in `Session.triggers`); `decide` picks the strictest rule that fires. R0 is code
only and always first. The other rules come from a rules file (`rulefile.py`): the packaged
default, or the root-owned active file when the recorder was started with a valid one.
"""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from agentfly.recorder import DEFAULT_PORT, rulefile
from agentfly.recorder.names import hosts_in_command, is_local_host
from agentfly.recorder.normalize import SUB_PREFIX, Parsed, base_name, interpreter, normalize
from agentfly.recorder.rulefile import RuleFile, RuleSpec

Action = dict[str, Any]

R0_MESSAGE: str = (
    "Blocked by rule R0: this touches AgentFly's own files or controls the recorder, "
    "which only the owner may do."
)
R1_MESSAGE: str = (
    "Blocked by rule R1: a secret was read earlier in this session, and now data is being sent out."
)

# R0 (SPEC section 5): the recorder's own process, as the kill check sees it. Tests patch these.
RECORDER_PID: int = os.getpid()
RECORDER_PPID: int = os.getppid()

# Tools that always count as outbound when marked (no local exception needed).
_ALWAYS_OUTBOUND: frozenset[str] = frozenset({"gh", "aws"})
# Tools that are outbound only when a non-local host appears in args.
_HOSTED_OUTBOUND: frozenset[str] = frozenset({"curl", "wget", "nc", "scp", "ssh", "rsync"})


@dataclass
class Session:
    id: str
    marked: bool
    start_time: str
    next_step: int
    # D21 A: the Task call that started this chat as a subagent, and the parent chat once known.
    parent_call: str = ""
    parent_id: str = ""
    # D21 fallback: the mark this chat inherited from its workspace holds until this time (epoch).
    inherited_until: float = 0.0
    # V5b: ids of the `after_then` rules (other than R1, whose trigger is `marked`) that fired in
    # this chat, and, per id, the time a trigger inherited through the workspace fallback ends.
    # `inherited_triggers` is replaced, never changed in place.
    triggers: frozenset[str] = frozenset()
    inherited_triggers: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    message: str
    check: Callable[[Action, Session], bool]
    kind: str = "builtin"  # "match" and "after_then" come from a rules file
    # after_then only: does this action make the trigger fire? (`check` tests the follow-up)
    after: Callable[[Action], bool] | None = None


def _shell_command(action: Action) -> str | None:
    if str(action.get("hook_event_name", "")) != "beforeShellExecution":
        return None
    return str(action.get("command", ""))


def _argv_is_outbound(argv: tuple[str, ...]) -> bool:
    lower_argv: list[str] = [a.lower() for a in argv]
    base_names: list[str] = [base_name(a) for a in argv]

    if any(name in _ALWAYS_OUTBOUND for name in base_names):
        return True

    if "git" in base_names and "push" in lower_argv:
        return True

    if any(interpreter(name) for name in base_names) and any("http" in a for a in lower_argv):
        return True

    if any(name in _HOSTED_OUTBOUND for name in base_names):
        hosts: list[str] = hosts_in_command(argv)
        if not hosts:
            # Tool present but no host parsed — treat as outbound (safe for demo).
            return True
        return any(not is_local_host(h) for h in hosts)

    return False


@lru_cache(maxsize=16)  # every `command_class` clause of every rule asks about the same command
def parsed_is_outbound(parsed: Parsed) -> bool:
    """SPEC section 5 'Blocking': unparseable text, code a shell reads, inline code, or a tool."""
    if parsed.unparsed or parsed.unquoted_heredoc or parsed.code_heredoc or parsed.one_liner:
        return True
    return any(_argv_is_outbound(argv) for argv in parsed.commands)


def is_outbound_send(action: Action) -> bool:
    """True if a shell command looks like sending data off-box (after normalisation)."""
    cmd: str | None = _shell_command(action)
    if cmd is None or not cmd.strip():
        return False
    return parsed_is_outbound(normalize(cmd))


# ---------------------------------------------------------------- R0: protect AgentFly itself

# Case-folded. `hooks.json` also covers `.cursor/hooks.json` in any folder and
# `/Library/Application Support/Cursor/hooks.json` (and a bare name after a `cd`). The last three
# are the recorder's launchd labels (its own, Homebrew's current and legacy): they name the service
# file in `~/Library/LaunchAgents` with or without `.plist`, which `defaults` adds on its own.
# The package `init -g` and `uninstall` run as root (V3c): its tool environment under `uv tool`,
# `pipx` and Homebrew (`site-packages/agentfly` also catches a `cd` first and a custom
# `UV_TOOL_DIR`), and the two entry scripts in `~/.local/bin` (`agentfly` and `agentfly-hook`).
# Running `~/.local/bin/agentfly status` by its full path is denied too; `agentfly status` is not.
# agentfly/hook_client.py `_GUARD_PATHS` is the same list.
_R0_PATHS: tuple[str, ...] = (
    ".config/agentfly",
    ".local/share/agentfly",
    "/library/application support/agentfly",
    "hooks.json",
    "dev.agentfly.recorder",
    "homebrew.mxcl.agentfly",
    "sh.brew.agentfly",
    "uv/tools/agentfly-recorder",
    "pipx/venvs/agentfly-recorder",
    "site-packages/agentfly",
    "/cellar/agentfly",
    "/homebrew/opt/agentfly",
    "/local/opt/agentfly",
    ".local/bin/agentfly",
)
_R0_SUBCOMMANDS: frozenset[str] = frozenset({"serve", "stop", "uninstall", "wipe"})
# `uv tool`, `pipx` and `brew` verbs that install, change or remove a tool (V3c). Denied when
# they could reach AgentFly: its name, a file or URL, a variable, or every tool at once.
_PACKAGE_VERBS: dict[str, frozenset[str]] = {
    "uv": frozenset({"install", "upgrade", "uninstall"}),
    "pipx": frozenset(
        {"install", "install-all", "upgrade", "upgrade-all", "reinstall", "reinstall-all"}
        | {"uninstall", "uninstall-all", "inject", "uninject", "runpip"}
    ),
    "brew": frozenset(
        {"install", "upgrade", "reinstall", "uninstall", "remove", "rm", "link", "unlink"}
    ),
}
_ARCHIVE_SUFFIXES: tuple[str, ...] = (".whl", ".tar.gz", ".tgz", ".zip")
# Options whose value is a Python, not a tool: `uv tool install --python /opt/x/python3 ruff`.
_PYTHON_OPTIONS: frozenset[str] = frozenset({"--python", "-p"})
# Programs that hand their input to a command as operands the text does not show.
_FEEDERS: frozenset[str] = frozenset({"xargs", "parallel"})
_EXEC_FLAGS: frozenset[str] = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_R0_KILLERS: frozenset[str] = frozenset({"pkill", "killall"})
_R0_RECORDER_WORDS: tuple[str, ...] = ("agentfly", "uvicorn", "recorder")
_PROCESS_LOOKUPS: tuple[str, ...] = ("pgrep", "pidof", "lsof", "ps", "fuser")
_R0_LOOKUPS: tuple[str, ...] = (*_PROCESS_LOOKUPS, "agentfly")
_PORT = re.compile(
    rf"(?<![a-z0-9])(?<!\d\.){DEFAULT_PORT}(?![a-z0-9])(?!\.\d)"
)  # D25; not inside a hex id
_INT = re.compile(r"-?\d+")
_LOOKUP = re.compile(rf"(?<![a-z0-9_])({'|'.join(_PROCESS_LOOKUPS)})(?![a-z0-9_])")


def _fold_path(text: str) -> str:
    """Case-folded text with `\\`, repeated `/` and `/./` removed (`Application\\ Support`)."""
    plain: str = text.casefold().replace("\\", "")
    while "//" in plain:
        plain = plain.replace("//", "/")
    return plain.replace("/./", "/")


def _path_forms(text: str) -> list[str]:
    """The text folded, and again with `..` resolved when it looks like a path."""
    forms: list[str] = [_fold_path(text)]
    if "/" in text and ".." in text:
        forms.append(_fold_path(posixpath.normpath(text)))
    return forms


def _could_be_agentfly(word: str, manager: str) -> bool:
    """An operand that is not a plain tool name: a file, a URL, a variable or a pattern."""
    if any(mark in word for mark in "$`*?{") or word.endswith(_ARCHIVE_SUFFIXES):
        return True
    if manager == "brew":  # `user/tap/formula` is a plain name to brew; a path or URL is not
        return word.startswith((".", "/", "~")) or "://" in word or word.endswith(".rb")
    return "/" in word or ":" in word or word.startswith(".")


def _package_command_hit(words: list[str], names: list[str], *, lossy: bool = False) -> bool:
    """`uv tool install --force dist/*.whl`, `pipx reinstall agentfly-recorder`, `brew upgrade`.

    `lossy`: the words come from text that could not be parsed, so an operand may have been lost
    (`brew upgrade $(x`); any such verb is then taken for aimed at AgentFly.
    """
    managers: list[int] = [i for i, name in enumerate(names) if name in _PACKAGE_VERBS]
    if not managers:
        return False
    # `echo x.whl | xargs uv tool install`, `find . -exec uv tool install {} \;`: operands unseen.
    lossy = lossy or any(n in _FEEDERS for n in names) or any(w in _EXEC_FLAGS for w in words)
    named: bool = any("agentfly" in w for w in words)
    end: int = len(words)
    for manager in {names[i] for i in managers}:
        verbs: frozenset[str] = _PACKAGE_VERBS[manager]
        # Tables read from the right, so each manager word costs O(1): a long command must not
        # keep R0 busy past the hook client's wait (it would then answer with the offline guard).
        verb_at, tool_at = [end] * (end + 1), [end] * (end + 1)
        all_from, operand_from, aimed_from = ([False] * (end + 1) for _ in range(3))
        for k in range(end - 1, -1, -1):
            word: str = words[k]
            operand: bool = not word.startswith("-") and (
                k == 0 or words[k - 1] not in _PYTHON_OPTIONS
            )
            verb_at[k] = k if word in verbs else verb_at[k + 1]
            tool_at[k] = k if word == "tool" else tool_at[k + 1]
            all_from[k] = all_from[k + 1] or word == "--all"
            operand_from[k] = operand_from[k + 1] or operand
            aimed_from[k] = aimed_from[k + 1] or (operand and _could_be_agentfly(word, manager))
        for index in (i for i in managers if names[i] == manager):
            start: int = index + 1
            if manager == "uv":
                if tool_at[start] == end:
                    continue
                start = tool_at[start] + 1
            at: int = verb_at[start]
            if at == end:
                continue
            if (
                lossy
                or named
                or words[at].endswith("-all")
                or all_from[start]
                or aimed_from[at + 1]
                or (words[at] == "upgrade" and not operand_from[at + 1])
            ):
                return True
    return False


def _r0_command_hit(argv: tuple[str, ...], *, lossy: bool = False) -> bool:
    """`agentfly serve|stop|uninstall|wipe`, `brew services`, `launchctl`, `pkill`, `kill`, and
    `uv tool`, `pipx` or `brew` installing, upgrading or removing a tool. `lossy`: the text could
    not be parsed, so these words are a plain scan of it."""
    words: list[str] = [w.casefold() for w in argv]
    names: list[str] = [base_name(w) for w in argv]
    for index, name in enumerate(names):
        if (name == "agentfly" or name.startswith("agentfly.")) and any(
            w in _R0_SUBCOMMANDS for w in words[index + 1 :]
        ):
            return True
    if "brew" in names and "services" in words:
        if any("agentfly" in w or w == "--all" for w in words):
            return True
    if "launchctl" in names and any("agentfly" in w for w in words):
        return True
    if _package_command_hit(words, names, lossy=lossy):
        return True
    if any(name in _R0_KILLERS for name in names):
        rest: list[str] = [w for w, n in zip(words, names, strict=True) if n not in _R0_KILLERS]
        if any(key in w for w in rest for key in _R0_RECORDER_WORDS):
            return True
    if "kill" in names:
        return _kill_hits_recorder(words, names.index("kill"))
    return False


def _kill_hits_recorder(words: list[str], at: int) -> bool:
    """`kill` of the recorder's PID, of every process (`0`, `-1`), or of something looked up."""
    own: set[int] = {RECORDER_PID} | ({RECORDER_PPID} if RECORDER_PPID > 1 else set())
    args: list[str] = words[at + 1 :]
    for position, arg in enumerate(args):
        if any(f"{SUB_PREFIX}{key}" in arg or f",{key}" in arg for key in _R0_LOOKUPS):
            return True
        if not _INT.fullmatch(arg):
            continue
        number: int = int(arg)
        if abs(number) in own or arg == "0":  # `kill -0 PID` only probes
            return True
        if number == -1 and position > 0:  # `kill -1 123` is SIGHUP, `kill -9 -1` is everything
            return True
    return False


def _action_paths(action: Action) -> list[str]:
    """Every file the action names: a Read, a Write or Edit (`tool_input`), an after-edit."""
    found: list[str] = []
    value: Any = action.get("file_path")
    if isinstance(value, str):
        found.append(value)
    tool_input: Any = action.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "target_file"):
            if isinstance(tool_input.get(key), str):
                found.append(tool_input[key])
    attachments: Any = action.get("attachments")
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                found += [str(item[key]) for key in ("file_path", "path") if key in item]
            elif isinstance(item, str):
                found.append(item)
    return found


def check_r0(action: Action, session: Session) -> bool:  # noqa: ARG001 - a rule gets the session
    """AgentFly's own files and process: always, marked or not (SPEC section 5)."""
    texts: list[str] = list(_action_paths(action))
    cmd: str | None = _shell_command(action)
    if cmd is not None:
        texts.append(cmd)
        cwd: Any = action.get("cwd")
        if isinstance(cwd, str):
            texts.append(cwd)
    haystack: str = "\n".join(form for text in texts for form in _path_forms(text))
    if any(path in haystack for path in _R0_PATHS):
        return True
    if cmd is None:
        return False
    parsed: Parsed = normalize(cmd)
    # Word by word too: `~/.config/"agentfly"`, `$'..'`, `a/../.config/agentfly`.
    words: list[str] = [w for argv in parsed.all_commands() for w in argv]
    word_forms: str = "\n".join(form for w in words for form in _path_forms(w))
    if any(path in word_forms for path in _R0_PATHS):
        return True
    if _PORT.search(haystack) or _PORT.search(word_forms):
        return True
    if any(_r0_command_hit(argv, lossy=parsed.unparsed) for argv in parsed.all_commands()):
        return True
    if parsed.unparsed and _LOOKUP.search(cmd.casefold()):
        # Substitutions are lost in text that cannot be parsed: a `kill` next to a lookup is aimed.
        return any("kill" in {base_name(w) for w in argv} for argv in parsed.all_commands())
    return False


# ---------------------------------------------------------------- the rule set (V5b)

MARK_RULE: str = rulefile.MARK_RULE  # the after_then rule whose trigger is `Session.marked`
BLOCK_TAIL: str = " Do not retry with another tool or language. Stop and tell the user."
SKIP_TAIL: str = " If the user skips this, do not retry with another tool or language."

# Command classes a rules file may name (`command_class = "outbound"`): engine code, not data.
# (tests/test_rules_load.py checks that these names are the ones `rulefile` accepts.)
CLASSES: dict[str, rulefile.CommandClass] = {"outbound": parsed_is_outbound}

_SEVERITY_RANK: dict[str, int] = {"block": 2, "warn": 1, "highlight": 0}
_VERDICT: dict[str, str] = {"block": "blocked", "warn": "warned", "highlight": "highlighted"}

R0_RULE: Rule = Rule(id=rulefile.RESERVED_ID, severity="block", message=R0_MESSAGE, check=check_r0)


def _never(action: Action) -> bool:  # noqa: ARG001
    return False


# ---------------------------------------------------------------- the rules limit (V5b-fix2)

# A rule is unfinished when the hook's steps (floating patterns, command lists) run out while its
# trigger or check runs (`rulefile.WorkLimit`). An unfinished block rule denies with LIMIT_RULE, an
# unfinished warn asks with LIMIT_WARN_RULE. The space keeps the id outside the file id grammar;
# neither rule is ever in `RuleSet.rules`.
LIMIT_ID: str = "rules limit"
LIMIT_MESSAGE: str = (
    "AgentFly's rules took too long to check this action (the rules limit). Simplify the rules "
    "file's patterns or command lists; `agentfly rules check` may name the heavy ones."
)


def _never_fires(action: Action, session: Session) -> bool:  # noqa: ARG001
    return False


LIMIT_RULE: Rule = Rule(LIMIT_ID, "block", LIMIT_MESSAGE, _never_fires)
LIMIT_WARN_RULE: Rule = Rule(LIMIT_ID, "warn", LIMIT_MESSAGE, _never_fires)


@contextmanager
def one_hook() -> Iterator[rulefile.Meter]:
    """Run one hook's `mark` and `decide` under a fresh meter of `rulefile.FLOAT_STEPS` steps."""
    with rulefile.metered(rulefile.Meter(left=rulefile.FLOAT_STEPS)) as meter:
        yield meter


def _note_unfinished(rule_id: str) -> None:
    meter: rulefile.Meter | None = rulefile.current_meter()
    assert meter is not None, "only a meter raises WorkLimit"
    meter.note(rule_id)


@dataclass(frozen=True)
class RuleSet:
    """The rules in force: R0 first, then the file's rules in file order."""

    rules: tuple[Rule, ...]
    source: str  # "default", "active", or what a caller calls its own file
    path: str  # the file the rules came from
    problem: str | None  # why the active file was not used (the default runs instead)
    secret: Callable[[Action], bool]  # does this action read a secret? (sets `Session.marked`)
    broken: bool = False  # the packaged default itself could not be read: only R0 runs


def _compose(spec: RuleSpec) -> Rule:
    if spec.kind == "match":
        clause = spec.clause
        assert clause is not None

        def check_match(action: Action, session: Session) -> bool:  # noqa: ARG001
            return clause.matches(action, CLASSES)

        return Rule(spec.id, spec.severity, spec.message, check_match, kind="match")
    after, then = spec.after, spec.then
    assert after is not None and then is not None
    rid: str = spec.id

    def check_then(action: Action, session: Session) -> bool:
        fired: bool = session.marked if rid == MARK_RULE else rid in session.triggers
        return fired and then.matches(action, CLASSES)

    def trigger(action: Action) -> bool:
        return after.matches(action, CLASSES)

    return Rule(spec.id, spec.severity, spec.message, check_then, kind="after_then", after=trigger)


def build_ruleset(file: RuleFile, *, source: str, path: str) -> RuleSet:
    """Rules from a file that `rulefile.load_bytes` accepted. R0 is added in front; it is never
    in a file.

    Whether an action reads a secret is decided by R1's `after` clause, so the lists in the file
    rule. Every accepted file has an R1 at least as strong as the program's minimum (D27); a file
    without one never gets here, and asking for its rules is a mistake in the caller.
    """
    composed: tuple[Rule, ...] = tuple(_compose(spec) for spec in file.rules)
    secret: Callable[[Action], bool] | None = next(
        (rule.after for rule in composed if rule.id == MARK_RULE and rule.after is not None), None
    )
    if secret is None:
        raise ValueError(f"a rules file without {MARK_RULE} was not checked by load_bytes")
    return RuleSet((R0_RULE, *composed), source, path, None, secret)


def _load_default() -> RuleSet:
    path: str = str(rulefile.default_path())
    try:
        loaded: RuleFile = rulefile.load_default()
        if not loaded.errors:
            return build_ruleset(loaded, source="default", path=path)
        reason: str = rulefile.summary(loaded.errors)
    except Exception as exc:  # noqa: BLE001 - a damaged install must not stop `uninstall`
        reason = f"{type(exc).__name__}: {exc}"
    # Only R0 runs, and the recorder refuses to start on it (`app.lifespan`).
    problem = f"the packaged default rules cannot be used: {reason}"
    return RuleSet((R0_RULE,), "default", path, problem, _never, broken=True)


DEFAULT: RuleSet = _load_default()
RULES: list[Rule] = list(DEFAULT.rules)  # the rules in force; R0 first
_active: RuleSet = DEFAULT


def current() -> RuleSet:
    return _active


def activate(ruleset: RuleSet) -> None:
    """Put a rule set in force. The recorder does this once at start (and tests, per test)."""
    global _active
    RULES[:] = ruleset.rules
    _active = ruleset


def _refusal(path: Path, errors: tuple[str, ...]) -> str:
    """`rulefile.refusal`, unless the packaged default is damaged too: then nothing runs instead
    and the recorder refuses to start (`app.lifespan`), so the line ends with the default's own
    reason, not with "in force" (CR6)."""
    line: str = rulefile.refusal(path, errors)
    if not DEFAULT.broken:
        return line
    return line.removesuffix(rulefile.DEFAULT_IN_FORCE) + (DEFAULT.problem or "")


def load_active() -> RuleSet:
    """The active file's rules if it exists, is trusted and valid, else the packaged default.

    Never raises. A file that exists but cannot be used (a link, not root's, writable by others,
    or wrong inside) is reported in `problem`; a missing file is the normal case of a developer
    `serve` and says nothing.
    """
    path, present = rulefile.in_force_path()
    try:
        if not present:
            return DEFAULT
        loaded: RuleFile = rulefile.load_active_file(path)
        if loaded.errors:
            return replace(DEFAULT, problem=_refusal(path, loaded.errors))
        return build_ruleset(loaded, source="active", path=str(path))
    except Exception as exc:  # noqa: BLE001 - the recorder must start whatever the file holds
        reason = (f"could not be read ({type(exc).__name__})",)
        return replace(DEFAULT, problem=_refusal(path, reason))


def find_rule(rule_id: str | None) -> Rule | None:
    """The rule in force with this id (one lookup per hook; see `app.apply_rules`), or the limit
    rule for its id."""
    if rule_id == LIMIT_ID:
        return LIMIT_RULE
    return next((rule for rule in _active.rules if rule.id == rule_id), None)


def reads_secret(action: Action) -> bool:
    """Does this action read a secret by the rule set's lists? (What sets `Session.marked`.)"""
    return _active.secret(action)


def is_secret_path(path: str) -> bool:
    """Is this file a secret by the rule set's lists? (The page's `sensitive` badge asks.)"""
    return reads_secret({"hook_event_name": "beforeReadFile", "file_path": path})


def mark(action: Action, session: Session, rules: RuleSet | None = None) -> Session:
    """Return the session with what this action sets off: R1's mark and every after_then trigger.

    Call it before `decide`: an action that sets a trigger off and is also the follow-up (`cat .env
    | curl …`, `pip install x && git push`) is judged with the trigger already set. A trigger left
    unfinished by the hook's meter is not recorded; the meter notes the rule (V5b-fix2 §4.3).
    """
    ruleset: RuleSet = rules or _active
    marked: bool = session.marked or ruleset.secret(action)
    fired: set[str] = set()
    for rule in ruleset.rules:
        if rule.after is None or rule.id == MARK_RULE or rule.id in session.triggers:
            continue
        try:
            if rule.after(action):
                fired.add(rule.id)
        except rulefile.WorkLimit:
            _note_unfinished(rule.id)
    if marked == session.marked and not fired:
        return session
    return replace(session, marked=marked, triggers=session.triggers | fired)


def _outcome(rule: Rule, action: Action, session: Session) -> bool | None:
    """Whether the rule fires, or None when the hook's meter left it (or its trigger) unfinished.

    `session` is the one the rules see (`SessionStore.effective`). A trigger that `mark` left
    unfinished but that this session holds all the same (through a parent chat or the workspace
    fallback: `mark` looks only at the chat's own) is held, so the check runs as usual (CR2)."""
    meter: rulefile.Meter | None = rulefile.current_meter()
    held: bool = rule.after is not None and rule.id in session.triggers
    if meter is not None and rule.id in meter.unfinished and not held:
        return None
    try:
        return rule.check(action, session)
    except rulefile.WorkLimit:
        _note_unfinished(rule.id)
        return None


def winning_rule(action: Action, session: Session, rules: RuleSet | None = None) -> Rule | None:
    """The strictest rule that fires (block, then warn, then highlight); a tie goes to the first.

    One pass in file order (V5b-fix2 §4.3). An unfinished block rule makes the answer LIMIT_RULE,
    unless a block before it fired or R1 fires after it; an unfinished warn counts at its place as
    LIMIT_WARN_RULE; an unfinished highlight is skipped. With no meter nothing is unfinished.
    """
    limit_block: bool = False
    best: Rule | None = None
    for rule in (rules or _active).rules:
        if limit_block and rule.id != MARK_RULE:
            continue  # only R1 can still change a deny
        outcome: bool | None = _outcome(rule, action, session)
        if rule.severity == "block":
            if outcome is None:
                limit_block = True
            elif outcome:
                return rule  # nothing outranks a block, and the first block is the tie-break
            continue
        if outcome:
            candidate: Rule = rule
        elif outcome is None and rule.severity == "warn":
            candidate = LIMIT_WARN_RULE
        else:
            continue  # not fired, or an unfinished highlight (the meter noted it)
        if best is None or _SEVERITY_RANK[candidate.severity] > _SEVERITY_RANK[best.severity]:
            best = candidate
    return LIMIT_RULE if limit_block else best


def decide(
    action: Action, session: Session, rules: RuleSet | None = None
) -> tuple[str, str | None]:
    """Return (verdict, rule_id): blocked, warned, highlighted or allow. Pure: call mark() first."""
    rule: Rule | None = winning_rule(action, session, rules)
    if rule is None:
        return ("allow", None)
    return (_VERDICT[rule.severity], rule.id)


def block_messages(rule: Rule | None) -> tuple[str, str]:
    """user_message, agent_message of a deny. A rule that is gone gets R1's text (as before)."""
    message: str = rule.message if rule is not None else R1_MESSAGE
    return message, message + BLOCK_TAIL


def ask_messages(rule: Rule) -> tuple[str, str]:
    """user_message, agent_message of a warn on a shell command (Cursor asks the user)."""
    return rule.message, rule.message + SKIP_TAIL


def deny_messages(rule_id: str) -> tuple[str, str]:
    """user_message, agent_message for a blocked rule."""
    return block_messages(find_rule(rule_id))

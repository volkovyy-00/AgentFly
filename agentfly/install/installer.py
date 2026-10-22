"""Install and remove AgentFly's system files (SPEC section 7, D1, D2, D5, D23).

Order matters. Install: check everything, stage the Python and the client, run the exact
registered commands once, move them into place, write the hash record, and only then add the
hook entries. Uninstall: take the hook entries out first, then move the folder out of the way
(one rename, so the registered interpreter path is gone at once) and delete it. A hooks entry
that points at a missing client makes Python exit 2, and Cursor then denies every action
(S2 F1); a missing interpreter exits 127 and Cursor lets the action through. So no step may
leave the interpreter in place while the client is gone. Before any of that, uninstall copies an
edited rules file next to the `hooks.json` backups (D30); a copy it cannot write stops it there.
"""

from __future__ import annotations

import errno
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from agentfly.install import InstallError, cursor, hooks_file, packages, pythons, records
from agentfly.install.hooks_file import HookEntry
from agentfly.install.layout import INTERPRETER_REL, Layout
from agentfly.install.pythons import PythonBuild
from agentfly.recorder import rulefile

# Cursor's timeout is in seconds. With the recorder down the client answers in about 0.57 s; with
# it up, in about 60 ms. A Cursor timeout fails open, so there is headroom for a busy machine.
TIMEOUT_SECONDS: int = 2
_UNSAFE_IN_QUOTES: frozenset[str] = frozenset('"$`\\\n')


@dataclass(frozen=True)
class Outcome:
    changed: bool
    messages: list[str]
    cursor_reload: bool = True  # False when only the rules file changed: Cursor reads no rules


# ---------------------------------------------------------------- what is registered


def prefix(layout: Layout) -> str:
    """How our entries are recognised: the quoted path of the bundled interpreter."""
    return f'"{layout.interpreter}"'


def command_for(interpreter: Path, client: Path, event: str) -> str:
    return f'"{interpreter}" -I -S "{client}" cursor {event}'


def desired_entries(layout: Layout) -> list[HookEntry]:
    return [
        HookEntry(event, command_for(layout.interpreter, layout.client, event), TIMEOUT_SECONDS)
        for event in cursor.EVENTS
    ]


def client_source() -> Path:
    return Path(__file__).resolve().parents[1] / "hook_client.py"


def agentfly_version() -> str:
    try:
        return metadata.version("agentfly-recorder")
    except metadata.PackageNotFoundError:
        return "unknown"


def _check_paths(layout: Layout) -> None:
    for path in (layout.system_root, layout.cursor_dir):
        if _UNSAFE_IN_QUOTES & set(str(path)):
            raise InstallError(f"{path} has a character that cannot be quoted safely in a command")


# ---------------------------------------------------------------- small file helpers


def _chown(path: Path, layout: Layout) -> None:
    if layout.owner is not None and os.geteuid() == 0:
        os.lchown(path, *layout.owner)


def _make_dir(path: Path, layout: Layout) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o755)
    _chown(path, layout)


def _write_atomic(path: Path, data: bytes, layout: Layout, mode: int = 0o644) -> None:
    """Write beside the target, flush to disk, then rename over it."""
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        # A fresh 0600 file: a stale temp (its mode kept) or a link at this name gets no bytes.
        temp.unlink(missing_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        with open(os.open(temp, flags, 0o600), "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        _chown(temp, layout)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


DEFAULT_RECORD_PATH = "agentfly/rules/default.toml"  # as the wheel's RECORD writes it


def _packaged_default(current: packages.Check) -> bytes:
    """The packaged default rules, read once, checked, and nothing else is ever written.

    `packages.require` hashed the tool environment at the start; the file is read again here, so
    its bytes are compared with that RECORD hash and must parse cleanly under the rules the
    recorder applies (D27). What is returned is what gets written.
    """
    wanted = packages.recorded_hash(current, DEFAULT_RECORD_PATH)
    if wanted is None:
        raise InstallError(
            f"{DEFAULT_RECORD_PATH} is not listed in AgentFly's RECORD, so the default rules "
            "cannot be checked; nothing was changed"
        )
    try:
        data = rulefile.default_path().read_bytes()
    except OSError as exc:
        # The error's text names the path, which may hold control characters (packages.visible).
        raise InstallError(
            f"cannot read the packaged default rules ({packages.visible(str(exc))})"
        ) from exc
    if rulefile.sha256_of(data) != wanted:
        raise InstallError(
            "the packaged default rules are not the file that was checked a moment ago; nothing "
            "was changed. Reinstall AgentFly from a source you trust, then run `agentfly init -g`"
        )
    loaded = rulefile.load_bytes(data)
    if loaded.errors:
        raise InstallError(
            f"the packaged default rules cannot be used ({rulefile.summary(loaded.errors)}); "
            "nothing was changed"
        )
    return data


RULES_WRITTEN = frozenset({"missing", "older", "untrusted"})  # states in which `init -g` writes


def check_packaged_default(layout: Layout, current: packages.Check) -> None:
    """Raise the error root's install would raise about the rules file: a link or a folder in its
    place (CR7), or a damaged default it is about to write.

    The unprivileged run calls this before the password, so either stops there. It is called only
    when there is work to do, so a file the recorder cannot read (`unreadable`) stops it too: root
    would refuse it before changing anything. Where the file is the owner's (`edited`) or cannot be
    opened (`unknown`), nothing is written, so nothing here can fail.
    """
    state = rules_state(layout, packages.recorded_hash(current, DEFAULT_RECORD_PATH))
    if state == "blocked":
        raise _blocked(layout)
    if state == "unreadable":
        raise InstallError(f"{unreadable_notice(layout, current_reader())}; nothing was changed")
    if state in RULES_WRITTEN:
        _packaged_default(current)


# The rules file follows one principle: `init -g` writes only bytes it has checked, and never
# changes the trust of bytes it has not checked. What it writes is the packaged default
# (`_packaged_default`: hashed against the wheel's RECORD, parsed under D27). It writes where the
# file is missing or holds known bytes (this version's default or an older one the package shipped,
# D28), in any mode or owner: rewriting known bytes is harmless. An edited file is the owner's and
# is never written, chowned or chmodded: a chown or a chmod would hand rules nobody has looked at
# to a recorder that believes the owner's file.


def rules_owner_uid(layout: Layout) -> int:
    """Who must own the rules file: the layout's system user, or whoever runs, with no owner."""
    return layout.owner[0] if layout.owner is not None else os.getuid()


def _not_exactly_ours(layout: Layout) -> str | None:
    """Why the file is not exactly what `init -g` writes (the owner's, mode 0644), or None.

    Stricter than the recorder's trust test, which loads a root:admin 0640 file too: bytes that
    are known are rewritten, which costs nothing, so the installer asks for the exact file. The
    reason is the first clause of the recorder's own words (the rest advises on a file nobody
    wrote), or the mode when the recorder would load the file.
    """
    problem = rulefile.trust_problem(layout.rules, rules_owner_uid(layout))
    if problem is not None:
        return problem.split("; ", 1)[0]
    try:
        mode = stat.S_IMODE(layout.rules.lstat().st_mode)
    except OSError as exc:
        return f"cannot be read: {exc.strerror or type(exc).__name__}"
    return None if mode == 0o644 else f"has mode {mode:04o}, not the 0644 that `init -g` writes"


def rules_state(layout: Layout, wanted: str | None) -> str:
    """What is at the rules file's place:

    - `missing`;
    - `current` (this version's default, in exactly the file `init -g` writes);
    - `untrusted` (this version's default, in a file that is not exactly that: not the owner's, or
      not mode 0644);
    - `older` (a default the package once carried, never edited);
    - `edited` (anything else, the owner's);
    - `unknown` (an unprivileged run cannot open it, another user's 0600 file for one; root
      decides);
    - `unreadable` (an unprivileged run cannot open it, and by owner and mode the recorder cannot
      either: the system user's 0600 file, `unreadable_notice`; root would only say so);
    - `blocked` (a link or a folder, which `init -g` will not write through).

    `wanted` is the sha256 of this version's default. A file too big to be a rules file, or one
    that even root cannot read, is `edited`: it is not ours to replace.
    """
    path = layout.rules
    if path.is_symlink() or (path.exists() and not path.is_file()):
        return "blocked"
    if not path.exists():
        return "missing"
    try:
        with path.open("rb") as handle:
            raw = handle.read(rulefile.MAX_FILE_BYTES + 1)
    except PermissionError:
        if os.geteuid() == 0:
            return "edited"
        return "unreadable" if unreadable_notice(layout, current_reader()) else "unknown"
    except OSError:
        return "edited"
    if len(raw) > rulefile.MAX_FILE_BYTES:
        return "edited"
    digest = rulefile.sha256_of(raw)
    if digest == wanted:
        return "untrusted" if _not_exactly_ours(layout) else "current"
    return "older" if rulefile.is_older_default(digest) else "edited"


def rules_notice(layout: Layout, wanted: str | None) -> str | None:
    """The line that says an edited rules file was kept; None for any other state.

    A trusted edit is kept and this version's default rules are not applied. An untrusted one is
    kept as well, but the recorder will not read it: the reason is the recorder's own
    (`rulefile.trust_problem`, which says what to do), and the default rules run instead.
    """
    return _kept_notice(layout, rules_state(layout, wanted))


def _kept_notice(layout: Layout, state: str) -> str | None:
    """`rules_notice` for a `rules_state` the caller has already looked up."""
    if state == "unreadable":
        return unreadable_notice(layout, current_reader())
    if state != "edited":
        return None
    problem = rulefile.trust_problem(layout.rules, rules_owner_uid(layout))
    if problem is None:
        return (
            f"kept your edited rules file {layout.rules}; this version's default rules "
            "were not applied"
        )
    return (
        f"kept your edited rules file {layout.rules}, but the recorder will not read it: "
        f"{problem}; {rulefile.DEFAULT_IN_FORCE}"
    )


RESTART_RECORDER = "restart the recorder (`agentfly stop`, `agentfly start`)"


def unreadable_notice(layout: Layout, reader: Reader) -> str | None:
    """The line for a rules file the recorder would believe but its user cannot read, or None.

    Decided by owner and mode alone (`lstat`, no open), so the unprivileged run, which cannot read
    the bytes, decides as root does: a regular file of the system user that no one else can write
    and that `reader` cannot read (a 0600 root file). The recorder then runs the packaged default.
    `init -g` never chmods it (D3: that puts unreviewed rules in force), so the line gives the fix.
    Another owner's file or a group-writable one is not this case: its notice says why. Nor is a
    file its group can read when the user is not known (root with no `SUDO_UID`): that user may be
    in the group, and `assert_locked` decides at the end, as before.
    """
    try:
        info = layout.rules.lstat()
    except OSError:
        return None
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != rules_owner_uid(layout)
        or info.st_mode & 0o022
        or _readable_by(info, reader)
        or (reader.uid == 0 and info.st_mode & 0o040)
    ):
        return None
    return (
        f"the recorder cannot read the rules file {layout.rules}, so {rulefile.DEFAULT_IN_FORCE}; "
        f'to use it, run `sudo chmod 644 "{layout.rules}"`, then {RESTART_RECORDER}'
    )


def _blocked(layout: Layout) -> InstallError:
    if layout.rules.is_symlink():
        return InstallError(f"{layout.rules} is a symbolic link; remove it first")
    return InstallError(f"{layout.rules} is not a regular file; remove it first")


def _write_rules(layout: Layout, data: bytes, state: str) -> str:
    """Put the checked default in place (atomic, 0644, the system user's); say what was done."""
    reason = _not_exactly_ours(layout) if state == "untrusted" else None  # before it is replaced
    _write_atomic(layout.rules, data, layout)
    restart = f"{RESTART_RECORDER} to apply them"
    if state == "older":
        return (
            f"replaced the unedited default rules in {layout.rules} with this version's; {restart}"
        )
    if state == "untrusted":
        return (
            f"rewrote the default rules in {layout.rules}: the file "
            f"{reason or 'was not exactly the one init -g writes'}; {restart}"
        )
    return f"wrote the default rules to {layout.rules}"


def _read_hooks(layout: Layout) -> str | None:
    try:
        data = layout.hooks_file.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InstallError(f"cannot read {layout.hooks_file} ({exc.strerror})") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallError(f"{layout.hooks_file} is not UTF-8 text; nothing was written") from exc


# ---------------------------------------------------------------- is it installed and intact


def _python_matches(layout: Layout, python: dict[str, Any]) -> bool:
    """The bundled Python is there and equals the record's hashes (pinned or not)."""
    return (
        layout.interpreter.is_file()
        and pythons.file_sha256(layout.interpreter) == python["interpreter_sha256"]
        and pythons.tree_digest(layout.python_dir) == python["tree_sha256"]
    )


def python_intact(layout: Layout) -> bool:
    """Root may run on the bundled Python: it is installed and matches the record (V3c)."""
    record = records.read(layout)
    try:
        return record is not None and _python_matches(layout, record["python"])
    except (KeyError, TypeError, OSError):
        return False


def status(layout: Layout, build: PythonBuild, source: Path, current: packages.Check) -> set[str]:
    """Which parts are missing or differ: any of "python", "client", "hooks", "packages", "rules".

    Empty when intact. "packages" is the record's package hashes differing from `current`, the
    check of the tool environment: an upgrade is not "intact". "rules" is a missing rules file
    (an install from before V5b has none), a link or folder in its place, an unedited default
    from before this version's (D28), this version's default in a file that is not exactly the
    one `init -g` writes, or a file an unprivileged run cannot open (`unknown`: root decides, after
    the password). One the recorder cannot read either (`unreadable`) is not: root would only say
    so. A file the owner edited is never "different": it is theirs, whatever it says, and no hash
    of it is kept.
    """
    record = records.read(layout)
    everything = {"python", "client", "hooks", "packages", "rules"}
    if record is None:
        return everything
    bad: set[str] = set()
    if rules_state(layout, packages.recorded_hash(current, DEFAULT_RECORD_PATH)) in (
        RULES_WRITTEN | {"unknown", "blocked"}
    ):
        bad.add("rules")
    try:
        python = record["python"]
        if python["archive_sha256"] != build.sha256 or not _python_matches(layout, python):
            bad.add("python")
        wanted = pythons.file_sha256(source)
        if (
            not layout.client.is_file()
            or pythons.file_sha256(layout.client) != wanted
            or record["client"]["sha256"] != wanted
        ):
            bad.add("client")
    except (KeyError, TypeError, OSError):
        return everything
    if record.get("packages") != packages.to_record(current.distributions):
        bad.add("packages")
    try:
        text = _read_hooks(layout)
        found = hooks_file.our_entries(text, prefix(layout)) if text is not None else []
    except InstallError:
        found = []
    if not hooks_file.same_entries(found, desired_entries(layout)):
        bad.add("hooks")
    return bad


def _unescaped(text: str) -> str:
    """JSON text with `\\/` and `\\uXXXX` decoded, so a path matches however it was escaped."""
    text = text.replace("\\/", "/")
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)


def _mentions_ours(text: str, layout: Layout) -> bool:
    """Raw-text test for a file that may not parse: our folder, with plain or escaped slashes."""
    return f"{layout.system_root}/" in _unescaped(text)


def _leftovers(layout: Layout) -> list[Path]:
    """Folders an uninstall moved aside and did not finish deleting."""
    return sorted(layout.system_root.parent.glob(f".{layout.system_root.name}-removing-*"))


def is_installed(layout: Layout) -> bool:
    """Anything of ours on disk: the folder, a leftover, or a hook entry (even in a bad file)."""
    if layout.system_root.exists() or layout.system_root.is_symlink() or _leftovers(layout):
        return True
    try:
        text = _read_hooks(layout)
    except InstallError:
        return True
    return text is not None and _mentions_ours(text, layout)


# ---------------------------------------------------------------- install


def smoke(command: str, event: str, run_as: tuple[int, int] | None) -> None:
    """Run one registered command through `sh -c` as the user and check it answers in JSON.

    As the user, not root: root can read files the user cannot, and a client the user cannot
    start exits 2, which makes Cursor deny everything. HOME is an empty folder, so nothing is
    written under the real home.
    """
    extra: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as home:
        if run_as is not None and os.geteuid() == 0:
            os.chown(home, *run_as)
            extra = {"user": run_as[0], "group": run_as[1], "extra_groups": []}
        payload = json.dumps({"hook_event_name": event}).encode()
        try:
            result = subprocess.run(
                ["/bin/sh", "-c", command],
                input=payload,
                capture_output=True,
                env={"HOME": home, "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=20,
                check=False,
                **extra,
            )
            answer = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise InstallError(
                f"the hook command does not start as the user ({type(exc).__name__}): {command}"
            ) from exc
    if result.returncode != 0 or not isinstance(answer, dict):
        raise InstallError(
            f"the hook command exited {result.returncode} or printed no JSON object: {command}\n"
            f"{result.stderr.decode(errors='replace')[-300:]}"
        )


@dataclass(frozen=True)
class Reader:
    """The user who has to read what is installed: the hook client and Python by the hook, the
    rules file by the recorder, all run as this user (V5d)."""

    uid: int
    groups: frozenset[int]


def current_reader() -> Reader:
    """Whoever runs now (`doctor` is the user)."""
    return Reader(os.geteuid(), frozenset({os.getegid(), *os.getgroups()}))


def reader_for(run_as: tuple[int, int] | None) -> Reader:
    """The user the hooks will run as: who ran `sudo` when the installer knows (`run_as`, from
    `SUDO_UID` and `SUDO_GID`), else whoever runs."""
    if run_as is None:
        return current_reader()
    uid, gid = run_as
    try:
        groups = os.getgrouplist(pwd.getpwuid(uid).pw_name, gid)
    except (KeyError, OSError):
        groups = []
    return Reader(uid, frozenset({gid, *groups}))


def _readable_by(info: os.stat_result, reader: Reader) -> bool:
    """Can the user read the file: by the others' bit, as its owner, or in its group. Root can
    read everything, which says nothing about the user, so for root only the others' bit counts."""
    if info.st_mode & 0o004:
        return True
    if reader.uid == 0:
        return False
    if info.st_uid == reader.uid and info.st_mode & 0o400:
        return True
    return info.st_gid in reader.groups and bool(info.st_mode & 0o040)


def lock_problems(layout: Layout, *, check_owner: bool, reader: Reader | None = None) -> list[str]:
    """What in the system folder is a stray link, or can be written by group or others.

    Also what the user could not enter or read (the hook would fail), and, when `check_owner`, what
    is not owned by the system user. `doctor` asks this as the user; the installer asks it as root.
    Everything must be readable by others, except the rules file, which only the recorder reads:
    root's mode 0640 file in a group the user is in is fine (V5d; the recorder loads it, D3).
    `reader` is the user (default: whoever runs).
    """
    if layout.system_root.is_symlink():
        return [f"{layout.system_root} is a symbolic link"]
    problems: list[str] = []
    for path in [layout.system_root, *layout.system_root.rglob("*")]:
        relative = path.relative_to(layout.system_root).parts
        if path.is_symlink() or (relative and relative[0].startswith((".old-", ".staging-"))):
            continue  # a link is not followed; the work folders are not live
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o001:
            problems.append(f"{path} cannot be entered by the user, so the hook would fail")
        if info.st_mode & 0o022:
            problems.append(f"{path} can be written by group or others")
        if path == layout.rules:
            if not _readable_by(info, reader or current_reader()):
                problems.append(
                    f"{path} cannot be read by the user, so the recorder could not load it"
                )
        elif not info.st_mode & 0o004:
            problems.append(f"{path} cannot be read by the user, so the hook would fail")
        if check_owner and layout.owner is not None and info.st_uid != layout.owner[0]:
            problems.append(f"{path} is not owned by the system user")
    return problems


def assert_locked(layout: Layout, run_as: tuple[int, int] | None = None) -> None:
    """Nothing in the system folder is a stray link, or writable by group or others."""
    problems = lock_problems(layout, check_owner=os.geteuid() == 0, reader=reader_for(run_as))
    if problems:
        raise InstallError(problems[0])


def _backup(layout: Layout, text: str) -> Path:
    _make_dir(layout.backups, layout)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = layout.backups / f"hooks.json.{stamp}"
    counter = 0
    while target.exists():
        counter += 1
        target = layout.backups / f"hooks.json.{stamp}-{counter}"
    _write_atomic(target, text.encode("utf-8"), layout)
    return target


def _sha256(text: str) -> str:
    return rulefile.sha256_of(text.encode("utf-8"))


def _apply_hooks(
    layout: Layout, entries: list[HookEntry], existing: str | None, merged: str
) -> bool:
    """Write the merged hooks file (its backup is already taken); True when the file changed."""
    if merged == existing:
        return False
    _make_dir(layout.cursor_dir, layout)
    _write_atomic(layout.hooks_file, merged.encode("utf-8"), layout)
    try:
        written = _read_hooks(layout)
        ok = written is not None and hooks_file.same_entries(
            hooks_file.our_entries(written, prefix(layout)), entries
        )
    except InstallError:
        ok = False
    if not ok:
        # Straight back, with no second backup that could itself fail: the first one is on disk.
        if existing is None:
            layout.hooks_file.unlink(missing_ok=True)
        else:
            _write_atomic(layout.hooks_file, existing.encode("utf-8"), layout)
        raise InstallError("the hooks file did not read back as written; the old one is restored")
    return True


def _rewrite_hooks(layout: Layout, new_text: str, old_text: str) -> None:
    """Replace the hooks file; the text it holds now is backed up first, always."""
    _backup(layout, old_text)
    _write_atomic(layout.hooks_file, new_text.encode("utf-8"), layout)


def _recorded_original(layout: Layout, info: dict[str, Any] | None) -> str | None:
    """The hooks file as it was before install: the backup the record names, if it still matches."""
    if not info:
        return None
    try:
        name = info["original_backup"]
        if not isinstance(name, str) or Path(name).name != name:
            return None
        original = (layout.backups / name).read_bytes().decode("utf-8")
    except (KeyError, TypeError, OSError, UnicodeDecodeError):
        return None
    return original if _sha256(original) == info.get("original_sha256") else None


def _only_ours_differs(
    layout: Layout, entries: list[HookEntry], current: str, original: str
) -> bool:
    """Whether `current` and `original` differ in nothing but our entries (spliced forms equal)."""
    mark = prefix(layout)
    try:
        with_ours = hooks_file.merge(original, entries, mark)
        return hooks_file.remove_ours(current, mark) == hooks_file.remove_ours(with_ours, mark)
    except InstallError:
        return False


def _hooks_info(
    layout: Layout,
    previous: dict[str, Any] | None,
    existing: str | None,
    merged: str,
    backup: Path | None,
    entries: list[HookEntry],
) -> dict[str, Any]:
    """What uninstall needs to give the original hooks file back byte for byte.

    The splice cannot tell "no hooks key" from an empty one, so install records the backup of
    the file as it was and the hash of what it wrote. A file we did not touch keeps the old values.
    """
    old = (previous or {}).get("hooks_file", {})
    if existing is not None and merged == existing:
        keys = ("original_backup", "original_sha256", "written_sha256")
        return {key: old[key] for key in keys if key in old}
    info: dict[str, Any] = {
        "original_backup": None,
        "original_sha256": None,
        "written_sha256": _sha256(merged),
    }
    mark = prefix(layout)
    if existing is None or backup is None:
        return info
    if not existing.strip() or not hooks_file.our_entries(existing, mark):
        info["original_backup"], info["original_sha256"] = backup.name, _sha256(existing)
    else:  # a repair or upgrade: the earlier original still holds if nothing but ours changed
        kept = _recorded_original(layout, old)
        if kept is not None and _only_ours_differs(layout, entries, existing, kept):
            info["original_backup"], info["original_sha256"] = (
                old["original_backup"],
                old["original_sha256"],
            )
    return info


def _exact_original(layout: Layout, info: dict[str, Any] | None, current: str) -> str | None:
    """The original hooks file, when the file is still exactly what install wrote.

    Anything else (another tool edited it since, a backup that is gone or changed) gives None and
    the caller keeps the spliced text.
    """
    original = _recorded_original(layout, info)
    if original is None or info is None or _sha256(current) != info.get("written_sha256"):
        return None
    return original


def _swap_in(new: Path, target: Path, graveyard: Path) -> None:
    if target.exists() or target.is_symlink():
        os.rename(target, graveyard)
    os.rename(new, target)


def _restore(layout: Layout, graveyard: Path) -> None:
    """Put back what a failed repair replaced, so the live entries still point at a good tree.

    Nothing is deleted: the new tree steps aside into the graveyard, then the old one comes back.
    If the second rename fails the first is undone, and the old tree stays in the graveyard.
    """
    old_python, old_client = graveyard / "python", graveyard / "hook_client.py"
    if old_python.exists():
        failed = graveyard / "failed-python"
        stepped_aside = layout.python_dir.exists() or layout.python_dir.is_symlink()
        if stepped_aside:  # it is missing when the swap itself stopped halfway
            os.rename(layout.python_dir, failed)
        try:
            os.rename(old_python, layout.python_dir)
        except BaseException:
            if stepped_aside:
                os.rename(failed, layout.python_dir)
            raise
    if old_client.exists():
        os.replace(old_client, layout.client)


def _remove_folder(layout: Layout) -> list[str]:
    """Delete the system folder so that no step leaves the interpreter next to a missing client.

    The folder is renamed away first: one atomic step after which the registered interpreter path
    is gone and a command Cursor cached exits 127 (allowed), whatever happens to the deletion.
    Leftovers of an earlier interrupted run go after that, so a leftover that will not delete
    can never hold up the rename.
    """
    messages: list[str] = []
    earlier = _leftovers(layout)
    if layout.system_root.exists():
        aside = layout.system_root.with_name(
            f".{layout.system_root.name}-removing-{time.time_ns()}"
        )
        os.rename(layout.system_root, aside)
        shutil.rmtree(aside)
        messages.append(f"removed {layout.system_root}")
    for old in earlier:
        shutil.rmtree(old)
        messages.append(f"removed leftover {old}")
    return messages


def _undo_first_install(
    layout: Layout, *, created_hooks: bool, hooks_info: dict[str, Any] | None
) -> None:
    """A hook entry must never outlive the files it runs: entries first, then the folder."""
    _strip_hooks(layout, created=created_hooks, hooks_info=hooks_info)
    _remove_folder(layout)


def install(
    layout: Layout,
    build: PythonBuild,
    *,
    cursor_version: str,
    source: Path,
    archive: Path | None = None,
    run_as: tuple[int, int] | None = None,
) -> Outcome:
    """Install or repair. `archive` is a downloaded copy of the build (re-checked here)."""
    _check_paths(layout)
    previous = records.read(layout)
    # Root hashes the tool environment again: this is what the record gets. It is not a second
    # defence, root has imported that code already; the check that matters ran before the password.
    current = packages.require(previous, "agentfly init -g")
    bad = status(layout, build, source, current)
    # One look at the rules file: the notice and what is written below come from the same state.
    rules = rules_state(layout, packages.recorded_hash(current, DEFAULT_RECORD_PATH))
    unread = unreadable_notice(layout, reader_for(run_as))
    # About an edited file only; it is never written below. One the user cannot read is not "kept".
    notice = unread if rules == "edited" and unread else _kept_notice(layout, rules)
    if not bad:
        return Outcome(
            False, ["already installed and intact; nothing changed", *([notice] if notice else [])]
        )
    if layout.system_root.is_symlink():
        raise InstallError(f"{layout.system_root} is a symbolic link; remove it first")
    if rules == "blocked":
        raise _blocked(layout)  # before anything is changed, not halfway through
    if unread and bad - {"rules"}:
        # `assert_locked` would refuse it at the end; the unprivileged run stopped on it too.
        raise InstallError(f"{unread}; nothing was changed")
    rules_data = _packaged_default(current) if rules in RULES_WRITTEN else None
    created_hooks = _read_hooks(layout) is None or bool(
        previous and previous.get("hooks_file", {}).get("created")
    )
    created_root = not layout.system_root.exists()
    _make_dir(layout.system_root, layout)
    for stale in [
        *layout.system_root.glob(".staging-*"),
        *layout.system_root.glob(".old-*"),
        *_leftovers(layout),  # what an interrupted uninstall moved aside
    ]:
        shutil.rmtree(stale, ignore_errors=True)
    staging = layout.system_root / f".staging-{os.getpid()}"
    graveyard = layout.system_root / f".old-{os.getpid()}"
    staging.mkdir()
    os.chmod(staging, 0o755)  # the umask may be 077; the user must be able to run what is in here
    messages: list[str] = []
    keep_graveyard = False
    hooks_info: dict[str, Any] | None = None
    try:
        new_python: Path | None = None
        if "python" in bad:
            staged_archive = staging / "python.tar.gz"
            if archive is not None:
                shutil.copyfile(archive, staged_archive)
                pythons.check_archive(staged_archive, build)
            else:
                pythons.download(build, staged_archive)
            new_python = pythons.extract(staged_archive, staging)
            pythons.compile_stdlib(new_python)
            pythons.lock_tree(new_python, layout.owner)
            staged_archive.unlink()
            messages.append(f"installed {build.name}")
        staged_client = staging / "hook_client.py" if "client" in bad else layout.client
        if "client" in bad:
            _write_atomic(staged_client, source.read_bytes(), layout)

        interpreter = (new_python or layout.python_dir) / INTERPRETER_REL
        first = cursor.EVENTS[0]  # the staged files first: a bad build never replaces a good one
        smoke(command_for(interpreter, staged_client, first), first, run_as)

        graveyard.mkdir()  # what is replaced waits here until the whole install has worked
        if new_python is not None:
            _swap_in(new_python, layout.python_dir, graveyard / "python")
        if "client" in bad:
            if layout.client.exists():
                shutil.copy2(layout.client, graveyard / "hook_client.py")
            os.replace(staged_client, layout.client)
        shutil.rmtree(staging, ignore_errors=True)
        if rules_data is not None:
            messages.append(_write_rules(layout, rules_data, rules))
        assert_locked(layout, run_as)
        for event in cursor.EVENTS:  # every command as registered, through `sh -c` (S2 F1)
            smoke(command_for(layout.interpreter, layout.client, event), event, run_as)

        entries = desired_entries(layout)
        existing = _read_hooks(layout)
        merged = hooks_file.merge(
            existing, entries, prefix(layout)
        )  # a bad file fails here, before the record and the hooks are written
        backup = _backup(layout, existing) if existing is not None and merged != existing else None
        hooks_info = _hooks_info(layout, previous, existing, merged, backup, entries)
        record = records.build(
            agentfly_version=agentfly_version(),
            cursor_version=cursor_version,
            archive_name=build.name,
            archive_sha256=build.sha256,
            interpreter_sha256=pythons.file_sha256(layout.interpreter),
            tree_sha256=pythons.tree_digest(layout.python_dir),
            client_sha256=pythons.file_sha256(layout.client),
            entries=[asdict(e) for e in entries],
            created_hooks_file=created_hooks,
            layout=layout,
            packages=packages.to_record(current.distributions),
        )
        record["hooks_file"].update(hooks_info)
        _write_atomic(layout.record, records.dumps(record).encode(), layout)
        if "packages" in bad:
            messages.append(f"recorded the hashes of {len(current.distributions)} packages")
        if _apply_hooks(layout, entries, existing, merged):
            messages.append(f"registered {len(entries)} hooks in {layout.hooks_file}")
        done = messages or ["repaired"]
        if notice:
            done.append(notice)
        return Outcome(True, done, cursor_reload=bad != {"rules"})
    except BaseException as failure:
        # A hook entry must never outlive the files it runs (S2 F1): entries go before the folder,
        # and a repair puts the old Python and client back. If this cleanup itself fails, the
        # folder stays, which is the safe side; the original error is still the one raised.
        try:
            if created_root:
                _undo_first_install(layout, created_hooks=created_hooks, hooks_info=hooks_info)
            else:
                _restore(layout, graveyard)
        except Exception:
            if created_root:
                note = (
                    "cleaning up the failed install did not finish; "
                    f"run `agentfly uninstall` to remove what is left of {layout.system_root}"
                )
            else:  # the previous files are kept, never deleted by the lines below
                keep_graveyard = True
                note = (
                    f"restoring the previous files failed; they are kept in {graveyard} "
                    "(the next `agentfly init -g` removes that folder)"
                )
            print(f"agentfly init: {note}", file=sys.stderr)
            failure.add_note(note)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if not keep_graveyard:
            shutil.rmtree(graveyard, ignore_errors=True)


# ---------------------------------------------------------------- uninstall


def _strip_hooks(layout: Layout, *, created: bool, hooks_info: dict[str, Any] | None) -> list[str]:
    """Take our entries out of the system hooks file; delete the file if it was ours alone.

    Refuses (changing nothing, not even a backup) when the file is not valid JSON but mentions
    us, or when entries that are not ours still point into our folder: removing the folder would
    break them. "Points into" is decided on the parsed command strings, so JSON escapes such as
    `\\/` do not hide an entry. `hooks_info` is the record's `hooks_file` section.
    """
    text = _read_hooks(layout)
    if text is None:
        return []
    mark = prefix(layout)
    try:
        ours = hooks_file.our_entries(text, mark)
    except InstallError:
        if _mentions_ours(text, layout):
            raise InstallError(
                f"{layout.hooks_file} mentions AgentFly but is not valid JSON; remove "
                "AgentFly's entries by hand, then run uninstall again. Nothing was removed."
            ) from None
        return []  # not parseable and not ours: Cursor ignores it too
    result = hooks_file.remove_ours(text, mark) if ours else text
    if any(f"{layout.system_root}/" in command for command in hooks_file.commands(result)):
        raise InstallError(
            f"{layout.hooks_file} has entries that point into {layout.system_root} but are not "
            "the ones AgentFly wrote; remove them by hand, then run uninstall again. "
            "Nothing was removed."
        )
    if not ours:
        return []
    if created and hooks_file.holds_nothing_else(result):
        layout.hooks_file.unlink()
        return [f"removed {layout.hooks_file} (AgentFly created it)"]
    exact = _exact_original(layout, hooks_info, text)
    _rewrite_hooks(layout, exact if exact is not None else result, text)
    return [f"removed AgentFly's {len(ours)} entries from {layout.hooks_file}"]


def _keep_old_backups(layout: Layout) -> list[str]:
    """Earlier versions kept backups inside the system folder: move them out before it goes."""
    old = layout.system_root / "backups"
    if old.is_symlink() or not old.is_dir():
        return []
    moved = 0
    for item in sorted(old.iterdir()):
        if item.is_symlink() or not item.is_file():
            continue
        _make_dir(layout.backups, layout)
        target, counter = layout.backups / item.name, 0
        while target.exists():
            counter += 1
            target = layout.backups / f"{item.name}-{counter}"
        os.rename(item, target)
        moved += 1
    return [f"kept {moved} earlier backup(s) in {layout.backups}"] if moved else []


def describe_oserror(exc: OSError) -> str:
    """One line for the user: the system's reason, and the file it was about."""
    return (exc.strerror or str(exc)) + (f": {exc.filename}" if exc.filename else "")


def _rules_bytes(layout: Layout) -> tuple[bytes, int] | str | None:
    """The rules file's bytes and the copy's mode; why it is no rules file; None when it is missing.

    One descriptor that follows no link and does not block, after an `lstat` that already turns
    away a link, a folder and a pipe; at most `MAX_FILE_BYTES` + 1 bytes are read. Raises OSError
    when a plain file cannot be read.
    """
    try:
        info = layout.rules.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return "a symbolic link"
    if not stat.S_ISREG(info.st_mode):
        return "not a regular file"
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
    try:
        fd = os.open(layout.rules, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:  # it became a link after the lstat
            return "a symbolic link"
        raise
    with open(fd, "rb") as handle:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode):
            return "not a regular file"
        data = handle.read(rulefile.MAX_FILE_BYTES + 1)
    if len(data) > rulefile.MAX_FILE_BYTES:
        return f"over {rulefile.MAX_FILE_BYTES} bytes"
    # The copy's group is the system user's, not the original's: it is readable by group and
    # others only if the original was readable by both, so nobody reads it who could not before.
    return data, 0o644 if mode & 0o044 == 0o044 else 0o600


def _keep_rules_copy(layout: Layout) -> list[str]:
    """D30: copy a rules file that is not an unedited shipped default next to the hooks.json
    backups, under a time-stamped name that never replaces an earlier copy, and say where.

    Runs before anything is removed, so a copy that cannot be written stops the uninstall with the
    hook entries, the folder and the file as they were. A link, a folder, a pipe or a file too big
    to load is named and skipped: the recorder could never have read it.
    """
    if layout.system_root.is_symlink() or not layout.system_root.is_dir():
        return []  # nothing is read through a link, and a file holds no rules; handled below
    try:
        raw = _rules_bytes(layout)
    except OSError as exc:
        raise InstallError(
            f"cannot read the rules file {layout.rules} to keep a copy ({describe_oserror(exc)}); "
            "nothing was removed. Move it away by hand, then run `agentfly uninstall` again"
        ) from exc
    if raw is None:
        return []
    if isinstance(raw, str):
        return [f"{layout.rules} is {raw}, which the recorder never loads; no copy was kept"]
    data, mode = raw
    if rulefile.sha256_of(data) in rulefile.SHIPPED_DEFAULTS:
        return []
    try:
        target = _write_rules_copy(layout, data, mode)
    except OSError as exc:
        raise InstallError(
            f"cannot keep a copy of the edited rules file {layout.rules} in {layout.backups} "
            f"({describe_oserror(exc)}); nothing was removed"
        ) from exc
    return [f"kept a copy of your edited rules file in {target}"]


def _write_rules_copy(layout: Layout, data: bytes, mode: int) -> Path:
    """`rules.toml.<stamp>` in the backups folder, which must be a folder: no link is followed."""
    backups = layout.backups
    if backups.is_symlink() or (backups.exists() and not backups.is_dir()):
        what = "a symbolic link" if backups.is_symlink() else "not a folder"
        raise NotADirectoryError(errno.ENOTDIR, f"it is {what}")
    _make_dir(backups, layout)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target, counter = backups / f"rules.toml.{stamp}", 0
    while target.exists() or target.is_symlink():
        counter += 1
        target = backups / f"rules.toml.{stamp}-{counter}"
    _write_atomic(target, data, layout, mode)
    return target


def uninstall(layout: Layout) -> Outcome:
    """A copy of an edited rules file, then our hook entries, then the system folder. Needs
    neither Cursor nor a version."""
    _check_paths(layout)
    record = records.read(layout)
    info = record.get("hooks_file") if record else None
    messages = _keep_rules_copy(layout)
    try:
        created = bool(info and info.get("created"))
        messages += _strip_hooks(layout, created=created, hooks_info=info)
        if layout.system_root.is_symlink():
            raise InstallError(f"{layout.system_root} is a symbolic link; remove it by hand")
        messages += _keep_old_backups(layout)
        messages += _remove_folder(layout)
    except OSError as exc:
        reason = describe_oserror(exc)
        raise InstallError(
            f"cannot finish removing AgentFly ({reason}); run `agentfly uninstall` again"
        ) from exc
    return Outcome(bool(messages), messages or ["nothing of AgentFly's was installed"])

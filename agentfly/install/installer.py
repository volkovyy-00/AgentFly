"""Install and remove AgentFly's system files (SPEC section 7, D1, D2, D5, D23).

Order matters. Install: check everything, stage the Python and the client, run the exact
registered commands once, move them into place, write the hash record, and only then add the
hook entries. Uninstall: take the hook entries out first, then the folder. A hooks entry that
points at a missing client makes Python exit 2, and Cursor then denies every action (S2 F1).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from agentfly.install import InstallError, cursor, hooks_file, pythons, records
from agentfly.install.hooks_file import HookEntry
from agentfly.install.layout import INTERPRETER_REL, Layout
from agentfly.install.pythons import PythonBuild

# Cursor's timeout is in seconds. With the recorder down the client answers in about 0.57 s; with
# it up, in about 60 ms. A Cursor timeout fails open, so there is headroom for a busy machine.
TIMEOUT_SECONDS: int = 2
_UNSAFE_IN_QUOTES: frozenset[str] = frozenset('"$`\\\n')


@dataclass(frozen=True)
class Outcome:
    changed: bool
    messages: list[str]


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
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        _chown(temp, layout)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


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


def status(layout: Layout, build: PythonBuild, source: Path) -> set[str]:
    """Which parts are missing or differ: any of "python", "client", "hooks"; empty when intact."""
    record = records.read(layout)
    if record is None:
        return {"python", "client", "hooks"}
    bad: set[str] = set()
    try:
        python = record["python"]
        if (
            python["archive_sha256"] != build.sha256
            or not layout.interpreter.is_file()
            or pythons.file_sha256(layout.interpreter) != python["interpreter_sha256"]
            or pythons.tree_digest(layout.python_dir) != python["tree_sha256"]
        ):
            bad.add("python")
        wanted = pythons.file_sha256(source)
        if (
            not layout.client.is_file()
            or pythons.file_sha256(layout.client) != wanted
            or record["client"]["sha256"] != wanted
        ):
            bad.add("client")
    except (KeyError, TypeError, OSError):
        return {"python", "client", "hooks"}
    try:
        text = _read_hooks(layout)
        found = hooks_file.our_entries(text, prefix(layout)) if text is not None else []
    except InstallError:
        found = []
    if not hooks_file.same_entries(found, desired_entries(layout)):
        bad.add("hooks")
    return bad


def _mentions_ours(text: str, layout: Layout) -> bool:
    """Raw-text test for a file that may not parse: the quotes of `prefix` are escaped there."""
    return f"{layout.system_root}/" in text


def is_installed(layout: Layout) -> bool:
    """Anything of ours on disk: the folder, or a hook entry (even in a file we cannot parse)."""
    if layout.system_root.exists() or layout.system_root.is_symlink():
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


def assert_locked(layout: Layout) -> None:
    """Nothing in the system folder is a stray link, or writable by group or others."""
    if layout.system_root.is_symlink():
        raise InstallError(f"{layout.system_root} is a symbolic link")
    for path in [layout.system_root, *layout.system_root.rglob("*")]:
        relative = path.relative_to(layout.system_root).parts
        if path.is_symlink() or (relative and relative[0].startswith((".old-", ".staging-"))):
            continue  # a link is not followed; the work folders are not live
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o001:
            raise InstallError(f"{path} cannot be entered by the user, so the hook would fail")
        if info.st_mode & 0o022:
            raise InstallError(f"{path} can be written by group or others")
        if not info.st_mode & 0o004:
            raise InstallError(f"{path} cannot be read by the user, so the hook would fail")
        if layout.owner is not None and os.geteuid() == 0 and info.st_uid != layout.owner[0]:
            raise InstallError(f"{path} is not owned by the system user")


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


def _apply_hooks(layout: Layout, entries: list[HookEntry]) -> bool:
    """Merge our entries into the system hooks file; True when the file changed."""
    existing = _read_hooks(layout)
    merged = hooks_file.merge(existing, entries, prefix(layout))
    if merged == existing:
        return False
    if existing is not None:
        _backup(layout, existing)
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
        if existing is None:
            layout.hooks_file.unlink(missing_ok=True)
        else:
            _write_atomic(layout.hooks_file, existing.encode("utf-8"), layout)
        raise InstallError("the hooks file did not read back as written; the old one is restored")
    return True


def _swap_in(new: Path, target: Path, graveyard: Path) -> None:
    if target.exists() or target.is_symlink():
        os.rename(target, graveyard)
    os.rename(new, target)


def _restore(layout: Layout, graveyard: Path) -> None:
    """Put back what a failed repair replaced, so the live entries still point at a good tree."""
    old_python, old_client = graveyard / "python", graveyard / "hook_client.py"
    if old_python.exists():
        shutil.rmtree(layout.python_dir, ignore_errors=True)
        os.rename(old_python, layout.python_dir)
    if old_client.exists():
        os.replace(old_client, layout.client)


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
    bad = status(layout, build, source)
    if not bad:
        return Outcome(False, ["already installed and intact; nothing changed"])
    if layout.system_root.is_symlink():
        raise InstallError(f"{layout.system_root} is a symbolic link; remove it first")
    previous = records.read(layout)
    created_hooks = _read_hooks(layout) is None or bool(
        previous and previous.get("hooks_file", {}).get("created")
    )
    created_root = not layout.system_root.exists()
    _make_dir(layout.system_root, layout)
    for stale in [*layout.system_root.glob(".staging-*"), *layout.system_root.glob(".old-*")]:
        shutil.rmtree(stale, ignore_errors=True)
    staging = layout.system_root / f".staging-{os.getpid()}"
    graveyard = layout.system_root / f".old-{os.getpid()}"
    staging.mkdir()
    os.chmod(staging, 0o755)  # the umask may be 077; the user must be able to run what is in here
    messages: list[str] = []
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
        assert_locked(layout)
        for event in cursor.EVENTS:  # every command as registered, through `sh -c` (S2 F1)
            smoke(command_for(layout.interpreter, layout.client, event), event, run_as)

        entries = desired_entries(layout)
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
        )
        _write_atomic(layout.record, records.dumps(record).encode(), layout)
        if _apply_hooks(layout, entries):
            messages.append(f"registered {len(entries)} hooks in {layout.hooks_file}")
        return Outcome(True, messages or ["repaired"])
    except BaseException:
        # A hook entry must never outlive the files it runs (S2 F1): entries go before the folder,
        # and a repair puts the old Python and client back. If this cleanup itself fails, the
        # folder stays, which is the safe side; the original error is still the one raised.
        with contextlib.suppress(Exception):
            if created_root:
                _strip_hooks(layout, created=created_hooks)
                shutil.rmtree(layout.system_root, ignore_errors=True)
            else:
                _restore(layout, graveyard)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(graveyard, ignore_errors=True)


# ---------------------------------------------------------------- uninstall


def _strip_hooks(layout: Layout, *, created: bool) -> list[str]:
    """Take our entries out of the system hooks file; delete the file if it was ours alone.

    Refuses (changing nothing) when the file is not valid JSON but mentions us, or when entries
    that are not ours still point into our folder: removing the folder would break them.
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
    if f"{layout.system_root}/" in result:
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
    _write_atomic(layout.hooks_file, result.encode("utf-8"), layout)
    return [f"removed AgentFly's {len(ours)} entries from {layout.hooks_file}"]


def uninstall(layout: Layout) -> Outcome:
    """Our hook entries first, then the system folder. Needs neither Cursor nor a version."""
    _check_paths(layout)
    record = records.read(layout)
    messages = _strip_hooks(
        layout, created=bool(record and record.get("hooks_file", {}).get("created"))
    )
    if layout.system_root.is_symlink():
        raise InstallError(f"{layout.system_root} is a symbolic link; remove it by hand")
    if layout.system_root.exists():
        shutil.rmtree(layout.system_root)
        messages.append(f"removed {layout.system_root}")
    return Outcome(bool(messages), messages or ["nothing of AgentFly's was installed"])

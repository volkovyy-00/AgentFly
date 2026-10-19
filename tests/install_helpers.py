"""Shared pieces for tests/test_install_*.py: a layout in a temp folder and a fake Python build.

The fake build is a tarball whose `python/bin/python3.12` runs the interpreter running the tests,
so the hook client really starts. No test writes a `.cursor/hooks.json` (V5a's R0 guards that
path); the system file here is `<tmp>/Library/Application Support/Cursor/hooks.json`.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any
from unittest import mock

from agentfly.install import installer, packages, records
from agentfly.install.layout import Layout
from agentfly.install.pythons import PythonBuild
from tests.helpers import client_env

OTHER_TOOL_ENTRY = '{"command": "/opt/other/audit.sh", "timeout": 5}'


def make_layout(tmp: Path) -> Layout:
    support = tmp / "Library" / "Application Support"  # the space is on purpose (S2 F1)
    return Layout(support / "AgentFly", support / "Cursor", tmp / "Cursor.app", None)


def make_cursor_app(layout: Layout, version: str = "3.24.12") -> None:
    plist = layout.cursor_app / "Contents" / "Info.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({"CFBundleShortVersionString": version}))


def tar_bytes(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


def _file(name: str, data: bytes, mode: int = 0o664) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size, info.mode = len(data), mode
    return info, data


def _dir(name: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type, info.mode = tarfile.DIRTYPE, 0o775
    return info, None


def _link(name: str, target: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type, info.linkname = tarfile.SYMTYPE, target
    return info, None


def fake_python_tar() -> bytes:
    script = f'#!/bin/sh\nexec "{sys.executable}" "$@"\n'.encode()
    return tar_bytes(
        [
            _dir("python"),
            _dir("python/bin"),
            _file("python/bin/python3.12", script, 0o775),
            _link("python/bin/python3", "python3.12"),
            _dir("python/lib"),
            _dir("python/lib/python3.12"),
            _file("python/lib/python3.12/helper.py", b"VALUE = 1\n"),
        ]
    )


def evil_tar(kind: str) -> bytes:
    members = {
        "traversal": [_file("python/../../escape.txt", b"x")],
        "absolute": [_file("/etc/escape.txt", b"x")],
        "outside-link": [_dir("python"), _link("python/evil", "../../outside")],
        "absolute-link": [_dir("python"), _link("python/evil", "/etc/passwd")],
        "other-root": [_file("other/file", b"x")],
    }[kind]
    return tar_bytes(members)


def build_for(data: bytes, name: str = "fake-python.tar.gz", url: str = "") -> PythonBuild:
    return PythonBuild(name=name, url=url, sha256=hashlib.sha256(data).hexdigest())


def write_archive(folder: Path, data: bytes) -> tuple[Path, PythonBuild]:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "fake-python.tar.gz"
    path.write_bytes(data)
    return path, build_for(data)


class FsOps:
    """Count the file-system calls that change a tree, and optionally stop at one of them.

    `before(number, name, args, kwargs)` runs ahead of every call (1-based); raise from it to
    stop there. Only `os.rename/replace/unlink/rmdir/remove` are wrapped, which is all that
    `shutil.rmtree`, `Path.unlink` and our atomic writes use. Keep the `with` block tight.
    """

    NAMES = ("rename", "replace", "unlink", "rmdir", "remove")

    def __init__(
        self, before: Callable[[int, str, tuple[Any, ...], dict[str, Any]], None] | None = None
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._before = before
        self._stack = contextlib.ExitStack()

    def __enter__(self) -> FsOps:
        for name in self.NAMES:
            self._stack.enter_context(
                mock.patch.object(os, name, self._wrap(name, getattr(os, name)))
            )
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._stack.close()

    def _wrap(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            if self._before is not None:
                self._before(len(self.calls), name, args, kwargs)
            return real(*args, **kwargs)

        return call


def stop_at(number: int, error: BaseException) -> Callable[..., None]:
    """A `before` hook that raises `error` ahead of call `number`."""

    def before(count: int, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        if count == number:
            raise error

    return before


def run_hook_command(command: str, home: Path, event: str = "beforeShellExecution") -> Any:
    """Run a registered hooks.json command as Cursor does: through `sh -c`, event on stdin."""
    return subprocess.run(
        ["/bin/sh", "-c", command],
        input=json.dumps({"hook_event_name": event}),
        capture_output=True,
        text=True,
        env=client_env(home),
        check=False,
    )


# ---------------------------------------------------------------- a fake tool environment (V3c)

# name -> (version, {path as RECORD writes it: content}); `../../../bin/` is the venv's bin folder
TOOL_DISTS: dict[str, tuple[str, dict[str, bytes]]] = {
    "agentfly-recorder": (
        "0.1.0",
        {
            "agentfly/__init__.py": b"",
            "agentfly/module.py": b"VALUE = 1\n",
            "../../../bin/agentfly": b"#!/bin/sh\nexit 0\n",
        },
    ),
    "fakedep": ("1.0", {"fakedep/__init__.py": b"X = 1\n", "fakedep/_speed.so": b"\x7fELF"}),
}


MODULE = "agentfly/module.py"
NEW_AGENTFLY = {**TOOL_DISTS["agentfly-recorder"][1], MODULE: b"VALUE = 2\n"}


def path_of(env: packages.Environment, rel: str) -> Path:
    """Where a path written as RECORD writes it is on disk."""
    return Path(os.path.normpath(env.site / rel))


def _record_hash(data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return "sha256=" + digest.decode()


def write_dist(env: packages.Environment, name: str, version: str, files: dict[str, bytes]) -> Path:
    """One installed distribution: its files, `METADATA` and a `RECORD` that hashes them all."""
    info = env.site / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    own = {
        "METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode(),
        "INSTALLER": b"uv\n",
    }
    rows = []
    for rel, data in files.items():
        target = path_of(env, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rows.append(f"{rel},{_record_hash(data)},{len(data)}")
    for rel, data in own.items():
        (info / rel).write_bytes(data)
        rows.append(f"{info.name}/{rel},{_record_hash(data)},{len(data)}")
    rows.append(f"{info.name}/RECORD,,")
    (info / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return info


def upgrade(env: packages.Environment, name: str, version: str, files: dict[str, bytes]) -> None:
    """What `uv tool upgrade` leaves: old files gone, a new dist-info with its own RECORD."""
    for old in env.site.glob(f"{name.replace('-', '_')}-*.dist-info"):
        for line in (old / "RECORD").read_text(encoding="utf-8").splitlines():
            path_of(env, line.split(",")[0]).unlink(missing_ok=True)
        shutil.rmtree(old)
    write_dist(env, name, version, files)


def make_tool_env(
    root: Path, dists: dict[str, tuple[str, dict[str, bytes]]] | None = None
) -> packages.Environment:
    """A clean virtual environment of the shape `uv tool install` leaves: pyvenv.cfg, bin, site."""
    root = root.resolve()  # the check resolves paths once; messages then match these
    site = root / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "pyvenv.cfg").write_text("home = /nowhere/bin\n", encoding="utf-8")
    env = packages.Environment(root, site)
    for name, (version, files) in (dists or TOOL_DISTS).items():
        write_dist(env, name, version, files)
    return env


def install_system(layout: Layout, tmp: Path) -> PythonBuild:
    """`installer.install` into `layout` with the fake Python build; returns the build."""
    path, build = write_archive(tmp / "dl", fake_python_tar())
    installer.install(
        layout, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )
    return build


def status_of(layout: Layout, build: PythonBuild, source: Path | None = None) -> set[str]:
    """`installer.status` with the check of the (fake) tool environment, as the CLI makes it."""
    check = packages.inspect(packages.tool_environment(), records.read(layout))
    return installer.status(layout, build, source or installer.client_source(), check)


def hashes_of(env: packages.Environment) -> dict[str, Any]:
    """The record `init -g` would write for `env` as it is now (only its `packages` section)."""
    check = packages.inspect(env, None)
    assert not check.problems, check.problems
    return {"packages": packages.to_record(check.distributions)}

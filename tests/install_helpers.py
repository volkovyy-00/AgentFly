"""Shared pieces for tests/test_install_*.py: a layout in a temp folder and a fake Python build.

The fake build is a tarball whose `python/bin/python3.12` runs the interpreter running the tests,
so the hook client really starts. No test writes a `.cursor/hooks.json` (V5a's R0 guards that
path); the system file here is `<tmp>/Library/Application Support/Cursor/hooks.json`.
"""

from __future__ import annotations

import hashlib
import io
import plistlib
import sys
import tarfile
from pathlib import Path

from agentfly.install.layout import Layout
from agentfly.install.pythons import PythonBuild

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

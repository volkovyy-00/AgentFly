"""The bundled Python: pinned build, checksum, safe unpacking, locked modes (D5)."""

from __future__ import annotations

import http.server
import os
import re
import stat
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from agentfly.install import InstallError, pythons
from tests.install_helpers import build_for, evil_tar, fake_python_tar, write_archive


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


def serve(routes: dict[str, bytes]) -> Iterator[str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/start":  # GitHub answers a download with a 302
                self.send_response(302)
                self.send_header("Location", "/file.tar.gz")
                self.end_headers()
            elif self.path in routes:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(routes[self.path])
            else:
                self.send_error(404)

        def log_message(self, *args: object) -> None:
            pass

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def web() -> Iterator[str]:
    yield from serve({"/file.tar.gz": fake_python_tar()})


def test_the_pins_match_the_release_and_name_a_python_312_build() -> None:
    assert set(pythons.BUILDS) == {"x86_64", "aarch64"}
    for arch, build in pythons.BUILDS.items():
        assert re.fullmatch(r"[0-9a-f]{64}", build.sha256)
        assert f"cpython-3.12.15%2B20261013-{arch}-apple-darwin-install_only_stripped" in build.url
        assert build.url.startswith("https://github.com/astral-sh/python-build-standalone/")


def test_the_build_follows_the_hardware() -> None:
    assert "aarch64" in pythons.select_build(True).name
    assert "x86_64" in pythons.select_build(False).name


def test_hardware_detection_says_intel_when_the_sysctl_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An Intel Mac answers `sysctl -n hw.optional.arm64` with "unknown oid", exit 1.
    def sysctl(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", "unknown oid")

    monkeypatch.setattr(subprocess, "run", sysctl)
    assert not pythons.has_apple_silicon()
    assert pythons.select_build() is pythons.BUILDS["x86_64"]

    def apple(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, "1\n", "")

    monkeypatch.setattr(subprocess, "run", apple)
    assert pythons.select_build() is pythons.BUILDS["aarch64"]


def test_download_follows_the_redirect_and_checks_the_sum(tmp_path: Path, web: str) -> None:
    data = fake_python_tar()
    build = build_for(data, url=web + "/start")
    folder = tmp_path / "dl"
    target = folder / "got.tar.gz"
    pythons.download(build, target)
    assert target.read_bytes() == data
    assert list(folder.iterdir()) == [target]  # no partial file left


def test_a_wrong_checksum_is_named_and_leaves_nothing(tmp_path: Path, web: str) -> None:
    build = build_for(b"something else", name="pinned.tar.gz", url=web + "/start")
    folder = tmp_path / "dl"
    with pytest.raises(InstallError, match=r"checksum mismatch for pinned\.tar\.gz.*nothing"):
        pythons.download(build, folder / "got.tar.gz")
    assert list(folder.iterdir()) == []


def test_a_failed_download_is_an_install_error(tmp_path: Path, web: str) -> None:
    build = build_for(b"x", url=web + "/missing")
    with pytest.raises(InstallError, match="cannot download"):
        pythons.download(build, tmp_path / "got.tar.gz")


@pytest.mark.parametrize(
    "kind", ["traversal", "absolute", "outside-link", "absolute-link", "other-root"]
)
def test_an_unsafe_archive_is_refused_before_anything_is_unpacked(
    tmp_path: Path, kind: str
) -> None:
    archive, _ = write_archive(tmp_path / "in", evil_tar(kind))
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(InstallError, match="unsafe|unpack"):
        pythons.extract(archive, out)
    assert list(out.iterdir()) == []
    assert not (tmp_path / "escape.txt").exists()


def test_extract_and_lock_set_explicit_modes_whatever_the_umask(tmp_path: Path) -> None:
    archive, _ = write_archive(tmp_path / "in", fake_python_tar())
    old = os.umask(0o077)
    try:
        root = pythons.extract(archive, tmp_path)
        pythons.lock_tree(root, None)
    finally:
        os.umask(old)
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode in (0o755, 0o644), (path, oct(mode))
    assert stat.S_IMODE((root / "bin" / "python3.12").stat().st_mode) == 0o755
    assert (root / "bin" / "python3").is_symlink()


def test_tree_digest_notices_any_change(tmp_path: Path) -> None:
    archive, _ = write_archive(tmp_path / "in", fake_python_tar())
    root = pythons.extract(archive, tmp_path)
    before = pythons.tree_digest(root)
    assert pythons.tree_digest(root) == before
    (root / "lib" / "python3.12" / "helper.py").write_text("VALUE = 2\n")
    assert pythons.tree_digest(root) != before
    (root / "lib" / "python3.12" / "helper.py").write_text("VALUE = 1\n")
    (root / "extra").write_text("")
    assert pythons.tree_digest(root) != before

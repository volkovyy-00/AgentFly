"""Build the wheel, install it with `uv tool` under a temporary HOME and run it (card V2).

Needs `uv`, and the network the first time (hatchling is fetched into uv's cache). Offline, the
tests skip; with `CI` set they fail, so a runner that lost the network cannot pass by skipping.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from agentfly.install import elevate
from tests.helpers import free_port, make_legacy, package_files
from tests.test_hook_client import EVENT, check_allow_and_log, run_client

REPO = Path(__file__).resolve().parents[1]
UV = shutil.which("uv")
# One wheel build per run, and tests that plant files in that install and put them back: all of
# them share one xdist worker, in file order.
pytestmark = [
    pytest.mark.skipif(UV is None, reason="uv is not installed"),
    pytest.mark.xdist_group(name="package"),
]
_OFFLINE_HINTS = ("error sending request", "dns error", "Failed to fetch", "Connection refused")


@dataclass(frozen=True)
class Installed:
    home: Path
    env: dict[str, str]
    wheel: Path
    sdist: Path

    @property
    def bin(self) -> Path:
        return self.home / ".local" / "bin"

    @property
    def python(self) -> Path:
        return next(self.home.glob(".local/share/uv/tools/*/bin/python"))

    @property
    def package_dir(self) -> Path:
        found = list(
            (self.home / ".local/share/uv/tools").glob("*/lib/python*/site-packages/agentfly")
        )
        assert len(found) == 1, found
        return found[0]


def run_uv(args: list[str], env: dict[str, str]) -> None:
    assert UV is not None
    result = subprocess.run(
        [UV, *args], cwd=REPO, env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        if any(hint in result.stderr for hint in _OFFLINE_HINTS):
            reason = f"uv could not reach the network: {result.stderr.strip()[-300:]}"
            if os.environ.get("CI"):
                pytest.fail(reason)
            pytest.skip(reason)
        pytest.fail(f"uv {' '.join(args)} failed:\n{result.stderr}")


def fake_uv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stderr: str) -> None:
    """Make `run_uv` run a `uv` that exits 1 with `stderr` (no build, no network)."""
    script = tmp_path / "uv"
    script.write_text(f"#!/bin/sh\necho '{stderr}' >&2\nexit 1\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr(sys.modules[__name__], "UV", str(script))


NETWORK_ERROR = "error sending request for url (https://pypi.org/simple/)"


@pytest.mark.parametrize(
    ("ci", "stderr", "outcome", "shown"),
    [
        (None, NETWORK_ERROR, pytest.skip.Exception, "could not reach the network"),
        ("true", NETWORK_ERROR, pytest.fail.Exception, "could not reach the network"),
        (None, "error: build backend failed", pytest.fail.Exception, "build backend failed"),
        ("true", "error: build backend failed", pytest.fail.Exception, "build backend failed"),
    ],
    ids=["offline", "offline-on-ci", "other-failure", "other-failure-on-ci"],
)
def test_a_uv_failure_skips_only_offline_and_off_ci(
    ci: str | None,
    stderr: str,
    outcome: type[BaseException],
    shown: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if ci is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci)
    fake_uv(tmp_path, monkeypatch, stderr)
    with pytest.raises(outcome, match=shown):
        run_uv(["build"], {})


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Installed:
    assert UV is not None
    # Module fixtures run before the per-test HOME swap, so this is the real uv cache.
    cache = subprocess.run([UV, "cache", "dir"], capture_output=True, text=True, check=True)
    work = tmp_path_factory.mktemp("package")
    home = work / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "UV_CACHE_DIR": cache.stdout.strip(),
        "UV_TOOL_DIR": str(home / ".local/share/uv/tools"),
        "UV_TOOL_BIN_DIR": str(home / ".local/bin"),
        "UV_PYTHON_DOWNLOADS": "never",
    }
    out = work / "dist"
    run_uv(["build", "--out-dir", str(out), "--python", sys.executable], env)
    wheel = next(out.glob("*.whl"))
    sdist = next(out.glob("*.tar.gz"))
    run_uv(["tool", "install", "--python", sys.executable, str(wheel)], env)
    return Installed(home=home, env=env, wheel=wheel, sdist=sdist)


def test_wheel_carries_the_page_and_nothing_private(installed: Installed) -> None:
    names = zipfile.ZipFile(installed.wheel).namelist()
    for needed in (
        "agentfly/ui_dist/index.html",
        "agentfly/hook_client.py",
        "agentfly/cli/serve.py",
        "agentfly/cli/__main__.py",
        "agentfly/install/installer.py",
        "agentfly/recorder/app.py",
    ):
        assert needed in names, needed
    assert any(n.startswith("agentfly/ui_dist/assets/") for n in names)
    top = {n.split("/")[0] for n in names if not n.startswith("agentfly_recorder-")}
    assert top == {"agentfly"}, top  # no tests, docs, .env or hooks/ in the wheel
    assert installed.wheel.name.startswith("agentfly_recorder-")


def test_sdist_builds_the_same_page(installed: Installed) -> None:
    with tarfile.open(installed.sdist) as archive:
        names = archive.getnames()
    assert any(n.endswith("/ui/dist/index.html") for n in names)
    assert not any("/.env" in n or "/docs/" in n or "/tests/" in n for n in names)


def test_both_commands_are_on_the_tool_bin_dir(installed: Installed) -> None:
    for name in ("agentfly", "agentfly-hook"):
        assert (installed.bin / name).is_file(), name
    result = subprocess.run(
        [str(installed.bin / "agentfly"), "serve", "--help"],
        env=installed.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0 and "--port" in result.stdout and "--host" not in result.stdout


def test_the_installed_tool_offers_init_g_and_uninstall_and_runs_as_a_module(
    installed: Installed,
) -> None:
    for tail in (["init", "--help"], ["uninstall", "--help"]):
        result = subprocess.run(
            [str(installed.bin / "agentfly"), *tail],
            env=installed.env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    # What sudo runs on a first install (V3c): the tool environment's base Python with -I -S, the
    # site folder appended and no byte-code read; the real wheel's dependencies load from there.
    command = elevate.sudo_command(
        ["init", "--help"],
        site=installed.package_dir.parent,
        python=Path(os.path.realpath(installed.python)),
    )
    result = subprocess.run(
        command[1:], env=installed.env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0 and "--global" in result.stdout, result.stderr


CHECK_SCRIPT = (
    "import json; from agentfly.install import packages; "
    "check = packages.inspect(packages.tool_environment(), None); "
    "print(json.dumps({'problems': check.problems, 'dists': sorted(check.distributions)}))"
)


def package_check(installed: Installed) -> dict[str, list[str]]:
    """`packages.inspect` run by the installed tool itself, on its own real environment."""
    result = subprocess.run(
        [str(installed.python), "-I", "-B", "-c", CHECK_SCRIPT],
        env=installed.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    found: dict[str, list[str]] = json.loads(result.stdout)
    return found


def test_a_real_uv_tool_environment_passes_the_package_check(installed: Installed) -> None:
    found = package_check(installed)
    assert found["problems"] == [], found["problems"]  # only _virtualenv.* is unlisted, and allowed
    assert "agentfly-recorder" in found["dists"] and len(found["dists"]) > 5


def test_a_planted_file_and_a_changed_file_in_a_real_environment_are_named(
    installed: Installed,
) -> None:
    extra = installed.package_dir / "_planted.so"
    module = installed.package_dir / "install" / "layout.py"
    original = module.read_bytes()
    try:
        extra.write_bytes(b"\x7fELF")
        module.write_bytes(original + b"\n# changed\n")
        problems = package_check(installed)["problems"]
    finally:
        extra.unlink(missing_ok=True)
        module.write_bytes(original)
    assert f"{extra} is not listed in any RECORD" in problems
    assert f"{module} does not match its RECORD" in problems
    assert package_check(installed)["problems"] == []


def fetch(port: int, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture()
def running_recorder(installed: Installed, tmp_path: Path) -> Iterator[tuple[int, Path]]:
    home = tmp_path / "serve-home"
    make_legacy(home)
    port = free_port()
    env = {**installed.env, "HOME": str(home)}
    process = subprocess.Popen(
        [str(installed.bin / "agentfly"), "serve", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if fetch(port, "/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("agentfly serve did not answer /health in 20 s")
        yield port, home
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_serve_answers_health_and_serves_the_page_from_the_wheel(
    installed: Installed, running_recorder: tuple[int, Path]
) -> None:
    port, home = running_recorder
    assert json.loads(fetch(port, "/health")[1]) == {
        "ok": True,
        "offline_guard_count": 0,
        "last_hook_at": None,
    }
    status, page = fetch(port, "/")
    assert status == 200 and b'<div id="root"' in page
    asset = re.search(rb'/assets/[^"\']+', page)
    assert asset is not None
    status, body = fetch(port, asset.group().decode())
    assert status == 200
    inside = zipfile.ZipFile(installed.wheel).read("agentfly/ui_dist" + asset.group().decode())
    assert body == inside
    assert (installed.package_dir / "ui_dist" / "index.html").read_bytes() == page
    assert fetch(port, "/docs")[0] == 404 and fetch(port, "/openapi.json")[0] == 404
    # first start moved the hackathon folder, and the token was rewritten
    assert json.loads((home / ".local/share/agentfly/sessions.json").read_text())[0]["marked"]
    assert (home / ".config/agentfly/token").read_text() != "old-token"
    assert not (home / ".config/flightrecorder").exists()


def test_installed_hook_with_no_recorder_prints_allow(
    installed: Installed, isolated_home: Path
) -> None:
    package = installed.package_dir
    before = package_files(package)
    result = run_client([str(installed.bin / "agentfly-hook")], isolated_home, EVENT)
    check_allow_and_log(result, isolated_home)
    assert (
        package_files(package) == before
    )  # run with PYTHONDONTWRITEBYTECODE=1, so not even a __pycache__

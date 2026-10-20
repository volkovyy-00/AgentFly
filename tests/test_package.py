"""Build the wheel, install it with `uv tool` under a temporary HOME and run it (card V2).

Needs `uv`, and the network the first time (hatchling is fetched into uv's cache).
"""

from __future__ import annotations

import hashlib
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
from tests.helpers import RECORDER_CODE, free_port, make_legacy, package_files
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
            pytest.skip(f"uv could not reach the network: {result.stderr.strip()[-300:]}")
        pytest.fail(f"uv {' '.join(args)} failed:\n{result.stderr}")


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
        "agentfly/recorder/rulefile.py",
        "agentfly/rules/default.toml",
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


DEFAULT_SCRIPT = (
    "import json; from agentfly.install import installer, packages; "
    "check = packages.inspect(packages.tool_environment(), None); "
    "data = installer._packaged_default(check); "
    "print(json.dumps({'problems': check.problems, 'bytes': len(data), "
    "'recorded': packages.recorded_hash(check, installer.DEFAULT_RECORD_PATH)}))"
)


def test_the_wheels_record_lists_the_default_rules_and_init_would_write_them(
    installed: Installed,
) -> None:
    """D28 on the real wheel: RECORD lists `agentfly/rules/default.toml` with its hash, and the
    installer's check of that file (RECORD hash, then a clean parse) passes in the installed
    tool."""
    result = subprocess.run(
        [str(installed.python), "-I", "-B", "-c", DEFAULT_SCRIPT],
        env=installed.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    default = installed.package_dir / "rules" / "default.toml"
    assert found["problems"] == [] and found["bytes"] == default.stat().st_size
    assert found["recorded"] == hashlib.sha256(default.read_bytes()).hexdigest()


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
    # The wheel's own modules, not the repo's `agentfly/` (see `test_the_child_..._wheel`), and a
    # rules file that does not exist: `RECORDER_CODE` never lets a child read the real one.
    process = subprocess.Popen(
        [str(installed.python), "-I", "-B", "-c", RECORDER_CODE, "serve", "--port", str(port)],
        cwd=tmp_path,
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


def test_the_child_recorder_imports_the_wheel_and_not_the_source_tree(
    installed: Installed, tmp_path: Path
) -> None:
    """Without `-I` the repo's `agentfly/` would shadow the wheel and these tests would test it."""
    code = (
        "import agentfly, agentfly.recorder.rulefile as r; print(agentfly.__file__, r.ACTIVE_RULES)"
    )
    result = subprocess.run(
        [str(installed.python), "-I", "-B", "-c", code],
        cwd=REPO,
        env=installed.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    where, rules = result.stdout.split(maxsplit=1)
    assert Path(where).resolve().is_relative_to(installed.package_dir.resolve()), where
    assert (installed.package_dir / "rules" / "default.toml").is_file()
    assert rules.strip() == "/Library/Application Support/AgentFly/rules.toml"


@pytest.mark.parametrize("command", ["check", "test"])
def test_the_installed_tool_checks_and_tests_the_default_rules_it_carries(
    installed: Installed, command: str
) -> None:
    """Always with an explicit FILE: a child process must never read the real rules file."""
    default = installed.package_dir / "rules" / "default.toml"
    result = subprocess.run(
        [str(installed.bin / "agentfly"), "rules", command, str(default)],
        env=installed.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert str(default) in result.stdout and result.stderr == ""


def hook_bytes(port: int, home: Path, body: dict[str, object]) -> bytes:
    """POST one event as the hook client would (it only ever talks to port 8787, so not it)."""
    token = (home / ".config/agentfly/token").read_text(encoding="utf-8").strip()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/hook",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Recorder-Token": token},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        answer: bytes = response.read()
    return answer


def test_the_demo_replays_with_byte_identical_answers_from_the_wheel(
    running_recorder: tuple[int, Path],
) -> None:
    """R1 is loaded from the default rules file inside the wheel; the answers do not change."""
    port, home = running_recorder
    scenario = json.loads((REPO / "demo" / "scenario.json").read_text(encoding="utf-8"))
    sent = [
        {**{k: v for k, v in item["event"].items() if k != "content"}, "conversation_id": "wheel"}
        for item in scenario["demo"]["events"]
    ]
    answers = [hook_bytes(port, home, body) for body in sent]
    assert answers[:2] == [b'{"permission":"allow"}'] * 2
    assert answers[2] == (
        b'{"permission":"deny","user_message":"Blocked by rule R1: a secret was read earlier in '
        b'this session, and now data is being sent out.","agent_message":"Blocked by rule R1: a '
        b"secret was read earlier in this session, and now data is being sent out. Do not retry "
        b'with another tool or language. Stop and tell the user."}'
    )
    # The chat read .env: the entry that ships beside R1 now denies `npm publish` in it.
    publish = {**sent[2], "command": "npm publish"}
    assert json.loads(hook_bytes(port, home, publish))["user_message"] == (
        "Blocked: a .env file was read earlier in this session, so npm publish is off."
    )
    fresh = {**publish, "conversation_id": "wheel-fresh", "workspace_roots": ["/elsewhere"]}
    assert hook_bytes(port, home, fresh) == b'{"permission":"allow"}'


def test_the_wheels_recorder_lists_the_default_rules_it_carries(
    installed: Installed, running_recorder: tuple[int, Path]
) -> None:
    port, _ = running_recorder
    listing = json.loads(fetch(port, "/api/rules")[1])
    assert listing["source"] == "default" and listing["problem"] is None
    assert listing["file"] == str(installed.package_dir / "rules" / "default.toml")
    assert [r["id"] for r in listing["rules"]][:3] == ["R0", "R1", "npm-publish-after-env"]
    assert "rules_problem" not in json.loads(fetch(port, "/health")[1])


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

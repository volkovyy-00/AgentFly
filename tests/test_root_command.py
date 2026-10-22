"""The exact command `init -g` and `uninstall` pass to `sudo` (V3c), run without `sudo`.

A real virtual environment holds a copy of the package, with a `.pth`, a `sitecustomize.py` and an
unchecked-hash `.pyc` planted in it; each would write a marker file if Python ran it. The old
command (`-I -B -m agentfly.cli`) is the control: it runs the `.pth` and the `.pyc`. (Its
`sitecustomize` marker is not asserted: Homebrew's Python ships a `sitecustomize` of its own that
comes first on `sys.path`, so a planted one never runs there.)
"""

from __future__ import annotations

import importlib.util
import os
import py_compile
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from agentfly.install import elevate, installer, packages
from agentfly.install.layout import Layout
from tests.helpers import REPO
from tests.install_helpers import (
    build_for,
    install_system,
    make_cursor_app,
    make_layout,
    status_of,
    write_dist,
)

# Half of these run Python through the `sudo` command line and take 2 s or more in a parallel run.
pytestmark = pytest.mark.slow

OLD_COMMAND = ["-I", "-B", "-m", "agentfly.cli", "init", "--help"]
PRINT_ENVIRONMENT = (
    "import sys; sys.path.append(sys.argv[1]); from agentfly.install import packages; "
    "env = packages.tool_environment(); print(env.site); print(env.prefix)"
)


@dataclass(frozen=True)
class Venv:
    root: Path
    site: Path

    @property
    def python(self) -> Path:
        return self.root / "bin" / "python"

    def marker(self, name: str) -> Path:
        return self.root / f"marker-{name}"

    def markers(self) -> set[str]:
        return {path.name.removeprefix("marker-") for path in self.root.glob("marker-*")}


def link_module(site: Path, name: str) -> None:
    """`agentfly.cli` imports neo4j (via wipe, localstore and store); it needs typing_extensions."""
    spec = importlib.util.find_spec(name)
    assert spec is not None and spec.origin is not None, name
    where = spec.submodule_search_locations
    source = Path(next(iter(where))) if where else Path(spec.origin)
    (site / source.name).symlink_to(source, target_is_directory=bool(where))


@pytest.fixture
def venv(tmp_path: Path) -> Venv:
    root = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root)], check=True)
    site = next((root / "lib").glob("python*/site-packages"))
    shutil.copytree(
        REPO / "agentfly", site / "agentfly", ignore=shutil.ignore_patterns("__pycache__")
    )
    for name in ("neo4j", "typing_extensions"):
        link_module(site, name)
    made = Venv(root, site)
    # The planted code: a .pth line, a sitecustomize, and a .pyc (hash not checked) for a module.
    (site / "evil.pth").write_text(
        f"import pathlib; pathlib.Path({str(made.marker('pth'))!r}).write_text('x')\n"
    )
    (site / "sitecustomize.py").write_text(
        f"import pathlib; pathlib.Path({str(made.marker('sitecustomize'))!r}).write_text('x')\n"
    )
    target = site / "agentfly" / "install" / "__init__.py"
    source = target.read_text(encoding="utf-8")
    plant = f"import pathlib; pathlib.Path({str(made.marker('pyc'))!r}).write_text('x')\n"
    evil = tmp_path / "evil_init.py"
    evil.write_text(
        source.replace(
            "from __future__ import annotations\n", f"from __future__ import annotations\n{plant}"
        )
    )
    py_compile.compile(
        str(evil),
        cfile=importlib.util.cache_from_source(str(target)),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )
    return made


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, check=False
    )


def test_the_old_command_runs_the_planted_pth_and_byte_code(venv: Venv) -> None:
    """The control: without it the next test could pass for the wrong reason."""
    result = run([str(venv.python), *OLD_COMMAND], venv.root)
    assert result.returncode == 0, result.stderr
    assert {"pth", "pyc"} <= venv.markers()


@pytest.mark.parametrize("name", ["init", "uninstall"])
def test_the_command_passed_to_sudo_runs_none_of_the_planted_code(venv: Venv, name: str) -> None:
    command = elevate.sudo_command([name, "--help"], site=venv.site)
    assert command[0] == "/usr/bin/sudo"
    result = run(command[1:], venv.root)  # the same words, without sudo
    assert result.returncode == 0, result.stderr
    assert f"agentfly {name}" in result.stdout  # it did run the package
    assert venv.markers() == set()


def test_the_environment_is_found_under_the_flags_root_runs_with(venv: Venv) -> None:
    """Under `-S`, `sysconfig` names the base Python; the place `agentfly` came from does not."""
    fake = packages.Environment(venv.root, venv.site)

    files = {
        str(path.relative_to(venv.site)): path.read_bytes()
        for path in (venv.site / "agentfly").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    write_dist(fake, "agentfly-recorder", "0.1.0", files)
    flags = elevate.sudo_command([], site=venv.site)[1:7]  # the interpreter and its options
    result = run([*flags, "-c", PRINT_ENVIRONMENT, str(venv.site)], venv.root)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [str(venv.site), str(venv.root)]
    assert venv.markers() == set()


def test_the_command_line_is_fixed_apart_from_the_site_the_python_and_the_tail(
    tmp_path: Path,
) -> None:
    site = tmp_path / "toolenv" / "lib" / "python3.12" / "site-packages"
    bundled = Path("/Library/Application Support/AgentFly/python/bin/python3.12")
    command = elevate.sudo_command(["init", "-g"], site=site, python=bundled)
    assert command == [
        "/usr/bin/sudo",
        str(bundled),
        "-I",
        "-S",
        "-B",
        "-X",
        "pycache_prefix=/var/empty",
        "-c",
        elevate.BOOTSTRAP,
        str(site),
        "init",
        "-g",
    ]
    assert "environ" not in elevate.BOOTSTRAP


def test_without_a_bundled_python_root_runs_the_base_interpreter_of_the_environment(
    tmp_path: Path,
) -> None:
    command = elevate.sudo_command(["uninstall"], site=tmp_path)
    assert command[1] == os.path.realpath(sys.executable)


def test_the_bundled_python_is_chosen_only_while_it_matches_the_record(tmp_path: Path) -> None:
    layout: Layout = make_layout(tmp_path)
    make_cursor_app(layout)
    assert not installer.python_intact(layout)  # nothing installed: a first install
    install_system(layout, tmp_path)
    assert installer.python_intact(layout)
    layout.interpreter.write_text("#!/bin/sh\nexit 0\n")
    assert not installer.python_intact(layout)


def test_a_different_pinned_build_does_not_make_the_recorded_python_untrusted(
    tmp_path: Path,
) -> None:
    """`uninstall` needs a Python that matches the record, not the one this release pins."""
    layout = make_layout(tmp_path)
    make_cursor_app(layout)
    install_system(layout, tmp_path)
    other = build_for(b"another build", name="newer.tar.gz")
    assert status_of(layout, other) == {"python"}
    assert installer.python_intact(layout)

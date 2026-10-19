"""The one `sudo`: the command re-runs itself as root, with no flag to say so."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import IO

from agentfly.install import packages

# A folder only root can write: Python reads and writes byte-code under it, never beside the source.
NO_PYCACHE = "/var/empty"
# `-c` and not `-m`: `-m agentfly.cli` finds the package through `site`, which `-S` turns off. The
# site folder is appended, so nothing in it can shadow the standard library.
BOOTSTRAP = (
    "import sys; sys.path.append(sys.argv[1]); "
    "from agentfly.cli import main; sys.exit(main(sys.argv[2:]))"
)


def sudo_command(tail: list[str], *, site: Path, python: Path | None = None) -> list[str]:
    """`sudo python -I -S -B -X pycache_prefix=/var/empty -c <bootstrap> <site> <tail>`.

    -I ignores the user's environment and folders; -S runs no `site`, so no `.pth` and no
    `sitecustomize`; -B and the pycache prefix keep root from reading or writing `__pycache__`
    (an unchecked-hash `.pyc` runs instead of its source). `python` is the bundled, root-owned
    Python when the caller found it installed and unchanged; otherwise the base interpreter of the
    tool environment (`realpath`, so the environment's own `bin/python` link and `pyvenv.cfg` are
    not part of what root trusts). The full path of sudo avoids a planted `sudo` on PATH.
    """
    interpreter = str(python) if python is not None else os.path.realpath(sys.executable)
    return [
        "/usr/bin/sudo",
        interpreter,
        "-I",
        "-S",
        "-B",
        "-X",
        f"pycache_prefix={NO_PYCACHE}",
        "-c",
        BOOTSTRAP,
        str(site),
        *tail,
    ]


def run_elevated(
    tail: list[str], stdin: IO[bytes] | None = None, *, python: Path | None = None
) -> int:
    command = sudo_command(tail, site=packages.tool_environment().site, python=python)
    return subprocess.run(command, stdin=stdin, check=False).returncode

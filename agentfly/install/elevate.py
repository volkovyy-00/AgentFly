"""The one `sudo`: the command re-runs itself as root, with no flag to say so."""

from __future__ import annotations

import subprocess
import sys
from typing import IO


def sudo_command(tail: list[str]) -> list[str]:
    """`sudo python -I -B -m agentfly.cli <tail>`.

    -I ignores the user's environment and site folders; -B stops root from writing __pycache__
    into the user's tool environment. The full path of sudo avoids a planted `sudo` on PATH.
    """
    return ["/usr/bin/sudo", sys.executable, "-I", "-B", "-m", "agentfly.cli", *tail]


def run_elevated(tail: list[str], stdin: IO[bytes] | None = None) -> int:
    return subprocess.run(sudo_command(tail), stdin=stdin, check=False).returncode

"""`./install.sh` and HOOKS.md no longer use the hackathon folder or the pre-V2 module paths."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from tests.helpers import REPO, client_env

EVENTS = {
    "beforeShellExecution",
    "beforeReadFile",
    "beforeMCPExecution",
    "afterFileEdit",
    "preToolUse",
}


def test_install_on_a_fresh_home_creates_no_hackathon_folder(
    tmp_path: Path, isolated_home: Path
) -> None:
    # Work in a copy so the real repo gets no .cursor/hooks.json from a test.
    work = tmp_path / "work"
    (work / "hooks").mkdir(parents=True)
    shutil.copy(REPO / "install.sh", work / "install.sh")
    shutil.copy(REPO / "hooks" / "hook.py", work / "hooks" / "hook.py")
    result = subprocess.run(
        ["/bin/bash", str(work / "install.sh")],
        cwd=work,
        env=client_env(isolated_home),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not (isolated_home / ".config" / "flightrecorder").exists()
    assert not (isolated_home / ".config").exists()  # install makes no user folder at all
    assert not (work / "logs").exists()
    hooks = json.loads((work / ".cursor" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == EVENTS
    assert all(entry["timeout"] == 1 for group in hooks.values() for entry in group)
    assert "flightrecorder" not in result.stdout + result.stderr


OLD_PATTERNS = [
    r"flightrecorder",
    r"python -m recorder\b",
    r"uvicorn recorder\b",
    r"hook_passthrough",
    r"(?<![\w/])recorder/[a-z_]+\.py",
    r"\blogs/events\.jsonl",  # the repo-local log is gone; the v1 path has a longer prefix
]


def test_hooks_md_names_no_old_path_or_command() -> None:
    text = (REPO / "HOOKS.md").read_text(encoding="utf-8")
    text = text.replace(".local/share/agentfly/logs/events.jsonl", "")
    for pattern in OLD_PATTERNS:
        assert re.search(pattern, text) is None, pattern
    assert "~/.config/agentfly/token" in text and "AGENTFLY_PORT" in text


def test_readme_and_hooks_md_name_the_trail_as_home_and_the_graph_tab() -> None:
    for name in ("README.md", "HOOKS.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "Live Trail" in text and "/?view=graph" in text, name
        assert "Watch the live graph" not in text, name

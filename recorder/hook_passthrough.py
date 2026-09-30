#!/usr/bin/env python3
"""Compat shim for older .cursor/hooks.json paths.

Prefer hooks/hook.py (written by ./install.sh). This file only exists so a
stale hooks.json that still points here does not exit 2 and lock the agent.
"""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent.parent / "hooks" / "hook.py"),
    run_name="__main__",
)

#!/usr/bin/env python3
"""Thin shim: runs agentfly/hook_client.py.

`./install.sh` and existing `.cursor/hooks.json` files point here. Stdlib only, so it runs on
any Python, installed package or not. It goes away with V3 (`agentfly init -g`).
"""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent.parent / "agentfly" / "hook_client.py"),
    run_name="__main__",
)

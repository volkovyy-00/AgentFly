#!/usr/bin/env python3
"""Thin shim: runs agentfly/hook_client.py.

`./install.sh` (for development) and existing `.cursor/hooks.json` files point here. Stdlib only, so
it runs on any Python, installed package or not. It stays: `agentfly init -g` installs a copy of
the hook client and uses no shim.
"""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent.parent / "agentfly" / "hook_client.py"),
    run_name="__main__",
)

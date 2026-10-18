# V3c · Root never runs a changed AgentFly: package check before `sudo`, R0 guards the install folder

You are a worker on card V3c in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v3c-package-check. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v3c-package-check only, the lead merges.

**Summary.** `init -g` and `uninstall` run AgentFly's own code as root, and that code sits in a folder the agent's user can write. Stop the agent from changing it, and refuse to ask for the password when it has been changed anyway.

**Written against:** 70f5c77 (2026-10-18); V3b (`doctor`) is not on main yet.

**What was observed (2026-10-18, on the owner's Mac, `uv tool` install of 0.1.0)**
- `sudo` runs the tool environment's `bin/python` with `-I -B`. That runs uv's `_virtualenv.pth` and the base Python's `sitecustomize.py`, and an unchecked-hash `.pyc` planted in `__pycache__` ran instead of its source. Root imports only `agentfly.*` and the standard library, no dependency.
- `bin/python` links to Homebrew's Python in `/usr/local/Cellar`, which the user can write; its standard library is not in any `RECORD`.
- Each `site-packages/*.dist-info/RECORD` hashes every file and entry script except `RECORD` itself; only `_virtualenv.py` and `_virtualenv.pth` (and `__pycache__`) are in no `RECORD`.

**References**
- `agentfly/install/elevate.py` § `sudo_command`: the one root command line.
- `agentfly/cli/init.py` § `_as_user` and `agentfly/cli/uninstall.py` § `run`: the last user-side code before `sudo`. `agentfly/install/records.py` § `build`: the root-owned `hashes.json`; the package hashes and versions go here.
- `agentfly/recorder/rules.py` § `_R0_PATHS` and `agentfly/hook_client.py` § `_GUARD_PATHS`: the two guard lists, kept equal (substring match, case-folded, `cwd` included); `tests/cases.py` § `GUARD_PATHS` spells them.
- SPEC.md § 10 "Known gaps" (the hash check is run by the code it checks; the install card decides where reference hashes live) and § 7 `doctor`.

**Scope**
- Reference: each `init -g` first checks every file of every distribution in the tool environment against that distribution's `RECORD`, then stores those hashes and each distribution's version in the root-owned record. Before asking for a password, `init -g` and `uninstall` compare each distribution against the stored hashes, or against its `RECORD` when its version differs from the stored one (an upgrade). A file in `site-packages` that no `RECORD` lists, other than uv's `_virtualenv.*` and `__pycache__`, is a mismatch. On a mismatch they stop, name the file, and say to reinstall the package and run again. An editable install is refused with the wheel-install hint.
- Root runs on the bundled root-owned Python whenever it is installed and matches its recorded hash (only a first install runs on the tool environment's Python), reads no `__pycache__` and runs no `.pth` or `sitecustomize`.
- R0 and the offline guard also deny touching the AgentFly tool environment (default `uv tool`, `pipx` and Homebrew keg locations) and its two entry scripts in `~/.local/bin`, and installing, upgrading, reinstalling or removing AgentFly with `uv tool`, `pipx` or `brew` (owner 2026-10-18). When a distribution's version differs from the record, `init -g` and `uninstall` print "changed from X to Y" and go on only after the owner confirms. `doctor` gets one more line: package unchanged.
- Touches: `agentfly/install/`, `agentfly/cli/{init,uninstall,doctor}.py`, the two guard lists, their tests and `tests/cases.py`, SPEC § 5 R0 list and § 10, README "Installation".
- Not included: hashes fetched from PyPI (the package is not published yet), guarding or hashing the base Python the tool environment runs on (uv's or Homebrew's; other projects use it), guarding a source checkout, the recorder's per-session hash check, a page banner.

**Acceptance criteria**
- One changed file (module, entry script or dependency file) or one extra unlisted file (a `.so` beside an AgentFly module) stops `init -g` and `uninstall` before any `sudo` prompt, names the file and says how to recover; an unchanged install goes ahead.
- After an upgrade of AgentFly or of one dependency alone, with untouched files, `init -g` and `uninstall` go ahead and the record holds the new hashes; an upgrade with one file changed against its own `RECORD` is stopped.
- The exact command `init -g` passes to `sudo`, run without `sudo`, runs none of a planted `.pth`, `sitecustomize.py` and unchecked-hash `.pyc` for an AgentFly module (the marker file they would write does not appear); with the bundled Python installed, that command runs on it, and a Homebrew or uv Python upgrade does not stop `init -g` or `uninstall`.
- Reading, writing or deleting a file in the AgentFly tool environment or `~/.local/bin/agentfly` is denied by R0 and, with the recorder down, by the offline guard, in every spelling `tests/cases.py` covers; work inside an AgentFly source checkout, `agentfly status` and `uv tool list` stay allowed.
- `uv tool install --force <wheel>`, `uv tool upgrade agentfly-recorder`, `pipx reinstall agentfly-recorder` and `brew upgrade agentfly` are denied by R0, wrapped too; after an upgrade `init -g` names old and new versions and stops unless the owner confirms.
- `doctor` fails its package line after one changed file and passes after a reinstall; SPEC § 10 names what stays unchecked (the checker checks itself; the base Python; `RECORD` is trusted on each new version; a file changed while the password prompt waits; a first install runs on the tool environment's Python; a tool environment outside the default places).

**Dependencies:** V3b merged (`doctor`). V5b starts after this card (both touch `agentfly/install/`).

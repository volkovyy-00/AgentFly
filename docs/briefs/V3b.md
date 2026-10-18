# V3b · Service and `doctor`: `start`, `stop`, `status`, `doctor`

You are a worker on card V3b in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v3b-service. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v3b-service only, the lead merges.

**Summary.** The recorder should start at login and come back by itself when killed, and one command should say whether AgentFly is installed, intact and running.

**Written against:** 70f5c77 (2026-10-18).

**Facts (Cursor 3.25.9, 2026-10-18, V3a manual check)**
- The Hooks log is `~/Library/Application Support/Cursor/logs/<start time>/window*/output_*/cursor.hooks.*.log` (the newest start folder is the running Cursor); after a restart it says `Loaded N enterprise hook(s) for steps: …`, or `No enterprise hooks configuration found` when Cursor has not been restarted since `init -g`. Settings → Hooks does not list system hooks. `Failed to parse project hooks configuration` and `Invalid user config` lines about other files are common and are not about ours.
- One trial: an allow from `~/.claude/settings.json` did not cancel AgentFly's shell deny (D24 stays a warning).

**References**
- SPEC.md § 7 "Install, run, uninstall" (Run, `doctor`, Uninstall) is the target; § 10 "Known gaps" says the install card decides where the reference hashes live and what checks them.
- `docs/DECISIONS.md` § D8 and § D4: `brew services` for Homebrew, AgentFly's own LaunchAgent otherwise, `KeepAlive` on both; § D23 and § D24 for the events and Hooks-log checks.
- `agentfly/install/records.py` § `build`: the root-owned `hashes.json` that `init -g` writes; `doctor` compares the installed files with it.
- `agentfly/recorder/rules.py` § `_R0_PATHS` and `agentfly/hook_client.py` § `_GUARD_PATHS`: the two guard lists, kept equal.

**Scope**
- `start`, `stop`, `status`: an install inside a Homebrew prefix delegates to `brew services`; any other install writes and loads its own LaunchAgent in `~/Library/LaunchAgents` with `KeepAlive`, running `serve` from the same install. `status` names the manager, whether it runs, and what `/health` answers. `uninstall` also stops and removes the service; R0 and the offline guard also cover the service's plist path (AgentFly's own and Homebrew's `homebrew.mxcl.agentfly.plist`).
- `doctor`: one line per check (ok, warn, fail), exit 1 on any fail; the checks are the SPEC § 7 list, plus "Cursor loaded our hooks" from the Hooks log.
- Touches: new `agentfly/cli/{start,stop,status,doctor}.py`, `agentfly/cli/__init__.py`, `agentfly/cli/uninstall.py`, `agentfly/install/`, the two guard lists and their tests (`tests/cases.py`), `tests/test_install_*.py`, README "Installation", SPEC § 5 R0 list and § 7, AGENTS.md "Commands" and "Testing".
- Not included: the Homebrew formula and a real `brew services` run (V4), the package check before `sudo` and R0's install-folder guard (V3c), the rules file (V5b), a hash banner on the page, resolving the PyPI `agentfly` name clash.

**Acceptance criteria**
- On a `uv tool` install, `agentfly start` leaves a loaded LaunchAgent with `KeepAlive`; after `kill -9` of the recorder `/health` answers again within 15 s; `stop` keeps it down; `status` reports each state correctly (tests with a stub `launchctl`, plus manual on the owner's Mac).
- With a stub `brew` and the package under a Homebrew prefix, `start`, `stop` and `status` run `brew services` and write no LaunchAgent.
- After a clean `init -g`, `start` and a Cursor restart, `doctor` is all ok; each of these turns only its own line to fail: a changed client or Python, changed or missing AgentFly entries in `hooks.json`, a missing hash record, a user-writable bundled Python, a missing client, `KeepAlive` off or the service not loaded, another `agentfly` earlier on `PATH`, a registered event off the known list, an "Invalid … config" / "Failed to parse" Hooks-log line about the system file (not user or project files) or "No enterprise hooks". A gate hook in `~/.claude/settings.json` is a warn.
- After `uninstall`, `launchctl list | grep agentfly` prints nothing and the plist is gone; reading, writing or deleting the plist is denied by R0 and by the offline guard.
- With the service stopped, `doctor` fails the service line and the offline guard still denies `curl https://example.invalid` with "agentfly start" (manual on the owner's Mac).

**Dependencies:** V3a ✅, F3 ✅. Runs alongside V2c (shared: SPEC.md and AGENTS.md "Testing", different sections); V3c and then V5b start after this merges.

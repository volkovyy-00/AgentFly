# V3a · System install: `agentfly init -g` and `agentfly uninstall`

You are a worker on card V3a in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v3a-install. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v3a-install only, the lead merges.

**Summary.** With one password, one command makes Cursor check every project through AgentFly, using a hook client and a Python that the agent cannot change; a second command takes it all out again. The service commands and `doctor` are the next card (V3b).

**Written against:** b8ca2b1 (2026-10-18).

**References**
- `SPEC.md` § "3. How it works" (System hooks file, Where files live) and § "7. Install, run, uninstall" (`init -g`, Uninstall): the target.
- `docs/DECISIONS.md` D2 (system hooks.json, quoted command path), D5 (bundled root-owned Python; a missing client is a loud failure), D23 (only events the installed Cursor accepts, else write nothing), D9 A with D21 A (events: the four gates, `afterFileEdit`, `sessionStart`, `sessionEnd`, `subagentStart` record-only), D22 and D24 (the two manual checks below).
- `docs/spikes/S5-brief.md` § "2. Hook dump": the event names Cursor 3.24.12 accepted, and how one unknown name disables the whole file. `docs/spikes/S2-tamper.md` F1 (an unquoted path made Python exit 2) and F2 (the framework Python is group-writable).
- `agentfly/hook_client.py` § `main`: the file `init -g` installs, run as `python -I -S <client> cursor <event>`. `docs/reports/V2b.md` § "Measurements" (both runs): how V2b measured, and that the bare interpreter alone had p95 38–56 ms on this Mac.
- `install.sh`: today's dev wiring into the repo's `.cursor/hooks.json`.

**Scope**
- `init -g`, with one `sudo`: installs a pinned relocatable standalone Python (checksum verified) and the hook client in `/Library/Application Support/AgentFly/`, root-owned and writable by root only, records their hashes there for V3b's `doctor`, and merges tagged entries (quoted path, explicit timeout) into `/Library/Application Support/Cursor/hooks.json` with a backup and an atomic write. An unknown Cursor version or event means nothing is written. You pick the Python build, how it is fetched and how it is updated, and give the reason in the report.
- `uninstall`: removes AgentFly's hook entries first, then its system folder; other tools' entries stay. Tests run the install code against a temporary root. The CLI has no flag or environment variable that moves the system paths (same reason as D25).
- New command modules sit in `agentfly/cli/` next to `serve.py`. `agentfly/cli/__init__.py` is a declared merge point (one import and one registration line per command). Also touches: new `agentfly/install/`, `install.sh` (a dev wrapper or deleted; keep `tests/test_install_docs.py` in step), README "Installation", new `tests/test_install_*.py`. No test fixture may be a `.cursor/hooks.json` (V5a's R0 guards that path).
- Not included: `start`, `stop`, `status`, the LaunchAgent and `doctor` (V3b); installing the rules file (V5b; SPEC § 7 lists it under `init -g`, the lead moved it there); Homebrew (V4); per-project `init` (D20). For the checks below, run the recorder with `agentfly serve` in the foreground.

**Acceptance criteria**
- Merging into a hooks.json that holds another tool's entries leaves theirs byte-identical, tags ours, keeps a backup and quotes every path. The install leaves a hash record whose SHA-256 values match the installed client and Python. A second `init -g` changes nothing. `uninstall` removes only our entries, then the system folder.
- When Cursor's version or any event is not on the known list, or the Python download fails its checksum, `init -g` exits non-zero, writes nothing and names what failed.
- After `init -g`, the user cannot write to the installed client, the Python or the hooks file without `sudo`. (manual, on the owner's Mac)
- Owner's Mac (wheel installed with `uv tool`, the repo's `.cursor/hooks.json` moved aside and restored after; terminal log in the report): in a never-opened folder, reading `.env` and then `curl https://example.invalid` is denied 10 of 10 times, on both a sandboxed and an unsandboxed run (D22). (manual)
- Same setup, with a `~/.claude/settings.json` hook that answers allow on `beforeShellExecution`: the report says whether the R1 deny still holds (D24; if the allow wins, V3b's `doctor` fails on such hooks). (manual)
- 200 calls through the installed client with the recorder up: median and p95 are in the report next to the bare bundled interpreter. Target p95 50 ms; if it is missed, give the breakdown. After `uninstall`, Cursor runs a shell command with no AgentFly hook firing. (manual)

**Dependencies:** V2b merged (79a46a7).

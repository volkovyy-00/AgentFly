# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-19 (evening) CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: V3b-V6b-merged. S1–S5, V1a, V2, V8, V2b ✅ (2026-10-16); V1b, V5a, V6, V3a, F3, F5, F6 ✅ (2026-10-18). V2c ✅ merged fb72286 (2026-10-19; 3×2164 passed, 5 skipped; lead probes 5/5). V3b ✅ ba6f488 and V6b ✅ a9b753f merged 2026-10-19 (lead /code-review high: 3 V3b fixes + 1 V6b SPEC line done by the workers; trial merge 3×2534 passed, 5 skipped; lead probes 16/16).
Pending decisions: D16

## Spikes and cards
- Done cards: one line each under BOARD `## Done`. V5a was not red-teamed: a conformance/test-strength review stays open.
- Briefs ready (pass 2 done 2026-10-18): V3c (next) (package check before sudo, R0 guards install folder and blocks reinstalling AgentFly, version-change confirm), V5b (rules file, severities, rules check/test, /api/rules, npm rule in default; lead re-checks against main before dispatch), V5c (S3 additions, ten S3 rules as off-by-default example, bypass tests). Order: V3c → V5b → V5c (they share `agentfly/install/` and the CLI). V8b next on the recorder lane (V6b ✅; brief ready docs/briefs/V8b.md; shares step record, memory.py, store.py); its highlighted verdict comes from V5b.
- V4 on hold: this Mac is x86_64 with no Xcode CLT; `brew install --build-from-source` needs CLT, pydantic-core needs Rust, Homebrew 7 installs only from a tap. Rework V4's checks before briefing.
- Briefs: agent-ready-tickets, fresh pass 2, no pass 3 (owner 2026-10-18); dispatch with `docs/roles/dispatch.sh`. Merge: trial-merge parallel cards, probe cross-card behaviour, `--no-commit`, keep main's STATE/BOARD.
- Review evidence: the four 2026-10-18 probes re-run on the merged tree (subagentStart-only link, history marks for wrapped/`-d@` reads, offline file tools on token spellings; uninstall stop points via F3's per-call sweep): all pass.

## In flight
- V8b · worker (Claude Code, owner starts) · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v8b-recorder-fields · ag-v8b-recorder-fields · docs/reports/V8b.md · docs/briefs/V8b.md
- V3c · worker (Claude Code, owner starts) · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v3c-package-check · ag-v3c-package-check · docs/reports/V3c.md · docs/briefs/V3c.md

## Machine state (verified 2026-10-19 14:48 CEST)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent (V3a installed, then uninstalled). Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` agentfly-recorder 0.1.0 is the V3b branch build (V3b manual run); reinstall from main before any new manual check. V3b's run ended with `uninstall`: no LaunchAgent, no launchd row; one harmless override entry `dev.agentfly.v3bprobe54766 => enabled` stays (launchd cannot drop it).
- Recorder: not running (no listener on 8787, /health no answer). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files: ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly (logs, sessions.json). After V6, Neo4j gets nothing without `neo4j = true` in ~/.config/agentfly/config.toml (absent). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees: main + ag-v3c-package-check (b7a635b), ag-v8b-recorder-fields (a0258f7) (V3b, V6b, lead-trial removed 2026-10-19; merged branches deleted 2026-10-19). Disk 30 GiB free (2026-10-19).
- Git: origin/main = b6e51cc (owner pushed 2026-10-18 22:55); later commits are local only (owner pushes with `AGENTFLY_ALLOW_PUSH=1`). Origin repo is PUBLIC. core.hooksPath absolute; `.claude/settings.json` denies `git push` (a guard, not a lock: docs/learnings.md).
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
1. Start the V3c and V8b workers (commands given 2026-10-19); paste "V3c report ready" / "V8b report ready" when they finish.
2. Decide on 7 unverified /code-review findings in merged code (Open risks); lead proposes verifying them and a fix card after V3c/V8b.

## Decisions changed since last handoff (b8ca2b1)
- D4 note (owner 2026-10-18): the offline guard also denies Read, Write and Edit of guard paths (F5 builds it, SPEC §9).
- D14 note (owner 2026-10-18): Neo4j opt-in via config.toml; R0 denies `wipe`; wipe never clears marks.
- D21 note (owner 2026-10-18): the workspace fallback mark expires after 30 minutes.
- Owner 2026-10-19 (evening): setup changes after two brainstorm-advisor reviews and /code-review (3 fixes): lead-context cap, pre-commit merge rule, state-check branch warning, dispatch.sh, worker self-review, settings allow/ask/deny (advisor's version), merged branches and old logs deleted.
- Owner 2026-10-19: Cursor reopened; V3c dispatched (brief re-checked b7a635b), V8b dispatched ∥ V3c (a0258f7): warned step tested in process only; a step blocked by two rules shows the earlier half's rule.
- Owner 2026-10-19 (afternoon): V3b and V6b merged after a lead review; Homebrew `stop` leaving an old LaunchAgent goes to V4.
- Owner 2026-10-19: V2c merged; history "marked" gap for edit steps accepted, fixed by new card V6b (stored marked flag); no parallel rules lane (V5b stays after V3c).
- Owner 2026-10-18 (late): V3b ∥ V2c, then V3c → V5b → V5c; V5b split into V5b + V5c; package check and install-folder guard in a new V3c; R0 blocks the agent from installing/upgrading/removing AgentFly and a version change needs the owner's confirm; npm-publish rule in the default; S3 rules ship off by default.
- Owner 2026-10-18: F3's failed restore keeps the old Python in a printed `.old-*` folder (accepted); flaky history test folded into V2c.
- Owner 2026-10-18: R0 keeps the raw-text check (commit messages naming guard paths are denied); root runs user-writable code during sudo → V5b guards the install folder, V3b checks the package hash before sudo; V3/V5 split into a/b; V1b to a worker; staged merge.

## Open risks and findings
- `SessionStore.save` fsyncs sessions.json on every hook in the request handler; no card owns it.
- /code-review high 2026-10-19 (one pass, unverified): flag_marked queues on every marked event (V6b); `sudo agentfly uninstall` leaves the LaunchAgent (V3b); memory.replace order and evicted blocked step, merge waiting deque holds id-carrying halves (V2c); mark() runs twice per shell event; uninstall hint twice; memory.clear clears the merger.
- Same-step "read .env + curl": Cursor may check the curl before the read (the curl cannot carry the content); add to SPEC's known gaps.
- Missing interpreter → exit 127 → Cursor fails open; missing client → exit 2 → deny-all. Cursor reads the system file only at start-up (restart after init/uninstall).
- R0 gaps (V5a): `pkill python`/`killall python3` can kill the recorder (V3b KeepAlive restarts it); ruby/perl -e not inline code; relative paths after `cd`, globs, brace expansion and variables unseen; ~/.claude/settings.json not guarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md predates V6/V3a in places; Neo4j Session lacks workspace_root; D21 marks now stored by V6b (old rows keep the guessed value).
- No card owns SPEC §10's per-session hash check at session start (raised in V3b pass 2).
- V3b: the offline guard has path rules only, no `launchctl`/`brew` command rules (R0 has both). HOOKS.md has no `/api/sessions` contract (V6b; V9 should add it).
- V2c leftovers: `StrReplace`/`Delete` edits not merged as writes; an id-less read within 5 s of a create can join it (3.24.12 only); merge state lost on restart.
- V2c probe: a blocked step keeps its first half's order, so a `curl` whose `preToolUse` came before a `.env` read shows as blocked before that read (page and history order).

## Next 3 actions
1. Read V3c and V8b report heads when they arrive; trial-merge both and probe before asking to merge.
2. Then re-check V5b's brief against main, V5b, V5c; probe and trial-merge each.
3. After V3c and V8b merge: brief F7 (xdist, CI); move AGENTS.md "Testing" to tests/README.md. Rework V4's checks later.

Model used for rehearsals: Grok 4.7 High in Cursor chats.

# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-19 16:45 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: V3c-V8b-dispatched-setup. S1–S5, V1a, V1b, V2, V2b, V2c, V3a, V3b, V5a, V6, V6b, V8, F3, F5, F6 ✅ (BOARD Done; last merges V3b ba6f488, V6b a9b753f, trial 3×2534 passed). V3c and V8b dispatched 2026-10-19; V8b reports done (16:37), lead review not started. Setup changes committed 42bfe0a.
Pending decisions: D16

## Spikes and cards
- Done cards: one line each under BOARD `## Done`. V5a was not red-teamed: a conformance/test-strength review stays open.
- Order: V3c ∥ V8b → V5b → V5c (share `agentfly/install/` and the CLI) → V7 ∥ V9. F7 (xdist, CI; owner approved pytest-xdist and CI) and one fix card for the real /code-review findings come after V3c and V8b merge. V8b's highlighted verdict comes from V5b.
- Briefs: V5b, V5c exist (pass 2, 2026-10-18; references resolve, their only missing files are ones V5b creates). V7, V9, F7, the fix card: not written. Standing rule (lead.md, owner 2026-10-19): the lead writes or re-checks each brief with agent-ready-tickets and a fresh pass-2 reviewer before every dispatch, unasked; the owner says "go". Dispatch with `docs/roles/dispatch.sh <card> <slug>`.
- V4 on hold: this Mac is x86_64 with no Xcode CLT; `brew install --build-from-source` needs CLT, pydantic-core needs Rust, Homebrew 7 installs only from a tap. F7's CI runner may give V4 a place for its checks; rework then.
- Merge: trial-merge parallel cards in a scratch worktree, probe cross-card behaviour, merge with `--no-commit`, keep main's STATE/BOARD. Lead /code-review high on each branch before merge.
- Workers dispatched before 42bfe0a (V3c, V8b) lack the self-review line in docs/reports/README.md and the new settings until they merge main; the pre-commit merge rule reaches them already (hooksPath runs main's copy).

## In flight
- V8b · worker (Claude Code) · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v8b-recorder-fields · ag-v8b-recorder-fields · docs/reports/V8b.md · docs/briefs/V8b.md
- V3c · worker (Claude Code) · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v3c-package-check · ag-v3c-package-check · docs/reports/V3c.md · docs/briefs/V3c.md

## Machine state (verified 2026-10-19 16:39 CEST)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed). Cursor reopened by the owner 2026-10-19.
- `uv tool` agentfly-recorder 0.1.0 is the V3b branch build; reinstall from main before any manual check. No AgentFly LaunchAgent; one harmless launchd override `dev.agentfly.v3bprobe54766 => enabled` stays.
- Recorder: not running (no listener on 8787, /health no answer). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files: ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly (logs, sessions.json). Neo4j gets nothing without `neo4j = true` in ~/.config/agentfly/config.toml (absent). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it. Repo `logs/` deleted (owner 2026-10-19).
- Worktrees: main (42bfe0a); ag-v3c-package-check (b7a635b + uncommitted work, worker active); ag-v8b-recorder-fields (c92f664, 4 commits, report on branch). Merged branches deleted 2026-10-19. Disk 30 GiB free.
- Git: origin/main = b6e51cc (owner pushed 2026-10-18 22:55); later commits are local only (owner pushes with `AGENTFLY_ALLOW_PUSH=1`). Origin repo is PUBLIC. core.hooksPath absolute. `.claude/settings.json` (42bfe0a): allow ruff/pytest/npm ui checks; ask on core.hooksPath; deny push, --no-verify, commit -n, Read ~/.config/agentfly. Guards, not locks.
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
1. Paste "V3c report ready" when the V3c worker finishes (V8b already reports done; the lead reviews it next).

## Decisions changed since last handoff (097f4f4; earlier: git show 097f4f4:docs/STATE.md)
- Owner 2026-10-19: V3c dispatched (brief re-checked b7a635b); V8b dispatched ∥ V3c (a0258f7): a warned step is tested in process only (no runtime watch-only switch); a step blocked by two rules shows the earlier half's rule. V8b adds `marked_order` to `?all=1`.
- Owner 2026-10-19: setup after two brainstorm-advisor reviews and /code-review (3 fixes): lead-context cap, pre-commit merge rule (merge of a main commit may carry its lead files), state-check branch warning, dispatch.sh, worker self-review (/code-review high), settings allow/ask/deny (advisor's version; no sudo deny), merged branches and repo `logs/` deleted.
- Owner 2026-10-19: pytest-xdist approved (AGENTS.md list gets it with F7); CI on GitHub Actions approved (F7, `ci.yml`).
- Owner 2026-10-19: verify the 7 /code-review findings after V3c/V8b merge; one fix card for the real ones.
- Owner 2026-10-19: the lead refreshes or writes briefs itself before every dispatch (lead.md).

## Open risks and findings
- /code-review high 2026-10-19 (one pass, unverified): flag_marked queues on every marked event (V6b); `sudo agentfly uninstall` leaves the LaunchAgent (V3b); memory.replace order and evicted blocked step, merge waiting deque holds id-carrying halves (V2c); mark() runs twice per shell event; uninstall hint twice; memory.clear clears the merger.
- `SessionStore.save` fsyncs sessions.json on every hook in the request handler; no card owns it.
- Same-step "read .env + curl": Cursor may check the curl before the read (the curl cannot carry the content); add to SPEC's known gaps.
- Missing interpreter → exit 127 → Cursor fails open; missing client → exit 2 → deny-all. Cursor reads the system file only at start-up (restart after init/uninstall).
- R0 gaps (V5a): `pkill python`/`killall python3` can kill the recorder (KeepAlive restarts it); ruby/perl -e not inline code; relative paths after `cd`, globs, brace expansion and variables unseen; ~/.claude/settings.json not guarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md predates V6/V3a in places and has no `/api/sessions` contract (V9 should add it); Neo4j Session lacks workspace_root.
- No card owns SPEC §10's per-session hash check at session start (raised in V3b pass 2).
- V3b: the offline guard has path rules only, no `launchctl`/`brew` command rules (R0 has both); Homebrew `stop` leaving an old LaunchAgent goes to V4.
- V2c leftovers: `StrReplace`/`Delete` edits not merged as writes; an id-less read within 5 s of a create can join it (3.24.12 only); merge state lost on restart; a blocked step keeps its first half's order.
- Test suite ~4–5 min serial (2,539 tests; slowest: test_install_flow 69 s); F7 addresses it.

## Next 3 actions
1. Review V8b: read its report, lead /code-review high on `main...ag-v8b-recorder-fields`, probe the new fields; hold the merge for a trial merge with V3c.
2. When V3c reports: review it the same way, trial-merge V3c + V8b (3× full suite), probe, ask the owner to merge.
3. Then: re-check V5b's brief (standing rule), verify the 7 review findings → fix card, brief F7; move AGENTS.md "Testing" to tests/README.md.

Model used for rehearsals: Grok 4.7 High in Cursor chats.

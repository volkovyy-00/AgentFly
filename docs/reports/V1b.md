# V1b: SPEC catch-up
Status: done (as of 2026-10-18 17:00)
Result: SPEC.md now states S3, S5 and the owner answers of 2026-10-16..18. No "Pending S3" or "Pending S5" is left; the one marker is "Pending D16". Docs only; AGENTS.md needed no change. Unsettled points are listed below.
Evidence: Check command passes: ruff clean, 100 files formatted, 650 passed, 4 skipped. `grep "Pending S[35]" SPEC.md` is empty. Files: SPEC.md, docs/reports/V1b.md. Commit on ag-v1b-spec (see git log).
Needs owner: none. Optional: decide whether the 30-minute workspace fallback (D21) is a rules-file field (`scope`/`window`) or engine-only; I wrote it as engine behaviour.
Details: see "## 2026-10-18 17:00" below.

## 2026-10-18 17:00

### Decision to SPEC section

| Decision | SPEC section(s) |
|---|---|
| D1 | §2 (wording), §10 |
| D2 | §3, §7 (already stated) |
| D3 | §3, §5 (change flow), §10 (S5 sudo re-run: D3 stands) |
| D4 | §3, §9 (adds 401/403 and unreadable input to the guard triggers) |
| D5 | §3, §7, §8, §9 (missing client file is a loud failure, `doctor` red; replaces "Flagged to the owner") |
| D6 | §7 (already stated) |
| D7 | §3 (adds `config.toml`) |
| D8 | §3, §7 (already stated) |
| D9 | §8 (event table, `subagentStart`, duplicate reads: S5 found no linking field) |
| D10 | §3, §5 (S3 additions, narrowed heredoc rule, normalisation). The wget flag list (`--post-data`, `--post-file`, `--body-data`, `--body-file`) has no SPEC home: it is the content of one of the owner's rules and belongs in the rules file. |
| D11 | §5, §8 (already stated) |
| D12 | §5 (already stated) |
| D13 | §5 "Drafting in plain language", §12 (C: no plain language in v1) |
| D14 | §3 (Neo4j needs `neo4j = true`, `wipe` keeps marks), §4 (already stated), §5 (R0 denies `wipe`), §11 |
| D15 | §6 (already stated) |
| D16 | not written in: stays proposed; §0 and §12 carry "Pending D16" |
| D17 | §0 (it is the decision to write this SPEC); no other home |
| D18 | §3, §8, §12 (already stated) |
| D19 | §11 (already stated; `wipe` keeps marks added) |
| D20 | §7, §12 (already stated) |
| D21 | §5 "Subagents", §8 (`subagentStart` record-only) |
| D22 | §10 "The sandbox is not a control", known gaps |
| D23 | §3, §7 (`init -g`, `doctor`), §8 |
| D24 | §7 (`doctor`), §8 "Where hooks come from", §10 known gaps |
| D25 | §3, §8 |

Owner answers not in DECISIONS: R0 denies `agentfly serve` and `agentfly wipe` (§5); 401/403 gets the offline guard, every inline one-liner is denied offline (§3, §9); 0.5 s wait and the p95 target re-measured in V3a (§8).

### Reader questions

| Question | Answer in SPEC |
|---|---|
| Which events are registered? | §8 table: four gates, plus `afterFileEdit`, `sessionStart`, `sessionEnd`, `subagentStart` record-only; three never registered. |
| What happens to a subagent of a marked chat? | §5 "Subagents": marked through `parent_tool_call_id`, both ways; 30-minute workspace fallback; nothing depends on `subagentStop`. |
| Which port does the hook client use? | §3 and §8: always 8787, no port file, no environment variable. |
| What does R0 deny, including `serve` and `wipe`? | §5 "R0": AgentFly folders, any `hooks.json`, rules file, token; stop/remove commands and the port; `agentfly serve` and `agentfly wipe`; writes to guard paths. |
| What does the client do on 401/403? | §3 and §9: applies the offline guard, never an allow. |
| When does Neo4j receive steps? | §3: only with `neo4j = true` in `~/.config/agentfly/config.toml`. |
| What does `wipe` delete? | §3 and §11: saved sessions and steps from the local store; never the marks; the Neo4j copy only by the store's `--clear`. |

### Unsettled, left as is, or not decided here
- `scope` and `window` on `after_then`: D10 approved them as provisional option (a); D21 A replaced it and keeps the 30-minute workspace fallback. Whether that fallback is a rules-file field is not decided; SPEC describes it as engine behaviour. This is separate from the approved `path_scope`.
- `"@outbound"` (S3 proposal for a reserved name in `command` lists) was never approved; not in SPEC.
- The shape of inline tests (S3's `[[rule.test]]` with `steps` and `expect`) is not approved; SPEC says only that each rule carries inline tests.
- The exact R0 guard list is fixed in the R0 card (SPEC says so; V5a brief has a list).
- Duplicate reads: no merge key yet; S5 found no field linking `preToolUse` and `beforeReadFile`.
- MCP events and `ask` on non-shell events are untested.
- How Cursor combines an allow from `~/.claude/settings.json` with AgentFly's deny is untested (D24). Cursor's docs claim a priority rule; unverified on 3.24.12. Cursor's docs also name project-level `.claude/settings*.json`, which D24 does not mention; not in SPEC.
- Latency: V2b measured p95 69 ms against the 50 ms target. SPEC keeps 50 ms and says V3a re-measures. The 69 ms figure is in AGENTS.md and the V2b report only.
- `wipe` and the Neo4j copy: DECISIONS D14 only says `wipe` never clears marks. "Local store only; Neo4j only by `--clear`" comes from AGENTS.md and the V6 brief.
- Where the recorded hashes live (install card).
- AGENTS.md says "V3 re-measures" where the brief says V3a (not a contradiction; left).
- D19 names `tests/test_api_surface.py`; the real test is `tests/test_app.py` (`ROUTE_WHITELIST`). SPEC §11 says only "a test".

### Gaps outside the card
- AGENTS.md does not mention the `neo4j = true` switch; V6 builds it and should add the line.
- README.md and HOOKS.md still describe today's code (V3a owns README's install section).

### Test list check
Every file and named case in AGENTS.md "Testing" exists in `tests/`: none missing.

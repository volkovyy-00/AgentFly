# V1a: Rewrite SPEC.md and AGENTS.md for the approved decisions
Status: done (as of 2026-10-16 12:00)
Result: SPEC.md is now the v1 spec (sections 0–13, §4 still "what is stored and how commands are cleaned"). AGENTS.md, G1 flow, HOOKS/README references updated. Hackathon spec archived. D13 and D16 are marked pending. No code touched.
Evidence: branch ag-v1a-spec, commit 863b3e8 (report fix on top). Check command: ruff check clean, ruff format 72 files clean, pytest 158 passed, 4 skipped. Decision table and 20 code gaps below.
Needs owner: 3 items (see 'Second-opinion review'): quoted-heredoc hole in D10, cleaner leaks `-pSECRET`, D5 'missing files → guard' can't work. Recommend: tighten D10, fix cleaner before V6.
Details: see "## 2026-10-16 12:00" below.

## 2026-10-16 12:00

### What changed

| File | Change |
|---|---|
| `SPEC.md` | Rewritten as the v1 spec (outline from the brief; sections 0–13). |
| `docs/archive/SPEC-hackathon.md` | `git mv` of today's SPEC, plus a two-line "archived" note at the top. |
| `AGENTS.md` | v1-target paragraph and rule for gaps; today's commands kept and labelled; hatchling and the bundled Python (D5) approved; "Order of work" and the stage-order text removed; rule shape per D10; "Hook helper" rules renamed "Hook client rules" with the D4 offline guard replacing "unreachable → allow"; stripping list; API-surface rule; Testing list trimmed to tests that exist (R0 line and "helper drops `content`" line removed); S1 facts added to "Hook facts". |
| `docs/product-goals.md` | G1 target flow: dropped "(or `agentfly init` for one project)" (D20). Nothing else. |
| `HOOKS.md`, `README.md` | SPEC references only: the "ask before running commands OFF" pointer now names the archive; the stripping pointer names SPEC §8; README's SPEC link says "v1 spec" and links the archive. `HOOKS.md` "SPEC §4" references are unchanged and still true. |

### Decision → SPEC section

| Decision | Subject | SPEC section(s) |
|---|---|---|
| D1 | What "never edit its own rules" means (wording) | §2 (constraint), §10 |
| D2 | System `hooks.json` | §3, §7, §10 |
| D3 | Root-owned rules file, `sudo` approve | §3, §5 (change flow), §10 |
| D4 | Offline guard, KeepAlive, deny says `agentfly start` | §3, §7 (doctor), §8, §9 |
| D5 | One stdlib file on a bundled root-owned Python | §3, §7, §8, §10 |
| D6 | Tap + PyPI `agentfly-recorder`, macOS only, hatchling, name clash | §7, §12 |
| D7 | File locations, rename from flightrecorder, migration | §3, §7 |
| D8 | brew services / own LaunchAgent, uninstall order | §3, §7 |
| D9 | Event list (revisit after S5), stripping, dedup | §8 (Pending S5), §4 |
| D10 | Fixed rule kinds in TOML, R0 in code, normalisation, quoted heredoc | §5 (fields: Pending S3) |
| D11 | block / warn (`ask` on shell) / highlight | §5, §8 (answers), §10 ("Always Run") |
| D12 | Draft → check → diff → backtest → sudo approve | §5 |
| D13 | Plain-language drafting — **proposed, pending S3** | §5 (Pending S3), §12 |
| D14 | SQLite store, optional Neo4j, workspace path, 28 days, `wipe` | §3, §4 |
| D15 | Decision-first UI, Why card, S4 requests | §6 |
| D16 | G4 direction — **proposed, pending S5** | §12 (Pending S5) |
| D17 | SPEC.md rewrite, hackathon spec archived | §0, `docs/archive/` |
| D18 | `agentfly-hook <agent> <event>` | §3, §8, §12 |
| D19 | Split API, whitelist test, docs routes off | §11 |
| D20 | No per-project `init` (and G1 flow edit) | §7, §12, `docs/product-goals.md` |

"Pending S3 / S5" markers in SPEC.md: rule kinds and fields (§5), plain-language
drafting (§5), sensitive-list field names (§5 R1), subagent scope of the mark
(§5 R1), event list and unknown-event report (§8), sudo grace period (§10),
memory experiments (§12).

### Where today's code differs from the new SPEC

Paths and packaging
1. Paths: token, `sessions.json`, Neo4j `.env` and the logger all use `~/.config/flightrecorder`; the hook log is the repo's `logs/events.jsonl`. SPEC §3: `~/.config/agentfly/`, `~/.local/share/agentfly/` (D7). No migration exists.
2. No installable package: top-level `recorder/` and `hooks/`, no `agentfly` import package, CLI or `agentfly-hook`. `pyproject.toml` name is `agentfly`, no hatchling, no `ui/dist` in a wheel. The server runs via `uvicorn recorder.app:app`.
3. No `agentfly init/start/stop/status/doctor/uninstall/rules/wipe/serve`, no launchd/KeepAlive plist, no integrity hashes, no Homebrew formula.

Hooks
4. Hooks are registered per project (`install.sh` writes gitignored `.cursor/hooks.json`, command `.venv/bin/python hooks/hook.py`, not `python -I -S`, not quoted, not on a bundled root-owned Python). No system `hooks.json` (D2/D5).
5. `hooks/hook.py` answers plain allow when the recorder is unreachable (`allow_fail_open`). SPEC §9: offline guard (D4). No `agentfly start` text in messages.
6. `hooks/hook.py` replaces all of `tool_input` with `<omitted>`, so the server cannot see a Write target; SPEC §8 keeps the file path and MCP server/tool names. `output` stripping is not coded (event not registered). No `<agent>` argument, no `tool_use_id` dedup, no offline log.
7. `install.sh` registers five events; SPEC §8 adds `sessionStart` and `sessionEnd`. No Cursor-version gating.

Rules
8. Rules are one Python list with a single rule (R1); no TOML file, kinds, inline tests, or system-owned rules file. Sensitive names and outbound tools are hard-coded.
9. Severities: `block` only (a `warned` verdict exists only under `WATCH_ONLY`). No `highlight`, no `ask` answer on shell commands (D11).
10. R0 is not implemented (README says so). SPEC §5 defines it.
11. R1 has no normalisation: `bash -c`, `sh -c`, `env`, `sudo`, `$(…)` and backticks are not unwrapped, paths are not case-folded.
12. `python -c "print(1)"` and other inline one-liners without "http" are allowed after a mark (`tests/test_rules.py::test_python_print_allowed_after_mark` asserts exactly that). SPEC §5: any inline-code one-liner is outbound. V5 must change that test.
13. Unparseable commands are not outbound after a mark (`test_words_unbalanced_quote_does_not_raise`); SPEC §5 counts them outbound, except quoted-delimiter heredoc bodies.

Store and API
14. Store: Neo4j (background, enabled when credentials exist) is the only persistent store. No SQLite, no history, no retention, no `agentfly wipe`. `StepRecord` has no workspace path or session end time. The in-memory list keeps 500 steps.
15. FastAPI's `/docs`, `/redoc` and `/openapi.json` are served; `/v2` redirects exist but are not in D19's list (V2 should decide). No `/api/sessions`, `/api/sessions/{id}/steps`, `/api/rules`; `/health` has no offline count. `tests/test_api_surface.py` does not exist.

Page and docs
16. The page is the lane graph as home. No Live Trail, Why card, tabs, health strip or half-screen layout (V8). The OFFLINE banner exists.
17. `fake_agent.py`, `demo/` and the README/HOOKS install text describe the hackathon flow (`./install.sh`, `uv run uvicorn …`, fail-open). Deliberately left: the brief allows only SPEC references there.
18. `AGENTS.md` "Hook facts" still lists Cursor 3.5.17 fields from the hackathon, plus the S1 additions (3.24.12). The "Checkpoint A" bullet is hackathon history, kept.
19. Tests named in `AGENTS.md` Testing: all exist. Not listed because they do not exist yet: R0 (V5), helper drops `content` (V2), API surface (V2), stripping (V2).
20. `tests/test_app.py::test_forbidden_host` and similar set `config_dir` to a `flightrecorder` folder; they rename with the paths (V2).

### Judgement calls (please confirm or correct)
- **"Highlighted" as a fourth verdict** in SPEC §4. D11 says highlight = allow plus a UI mark, so something must record the mark; I named the verdict. The storage shape is V6's.
- **Cleaner vs quoted heredoc.** D10's quoted-heredoc exception is written into §5 (decisions) only. §4 (storage) keeps today's rule 4: any `<<EOF` is stored as `<program> <unparsed>`, so storage stays at least as strict as before. §4 says so.
- Command names `agentfly rules draft/check/apply`, `wipe`, `doctor`, `serve` come from D3/D6/D8/D12/D14 and the card texts. `rules test` is not named in SPEC (V5 names it).
- The R0 guard list in §5 is today's list widened by what D1–D3, D9 and D19 protect (config/data/system folders, any `hooks.json`, rules file, token, `launchctl`, a Write target). The card (V5) fixes the exact list; SPEC says so.
- §10 and §9 cite S2 only through DECISIONS.md. I did not read `docs/spikes/S1/S2` beyond what DECISIONS.md and BOARD.md quote.

### Second-opinion review (2026-10-16, after the commit)
A fresh reviewer (web + docs access) and I checked the SPEC independently. I re-ran the key findings.
Fixed in SPEC.md (wording, nothing new decided):
- §4 now says the new items are workspace path, end time and the *highlighted* verdict; the path is also in Neo4j when enabled. Step 2 names attached values (`-uadmin:pw`, `-pSECRET`) as values.
- §5 no longer says normalisation "extends the cleaner" (the cleaner unwraps nothing, checked). R0 list adds `agentfly stop/uninstall` and `brew services`.
- §8: file reads fire both `preToolUse` and `beforeReadFile` with no shared id, so they would show twice (S1 log: 3 vs 2). Marked open. `tool_use_id` on shell events is marked as seen in S1, not in Cursor's docs.
- §9: an offline allow shows nothing in Cursor (S1), so signals are the page and log. `KeepAlive` does not help after a deliberate stop. A missing hook file makes Python exit 2 and Cursor blocks everything; this is not the guard D5 describes.
- §7: `brew uninstall` before `agentfly uninstall` leaves a client that keeps denying and names a command that no longer exists.
- §10 known gaps: R0 is name-matching (stop, notes file); hash check is run by code that could be tampered; heredoc and "write a script then run it" are not caught.
- §12: D16 stays proposed. §0 says §§7, 8, 11 are technical. Glossary gains token, port, hash, heredoc, MCP, normalisation, backtest.

Needs the owner (not mine to decide):
1. **D10 heredoc hole.** By reading the rule: `bash <<'EOF' curl … EOF` and `python3 - <<'EOF' …` are executed code, yet pass R1 after a secret read. Recommend: the quoted-heredoc exception applies only when the command is not a shell or interpreter (`cat`, `git commit -m`, `tee`…); otherwise the body counts as outbound.
2. **Cleaner leak (code, not docs).** Verified by running it: `curl -uadmin:hunter2 https://x.com` is stored as `curl -uadmin:hunter2 x.com`; `mysql -pSECRET db` as `mysql -pSECRET <arg>`; `curl -H'Authorization: Bearer abc' x.com` keeps the bearer token. Cause: `recorder/clean.py::_classify_word` returns any `-x…` word as is. This breaks "no secrets stored" today, in Neo4j too. Recommend: keep only the first two characters of a short option (or the part before `=` for long ones), with tests; schedule before V6 stores anything.
3. **D5 "files missing → offline guard"** cannot work (no client runs). Recommend rewording D5 to "loud failure, `doctor` red".

Not changed (low): cleaner keeps a path only if the file exists; a two-part long host becomes `<arg>`; `beforeReadFile` documents only `user_message`; LAN addresses count as "your own computer"; D6's clash is unproven for uv/pipx/brew; whether `brew uninstall` leaves the plist is unconfirmed.

Gap 21 (code): the cleaner leak above. Gap 22 (code): reads are recorded twice (`preToolUse` + `beforeReadFile`).

### Check output
```
uv run ruff check .          → All checks passed!
uv run ruff format --check . → 72 files already formatted
uv run pytest -q             → 158 passed, 4 skipped, 1 warning
```
The npm checks were not run: no file under `ui/` changed.

### Not done (outside the card)
`docs/DECISIONS.md`, `BOARD.md`, `STATE.md`, `docs/learnings.md` untouched (lead only). D13 and D16 statuses left as proposed. No push, no merge.

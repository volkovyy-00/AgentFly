# V5b · Rules file and severities: R1 in TOML, warn and highlight, `rules check` / `rules test`, `GET /api/rules`

You are a worker on card V5b in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v5b-rules-file. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v5b-rules-file only, the lead merges.

**Summary.** Rules move out of Python into one protected file, so the owner adds a rule by editing that file; warn and highlight start doing what D11 says; two commands check a rules file and run its tests; the page can read the active rules.

**Written against:** 70f5c77 (2026-10-18).

**References**
- SPEC.md § 5 "Rules" (Severities, Rule file, R0, R1) and § 11 (`GET /api/rules`) are the target; `docs/DECISIONS.md` § D10 (fixed kinds in TOML, `match` and `after_then`, inline tests), § D11 (what each severity answers), § D3 (root-owned active file).
- `agentfly/recorder/rules.py` § `RULES`, § `decide`, § `deny_messages`: today's rule list, which only ever blocks; § `check_r0` stays in code.
- `agentfly/recorder/app.py` § `apply_rules`: turns a verdict into the hook answer; only `blocked` denies today. `agentfly/recorder/sessions.py` § `effective_marked`: how R1's mark is saved and follows parent and child chats.
- `docs/spikes/S3-rules.toml`: schema v0 as written for S3 (lists, `[[rule]]`, `after`/`then`, `[[rule.test]]` with `steps` and `expect`); start the file format from it.
- `agentfly/install/installer.py` § `install`: where `init -g` writes the root-owned files; the rules step goes here. § `status` decides what a repair redoes; an intact install returns early today.

**Scope**
- Kinds `match` and `after_then`, read with `tomllib`; named lists in the file. R1 and its sensitive-name lists move to a packaged default file; R1's engine-only outbound cases (one-liners, unparseable commands, wrappers, local-host exception) stay in Python behind one named built-in class the file refers to. An `after_then` trigger is kept per chat like R1's mark: it survives a restart, reaches subagents and parents (D21), and counts before the check on the same command, as R1's mark does.
- The active file is `/Library/Application Support/AgentFly/rules.toml`, root-owned and world-readable, written by `init -g` only when missing (a repair never overwrites it; an install from before this card gets it on its next `init -g`), removed by `agentfly uninstall` with the folder, read once at start. Without it (developer `serve`), the packaged default is used. An invalid active file, or one that names R0, is not loaded: the recorder runs on the packaged default and says so in `/health` and `/api/rules`. R0 is always first and in code only.
- Severities per D11: when several rules match, the strictest wins (block > warn > highlight; a tie goes to file order); its message is used. `WATCH_ONLY` and its two tests go: a trial rule is a `highlight` entry (SPEC § 5).
- `agentfly rules check [FILE]` (schema, unknown fields, an entry for R0, a pattern that matches everything) and `agentfly rules test [FILE]` (every inline test); both default to the file the recorder would load.
- Touches: `agentfly/recorder/` (rules, new rulefile, app, sessions, api), new packaged `agentfly/rules/default.toml` (in the wheel), new `agentfly/cli/{rules_check,rules_test}.py`, `agentfly/cli/__init__.py`, the rules step in `agentfly/install/`, a rules line in `agentfly/cli/doctor.py`, their tests, `tests/test_app.py` whitelist, SPEC § 5 field names, HOOKS.md (`WATCH_ONLY`), AGENTS.md "Working rules" (rules no longer "one list in rules.py") and "Testing".
- Not included: the S3 additions, the owner's 10 S3 rules and bypass tests (V5c); `rules draft`, `diff`, `backtest`, `apply` and live reload (V7); a rules view on the page; a `count` kind.

**Acceptance criteria**
- Every existing rule, R0, normaliser, subagent-mark and offline-guard test passes (bar the two `WATCH_ONLY` tests), and a replayed demo session gets byte-identical hook answers, with R1 now loaded from the packaged default file, also when run from the built wheel.
- "Block `npm publish` after reading `.env`" added as one entry in the packaged default: `npm publish` is denied after `cat .env` and allowed in a fresh chat, also in a subagent of the marked chat and after a recorder restart; the commit that adds it touches no `.py` file (diff in the report).
- A warn on a shell command answers `ask` with the rule text; a warn on any other event and every highlight answer `allow`; the page and history show the step as warned or highlighted; with a block and a warn both matching, the answer is deny.
- After `init -g` (fresh, or over an install from before this card) the active file exists root-owned, mode 644; a second `init -g` leaves an edited copy unchanged; `agentfly uninstall` removes it; an active file with a syntax error, an unknown field, or an entry for R0 is not used, and `/health`, `/api/rules` and a failing `doctor` line say the default is in force.
- `agentfly rules check` and `agentfly rules test` exit 0 on the default file; each of a schema error, an unknown field, an entry for R0, a match-everything pattern and a failing inline test exits 1 and names the rule.
- `GET /api/rules` returns each active rule's id, kind, severity and message (R0 first) and the file in use; it is in the route whitelist, and every other method on it is refused.

**Dependencies:** V5a ✅, V3a ✅, F5 ✅, V3b and V3c merged (V3c's package check guards the user-writable default that `init -g` copies, and V3c changes R0 in `rules.py`; both touch `agentfly/install/`); the lead re-checks this brief against main before dispatch.

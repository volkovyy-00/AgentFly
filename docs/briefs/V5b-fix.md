# V5b-fix · Review fixes on ag-v5b-rules-file (DRAFT: owner decisions A–C open; not dispatchable)

Source: lead trial 686ccbb (main 522b0b4 + V5b fe3386e): 3× check green (3871 passed, 5 skipped, 137–162 s); three fresh reviewers (rules engine; brief and tests; install, CLI, API), no blocker. Probes: lead scratchpad (not in repo).

## Owner decisions (open)
- A. A valid active file may today drop R1, set it to `highlight`, or narrow it, with no problem in `/health` and doctor `ok`. Lead proposal: refuse such a file like an R0 entry (R1 must exist with severity `block`; the default runs and the problem is shown).
- B. Packaged-rule updates never reach an install (`init -g` writes only when missing), so V5c's rules would reach no installed user. Lead proposal: doctor warns when the active file differs from the packaged default; the update path is V7's `apply`.
- C. Who fixes: the V5b worker (very large context) or a fresh worker on the same branch running a plan with superpowers:subagent-driven-development. Lead proposal: fresh worker.

## Fix list (should-fix)
1. Active file trust (D3): the recorder loads `rules.toml` without checking it. A symlink, a non-root owner or a group/other-writable mode is accepted silently (verified: such a file dropped R1, no `rules_problem`). Refuse it (no-follow open, uid 0, not group/other-writable) and run the default with a problem. Anchors: `rulefile.load_file`, `rules.load_active`.
2. `init -g` copies `default.toml` from the user-writable tool environment late in `install`, after the hash check, unparsed. Read the bytes once, check them against the package's RECORD hash, require a clean parse, then write. Anchors: `installer._install_rules`, `packages.require`.
3. Per-hook cost: path patterns are re-matched per word, per rule, per clause, and again in `store.reads_secret`. Verified: a valid file (20 `after_then` rules on one 200-entry list) plus a 300-word command takes 0.6 s, above the client's 0.5 s wait, so the offline guard answers (and allows `npm publish`). Compile each list once at load; reuse one per-hook result per list. Replace the 0.35 s wall-clock test in `tests/test_rulefile.py` (fails 3 of 4 under load) with a bound that does not depend on machine load.
4. Match-everything check misses `[!x]*`, `*[a-z]*`, `.*` (verified: `secret_names_ok` with one of them turns off R1 marking, no error). Judge patterns by what they match, not by spelling.
5. No test sends an `ask` answer through the hook client to its stdout; add one (StubRecorder returns the shell-warn answer; the client prints it unchanged).
6. doctor `check_rules` says the file is "the one the running recorder read" but only reads `/health.rules_problem`; an edited, not-restarted file shows `ok`. Fix the wording or compare with what the recorder loaded. `/health.rules_problem` should say the default is in force.
7. If A is approved: R1's id carries global meaning (`Session.marked`, D21 fallback, history flag, `sensitive` badge via `names.is_sensitive`); the A check covers it for v1.

## Nits
- `tests/test_rules_load.py` "unknown field" case is a second syntax error; add a real unknown field through `load_active` → `/health` → doctor.
- Dead code / double sources: `rules.RULES` mirror, `deny_messages`, `is_outbound_send`, `R1_MESSAGE`, `MARK_RULE` in two modules, `decide` then `find_rule` (lookup not once), import inside `names.is_sensitive`.
- `rules test` with 0 tests exits 0; a missing FILE says "not a file"; `schema = 1.0` accepted; `_folded_segments` cache keeps 512 whole words.
- AGENTS.md "Testing" lacks the three wheel tests; edits to AGENTS.md "Commands"/"Hook facts" are outside Touches (lead reviews).
- Duplicate tests: `test_rules_api` method refusals repeat `test_app`; `test_rules_cli` REFUSED ×2; `not hasattr(store, "find_rule")` proves little.

## Not in this fix (later cards)
- V5c: `npm${IFS}publish`, `echo publish | xargs npm`, `xargs npm <<< publish`, `pnpm publish`, `npx -y npm@latest publish`, `npm $(echo publish)` dodge; `npm run publish` is a false positive. Offline guard has no backing for file rules.
- Chats marked before V5b do not get the npm trigger after upgrade (accept; one line in the report).
- Pending Task snapshot copies parent triggers at Task start (same as marks).
- `status`/`start` do not show `rules_problem`; a broken packaged default makes launchd restart-loop with no reason shown.
- Lead (on merge): SPEC §8 (~l.707) shell-warn answer lacks `agent_message`; SPEC §7 doctor list (~l.575–592) lacks the rules line.

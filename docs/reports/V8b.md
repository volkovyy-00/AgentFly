# V8b: Recorder fields for the Why card and health strip
Status: done (as of 2026-10-19 16:12)
Result: A blocked step on /api/steps now has rule_text, user_message and agent_message (the deny answer's own strings); a warned step has rule_text only; /health has last_hook_at; ?all=1 has marked_order. All in memory; answers, history.db and Neo4j unchanged. The page was not touched.
Evidence: code commit c14c92e on ag-v8b-recorder-fields. Full check: ruff clean, 2557 passed, 5 skipped. New: tests/test_step_fields.py (18 tests) plus tests in test_memory, test_localstore, test_store. Live run on a throwaway HOME matched.
Needs owner: none
Details: see "## 2026-10-19 16:12" below.

## 2026-10-19 16:12
Done against `docs/briefs/V8b.md`. One code commit, c14c92e (code, tests, HOOKS.md, AGENTS.md "Testing"); this report is the second commit.

**What changed**
- `store.py`: `StepRecord` gets `user_message` and `agent_message` (`repr=False, compare=False`, like `raw_command`). No store reads them: SQLite and Neo4j write explicit fields.
- `app.py`: the hook answer is built once, in the new `hook_answer(verdict, rule_id)`, right after `decide()`. The step record gets the same strings before `step_merger.join`, so the step and the answer cannot differ. `/health` adds `last_hook_at`, set by each `/hook` request right after the token check passes (reset at start, so `null` until the first).
- `merge.py`: `Joined.merged()` copies the two messages from the same half as the verdict, rule and rule text. No other merge change: the tie rule (earlier half stays) was already in the strict `>` of `Joined.add`.
- `memory.py`: `_step_dict` adds `rule_text` (from `rule_description`) and the two messages, only when present. `snapshot(all_steps=True)` adds `marked_order` (`null` when unmarked or empty).
- `localstore.py`: a docstring line only. HOOKS.md (`/health`, `/api/steps`) and AGENTS.md "Testing" (one new bullet, no existing line edited) updated.

**How each acceptance criterion is checked**
- Demo replay: `test_the_demo_replays_blocked_step_carries_the_rule_text_and_the_answers_messages` posts the events of `demo/scenario.json` (no `content`, as the hook client strips it). The blocked step has R1's text and messages equal to the `/hook` answer; the two allowed steps have none of the three keys. `test_the_deny_answer_is_byte_for_byte_what_it_was` pins the literal answer bytes, not strings built from `deny_messages`.
- Watch-only: `test_a_warned_step_has_the_rule_text_and_no_messages` (`WATCH_ONLY` set in process); the answer is exactly `{"permission":"allow"}`.
- Merged: `test_a_merged_step_carries_the_messages_of_the_deny` and `test_on_a_tie_between_rules_the_earlier_halfs_rule_text_and_messages_stay`, each in both orders (R0 on a `preToolUse` naming a guard path against R1 on the shell: `rule`, `rule_text`, both messages name the earlier half).
- `/health`: `null` after start, a UTC time within a second after a hook, unchanged after a wrong or missing token, `offline_guard_count` unchanged (the count file is filled so the check is not 0 == 0). A session event counts as a hook; a restart forgets it.
- `?all=1`: `marked_order` equals `?limit=1`'s, `null` when unmarked and on an empty recorder; `/api/steps` stays `{session, steps}`.
- No change to storage: `test_the_deny_messages_never_reach_the_file` (scans `history.db`, `-wal` and `-shm`, with a positive control) and `test_the_deny_messages_never_reach_neo4j` (a recording `tx` into `_merge_step`: marker strings absent, parameter names equal a fixed list). Each was run once against a planted leak and failed as it should, then the leak was removed. No route is added (the whitelist test passes unchanged).
- Three existing tests changed on purpose: `?all=1` keys in `test_app.py`; the two exact `/health` bodies in `test_offline_guard.py` and `test_package.py`.

**Checks**
- `ruff check . && ruff format --check .`: clean.
- Whole suite (`pytest -q`, including the wheel build): 2557 passed, 5 skipped (the live-Neo4j tests, as before). Before the change I ran only the affected files: 1364 passed, 5 skipped. I did not run the whole suite on the base commit.
- Live run: a recorder from this branch on a free port under a throwaway HOME, the three demo events posted with the token. Result: `last_hook_at` null then `2026-10-19T14:11:54.006+00:00`; a wrong token gave 401; `?all=1` and `?limit=1` both said `marked_order: 2`; the blocked step's three fields equal the deny body; the server log has no body text.
- Not run: the web check and the stale-build check, because `ui/` and `ui/dist` are untouched.

**Review**
The plan went through a second-opinion review by a fresh agent before any code. It found four problems in my first plan, all fixed: the live check could not use `fake_agent.py` (the hook client's port is fixed at 8787, D25), so the replay test reads `demo/scenario.json` in process; there was no fake Neo4j driver to reuse; a history scan of `history.db` alone misses the write-ahead log; and a lone `afterFileEdit` that denies does carry its messages (it shows its own verdict), which now has a test.

**Choices to know about**
- `last_hook_at` is set by any `/hook` request that passed the token check, as the brief words it, so a right-token request with a bad content type or body also sets it. It has millisecond precision because the page reads it with `new Date(...)`, and the ECMAScript date string fixes the fraction at three digits.
- A warned step has `rule_text` and no messages, because its answer is a plain allow. A step with no rule has none of the three keys (absent, never `null`). `flagged` steps share the shape, so they carry them too.

**Gaps outside this card (left as they are)**
- The page still sends `GET /api/steps?limit=1` each poll (`ui/src/trail/useTrail.ts`). It can stop now; that is a UI change. `ui/README.md` lines 37-38 still say `?all=1` sends no `marked_order`.
- The three step fields are not in `/api/sessions/{id}/steps` (V9). The `highlighted` verdict and warn answers are V5b. HOOKS.md still has no `/api/sessions` contract.
- V6b's report suggested dropping the `marks=` argument of `memory.py`. It is not in this brief, so I left it.

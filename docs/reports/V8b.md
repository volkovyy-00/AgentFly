# V8b: Recorder fields for the Why card and health strip
Status: done (as of 2026-10-19 16:37)
Result: A blocked step on /api/steps now has rule_text, user_message and agent_message (the deny answer's own strings); a warned step has rule_text only; /health has last_hook_at; ?all=1 has marked_order. All in memory; answers, history.db and Neo4j unchanged. The page was not touched.
Evidence: commits c14c92e (code) and d0f2a67 (simplify) on ag-v8b-recorder-fields. Check on d0f2a67: ruff clean, 2555 passed, 5 skipped. tests/test_step_fields.py: 16 tests. Page checked in Chrome: Why card shows all three fields, health strip shows the last hook. Cold audit: no findings.
Needs owner: none
Details: see "## 2026-10-19 16:37" below.

## 2026-10-19 16:37
Final verification of c14c92e + e28d705, then one simplify commit, d0f2a67. No behavior change.

- **Smoke, real server.** A recorder from this branch on a free port under a throwaway HOME (port 8787 untouched). Two sessions posted: a merged R0-vs-R1 pair (kept R0 and its messages, the earlier half) and the `demo/scenario.json` replay. `/health` said `last_hook_at: null` at start, then a UTC millisecond time. `?all=1` and `?limit=1` both said `marked_order: 2`.
- **Smoke, the page.** In Chrome, `/` showed the blocked step's Why card with a "Messages sent" block (rule text, `user_message`, `agent_message`, equal to the deny answer) and the health strip "Recorder up · last hook 16:14:54 · offline guard 0" (local time of `14:14:54Z`). No console messages across a reload. The page's own `parseSnapshot` on the live bodies gave the three fields and `markedOrder` 2.
- **Suite.** `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`, run with `uv run` in this branch's own environment: 2557 passed, 5 skipped before the simplify pass, 2555 passed, 5 skipped after (two redundant tests removed).
- **Simplify (four reviewers: reuse, simplification, efficiency, altitude).** Applied: `build_step_record` takes the two messages (no second record copy per hook); the new test file imports the helpers it had copied from `test_step_merge.py` and reads the scenario once; the demo replays under a `/w` workspace, because `Path.resolve` on macOS's autofs `/home` costs about 90 ms an event (measured); two tests that repeated others and one assertion removed; a docstring cut to one line.
- **Simplify, skipped on purpose.** Deriving the two messages from `(verdict, rule_id)` instead of carrying them (two reviewers asked): SPEC §8 "The answers" makes the answer depend on the hook event (messages "where the event accepts both"; a shell warn answers `ask`), and a merged record no longer knows which half's event it is, so V5b's warn answers would break it. Also kept: the wrong-token test's `offline_guard_count` check and the Neo4j parameter-name list (both are brief criteria), a cache for `agent_message` (about 100 KB at the cap, stale once V5b loads rules from a file), storing `time.time()` for `last_hook_at` (4 µs a hook).
- **Cold audit.** One agent with only the diff and the correctness brief: no findings. It probed merge order (a warned half then a blocked half; a blocked half then an `afterFileEdit` deny) with its own script.
- **Not run.** The web check and stale-build check: `ui/` is untouched.

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

# V6b: History shows which chats were marked, and by which step
Status: done (as of 2026-10-19 13:47)
Result: History lists a chat as marked whenever the rules did (Read+Write of .env, subagent, parent via subagent, 30-minute fallback) and /api/sessions/{id}/steps names the marking step (marked_order). Old history.db opens with no loss. Hook answers unchanged. SPEC §4 reworded per lead review.
Evidence: commits e1f42ff, d3514e4, fd899c5 on ag-v6b-history-mark. Full check: 2197 passed, 5 skipped (baseline 2164). New test pins a fallback chat that marks itself at step 7: history = /api/steps = 7. Smoke and upgrade smoke as before.
Needs owner: none
Details: see "## 2026-10-19 13:47" below.

## 2026-10-19 13:47
Lead review of the branch: code fine, one SPEC wording fix. No code change was needed.

- **SPEC §4** (commit fd899c5). The sentence "A chat that was marked through a link has none." is now: a chat marked only through a link or the workspace fallback has no marking step; if it later marks itself (for example after the fallback window has ended), that step is its marking step. The AGENTS.md "Testing" bullet says the same in one clause.
- **Test that pins it.** `test_a_chat_marked_by_the_fallback_that_later_marks_itself_names_that_step` (`tests/test_history_mark.py`): chat P reads `.env` and starts a Task; chat B (same workspace, no link) runs six `ls` steps inside the 30-minute window, so History lists B as marked with `marked_order` null; the store's clock moves past the window; B runs `cat .env` as step 7. Then B is marked and `marked_order` is 7 in `/api/sessions/B/steps` and in `/api/steps`. It passed at once, because the behavior already worked (`apply_mark` returns `marks` true once the window is over). It can fail: with the clock not advanced it fails (`None == 7`), and with `marks=False` in `apply_rules` it fails (`None == 7`). Both mutations reverted.
- **Checks.** `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`: ruff clean, 2197 passed, 5 skipped (2196 before, plus the new test).

## 2026-10-19 12:11
Final verification (smoke, full check, simplify, independent audit) on e1f42ff + af3c012. Fixes are in d3514e4.

- **Smoke, real servers.** Same 18 hook events replayed over HTTP to `agentfly serve` built from the base commit e1d4aeb and from the branch. Base: `edit-env`, `parent`, `mp-child` and `fallback-chat` listed as not marked, and `/steps` has no `marked_order`. Branch: all four marked; `cat-env`, `edit-env`, `child`, `mp`, `fp` name step 1; `parent`, `mp-child`, `fallback-chat` have no marking step; `lone-write`, `example`, `other-workspace` not marked. The table is the same after a recorder restart. Hook answers are identical on both (one deny, the `curl` after `cat .env`).
- **Audit finding, confirmed and fixed.** The marking step (`steps.marks`) and its chat's flag (`sessions.marked`) were two queue items. With exactly one free slot the step was accepted and the flag dropped, so a chat whose last event was the marking one stayed "not marked" while `/steps` named its marking step. A failing test came first (`test_a_marking_step_marks_its_chat_in_the_same_write`); the step's own transaction now also sets the flag. The separate item stays for flags that come through links.
- **Audit, no other findings.** 300 random event sequences, and 200 with two restarts each, matched an oracle taken from `SessionStore`: history `marked_order` = live memory order, at most one marking step per chat, `marks` implies `marked`. Eight processes opened one old-schema file at once without a failure and without losing a row.
- **Simplify (behavior unchanged).** One listing template for the current and the pre-V6b query; one atomic upgrade check instead of per-column steps; `mark_sessions` drops quietly on a full queue (`flag_marked` already guards the call); the new tests import the helpers they had copied and use one deterministic route-level test for the first read after an upgrade. Removed: a merger unit test covered by the Read+Write tests (replacing the OR with a plain assignment still fails 4 tests, re-run on the final tree), and an old test that could not fail. `tests/test_history_mark.py` now has 26 tests.
- **Checks on the final tree.** `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`: 2196 passed, 5 skipped.
- **Skipped on purpose.** Dropping the `marks=` argument from `memory.py` (the step record now carries the same flag): it is outside this card's files and differs in one edge case; worth doing in V8b, which changes the step record again.

## 2026-10-19 12:10
Done against `docs/briefs/V6b.md`. One commit, e1f42ff (code, tests, SPEC §4, AGENTS.md "Testing").

**What changed**
- Two yes/no items are stored (SPEC §4 lists them): `sessions.marked` (the rules ever counted the chat as marked; it never goes down, also after the 30-minute window ends) and `steps.marks` (this step made the chat marked).
- `/api/sessions` reads `sessions.marked`. `/api/sessions/{id}/steps` has a new `marked_order` (lowest order with `marks`, not cut by the 10 000-step cap). Step objects keep the live trail's keys. No new route, so the whitelist test is unchanged.
- `store.py`: `StepRecord.marks`, set by `build_step_record(..., marks=)`; `apply_rules` passes the `marks` it already had from `apply_mark`, the same flag `/api/steps` uses.
- `merge.py`: `Joined` keeps `marks` as an OR over the halves of one action. Without it the id-less `afterFileEdit` that ends a Read+Write becomes the merged record's base and rewrites the row with `marks` false (`_UPSERT_STEP` replaces the whole row).
- `app.py`: `flag_marked` runs after the decision and offers the event's chat and its parents to `local_store.mark_sessions`. It is also called for session events. It catches every error and logs only the class name.
- `localstore.py`: a `MarkedSessions` queue item (`UPDATE … SET marked = 1 WHERE id = ? AND marked = 0`), queued after the step so the row exists. `_upgrade` adds both columns in one transaction and fills `sessions.marked` with the old guess. It checks the columns again inside the transaction (a second recorder may have upgraded first). A read that beats the upgrade uses `SESSIONS_QUERY_V1`, so the first read answers 200.

**Checks**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`: 2198 passed, 5 skipped. Baseline before the change, run during review: 2164 passed, 5 skipped. Web checks not run (`ui/` untouched).
- Red first: the new and updated tests failed for the missing feature (37 failed), then passed.
- Two mutations were caught and reverted: no OR across halves (5 tests fail, including AC1 and the merge unit test); flagging only the event's own chat (3 tests fail, including the parent-through-subagent and nested cases).
- Upgrade smoke: wrote four chats with the real `git show fb72286:agentfly/recorder/localstore.py`, then opened the file with the new code. The old recorder listed `{edit-env: false, plain: false, read-env: true, shell-env: true}`. A new reader before the upgrade gave the same flags and `marked_order` null; after the upgrade the same flags, columns `sessions.marked` and `steps.marks` at the end (same order as a fresh file), 4 of 4 steps kept, no `marks` set.
- Acceptance: (1) Read+Write of `.env` with one id, ending in an id-less `afterFileEdit`: listed marked, `marked_order` 1, also after a restart. (2) `cat .env`, a `.env` read, a lone Write, a `.env.example` read: flag and step equal `/api/steps?limit=` (parametrized). (3) Subagent of a marked chat, parent marked through its subagent (Task first, child first then Task, child first then `subagentStart`), nested chain, workspace fallback: marked, no marking step except the child's own read; another workspace: not marked. (4) The upgrade cases above plus a rollback test and two recorders on one old file. (5) A run with `mark_sessions` raising gives byte-identical answers and logs no message.

**Review**
A second-opinion review of the plan (fresh reviewer plus my own checks) changed it before coding: parents are flagged from the event's chain on every event, not captured once from `propagate()` (a one-shot flag could be dropped, and a parent already marked before the upgrade was skipped); the column check sits inside the upgrade transaction; `flag_marked` swallows errors; the Read+Write test ends with the id-less `afterFileEdit`.

**Known limits (no card needed)**
- A chat saved before this card keeps the value History showed for it and has no marking step (`marked_order` null). So an `edit`-only chat from before stays "not marked" (brief: not re-derived).
- A child whose events all came before its link was known is flagged on its next event, not retroactively; an idle one stays as it was.
- Retention can delete the marking step while the chat row stays: marked, `marked_order` null. After a restart `/api/steps` has no `marked_order` (memory is empty) while history still does.
- Each event of a marked chat queues two items (step and flag), so the 1024-item queue holds about 512 events in a burst. Hook events come at human pace.

**Outside this card (left as is)**
- `HOOKS.md` documents `/api/steps` only; `/api/sessions` and `/api/sessions/{id}/steps` (now with `marked_order`) have no contract text there. Worth a line when V9 uses them.
- The page (V9) does not read `marked_order` from history yet. The Neo4j copy has no marked flag, as the brief says.
- V8b changes `StepRecord` too: `marks` sits between `workspace_root` and `raw_command`; expect a trivial merge in `store.py`. V3b shares only SPEC.md and AGENTS.md "Testing": my SPEC edit is in §4, my AGENTS.md edit is one bullet after the History bullet.

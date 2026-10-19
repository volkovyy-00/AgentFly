# V2c: One step per action: merge by `tool_use_id`, path fallback for id-less reads and edits
Status: done (as of 2026-10-19 09:00)
Result: Hooks of one action are one step on the page, in history and in the Neo4j copy; hook answers unchanged. Final verification and code review done. Open: history "marked" misses an edit that began with a secret read.
Evidence: commits 8cd25d9, 482418b on ag-v2c-step-merge. Full check 2164 passed, 5 skipped; 3 runs in a row earlier on 8cd25d9 (2161). Real-server smoke replay of the capture: 5 steps. Live Neo4j test skipped here.
Needs owner: History "marked" ignores an `edit` step that began with a secret read (rules do mark the chat). A fix needs a `marked` column (SPEC §4). Recommended: accept now, add the column in a later card.
Details: see "## 2026-10-19 09:00" below.

## 2026-10-19 09:00
Final verification and code review after the first commit (8cd25d9). Changes in 482418b:
- Simplified `merge.py` (one pairing loop, `events` set instead of two flags, no cached merged record, path computed only for events that can pair) and `memory.py` (`replace` uses a found flag).
- A lone `preToolUse` Write now names its file and sensitive flag. It is built in `build_step_record` (store.py), so it also works with no chat id or a relative path.
- `_pair` returns nothing for any event except `beforeReadFile` and `afterFileEdit`.
- Tests added for the lone Write (secret file, relative path, no chat id).

Checks run on the final tree:
- `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`: 2164 passed, 5 skipped.
- Smoke: started a real `agentfly serve` under a temporary HOME and replayed `tests/fixtures/v2c_capture.json` over HTTP. The page feed and `/api/sessions/cap/steps` both gave the 5 steps (edit, edit, read, read, read). A `preToolUse` Shell plus a `curl` `beforeShellExecution` with one id after a `.env` read gave one `blocked` R1 step; answers were allow and deny.
- Not run: `fake_agent.py` against port 8787, the web check and stale-build check (no UI change), the live Neo4j test (needs `AGENTFLY_TEST_NEO4J_ENV`).

Reviews: a fresh reviewer before coding, four simplify reviewers, a cold correctness audit and `/code-review` at high. Dismissed with reasons: two Neo4j rule links on one step (the brief asks for both halves' links); an already-evicted step raised to blocked not entering the flagged list (needs 500 steps between halves, documented); a `resolve()` call on the hook path (read and edit steps already do it).

Decisions for the lead:
- History "marked" gap (Needs owner above). `test_an_edit_that_began_with_a_secret_read_is_an_edit_step` pins today's behaviour.
- Known remaining duplicates: `StrReplace` and `Delete` edits are not treated as writes (the brief names only `Write`); an id-less `beforeReadFile` within 5 s of a create can join the create's Read entry (clients without ids only, 3.24.12).
- Not done, as the card says: merge state across a restart, re-merging saved duplicates, an MCP path fallback, the page's UI code.
- Suggested follow-up card: the `marked` column, and any extra edit tool names once the owner captures them.

## 2026-10-18 20:00

### What changed
- `agentfly/recorder/merge.py` (new): `StepMerger`. Events of one chat with the same `tool_use_id` share one step. Id-less fallback (same chat, absolute path through `posixpath.normpath`, 5 s): a `beforeReadFile` joins the oldest unpaired `preToolUse` Read; an `afterFileEdit` joins the latest unused `preToolUse` Write. Waiting list in memory, 32 per chat, oldest dropped. Merged step: file and command from the specific event; kind `edit` if a half writes, else the specific kind; verdict and rule from the strictest gate half (`afterFileEdit` never raises it); time, order and link from the first half.
- `agentfly/recorder/app.py` `apply_rules`: rules and answers unchanged; after `decide` the record goes through `step_merger.join`. An update keeps the order number (`next_step` not bumped) and is re-sent to memory, Neo4j and SQLite, which overwrite by step id.
- `agentfly/recorder/memory.py`: `_Session.replace` / `MemorySteps.replace_from_record` swap the step, move the counts and keep the marking step. `MemorySteps.clear()` also clears the merger, so tests and the lifespan that reset memory cannot leave stale merge state.
- `tests/test_localstore.py`: flaky test fixed (`local_store.flush()` before the history read). I checked every other `/api/sessions` read in `tests/`; the rest either flush (directly or through `listed()`) or read an empty store.
- SPEC.md § 8 "Duplicates" and AGENTS.md "Hook facts" and "Testing" state the 3.25.9 findings.

### Review
A second-opinion pass (fresh reviewer) found the stale-merger-state risk in tests that call `memory_steps.clear()` without the lifespan (fixed), the `//` path case that `normpath` keeps (fixed), and confirmed the history "marked" gap.

### Gaps outside the card
- History "marked" (see Needs owner). Pinned by `test_an_edit_that_began_with_a_secret_read_is_an_edit_step`.
- Edit tools other than `Write` (SPEC lists `StrReplace` and `Delete`) are not treated as writes, so their id-less `afterFileEdit` stays a separate step.
- An id-less `beforeReadFile` can join the stale Read entry of a create within 5 s (that Read fires no `beforeReadFile`). Only affects clients that send no ids (3.24.12).
- Merge state is lost on restart; saved duplicates are not re-merged; no MCP path fallback; the page code is untouched.
- `fake_agent.py` replay against port 8787 was not run (the capture fixture replay covers the same path).

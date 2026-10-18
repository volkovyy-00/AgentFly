# V2c: One step per action: merge by `tool_use_id`, path fallback for id-less reads and edits
Status: done (as of 2026-10-18 20:00)
Result: Hooks of one action are now one step on the page, in history and in the Neo4j copy. Id match for every kind; path fallback for id-less reads and edits. Hook answers unchanged. Known gap: history "marked" for an edit that began with a secret read.
Evidence: full check 3 runs in a row, each 2161 passed, 5 skipped; ruff check and format clean. New tests/test_step_merge.py (28), tests/test_memory.py replace tests, live Neo4j test (skipped here). Commit: see git log on ag-v2c-step-merge.
Needs owner: History "marked" ignores an `edit` step that began with a secret read (the rules do mark the chat). Fixing needs a `marked` column (SPEC §4). Recommended: accept now, add the column in a later card.
Details: see "## 2026-10-18 20:00" below.

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

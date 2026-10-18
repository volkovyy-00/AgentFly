# V2c · One step per action: merge by `tool_use_id`, path fallback for id-less reads and edits

You are a worker on card V2c in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v2c-step-merge. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v2c-step-merge only, the lead merges.

**Summary.** One agent action often fires two Cursor hooks (a general `preToolUse` and a specific one such as `beforeShellExecution` or `beforeReadFile`), so the live trail and the history show it twice. Make each action one step, without changing what any hook answers.

**Written against:** a3d1abd (2026-10-18), plus F6 once merged.

**What was observed (2026-10-18, owner's hook log, Cursor 3.25.9 unless noted; counts only)**
- `beforeShellExecution` carried the same `tool_use_id` as its `preToolUse` Shell in 34 of 34 pairs (one on 3.24.12), and `beforeReadFile` matched its `preToolUse` Read in 28 of 28; all 59 read paths were absolute.
- On Cursor 3.24.12 `beforeReadFile` had no `tool_use_id` (3 of 3); there it arrived 0.2–0.8 s after its `preToolUse` Read, same chat, in order, also for two parallel reads.
- Capture (`docs/spikes/V2c-capture.md`): an edit fires `preToolUse` Read and Write under one id; `afterFileEdit` has no id and fired for a create only; parallel reads' halves returned in reverse order.

**References**
- `docs/DECISIONS.md` § D9, note "Merge rule (owner, 2026-10-18…)": the approved rule; this brief does not restate it all.
- `agentfly/recorder/app.py` § `apply_rules`: every event takes a new order number from `session.next_step` and is sent to memory, Neo4j and SQLite.
- `agentfly/recorder/store.py` § `_merge_step` (`SET` overwrites `tool`, links only ever added) and § `build_step_record`; `agentfly/recorder/localstore.py` § `_write` (`INSERT OR REPLACE` on session and order).
- `agentfly/recorder/memory.py` § `_Session` (its `append`): counts kind and verdict once, when a step is added, and sets the marked step.
- SPEC.md § 8 "Duplicates" and AGENTS.md "Hook facts" (S1/S2 line): both still say `beforeReadFile` has no `tool_use_id`.

**Scope**
- Events of one chat (`conversation_id`) with the same `tool_use_id` form one step, for every event kind, however many there are. Id-less fallback, same chat and normalised (`posixpath.normpath`) absolute path, within 5 s: a `beforeReadFile` joins the oldest unpaired `preToolUse` Read; an `afterFileEdit` joins the latest `preToolUse` Write. The waiting list is in memory only, expires and holds at most 32 per chat (oldest dropped). No pair: separate steps, as today.
- The second half updates the existing step (same order number, same step id); nothing is renumbered or re-linked. The merged step takes file and command from the specific event and is kind `edit` if any half writes (`preToolUse` Write or `afterFileEdit`), else the specific event's kind; its verdict is the strictest among gate events only (blocked > warned > highlighted > allowed; `afterFileEdit` never raises it), and it is marked when either half marked.
- Rules still decide every event on its own; hook answers and their timing do not change.
- Touches: `agentfly/recorder/` (app, memory, store, localstore), their tests, SPEC.md § 8 "Duplicates", AGENTS.md "Hook facts" and "Testing".
- Not included: a path fallback for MCP, a live MCP test, saving the waiting list across a restart, re-merging duplicate steps already saved, the page's UI code.

**Acceptance criteria**
- A replayed `preToolUse` + `beforeShellExecution` pair, and a `preToolUse` Read + `beforeReadFile` pair with one `tool_use_id`, each show as one step in `GET /api/steps`, in history (`GET /api/sessions/{id}/steps`) and (with the live Neo4j test) as one Step node with both halves' links.
- An id-less `beforeReadFile` 0.3 s after its `preToolUse` Read gives one step; one 6 s later, on another path, or in another chat gives two; an id-less `afterFileEdit` 0.5 s after its `preToolUse` Write gives one step, likewise; two id-less reads of one path pair with that path's two `preToolUse` Reads oldest first; a 33rd waiting Read drops the oldest, which then stays its own step.
- A merged step shows the specific event's kind and file or command, the strictest gate verdict and its read's marked state on the page and in history; page counts count it once; an `afterFileEdit` never turns an allowed edit into blocked.
- Every hook answer for a replayed session is byte-identical with and without the merge, and a made-up MCP pair with one `tool_use_id` gives one step.
- The capture in `docs/spikes/V2c-capture.md`, replayed as a fixture, gives its five expected steps, the create and the edit each one `edit` step; SPEC § 8 "Duplicates" and AGENTS.md "Hook facts" state the 3.25.9 findings.

**Dependencies:** F6 merged.

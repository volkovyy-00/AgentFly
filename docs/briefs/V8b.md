# V8b · Recorder fields for the Why card and health strip

You are a worker on card V8b in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v8b-recorder-fields. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v8b-recorder-fields only, the lead merges.

**Summary.** The live page already has places for the rule's text, the exact messages sent to Cursor and the time of the last hook, but the recorder does not send them yet, so the Why card and the health strip show less than they could.

**Written against:** b7a635b (2026-10-19).

**References**
- `ui/src/graph/snapshot.ts` § `parseStep` extras and `ui/src/trail/useTrail.ts` § `parseHealth`: the names and types the page reads (`rule_text`, `user_message`, `agent_message` as strings; `last_hook_at` as an ISO date string; `offline_guard_count`, which `/health` already sends since V2b). The page hides each one while it is absent.
- `ui/src/trail/useTrail.ts` § `useTrail` comment: the page sends `?limit=1` each poll only because `GET /api/steps?all=1` has no `marked_order`.
- `agentfly/recorder/app.py` § `apply_rules`, § `health`; `agentfly/recorder/rules.py` § `deny_messages`: where the answer and its messages are made. `agentfly/recorder/memory.py` § `_step_dict`, § `MemorySteps` (its `snapshot`): the step shape and the `?all=1` body.
- `agentfly/recorder/merge.py` § `Joined` (its `merged`): two hooks of one action become one step showing the strictest half's verdict and rule; on a tie the earlier half stays (V2c).
- SPEC.md § 4 ("the message is the rule's own text, which is not a secret") and § 6 "The Why card"; HOOKS.md "Server (this stage)" (`/health`) and "The page (`ui/` + memory API)" (`/api/steps`).

**Scope**
- Each step a rule fired on carries `rule_text` (that rule's message); it also carries `user_message` and `agent_message` exactly as the hook answer for it sent them, and not when the answer sent none (today: a plain allow for a warned step). A merged step carries those of the answer whose verdict it shows. `/health` adds `last_hook_at` (UTC, ISO 8601, the last `/hook` request that passed the token check; `null` before the first since start). `GET /api/steps?all=1` adds `marked_order`.
- These live in process memory only: no new column in the local store or Neo4j, SPEC § 4's stored list unchanged.
- Touches: `agentfly/recorder/` (app, memory, store's step record, merge if needed), their tests, HOOKS.md (`/health`, `/api/steps`), AGENTS.md "Testing".
- Not included: the page (it reads these already; dropping its `?limit=1` request is a later UI change), the `highlighted` verdict and warn answers (V5b), these fields in `/api/sessions` (V9), HOOKS.md's missing `/api/sessions` contract.

**Acceptance criteria**
- After the `fake_agent.py` demo replay (README → `.env` → curl to ntfy.sh), the blocked step on `/api/steps` has `rule_text` equal to R1's message and `user_message`/`agent_message` equal byte-for-byte to the deny answer the hook client got; allowed steps have none of the three keys.
- In watch-only mode (switched on in process by tests; no runtime switch exists, owner 2026-10-19), the warned step has `rule_text` and neither message key, and its answer is still a plain allow.
- A `preToolUse` (allowed) and a `beforeShellExecution` (blocked by R1) with one `tool_use_id`, in either order, are one step carrying the deny's messages; two halves of one id blocked by different rules (R0 on a `preToolUse` naming a guard path, R1 on the shell) give a step whose `rule`, `rule_text` and messages all name the earlier half's rule (owner 2026-10-19).
- `/health` sends `last_hook_at: null` after start, a UTC time within a second of the request after a hook, and no change after a request with a wrong token; `offline_guard_count` is unchanged.
- `?all=1` sends `marked_order` equal to what `?limit=1` sends, `null` when unmarked; without `all` or `limit` the body is `{session, steps}` as today.
- Hook answers are byte-identical to today; `history.db` has the same columns and Neo4j step nodes the same properties; no route is added.

**Dependencies:** V6b ✅ (a9b753f). Runs alongside V3c (shared: AGENTS.md "Testing" only).

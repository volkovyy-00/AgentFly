# V6b · History shows which chats were marked, and by which step

You are a worker on card V6b in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v6b-history-mark. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v6b-history-mark only, the lead merges.

**Summary.** History should say a chat was marked whenever the rules treated it as marked, and name the step that marked it, instead of guessing from the saved steps.

**Written against:** fb72286 (2026-10-19).

**What was observed (2026-10-19, V2c merge)**
- A Read and Write of `.env` under one `tool_use_id` is now one `edit` step. The live page says that step marked the chat (`marked_order` 1); `GET /api/sessions` lists the chat as not marked.
- History guesses "marked" from read and shell steps with a sensitive file, so a chat marked only through a linked chat (D21: a subagent of a marked chat, or a parent marked by its subagent) is never shown as marked.

**References**
- `agentfly/recorder/localstore.py` § `SESSIONS_QUERY`: today's guess; § `_SCHEMA` (only `CREATE … IF NOT EXISTS`, no migration yet) and § `session_steps`: the tables and the per-session steps answer. A merged step is rewritten whole (`_UPSERT_STEP`), so a later half must not clear its flag.
- `agentfly/recorder/app.py` § `apply_rules`: `store.apply_mark` returns `marks`, true only on the event whose own read or command marks the chat (links are resolved first); memory keeps the first such step as the marking step.
- `agentfly/recorder/sessions.py` § `effective_marked`: what the rules count as marked (itself, the 30-minute window, or a linked chat).
- `tests/test_step_merge.py` § `test_an_edit_that_began_with_a_secret_read_is_an_edit_step`: its comment names today's gap (history is not asserted).
- SPEC.md § 4 table: what is stored; the two new items go there.

**Scope**
- Store, for each chat, whether the rules ever counted it as marked, and for each step whether it marked the chat (owner 2026-10-19). `/api/sessions` uses the first; `/api/sessions/<id>/steps` names the marking step the way `/api/steps` does (`marked_order`).
- A `history.db` written before this card opens without loss; its old rows keep today's guessed value.
- Touches: `agentfly/recorder/` (localstore, store, app, sessions if needed), their tests, SPEC § 4, AGENTS.md "Testing".
- Not included: the page (V9), the Neo4j copy, V8b's step fields, re-deriving old rows, edit tools other than `Write`.

**Acceptance criteria**
- After a Read+Write of `.env` with one id, `/api/sessions` lists the chat as marked and its saved steps name that step as the marking one, also after a recorder restart.
- For `cat .env`, a `beforeReadFile` of `.env`, a lone Write of `.env` (does not mark under R1) and a read of `.env.example`, history's marked flag and marking step equal what `/api/steps` reports.
- A subagent of a marked chat, a parent marked through its subagent (links in either order) and a chat in the 30-minute workspace fallback are listed as marked, with no marking step; a chat in another workspace is not.
- A `history.db` from main at fb72286 with saved sessions opens, keeps every row, and lists the same marked flags as before; the first `/api/sessions` read after the upgrade answers 200.
- Hook answers are unchanged; nothing new is stored but the two yes/no items, which SPEC § 4 lists; the route whitelist test is unchanged.

**Dependencies:** V2c ✅ (fb72286). Runs alongside V3b (shared: SPEC.md, different sections, and AGENTS.md "Testing"); V8b starts after this merges (both change the step record).

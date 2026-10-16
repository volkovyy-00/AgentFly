# V2b · Hardened hook client: agent argument, stripping, offline guard, duplicates

You are a worker on card V2b in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v2b-hook-client. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v2b-hook-client only, the lead merges.

**Summary.** Make the hook client safe on its own: it knows which agent called it, never lets file, edit or output content leave the machine, keeps blocking risky sends while the recorder is down, and shows a shell or tool call that fires two hooks as one step.

**Written against:** b7f7192 (2026-10-16); start from main after V2 has merged.

**References**
- `SPEC.md` § "The hook client (D5, D18)", § "Stripping, before anything else", § "Duplicates" and § "The answers" — the client's contract.
- `SPEC.md` § "9. When the recorder is down" — the offline guard, what it denies and allows, and its accepted cost.
- `agentfly/hook_client.py` (today `hooks/hook.py`) § `sanitize` — replaces all of `tool_input` with `<omitted>`, so the recorder cannot see which file a Write targets, and leaves `afterShellExecution` `output` in place; § `allow_fail_open` — today's plain allow when the recorder is down.
- `docs/spikes/S1-global-hooks.md` § "Key names (never values), from the stub's log" — real field names on Cursor 3.24.12; `tool_use_id` arrives only on `preToolUse` and `beforeShellExecution`.

**Scope**
- Starts at: V2's package layout, client unchanged.
- Touches: `agentfly/hook_client.py`, the recorder's hook intake and `/health`, `tests/**`.
- Tests and manual runs use a temporary HOME and a port other than 8787 (the client gets a port override for tests; the default stays 8787); never touch the real `~/.config/flightrecorder` or `~/.cursor`.
- MCP: S1 never saw a real `beforeMCPExecution` payload, so build from Cursor's documented fields, keep only the server name and tool name (never its `command` or `url`), and say in the report that it is unverified.
- Not included: registering events in Cursor and the bundled Python (V3); the recorder's rule normalisation and R0 (V5) — the guard keeps its own word-level matcher; the page (`ui/**`); the per-chat mark kept by the client through an outage (SPEC § 9, v1.1). Duplicate file reads (`preToolUse` Read plus `beforeReadFile`, no shared id) are proposed, not built.

**Acceptance criteria**
- `agentfly-hook cursor <event>` answers as the client does today; `agentfly-hook <unknown agent> <event>` prints allow JSON, exits 0 and warns on stderr; empty or malformed stdin still prints valid JSON and exits 0.
- A marker string planted in `beforeReadFile` content, `afterFileEdit` edits, `afterShellExecution` output, a `preToolUse` Write's `content`, Grep's `pattern`, Shell's `command` and a `beforeMCPExecution` call's `tool_input` never appears in the hook log, stderr or the request body; the Read, Write and Grep `file_path` and the MCP server and tool names still arrive.
- With no recorder listening, or one that does not answer in time, 100 calls per event all print valid JSON and exit 0, and each guard decision is logged; `/health` reports their count as `offline_guard_count` once the recorder is back.
- Offline, every outbound command SPEC § 9 lists (bare, and wrapped in `bash -c`, `env` or `sudo`) and a command naming a guard path are denied with "agentfly start" in the message; `ls`, `curl localhost:8000/health` and `curl http://192.168.1.10` are allowed; an unparseable command is denied only if its raw text names a listed tool.
- A `preToolUse` call and a `beforeShellExecution` call with the same `tool_use_id` show as one step in `/api/steps`.
- Copied alone into an empty folder and run with `python -I -S`, the client passes the checks above, and with the recorder up 95 % of 200 calls finish under 50 ms; the report states the wait budget chosen for the recorder, measured with it up and slow.
- The report proposes a merge key for duplicate file reads, with fixture evidence for why it is safe (manual).

**Dependencies:** V2 merged.

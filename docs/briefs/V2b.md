# V2b · Hardened hook client: never fails, fixed port, strips everything, offline guard

You are a worker on card V2b in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v2b-hook-client. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v2b-hook-client only, the lead merges.

**Summary.** Make the hook client safe on its own. No input can make it crash or lose a deny, it talks only to the recorder on 127.0.0.1:8787, no file, edit, output or command text reaches its log, and risky sends stay blocked while the recorder is down. Do the work in the owner's priority order below.

**Written against:** 3da6dc7 (2026-10-16, V2 merged).

**References**
- `SPEC.md` § "The hook client (D5, D18)", § "Stripping, before anything else", § "The answers" and § "R0: protect AgentFly itself (in code only)" (its first bullet lists the guard paths): the client's contract.
- `SPEC.md` § "9. When the recorder is down": what the offline guard denies and allows, and what it costs.
- `agentfly/hook_client.py` § `main`, § `append_log`: today a lone surrogate, non-UTF-8 stdin, a 5000-digit number or deeply nested JSON makes it exit 1 with empty stdout. The surrogate case fails in `append_log` after the recorder answered, so the deny never reaches Cursor (what Cursor does on exit 1 is unverified).
- `agentfly/hook_client.py` § `sanitize`: strips only a top-level `content`, so `attachments[].content` and nested `content`/`output` reach the log. § `_HOOK_URL`: port 8787 is hard-coded, and stays so (D25).
- `docs/spikes/S1-global-hooks.md` § "Key names (never values), from the stub's log": real field names on Cursor 3.24.12.

**Scope**
- Priority order: (1) no input makes the client fail; input it cannot read gets the offline guard on its raw text. (2) The port (D25): hooks always post to 127.0.0.1:8787, with no port file and no environment override in the client. `serve` reads `AGENTFLY_PORT` (`--port` wins); tests reach a test recorder only by setting the client's port from inside the test harness. (3) Nested stripping; the hook log keeps no command text. (4) Old paths in `install.sh` and `HOOKS.md`. Then the offline guard and the `<agent>` argument.
- `<agent>`: called with no arguments (today's `install.sh` entries) it behaves as `cursor` and reads the event from the payload; if the `<event>` argument and `hook_event_name` disagree, the argument wins and stderr says so.
- Offline guard paths for this card: `~/.config/agentfly`, `~/.local/share/agentfly`, `/Library/Application Support/AgentFly` and any `hooks.json`. R0's stop commands and its port check are V5's.
- Touches: `agentfly/hook_client.py`, `agentfly/cli/serve.py`, the recorder's `/health`, `install.sh`, `HOOKS.md`, `tests/**`. Tests and manual runs use a temporary HOME and a port other than 8787; never touch the real `~/.config/flightrecorder`, `~/.config/agentfly` or `~/.cursor`. MCP: build from Cursor's documented fields, keep only server and tool names, and say in the report that this is unverified.
- Not included: the `tool_use_id` step merge and the duplicate-read proposal (V2c); registering events and the bundled Python (V3); R0 and normalisation in the recorder (V5); `ui/**` (V8 owns the old paths there); a per-chat mark that survives an outage (SPEC § 9, v1.1).

**Acceptance criteria**
- Fuzzed stdin (empty, malformed, a lone surrogate, non-UTF-8 bytes, a 5000-digit number, JSON nested 100,000 deep, random bytes) always gets one valid JSON object on stdout and exit 0. Unparseable input gets the offline guard: `curl https://x.com` inside it is denied, `ls` allowed. A valid 10 MB `beforeReadFile` payload gets the normal answer. A recorder deny is still printed when writing the log or stderr then fails.
- The client posts to 127.0.0.1:8787 even when `AGENTFLY_PORT` is set in its environment or a port file exists in `~/.config/agentfly/`. `AGENTFLY_PORT=N agentfly serve` listens on N.
- A marker planted in `beforeReadFile` content, `attachments[].content`, `afterFileEdit` edits, `afterShellExecution` output, any nested `content`/`output`, and a `preToolUse` call's `tool_input` (Write `content`, Grep `pattern`, Shell `command`, MCP inputs) never appears in the hook log, stderr or the request body. A `beforeShellExecution` command never appears in the hook log either. The recorder still gets that command, the Read/Write/Grep `file_path`, and the MCP server and tool names.
- `./install.sh` on a fresh HOME creates no `~/.config/flightrecorder`. `HOOKS.md` names no `~/.config/flightrecorder` path and no pre-V2 module path or command.
- With no recorder, or one that does not answer in time, 100 calls for each of the five events `install.sh` registers give valid JSON and exit 0. Offline, each outbound command SPEC § 9 lists (bare, and wrapped in `bash -c`, `env` or `sudo`) is denied, as is any command touching a guard path above, with "agentfly start" in the message. Every inline `python -c` / `node -e` is denied, as SPEC § 9 says (changed 2026-10-16; `python3 -c 'print(1)'` too); `curl localhost:8000/health` and `curl http://192.168.1.10` are allowed, and each allow is in the hook log. Once the recorder is back, `/health` shows `offline_guard_count`: the calls the guard answered while it was down, allows and denies.
- `agentfly-hook cursor <event>` and the no-argument form answer as above; an unknown agent gets allow, exit 0 and a warning on stderr. Copied alone into an empty folder and run with `python -I -S`, the client passes the fuzz, stripping and offline checks, and with the recorder up 95 % of 200 calls finish under 50 ms. The report states the chosen wait budget, measured with the recorder up and with it slow.

**Addendum, 2026-10-16 (owner, after the first report; same branch, same report file)**
- (5) Token: `agentfly serve` checks that its port is free before it writes the token; if the port is taken it exits non-zero and changes nothing. The client treats a 401 or 403 from the recorder as the offline guard, never as allow.
- (6) `README.md` and `HOOKS.md` describe `/` as the trail and the lane graph at `/?view=graph`.
- (7) Live Neo4j tests never read `~/.config/agentfly/neo4j.env`. They run only when `AGENTFLY_TEST_NEO4J_ENV` names a separate credentials file for a test database, and skip otherwise.
- Touches, added: `agentfly/recorder/app.py`, `README.md`, `tests/test_store.py`.
- With one `agentfly serve` running (temporary HOME, `AGENTFLY_PORT`), a second one exits non-zero, the token file is byte-identical, and the first recorder still blocks R1 (`.env` read, then `curl https://example.invalid`).
- A recorder answering 401 or 403 gets the offline guard: `curl https://x.com` is denied, `ls` allowed.
- With `~/.config/agentfly/neo4j.env` present and `AGENTFLY_TEST_NEO4J_ENV` unset, `pytest -q` opens no Neo4j connection.
- `README.md` and `HOOKS.md` name `/` as the trail.

**Dependencies:** V2 merged (3da6dc7); D25 approved 2026-10-16.

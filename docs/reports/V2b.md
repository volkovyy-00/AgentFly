# V2b: Hardened hook client: never fails, fixed port, strips everything, offline guard
Status: done (as of 2026-10-16 12:00)
Result: All acceptance items work except 95 % of calls under 50 ms: measured median 69 ms, p95 99 ms with the recorder up; bare `python -I -S` is 36 / 56 ms on this machine. Wait budget stays 0.5 s (a silent recorder costs ~570 ms per call).
Evidence: code 1916e0e on ag-v2b-hook-client; `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` = 483 passed (296 before); new tests in tests/test_hook_client.py, test_offline_guard.py, test_serve_port.py, test_install_docs.py.
Needs owner: SPEC §9/D4 say the guard denies every inline `python -c`/`node -e`; the brief allows `python3 -c 'print(1)'`. I followed the brief (deny only if the text mentions http). Fix SPEC §9, or tell me to deny all one-liners.
Details: see "## 2026-10-16 12:00" below.

## 2026-10-16 12:00

### What changed
- `agentfly/hook_client.py` (rewritten, stdlib only, one file):
  - Reads stdin as bytes with `os.read`; anything that is not a JSON object (empty, malformed, lone surrogate bytes, non-UTF-8, a 5000-digit number, JSON nested 100,000 deep, random bytes) gets the offline guard on its raw text and a valid JSON answer. A catch-all around the whole call runs the guard on the raw bytes it already holds, so a deny is not lost if stripping or printing fails.
  - Output is ASCII-only JSON, one line, exit 0. Log and stderr writes cannot change the answer (tested with an unwritable log folder and closed stderr, closed stdin, closed stdout). stderr messages carry only exception type names.
  - Port: `_HOST`/`_PORT` hard-coded to 127.0.0.1:8787 (D25). No environment variable, no port file; a source test fails if `environ`, `getenv` or `AGENTFLY_PORT` ever appear. Tests set the module attributes from `tests/client_harness.py`.
  - Transport: raw `_socket` POST, one total deadline (0.5 s) for connect and answer. A missing token, refused connection, timeout, non-200 status, bad JSON or an unknown `permission` all mean "recorder did not answer" and the offline guard answers.
  - Stripping, at every depth and without recursion: `content`, `output`, `edits` are removed (top-level `afterFileEdit.edits` becomes `<N edits>`); `tool_input` is reduced to a string `file_path`; MCP events (`beforeMCPExecution`, and `preToolUse` whose tool name starts with `mcp`) keep an allowlist (names, ids, cwd, workspace roots, `mcp_server_name`, `tool_name`) and drop `tool_input`, `url`, `mcp_server_url`, `command`. `command` stays in the request body only for `beforeShellExecution` and is never written to the hook log. Lone surrogates become U+FFFD before sending; nesting deeper than 24 levels is cut.
  - Offline guard (SPEC §9): scans every word (basename, case-folded), so `bash -c`, `env`, `sudo`, `timeout`, `xargs` need no unwrap list. Denies `gh`, `aws`, `git push`; `curl wget nc scp ssh rsync` unless every host is local/private (no host found = deny); `python/python3/node` when the text mentions `http`; any command naming `.config/agentfly`, `.local/share/agentfly`, `/Library/Application Support/AgentFly` or `hooks.json`. An unparseable command is denied only if its raw text names a tool. Deny text is in both messages, says `agentfly start`, and the agent message adds the "Do not retry..." sentence. Every guard answer is logged with `offline: true` and a `reason`; allows are logged too. It acts on `beforeShellExecution` commands only.
  - `<agent> <event>`: no arguments acts as `cursor`; if the argument and `hook_event_name` differ the argument wins and stderr says so; an unknown agent gets allow, exit 0 and a warning, without reading stdin.
  - The Checkpoint A test rule T0 (already disabled) is removed from the client.
- `agentfly/cli/serve.py`: `--port` default is now `AGENTFLY_PORT`, then 8787; a bad value exits 2 with a message. Only `serve` reads the variable.
- `agentfly/recorder/app.py` (`/health` only): `{"ok": true, "offline_guard_count": N}`. N is the size of `~/.local/share/agentfly/logs/offline-count`, to which the client appends one byte per call it answered while the recorder was down. The recorder never deletes the file, so the count is "since the file was last removed". It is advisory (user-writable file; file-path guarding is V5). `tests/test_package.py` expects the new body.
- `install.sh`: no `~/.config/flightrecorder`, no repo-local `logs/` folder, and the messages name the real hook log. `HOOKS.md`: all old paths and pre-V2 module commands replaced; it now describes the stripping, the offline guard and `<agent> <event>`. `hooks.json` entries and the shim are unchanged (V3).

### Decisions I made (flagging for the lead)
- The `python -c` rule (see Needs owner above).
- The guard is a flat word scan, a superset of `rules.is_outbound_send`: it denies `echo curl https://x.com`, `timeout 5 curl x`, `xargs curl x` too. `ipaddress.is_private` treats `169.254.169.254` and `0.0.0.0` as local, same as the recorder rule.
- A recorder 401, 500 or garbage answer counts as "down" (never a plain allow).
- A `preToolUse` Shell command is not guarded offline: its text is stripped, and `beforeShellExecution` fires for the same action.
- The offline count is the file size, never reset by the recorder (no read-then-delete race). A reset would belong with `agentfly wipe`.

### Measurements (this machine: x86_64 Mac, Python 3.12.11; the real client file run as a script with `python -I -S`, port edited in a copy to a non-8787 recorder)
| Case | median | p95 | max |
|---|---|---|---|
| recorder up, 200 calls | 68.6 ms | 98.9 ms | 171.6 ms |
| bare `python -I -S -c pass`, 200 calls | 35.7 ms | 55.7 ms | |
| recorder silent, budget 0.5 s, 10 calls | 570.6 ms | | 582.2 ms |

- The 50 ms / 95 % target is not met, and cannot be on this machine: the bare interpreter alone has a p95 of 38-56 ms. An earlier quieter run: bare 29 / 38 ms, client 56 / 93 ms. Breakdown of the client's ~27 ms over bare (quiet run): `json` + `_socket` + `time` imports ~14 ms, module load ~6 ms, compiling the 450-line script on every run ~8 ms (a script launched by path never uses a .pyc). The recorder itself answers in ~2 ms (warm connection).
- I used `_socket` and raw HTTP instead of `http.client` (~73 ms to import) or `urllib.request` (~89 ms). A further ~10 ms is possible by dropping `json` for `_json` plus a hand-written encoder, which I did not do: it trades robustness for a target the interpreter floor already blocks. The bundled Python and a pre-compiled entry (V3, packaging) are the real levers.
- A per-hook fsync in `SessionStore.put` (`agentfly/recorder/sessions.py`) runs inside the request handler; it is a latency floor outside this card.
- Wait budget: 0.5 s kept. With the recorder up the answer takes a few ms, so the budget is never reached; with it silent a call takes ~0.57 s, inside the 1 s `hooks.json` timeout with ~0.4 s to spare (startup under load reached 170 ms).
- `tests/test_hook_client.py::test_latency_with_the_recorder_up` only asserts a loose bound (median < 150 ms) so it does not flake; the numbers above are the real measurement.

### Check output
```
$ uv run ruff check . && uv run ruff format --check . && uv run pytest -q
483 passed, 1 warning in 73.27s
```
Baseline before the card: 296 passed.

### Gaps outside my files (not changed)
- `AGENTS.md` "Hook client rules" and "Hook facts" still say the client fails open and name `.cursor/hooks.json` helper paths; SPEC §8/§9 and the Hook facts need the V2b facts (fixed port, MCP names, stripping, `offline-count`). `README.md` may still name old paths (not checked, outside the touch list).
- `fake_agent.py` still looks for the word "unreachable" on stderr (kept in the client's message); with the guard, a `curl` step is now denied while the recorder is down, so its "server down" scenario no longer fails the way HOOKS.md used to say (HOOKS.md updated).
- The recorder parses a lone surrogate sent as a `\udXXX` escape without complaint; the client now replaces them, but a direct caller could still send one. A recorder-side crash would surface to the client as a guard answer.
- Offline guard on file-tool paths (Write to a guard path), R0's stop commands and its port check are V5. The `tool_use_id` merge and the duplicate-read proposal are V2c. `hooks.json` command quoting, `python -I -S` in the registered command and the bundled Python are V3.
- MCP field names follow Cursor's current docs (cursor.com/docs/hooks: `mcp_server_name`, `tool_name`, `tool_input`, `url`, `mcp_server_url`, `command`). Not verified on Cursor 3.24.12 or against a real MCP call. The docs also say a non-zero exit other than 2 fails open and invalid JSON blocks, so before this card a crash was a silent allow rather than a lost deny; the guard path makes that deny stick.
- The tests start real recorders and a stub on free ports under a temporary HOME; none uses 8787 or the real `~/.config/agentfly`, `~/.config/flightrecorder` or `~/.cursor`.

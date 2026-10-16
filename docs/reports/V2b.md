# V2b: Hardened hook client: never fails, fixed port, strips everything, offline guard
Status: done (as of 2026-10-16 14:30)
Result: Addendum items 5-8 and the D21 test are done: a second serve fails and changes nothing, 401/403 get the guard, docs say `/` is the trail, live Neo4j tests need AGENTFLY_TEST_NEO4J_ENV, every inline one-liner is denied. Latency still misses 50 ms (median 53 ms, p95 69 ms).
Evidence: commit cd465d8 on ag-v2b-hook-client; `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` = 552 passed, 4 skipped (the live Neo4j tests); main merged twice (f2941b6, 51c8bff).
Needs owner: none
Details: see "## 2026-10-16 14:30" below.

## 2026-10-16 14:30

Commit cd465d8. Merged `main` into `ag-v2b-hook-client` first (f2941b6: V8 and the addendum; 51c8bff: D21 A and the updated brief; both clean). Files changed in this round: `agentfly/cli/serve.py`, `agentfly/hook_client.py`, `README.md`, `HOOKS.md`, `tests/test_serve_port.py`, `test_offline_guard.py`, `test_hook_client.py`, `test_install_docs.py`, `test_store.py` and this report (`agentfly/recorder/app.py` needed no change).

### (5) `agentfly serve` and the token
- Cause: uvicorn runs the app's startup, which writes the token, *before* it opens its socket (uvicorn docs: "Don't open socket until after application startup", 0.11.2; `Server.startup` in the installed 0.54). A second `serve` therefore overwrote the first one's token and only then failed to bind. Before the fix the new test failed on exactly that: the token differed.
- Fix, in `agentfly/cli/serve.py` (not `app.py`; the app was not the problem): `bind_port` takes 127.0.0.1:PORT before anything else; if it is taken, `serve` prints "port N is already in use ... nothing was changed" and exits 1. The bound socket is handed to uvicorn (`Server.run(sockets=[sock])`), so nothing can take the port between the check and the start.
- The client already sent every non-200 answer (a 401 or 403 included) to the offline guard. New cases pin it: 401 and 403 with and without an `{"permission": "allow"}` body give a deny for `curl https://x.com` and an allow for `ls`.
- Test (`tests/test_serve_port.py::test_a_second_serve_on_a_taken_port_fails_and_changes_nothing`): temporary HOME and `AGENTFLY_PORT`; the first recorder gets a `.env` read; then a second `serve` exits non-zero and names the port; every file under HOME (size and mtime) and the token bytes are unchanged; the first recorder still denies `curl https://example.invalid` with R1.

### (6) README.md and HOOKS.md
- `/` is the Live Trail, the lane graph is the Graph tab at `/?view=graph` (`/?view=trail` also opens the trail); the mock is `/?mock=1` for the trail and `/?view=graph&mock=1` for the graph. README section 4 is rewritten; the `ui/` row, the GIF caption, HOOKS.md's page section, demo line and checkpoint table follow. Test: `tests/test_install_docs.py::test_readme_and_hooks_md_name_the_trail_as_home_and_the_graph_tab`.

### (7) Live Neo4j tests
- `tests/test_store.py` no longer reads `~/.config/agentfly/neo4j.env` and no longer connects at collection (the old `_neo4j_reachable()` ran `check_db.main()` with the real login at import). The live tests take a module fixture, `neo4j_test_env`, that returns the file named by `AGENTFLY_TEST_NEO4J_ENV` or skips (unset, missing file, the real login file even through a symlink, incomplete file, database unreachable). It connects only when a live test is selected, so `-k 'not live'` never does.
- Tests: `test_only_a_separate_named_file_counts_as_test_credentials`, and `test_database_tests_skip_and_never_touch_the_real_login` in three variants (unset; names the real login file; separate file with a dead port). Each runs a child pytest of the live tests with a HOME whose `neo4j.env` points at a local listener, and asserts all 4 live tests skip and the listener sees zero connections.
- Mistake worth knowing: my first version of that test had "live" in its name, so the child `pytest -k live` selected it and spawned more children (a fork loop). I killed it within minutes, renamed the test, and the processes are gone. Nothing else was affected.
- The 4 live tests have never run against a real database here; they are skipped until the owner names a test-database file.

### (8) One-liners (SPEC §9)
- The offline guard now denies every inline `python -c` / `node -e` (also `-p`, `--eval`, `--print`, combined flags such as `-Sc`, versioned names such as `python3.12` and `nodejs`, bare and wrapped in `bash -c`, `env` or `sudo`), `python3 -c 'print(1)'` included. A one-liner is found by the words right after the interpreter, up to its script or `-m`, so `bash -c 'python3 script.py'`, `python3 -m pytest -p no:cacheprovider` and `node app.js` stay allowed. A command that merely mentions `http` next to an interpreter is still denied.
- Known limit of a word-level scan: a script without a `.py`/`.js` suffix followed by `-c` counts as a one-liner.

### D21 A: the subagent link
- The client sends `parent_tool_call_id` (and `tool_use_id`, `conversation_id`) unchanged. It was only lost on MCP events: the MCP allowlist had no place for it, so a subagent's MCP call arrived without its parent link. Both ids (`parent_tool_call_id`, `parent_conversation_id`) are now in the allowlist.
- Tests (`tests/test_hook_client.py`): `parent_tool_call_id` and the child's own `conversation_id` reach the recorder body unchanged for `beforeShellExecution`, `beforeReadFile`, `afterFileEdit`, `preToolUse` (Write and MCP) and `beforeMCPExecution`, with planted text still absent; the parent's `Task` `preToolUse` keeps `tool_use_id` and a `subagentStart` keeps `parent_conversation_id`, `tool_call_id` and `parent_tool_call_id`. What the recorder does with the link is V5's.

### Measurements (this Mac, quieter than at 12:00; recorder up, real client file with `python -I -S`, interleaved, 200 calls)
| | median | p95 |
|---|---|---|
| bare `python -I -S -c pass` | 29.6 ms | 45.1 ms |
| client, recorder up | 53.4 ms | 69.2 ms |
The 50 ms target is still missed; the owner accepted that until V3 (the bundled Python). The wait budget stays 0.5 s.

### Check output
```
$ uv run ruff check . && uv run ruff format --check . && uv run pytest -q -rs     (AGENTFLY_TEST_NEO4J_ENV unset)
552 passed, 4 skipped (the live Neo4j tests: "AGENTFLY_TEST_NEO4J_ENV does not name a separate test-database credentials file")
```
Not run: `npm --prefix ui ci && npm --prefix ui run check` and the stale-build check; this card changes no `ui/` file.

### Gaps outside my files
- `AGENTS.md` still says Neo4j live tests / `check_db` use the real login, still describes the client as failing open, and the "Hook facts" section lacks D21's `parent_tool_call_id` and the fixed port; the Testing section does not list the new test files. SPEC §8/§9 text for the 401/403 rule and the `offline-count` file is V1b's.
- `.env.example` does not mention `AGENTFLY_TEST_NEO4J_ENV` (outside the touch list; README and HOOKS.md do).


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

### Final verification (after the first commit)
Simplification and an independent audit ran on the finished work; fixes below are in the second commit.
- Simplified: one tokenizer for the guard (no shlex, no `quick` mode, no recursion), one `_append` for the log and the count file, no `ctx` out-parameter, `typing` imported lazily (about 8 ms faster per call: before 83 / 139 ms, after 74 / 122 ms median / p95, interleaved with bare Python at 41 / 61 ms). Tests: shared `client` fixture, one recorder launcher, hoisted helper imports.
- Audit findings fixed: a URL hidden in a flag next to a local host (`curl --url=https://evil.com http://localhost`) was allowed; a payload with no/odd event name or a non-string `command` skipped the guard; `/Library/Application\ Support/AgentFly` and `~/.config//agentfly` were not matched; a tool name at either end of a huge cut-off payload could fall outside the 1 MB window (now head and tail are scanned); `python3.12` and `nodejs` were not treated as interpreters; the payload's event name was echoed to stderr; `tool_output`, `tool_response`, `prompt` and `text` keys are now stripped too. One more found while simplifying: a tool after a written-out `\n` in broken JSON was missed.
- Audit findings dismissed: `curl -H 'Content-Type: ...' http://localhost`, `curl -o out.json http://127.0.0.1` and `rsync -av ./a/ /tmp/b/` are denied offline, but `rules.py` calls them outbound too (same host guess), so the guard matches the recorder.
- Known limits of a word-level guard (SPEC §9 calls it simpler than R0): `c"u"rl`, `cu\rl`, `c=curl; $c url`, and `cd ~/.config && cat agentfly/token` pass it. `unreadable` input and an internal error are answered by the guard but are not counted in `offline_guard_count` (only calls where the recorder did not answer are). File-tool paths are not guarded offline (V5).
- Not applied: a per-event allowlist for `sanitize` (would change which fields the recorder receives).

### Check output
```
$ uv run ruff check . && uv run ruff format --check . && uv run pytest -q
503 passed, 1 warning in 69.88s
```
Baseline before the card: 296 passed. (483 at the first commit.)

### Gaps outside my files (not changed)
- `AGENTS.md` "Hook client rules" and "Hook facts" still say the client fails open and name `.cursor/hooks.json` helper paths; SPEC §8/§9 and the Hook facts need the V2b facts (fixed port, MCP names, stripping, `offline-count`). `README.md` may still name old paths (not checked, outside the touch list).
- `fake_agent.py` still looks for the word "unreachable" on stderr (kept in the client's message); with the guard, a `curl` step is now denied while the recorder is down, so its "server down" scenario no longer fails the way HOOKS.md used to say (HOOKS.md updated).
- The recorder parses a lone surrogate sent as a `\udXXX` escape without complaint; the client now replaces them, but a direct caller could still send one. A recorder-side crash would surface to the client as a guard answer.
- Offline guard on file-tool paths (Write to a guard path), R0's stop commands and its port check are V5. The `tool_use_id` merge and the duplicate-read proposal are V2c. `hooks.json` command quoting, `python -I -S` in the registered command and the bundled Python are V3.
- MCP field names follow Cursor's current docs (cursor.com/docs/hooks: `mcp_server_name`, `tool_name`, `tool_input`, `url`, `mcp_server_url`, `command`). Not verified on Cursor 3.24.12 or against a real MCP call. The docs also say a non-zero exit other than 2 fails open and invalid JSON blocks, so before this card a crash was a silent allow rather than a lost deny; the guard path makes that deny stick.
- The tests start real recorders and a stub on free ports under a temporary HOME; none uses 8787 or the real `~/.config/agentfly`, `~/.config/flightrecorder` or `~/.cursor`.

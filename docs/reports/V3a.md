# V3a: System install: `agentfly init -g` and `agentfly uninstall`
Status: done (as of 2026-10-18 21:10)
Result: init -g, repair, idempotence, merge, uninstall work on the owner's Intel Mac (Cursor 3.25.9). Follow-up done: main merged; the hook client now strips subagentStart `task` (and keeps only ids and names on session events). Manual results unchanged.
Evidence: merge d22f803 plus the follow-up commit on ag-v3a-install; `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` = 1903 passed, 4 skipped; test_a_planted_task_text_in_a_session_event_never_leaves_the_client (3 events).
Needs owner: none. For the lead: R1 can miss "read then curl" when the agent sends both in one step; a missing interpreter fails open (exit 127), not deny-all. Details below.
Details: see "## 2026-10-18 21:10" below.



## 2026-10-18 21:10

### Follow-up from the lead
1. **Merge.** `git merge main` into ag-v3a-install (merge commit d22f803), no conflicts. The one-line conflict in `agentfly/cli/__init__.py` is expected only when V6 lands.
2. **`task` stripped.** `agentfly/hook_client.py` `sanitize`: for `sessionStart`, `sessionEnd` and `subagentStart` the copy sent to the recorder (and logged) is an allowlist, `_SESSION_KEEP`: the common fields (`hook_event_name`, `conversation_id`, `session_id`, `generation_id`, `model`, `cwd`, `workspace_roots`, `cursor_version`, `user_email`, `transcript_path`, `tool_use_id`, `parent_tool_call_id`, `parent_conversation_id`) plus `tool_call_id`, `subagent_id`, `subagent_type`, `is_parallel_worker`. So `task`, and any other free-text field on those events (`additional_context`, `error_message`, nested copies), never leaves the client. An allowlist was chosen over adding `task` to `_STRIP_KEYS`: `task` is too common a key name to drop at every depth in other events, and the allowlist also covers fields Cursor adds later. Side effect: `sessionEnd` fields such as `reason` and `duration_ms` are no longer forwarded; the recorder uses none of them today.
3. **Test.** `tests/test_hook_client.py::test_a_planted_task_text_in_a_session_event_never_leaves_the_client` (for each of the three events): a marker in `task`, `additional_context`, `error_message` and a nested `task` is absent from the request body, the hook log, stderr and stdout; `parent_conversation_id`, `tool_call_id`, `subagent_id`, `subagent_type` and `is_parallel_worker` still reach the recorder.
4. **Check.** `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` = 1903 passed, 4 skipped.

### Lines AGENTS.md should change (not edited, per the lead)
- "Commands": add `agentfly init -g` (one sudo; installs the bundled Python and hook client in `/Library/Application Support/AgentFly/` and merges tagged entries into `/Library/Application Support/Cursor/hooks.json`) and `agentfly uninstall` (our entries first, then the folder). Say that `./install.sh` is development only and makes events arrive twice when `init -g` is also installed. Add: quit and reopen Cursor after `init -g` and after `uninstall`; Cursor reads the system file only at start-up and its Settings → Hooks panel does not list system hooks.
- "Hook client rules": say that session events (`sessionStart`, `sessionEnd`, `subagentStart`) are reduced to an allowlist of ids and names (`task` never leaves the client).
- "Testing": add `tests/test_install_*.py` (hooks-file splice with fuzz, pinned Python download/extract, Cursor version check, install/repair/uninstall flow on a temporary root, CLI and sudo command line) and the session-event strip test above. `tests/test_install_docs.py` also covers README and `install.sh`.
- "Hook facts": the Cursor 3.25.9 facts from the manual check (the 8 enterprise hooks load; the Hooks log lines `Loaded N enterprise hook(s)` / `No enterprise hooks configuration found`; a missing interpreter makes the command exit 127 and Cursor lets the action through).

## 2026-10-18 20:30

### Manual checks (owner's Intel Mac, Cursor 3.25.9; the owner ran the steps, I read the logs)
1. **Cursor loads it.** Cursor's Hooks log: `Enterprise config path: file:///Library/Application%20Support/Cursor/hooks.json` and `Loaded 8 enterprise hook(s) for steps: beforeShellExecution, beforeReadFile, beforeMCPExecution, preToolUse, afterFileEdit, sessionStart, sessionEnd, subagentStart`. On a real `echo hello`, `...hook_client.py cursor preToolUse` and `... beforeShellExecution` ran with `exit code: 0`; events.jsonl recorded `cursor_version: 3.25.9`. The Settings → Hooks panel does **not** list system-level hooks (the owner first read that as a failure and removed the 3.25.9 line; restored). `doctor` should read the Hooks log lines `Loaded N enterprise hook(s)` / `No enterprise hooks configuration found` instead. The 3.25.9 line is now marked verified.
2. **Locked.** Without sudo: `touch .../AgentFly/hook_client.py` Permission denied; `echo x >> .../python/bin/python3.12` permission denied; `echo x >> .../Cursor/hooks.json` permission denied. All installed files are `root:wheel`, none group/other-writable (`find` check).
3. **Password.** After `sudo -k`, `agentfly uninstall` asked for the password (three wrong attempts typed, then accepted). Earlier `init -g` and `uninstall` ran inside sudo's 5-minute cache and asked for nothing, so the message now reads "may ask". Not observed manually: a second `init -g` saying "already installed" (covered by `tests/test_install_flow.py` and the temp-root smoke test).
4. **R1 deny, D22.** Recorder up (no `offline` rows). Sandbox on (`sandbox=true`): 11 chats, each `.env` read followed by a curl: **11 of 11 denied**. Sandbox off: first run 10 chats, only 4 had the curl after the read (all denied); a second run with the read and the curl as two separate messages gave **6 of 6 denied**, so **10 of 10** valid trials denied.
   **Gap for R1 (V5):** when the agent sends the read and the curl in the same step, Cursor may check the curl first (log: `beforeShellExecution` allow, then `beforeReadFile .env`, same `generation_id`). 6 of 10 unsandboxed chats in the first run had only that early shell call and nothing after the read. A curl checked before the read cannot carry the file's content, but "read, then curl is denied" is not reliable when both are issued together.
5. **D24.** With a Claude-format `PreToolUse` allow hook for matcher `Shell` in `~/.claude/settings.json` (Cursor log: `Executing hook 2/2 from claude-user config`, output `permissionDecision: allow`), AgentFly's `beforeShellExecution` still returned `deny` ("Blocked by rule R1...") and Cursor logged `Merged 1 valid response for step beforeShellExecution`. So an allow did not override the R1 deny on the shell gate. One trial. Claude's format has no `beforeShellExecution` event, so this is the closest test. Untested: a foreign allow against an AgentFly `preToolUse` deny. I recommend `doctor` keeps the D24 warning.
6. **Latency** (installed in `/Library`, recorder up, 200 interleaved calls): load average 15, bare bundled Python 31 / 44 ms (median / p95), installed client 60-61 / 76-79 ms (two runs). Quiet machine, temporary root, read-only tree: bare 24 / 28, client 45 / 49-51. Target p95 50 ms met only in the quiet runs. Without stdlib bytecode: 104 / 114.
7. **Uninstall.** Removed `hooks.json` (AgentFly had created it) and then the folder; the empty `/Library/Application Support/Cursor` folder stays (harmless). **Without a Cursor restart** Cursor kept its old hook list and kept calling the removed interpreter: `exit code: 127`, which fails open (the shell command ran, nothing was blocked). After the owner quit and reopened Cursor: `No enterprise hooks configuration found`, no AgentFly mention in the Hooks log, no hook step for the shell command, events.jsonl unchanged. `uninstall`, `init -g` and the README now say to quit and reopen Cursor.

### Findings for the lead
- **Failure modes differ (SPEC §7, D5):** a missing interpreter gives shell exit 127, which Cursor treats as fail-open (observed). A missing client with the interpreter present gives Python exit 2, which denies everything (S2 F1). The install removes entries before files so neither state is left; a plain `brew uninstall`/`uv tool uninstall` leaves the system folder, so it stays guarded.
- **Cursor reads the system file only at start-up** (restart needed after install and uninstall). Hooks log lines to use in `doctor`/D23: `Loaded 8 enterprise hook(s) for steps: ...`, `No enterprise hooks configuration found`.
- Cursor passes Claude-format hooks from `~/.claude/settings.json` as `claude-user config` (plugins as `claude-plugin config`) and merges their responses with ours.
- `sessionEnd` at window close logged `Error: MainThreadShellExec not initialized` once (Cursor shutting down; the command line was correct). Not seen on normal actions.
- A repo-level `.cursor/hooks.json` doubles every event on this Mac (observed: two `preToolUse` rows per action in the AgentFly repo).
- Hardware detection on this Intel Mac: `sysctl -n hw.optional.arm64` = "unknown oid" (exit 1), so the x86_64 archive is chosen; the installed `python3.12` is `Mach-O 64-bit executable x86_64`.

### Final check
`uv run ruff check . && uv run ruff format --check . && uv run pytest -q` = 723 passed, 4 skipped (after the restart-hint change, the 3.25.9 comment update and the Intel-detection test).

### Not run
aarch64 build (Intel Mac); failure paths of `init -g` against the real Cursor; a second `init -g` manually. The sudo hand-off itself was exercised for real (install, repair-free first run, uninstall).


## 2026-10-18 19:10

### What was built
- `agentfly/install/` (new): `layout.py` (the fixed `SYSTEM` paths; tests build a temporary `Layout`), `cursor.py` (exact Cursor version list and the 8 events), `pythons.py` (pin, download, checksum, unpack, lock, byte-compile), `hooks_file.py` (text splice), `records.py` (hash record), `installer.py` (install, repair, uninstall), `elevate.py` (the one `sudo`).
- `agentfly/cli/init.py`, `uninstall.py`, `__main__.py` (new; `python -m agentfly.cli` did not work before, and the sudo re-exec needs it). `agentfly/cli/__init__.py`: one import and two registration lines.
- `install.sh` kept as a development-only wrapper (header and a warning that `init -g` makes every event arrive twice). README "Installation" rewritten. `tests/test_install_docs.py`, `tests/test_package.py` updated.

### Decisions I made (reasons)
- **Python build.** python-build-standalone release 20261013, CPython 3.12.15, `install_only_stripped`, x86_64 and aarch64 (SHA-256 pinned in `pythons.py`, copied from the release's `SHA256SUMS`; I re-hashed the x86_64 download: match). Why: relocatable, same minor version as the project and as V2b's measurements, about 25 MB, and a pinned sum makes a checksum failure real verification. Update path: a new AgentFly release bumps the pin; the next `init -g` sees the recorded archive hash differs and reinstalls. Fetched with `httpx` (approved; follows GitHub's 302).
- **One sudo.** `init -g` first checks Cursor and downloads and verifies the archive as the user (so a bad checksum costs no password and proxies work), then re-runs itself once as `sudo python -I -B -m agentfly.cli init -g`, piping the archive on stdin. Root re-hashes it. Already intact: no password. Only the client or hooks need repair: no download. `uninstall` never looks at Cursor or its version.
- **Entry tag.** Ours = a `command` that starts with the quoted path of the bundled interpreter. I added no extra JSON key, because an unknown key might make Cursor reject the whole file (untested; D23).
- **Events:** the four gates, `afterFileEdit`, `sessionStart`, `sessionEnd`, `subagentStart` (D9 A, D21 A). Timeout 2 s (offline guard answers in about 0.57 s; Cursor's timeout fails open per its docs, not checked on 3.24.12).
- **hooks.json edit by text splice**, so other tools' entries stay byte-identical (acceptance criterion). Every result is parsed again and compared with a plain-data model; an unexpected shape (not an object, duplicate keys, comments) writes nothing. A file with real entries comes back byte for byte after install then uninstall (fuzzed with random whitespace, CRLF, BOM, tabs). Documented edges: an empty array or `{ }` of another tool is normalised, and `"hooks": {}` stays if we had to add it.
- **Stdlib bytecode.** The stripped build ships no `__pycache__` and the user cannot write the tree, so every hook run would recompile `re`/`json`/`enum`. Root runs `compileall` before hashing. Measured below.
- **Smoke test as the user, not root** (`user=SUDO_UID`, no supplementary groups, empty HOME): root can read files the user cannot, and an unreadable client exits 2, which makes Cursor deny everything (S2 F1). The exact registered commands run through `sh -c` for all 8 events before `hooks.json` is touched.
- **Never leave an entry without its client.** First-install failure strips our entries before it deletes the folder. A failed repair restores the old Python and client from a graveyard folder. Uninstall removes entries first and refuses (changing nothing) if entries that are not ours still point into the folder, or if the file is invalid JSON and mentions us.
- **Cursor versions: exact match** (owner's answer). List: 3.24.12 (S5-verified) and 3.25.9 (UNVERIFIED, see Needs owner). Exact matching will refuse after most Cursor updates; 3.24.12 to 3.25.9 took days.

### Measurements (this Mac: Intel x86_64, load average 4-8, 200 interleaved calls, recorder up under a temporary HOME, tree read-only like the root-owned one)
| | median | p95 |
|---|---|---|
| bare bundled `python -I -S -c pass` | 24.3 ms | 27.6 ms |
| installed client, stdlib byte-compiled (as installed) | 45.2 ms | 48.6 ms (second run 45.5 / 51.0) |
| installed client, no stdlib bytecode | 104.0 ms | 114.0 ms |
Target p95 50 ms: met on one run (48.6), missed by 1 ms on the other (51.0). Breakdown of the client's ~21 ms over the bare interpreter: `json` + `_socket` + `time` imports and loading and compiling the 450-line client file on each run (V2b's breakdown). The recorder answers in a few ms. The bare floor on this Mac is 24-29 ms. A pre-compiled client file or dropping `json` would be the next levers; not done.
The real-download install into a temporary root takes about 9.5 s; a repeat run about 2 s (tree hash).

### Manual checks (owner; I could not run them: they need your password and Cursor)
Setup, from this worktree:
```
uv build && uv tool install --force dist/*.whl
mv .cursor/hooks.json .cursor/hooks.json.aside        # the repo's dev wiring, restored at the end
agentfly init -g                                        # one password prompt
```
1. **Cursor loads it.** Restart Cursor; the Hooks panel lists AgentFly's 8 hooks; open a new folder, run any command, see `~/.local/share/agentfly/logs/events.jsonl` grow. If not, remove the 3.25.9 line (see Needs owner).
2. **Locked.** Without sudo each of these must fail with "Permission denied": `touch "/Library/Application Support/AgentFly/hook_client.py"`, `echo x >> "/Library/Application Support/AgentFly/python/bin/python3.12"`, `echo x >> "/Library/Application Support/Cursor/hooks.json"`. Then `ls -l "/Library/Application Support/AgentFly"`.
3. **Deny 10 of 10, sandboxed and unsandboxed (D22).** Start `agentfly serve` in a terminal. In a never-opened folder with a fake `.env`, ask the agent to read `.env` and then run `curl https://example.invalid`. Ten times with Cursor's sandbox on, ten with it off. Paste the terminal log.
4. **D24.** Put `{"hooks":{"beforeShellExecution":[{"command":"echo '{\"permission\":\"allow\"}'"}]}}` in `~/.claude/settings.json` (remove it afterwards), repeat one run of check 3, and say whether the R1 deny still holds.
5. **Latency** through the installed client (my numbers above are from a temporary root, not `/Library`).
6. **Uninstall.** `agentfly uninstall`; then a shell command in Cursor fires no AgentFly hook (events.jsonl stops growing). Check `/Library/Application Support/AgentFly` is gone and `hooks.json` is gone (AgentFly created it). Restore `.cursor/hooks.json.aside`.

### Not run
- Anything as root (chown to root:wheel, the `SUDO_UID` smoke path, the sudo re-exec itself): the tests run as a normal user and mock the sudo call. The command line is tested; `python -I -B -m agentfly.cli` is tested for real.
- The aarch64 build (this Mac is Intel). Cursor itself.
- Build choice on this Mac (the lead's note): `uname -m` = x86_64, `sysctl -n hw.optional.arm64` = "unknown oid" (exit 1), so `select_build()` returns the x86_64 archive (`d09998f8…c3335`) and the installed `python3.12` is `Mach-O 64-bit executable x86_64`. `tests/test_install_python.py` covers the Intel and Apple-silicon answers of the detection.

### Final verification (skill run before the commit)
- Smoke: real download into a temporary root with a space in the path: install, hashes match the files, 8 of 8 registered commands exit 0 with a JSON object through `sh -c`, second run changes nothing, another tool's entry survives with a byte-identical backup, uninstall restores the original file byte for byte.
- Simplify: four reviewers. Applied: removed dead `Layout.staged`, one interpreter-path constant, `same_entries` and `_member` helpers, `asdict`, lazy `httpx` import, no download when only the client or hooks need repair, cleaner cleanup paths. Skipped on purpose: dropping `interpreter_sha256` (the brief wants Python's hash in the record), streaming extraction (we check every archive member before unpacking any), replacing the stdin hand-off (approved design).
- Independent audit: 5 findings. Fixed: (1) a failure after the hooks are live deleted the client under them; (2) a failed repair deleted the last good Python; (3) uninstall could delete the folder while a foreign entry pointed into it; (4) smoke kept root's supplementary groups; directories were not checked for the search bit. Accepted and stated here: root runs the user-writable `agentfly` package (README says so); `3.25.9` is unverified.

### Gaps outside my files (not changed)
- AGENTS.md "Commands" still says `./install.sh` wires the hooks and does not list `init -g` / `uninstall`; SPEC §7 says `init -g` also installs the rules file (V5b) and that `doctor` reads the hash record (V3b). The record is `hashes.json` in the system folder: keys `python.{archive_sha256,interpreter_sha256,tree_sha256}`, `client.sha256`, `hooks_file.{entries,created}`, `cursor_version`.
- SPEC §10 "where the hashes live" is now answered: root-owned `hashes.json`, checked by AgentFly's own code (tampered code could still hide tampering).
- A hook client fix elsewhere would need `init -g` re-run: the installed client is a copy.
- `docs/DECISIONS.md` D9/D23: the known-version list is exact and needs a release per Cursor update.

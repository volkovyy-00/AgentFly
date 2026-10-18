# V3a: System install: `agentfly init -g` and `agentfly uninstall`
Status: blocked on the owner's manual checks (they need the owner's password and Cursor) (as of 2026-10-18 19:10)
Result: Code and tests done. Install, repair, idempotence, merge, uninstall and the checksum/version refusals work against a temporary root with the real pinned Python. Not run: anything needing sudo or Cursor (4 acceptance items).
Evidence: code commit 0d69408; `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` = 722 passed, 4 skipped; tests/test_install_{cursor,hooks_file,python,flow,cli}.py; docs/reports/V3a.md "Manual checks".
Needs owner: Run the manual checks below. Cursor 3.25.9 is on the known list as UNVERIFIED (your Mac runs it): if AgentFly hooks do not fire after `init -g`, remove that one line in agentfly/install/cursor.py before merge.
Details: see "## 2026-10-18 19:10" below.

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

### Final verification (skill run before the commit)
- Smoke: real download into a temporary root with a space in the path: install, hashes match the files, 8 of 8 registered commands exit 0 with a JSON object through `sh -c`, second run changes nothing, another tool's entry survives with a byte-identical backup, uninstall restores the original file byte for byte.
- Simplify: four reviewers. Applied: removed dead `Layout.staged`, one interpreter-path constant, `same_entries` and `_member` helpers, `asdict`, lazy `httpx` import, no download when only the client or hooks need repair, cleaner cleanup paths. Skipped on purpose: dropping `interpreter_sha256` (the brief wants Python's hash in the record), streaming extraction (we check every archive member before unpacking any), replacing the stdin hand-off (approved design).
- Independent audit: 5 findings. Fixed: (1) a failure after the hooks are live deleted the client under them; (2) a failed repair deleted the last good Python; (3) uninstall could delete the folder while a foreign entry pointed into it; (4) smoke kept root's supplementary groups; directories were not checked for the search bit. Accepted and stated here: root runs the user-writable `agentfly` package (README says so); `3.25.9` is unverified.

### Gaps outside my files (not changed)
- AGENTS.md "Commands" still says `./install.sh` wires the hooks and does not list `init -g` / `uninstall`; SPEC §7 says `init -g` also installs the rules file (V5b) and that `doctor` reads the hash record (V3b). The record is `hashes.json` in the system folder: keys `python.{archive_sha256,interpreter_sha256,tree_sha256}`, `client.sha256`, `hooks_file.{entries,created}`, `cursor_version`.
- SPEC §10 "where the hashes live" is now answered: root-owned `hashes.json`, checked by AgentFly's own code (tampered code could still hide tampering).
- A hook client fix elsewhere would need `init -g` re-run: the installed client is a copy.
- `docs/DECISIONS.md` D9/D23: the known-version list is exact and needs a release per Cursor update.

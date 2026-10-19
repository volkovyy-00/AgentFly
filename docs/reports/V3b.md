# V3b: Service and `doctor`: `start`, `stop`, `status`, `doctor`
Status: done, except the manual checks on the owner's Mac (as of 2026-10-19 12:10)
Result: start/stop/status (own LaunchAgent, or brew services in a keg), uninstall removes the service, doctor (12 lines), guard lists cover the service labels. Tested with stubs and two throwaway real-launchd runs. Not run on the owner's Mac: the real label, init -g, doctor after a Cursor restart.
Evidence: 8 commits on ag-v3b-service after e1d4aeb; `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` = 2490 passed, 5 skipped (before: 2158 passed, 5 skipped without test_package). Tests: test_service.py, test_doctor.py, test_install_cli.py, tests/cases.py.
Needs owner: run the checklist below on your Mac after merging (it changes login items and needs `agentfly init -g`). Recommended: yes, once; it is the only part not tested against the real service.
Details: see "## 2026-10-19 12:10" below.

## 2026-10-19 12:10

### What changed
- New `agentfly/install/service.py`: the recorder as a launchd service. `start` writes
  `~/Library/LaunchAgents/dev.agentfly.recorder.plist` (`RunAtLoad`, `KeepAlive`, `ThrottleInterval` 5,
  `ProgramArguments` = this install's `python -I -m agentfly.cli serve`, stdout to `/dev/null`, stderr to
  `~/.local/share/agentfly/logs/recorder.log`) and loads it with `launchctl bootstrap gui/<uid>`; `stop` does
  `bootout`, waits until launchd has really let go, then deletes the file; `status`/`doctor` read `launchctl print`.
  A package under `<prefix>/Cellar/agentfly/` next to `<prefix>/bin/brew` uses `brew services start|stop|info --json`
  instead and writes no LaunchAgent.
- New `agentfly/cli/{start,stop,status,doctor}.py`, registered in `cli/__init__.py`. `start` waits up to 10 s for
  `/health`; `status` exits 0 only when `/health` answers.
- `cli/uninstall.py`: after the sudo part succeeds, removes the service as the user; a failed system part leaves the
  service running (the hooks are still registered); a service that will not unload ends in one line and a second run finishes it.
- New `agentfly/install/checks.py`, `hookslog.py`; `installer.lock_problems()` (the walk `assert_locked` used, reusable as the user).
- `_R0_PATHS` (rules.py) and `_GUARD_PATHS` (hook_client.py) += `dev.agentfly.recorder`, `homebrew.mxcl.agentfly`,
  `sh.brew.agentfly`; new test that the two tuples are equal.
- README "Installation" and "Usage", SPEC §5 R0 bullet and §7, AGENTS.md "Commands" and "Testing".

### Decisions and interpretations (please check)
1. **`stop` deletes the plist** (like `brew services stop`), so it stays down at the next login. The brief says "`stop` keeps it down".
2. **Guard strings are the labels without `.plist`.** `defaults write ~/Library/LaunchAgents/dev.agentfly.recorder KeepAlive -bool NO`
   and `plutil` slipped past a `.plist` pattern (probed before the change). A superset of the plist paths the brief names.
3. **Homebrew's label is not only `homebrew.mxcl.agentfly`.** Homebrew 7.0.9 names a formula's launchd job `sh.brew.<name>` and keeps
   `homebrew.mxcl.<name>` as a legacy alias (`/usr/local/Homebrew/Library/Homebrew/service.rb:85-105`). The brief and D8 name only the old one.
   Both are guarded; for Homebrew the service file is taken from `brew services info --json` (`loaded_file`), not a fixed name.
4. **`doctor` compares AgentFly's entries in `hooks.json`**, not the whole file's hash: other tools may edit that file.
5. **Twelve lines**: `record`, `python`, `lock`, `client`, `hooks`, `events`, `service`, `service-file`, `keepalive`, `path`, `hooks-log`,
   `claude-settings`. Beyond the brief: `service-file` (the plist equals what `start` writes, ignoring `KeepAlive`, so an edited
   `ProgramArguments` shows) and `lock` covers the whole system folder, not only the Python. A check that needs something another
   line already fails on says `warn "not checked: ..."`; each fault in the brief turns exactly one line to fail (one parametrized test each).
   After a real `stop` only `service` fails (`keepalive` and `service-file` warn).
6. `launchctl enable` runs only when `print-disabled` says the label is switched off: on the real launchd it leaves a permanent
   `"<label>" => enabled` entry that nothing can remove.
7. The offline guard has only path rules, no `launchctl`/`brew` command rules (pre-existing, SPEC §9); R0 has both. The plist paths are covered by both.

### Acceptance criteria
| Criterion | State |
|---|---|
| `start` leaves a loaded LaunchAgent with `KeepAlive`; `/health` back within 15 s after `kill -9`; `stop` keeps it down; `status` correct (stub tests + manual) | Stub tests pass. Real launchd, throwaway job: new process 4.0 s and 5.1 s after `kill -9`. **Manual on the real label: not run.** |
| Stub `brew`, package in a Homebrew prefix: `brew services`, no LaunchAgent written | Done (`test_a_homebrew_install_starts_and_stops_through_brew_services`). |
| After clean `init -g`, `start`, Cursor restart: all ok; each listed fault fails only its own line; gate hook in `~/.claude/settings.json` is a warn | Clean case and 20 faults tested on a temporary root (`test_doctor.py`). **Real `init -g` + Cursor restart: not run.** |
| After `uninstall`: `launchctl list \| grep agentfly` empty, plist gone; plist read/write/delete denied by R0 and the offline guard | Done in tests (`test_uninstall_also_stops_and_removes_the_service`; `tests/cases.py` `GUARD_PATHS` feeds both guards). |
| Service stopped: `doctor` fails the service line; offline guard still denies `curl https://example.invalid` with "agentfly start" (manual) | `doctor` part tested. **Manual part: not run.** |

### Real launchd, throwaway job (macOS 15.7, no AgentFly label used)
Shell probe with a `sleep` job, then the `service` module with a patched label, a temporary HOME and `/bin/sleep` as the program:
```
bootstrap while loaded            -> exit 5  "Bootstrap failed: 5: Input/output error"
bootout of a job that is gone     -> exit 3  "Boot-out failed: 3: No such process"
print of a job that is not loaded -> exit 113
print of a KeepAlive job          -> state = running / pid = N / properties = keepalive | runatload | inferred program
kill -9, KeepAlive, ThrottleInterval 5 -> new pid after 4.04 s (shell) and 5.07 s (service module)
bootout took 0.04 s and print was 113 at once (a sleep job; the recorder may take longer, `stop` polls up to 10 s)
service module: start, start again ("already running"), changed file (reloaded), stop, stop again ("already stopped"),
launchctl list | grep probe -> nothing
```
Left behind: one entry `"dev.agentfly.v3bprobe54766" => enabled` in launchd's override list, from my first shell probe, which ran `launchctl enable`
(that is why the code no longer does unless needed). Harmless; it cannot be removed without root.

### Manual checklist for the owner (after merge)
1. `uv build && uv tool install --force dist/*.whl`; `agentfly init -g` (needed: the hook client changed; until then `agentfly doctor` warns on `client`); quit and reopen Cursor.
2. `agentfly start` prints "recorder answers on 127.0.0.1:8787". `launchctl list | grep agentfly` shows one row. Stop a recorder you run by hand first.
3. `kill -9 $(pgrep -f 'agentfly.cli serve')`; `curl -s localhost:8787/health` answers again within 15 s.
4. `agentfly status` (exit 0), then `agentfly stop`: `launchctl list | grep agentfly` prints nothing and `~/Library/LaunchAgents/dev.agentfly.recorder.plist` is gone; `status` exits 1.
5. With the service stopped: `agentfly doctor` fails the `service` line only (warns on `service-file` and `keepalive`); in Cursor, `curl https://example.invalid` is denied with "agentfly start".
6. `agentfly start`, then `agentfly doctor`: all twelve lines ok.
7. `agentfly uninstall` (no sudo prefix): `launchctl list | grep agentfly` prints nothing, the plist is gone, restart Cursor.

### For the lead
- **D8 and the brief** name only `homebrew.mxcl.agentfly`; V4 should pin the formula's `plist_name` (or accept `sh.brew.agentfly`) and the `path` check
  accepts a symlink to the venv script, a script whose shebang names this Python, or a wrapper script that names the folder of our command (what
  `write_exec_script` makes); any other `agentfly` first on PATH fails. Check it against the real formula.
- The **enterprise-source error line** in the Hooks log has never been seen (only `Invalid user config` / `Failed to parse user|project hooks configuration`).
  `doctor` treats an error line that names no user/project/workspace/Claude source as about the system file.
- **SPEC §10** "where the reference hashes live" is answered by this card (`hashes.json`, checked by `doctor`); not edited here (V6b works in SPEC.md). Same for a
  known gap: globs and names built from variables (`rm ~/Library/LaunchAgents/dev.agent*`) bypass the label match.
- `sudo agentfly uninstall` takes the root branch and leaves the user's service; the README says to run it without `sudo`.
- `hook_client.py` changed (guard list): the installed copy is stale until `init -g` is run again.
- V3c: `checks.CHECKS` is a plain list of `check_*(ctx) -> Check` functions; a "package unchanged" line is one more function. `installer.lock_problems` is public.
- The test suite grew by about 330 tests and 30 s; `test_doctor.py` skips the install's smoke run and byte-compile for speed.
- A hand-started `agentfly serve` plus the service would crash-loop on the busy port; `start` warns when something already answers `/health`.
- R0 and the offline guard match the labels anywhere in a command, so an agent's `git commit -m '... dev.agentfly.recorder ...'` or
  `rg dev.agentfly.recorder` is denied (same as `.config/agentfly` today). Workers on V3c/V4 should avoid the literal in commands.
- Without a GUI session (ssh) `launchctl print` exits 112; `start`, `stop`, `status` and `uninstall` say so in one line, they do not treat the service as stopped.
- `start` also reloads a job that is loaded without `KeepAlive` although its file has it (the warning `doctor` gives).

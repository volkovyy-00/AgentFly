# V3b: Service and `doctor`: `start`, `stop`, `status`, `doctor`
Status: done (as of 2026-10-19 13:55)
Result: Lead review fixed: doctor `path` compares venvs, not the base Python; Homebrew `start` retires our own LaunchAgent and doctor fails `service` if both load; a failed sudo part in `uninstall` claims only what is known. Test for each.
Evidence: 8adf2c5 on ag-v3b-service; `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` = 2501 passed, 5 skipped (was 2490). New tests in test_doctor.py, test_service.py, test_install_cli.py.
Needs owner: none.
Details: see "## 2026-10-19 13:55" below (review fixes); then the manual run (13:26) and the build notes (12:10).

## 2026-10-19 13:55

### Lead review: three fixes (commit 8adf2c5; nothing else changed except the docs that stated the old behaviour)
| # | Cause | Fix | Tests |
|---|---|---|---|
| 1 | `checks._is_ours` compared `realpath(shebang interpreter)` with `realpath(sys.executable)`. Every venv's `python` is a symlink to the base Python, so any venv on the same base counted as ours (`ok path`). | New `_environment(python)`: the folder holding `pyvenv.cfg` beside the unresolved path or in its parent, else the installation itself. Both sides go through it. | `test_doctor.py`: `test_an_agentfly_of_another_venv_on_the_same_base_python_is_not_ours` (two venvs on one base, the other first on PATH, fails only `path`; failed before the fix with `ok path`), `..._of_this_venv_is_ours_even_when_it_is_not_the_recorded_script`, `test_two_commands_on_a_python_without_a_venv_share_its_environment` |
| 2 | `service.start` returned from `_brew_services` without looking at `dev.agentfly.recorder`, so an earlier install's KeepAlive job kept port 8787 and `status`/`doctor` said ok. | On the Homebrew path `start` first runs `_teardown_agent()` (unload, wait, delete the file) and prints "replacing the LaunchAgent of an earlier install ..." plus the unloaded/removed lines; nothing is printed when there is none. `State.agent_loaded` (set by `_inspect_brew` from `launchctl print`) makes `status` append "; dev.agentfly.recorder is loaded too" and `doctor`'s `service` line fail with the label and "run `agentfly start`, which removes ours". | `test_service.py`: `test_a_homebrew_start_replaces_the_launch_agent_of_an_earlier_install`, `..._removes_a_launch_agent_file_that_is_not_loaded`, `..._without_a_launch_agent_of_ours_says_nothing_about_one`, `test_the_state_of_a_homebrew_install_shows_a_loaded_launch_agent_of_ours`; `test_doctor.py`: `test_a_homebrew_service_and_our_own_launch_agent_together_fail_the_service_line` (only `service` fails), `test_a_homebrew_service_alone_is_ok`. Stub launchctl + stub brew; the old "launchd.calls() == []" assertion became "no bootstrap" because `start` now looks (one `print`) |
| 3 | `uninstall._as_user` printed "the recorder service was left running, because the hooks are still registered" for any non-zero sudo exit. | One line: `the sudo part failed (exit N); the service was not touched; run `agentfly uninstall` again`. The exit code is still returned. | `test_install_cli.py`: `test_uninstall_leaves_the_service_alone_when_the_system_part_fails` (reworded), `test_a_failed_system_part_does_not_claim_what_it_cannot_know` (the elevated part removed the entries, then failed), `test_a_cancelled_password_prompt_with_no_service_installed_says_the_same` |

Real check of #1 on this Mac (the lead's case: the repo's `.venv` and the uv tool share `/usr/local/Cellar/python@3.12/3.12.11/.../python3.12`):
```
run from the repo .venv,      command = ~/.local/bin/agentfly (uv tool)  -> env of shebang .../uv/tools/agentfly-recorder, ours .../ag-v3b-service/.venv -> _is_ours False
run from the uv tool's python, command = repo .venv/bin/agentfly          -> _is_ours False
run from the uv tool's python, command = ~/.local/bin/agentfly            -> _is_ours True
```
Full check: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` = ruff clean, 163 files formatted, **2501 passed, 5 skipped** (2490 before).

### Docs changed because they stated the old behaviour
README (service paragraph, doctor paragraph, uninstall paragraph), SPEC §7 (Run `start` bullet, `doctor` bullet, Uninstall bullet; §10 untouched), AGENTS.md "Testing" (Service and Doctor lines). The older sections below (12:10 "What changed", decision notes) still say a failed system part "leaves the service running"; this section replaces that.

### For the lead (seen while fixing, not changed because the review said to change nothing else)
- `agentfly stop` on a Homebrew install still stops only `brew services` (`_teardown_brew`). A LaunchAgent of ours left by an earlier install would keep the recorder up after `stop` ("already stopped" is printed if brew's job is not loaded). `start` retires it, `uninstall` removes both, `doctor` fails `service` while it is loaded. Making `stop` call `_teardown_agent()` too is one line plus a test; say if you want it.
- On a Homebrew install `status` and `doctor` now run one more `launchctl print`; if that fails (exit 112 without a GUI session) they end with the same one-line "cannot read the service state" as on the LaunchAgent path.
- The Homebrew paths are tested with the stub `brew`/`launchctl`, not a real Homebrew keg.
- `hook_client.py` is unchanged, so no `init -g` re-run is needed for these fixes. The `agentfly` installed on the owner's Mac is still the earlier build of this branch.

## 2026-10-19 13:26

### Manual run on the owner's Mac (Intel, macOS 15.7, Cursor 3.25.9, `uv tool install --force` of this branch, then real `agentfly init -g`)
| Step | Result |
|---|---|
| `doctor` after `init -g` and a Cursor restart | `record python lock client hooks events path hooks-log claude-settings` ok (`lock` on the real root-owned tree, `hooks-log`: "Cursor loaded AgentFly's 8 hooks"); `service` fail, `service-file` and `keepalive` warn |
| `agentfly start` | `loaded dev.agentfly.recorder`, "recorder answers on 127.0.0.1:8787", one `launchctl list` row; `/health` was `{"ok":true,"offline_guard_count":7}`: the offline guard had handled 7 hook calls since the Cursor restart |
| `kill -9` of the recorder | `/health` failed 0.05 s later and answered again after **1.2 s** (new pid; criterion 15 s) |
| `agentfly stop` | "unloaded", plist removed, `launchctl list \| grep agentfly` empty, still no answer 8 s later; `status` exit 1; `doctor` fails only `service` |
| Cursor agent runs `curl https://example.invalid` with the service stopped | **Blocked**; the agent answers "AgentFly's recorder is not running ... until you start it with `agentfly start`" (screenshot from the owner). The registered hook command, run by hand, also denied it and allowed `ls`, both exit 0 |
| `agentfly start`, then `doctor` | all 12 lines ok, exit 0 |
| `plutil -replace KeepAlive -bool NO` on the plist, then `doctor` | exactly one non-ok line: `fail keepalive`; `agentfly start` printed "the loaded job differs from its service file; reloaded it"; `doctor` back to 0 non-ok lines |
| `agentfly uninstall` (owner's Terminal, one password prompt) | hooks.json and `/Library/Application Support/AgentFly` removed, then "unloaded dev.agentfly.recorder" and the plist removed; afterwards no `launchctl` row, no plist, no folders, no leftover `.AgentFly-removing-*`; `doctor` says "not installed"; a second `uninstall` prints "nothing of AgentFly's is installed" and asks for no password |

Notes from the run
- `agentfly init -g` run through the Claude Code `!` prompt fails with "sudo: a terminal is required" and writes nothing (checked); it needs a real Terminal.
- The Cursor-restart reminder prints twice on `uninstall`: once by the sudo child, once by the parent. This was already so before V3b (`uninstall.py` printed it on a zero exit and the child on `changed`); the order is now child hint, service lines, parent hint. Not changed here.
- The installed `agentfly` is now this branch's build (`uv tool install --force`), and the leftover override entry `dev.agentfly.v3bprobe54766 => enabled` from my first probe is still in launchd's list.

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
| `start` leaves a loaded LaunchAgent with `KeepAlive`; `/health` back within 15 s after `kill -9`; `stop` keeps it down; `status` correct (stub tests + manual) | Stub tests pass. Real launchd, throwaway job: new process 4.0 s and 5.1 s after `kill -9`. **Real label on the owner's Mac: `/health` back after 1.2 s; `stop` stayed down (manual run above).** |
| Stub `brew`, package in a Homebrew prefix: `brew services`, no LaunchAgent written | Done (`test_a_homebrew_install_starts_and_stops_through_brew_services`). |
| After clean `init -g`, `start`, Cursor restart: all ok; each listed fault fails only its own line; gate hook in `~/.claude/settings.json` is a warn | Clean case and 20 faults tested on a temporary root (`test_doctor.py`). **Real `init -g` + Cursor restart: all ok once the service ran; a tampered `KeepAlive` failed only `keepalive` (manual run above).** |
| After `uninstall`: `launchctl list \| grep agentfly` empty, plist gone; plist read/write/delete denied by R0 and the offline guard | Done in tests (`test_uninstall_also_stops_and_removes_the_service`; `tests/cases.py` `GUARD_PATHS` feeds both guards). |
| Service stopped: `doctor` fails the service line; offline guard still denies `curl https://example.invalid` with "agentfly start" (manual) | `doctor` part tested. **Manual part done: Cursor blocked `curl https://example.invalid` and named `agentfly start` (manual run above).** |

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

### Manual checklist for the owner (all steps were run on 2026-10-19, see the section above)
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

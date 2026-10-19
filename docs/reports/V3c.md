# V3c: Root never runs a changed AgentFly: package check before `sudo`, R0 guards the install folder
Status: done (as of 2026-10-19 16:42)
Result: init -g/uninstall hash the tool environment before any password prompt, stop on a changed or extra file, ask on upgrades. Root runs -I -S -B, no byte-code, on the bundled Python. R0 guards the environment and uv/pipx/brew installs. doctor has a package line. Real sudo and Homebrew not tried.
Evidence: 17c8350 on ag-v3c-package-check. `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`: 3303 passed, 5 skipped (baseline 2534). New: test_install_packages.py (37), test_root_command.py (8), plus CLI, doctor, R0, offline-guard and real-wheel cases.
Needs owner: Rebuilding at the same version stops init -g and uninstall (as the brief says); the wheel is rebuilt every card. Keep it and raise the version before each rebuild, or ask instead of stopping when files match their own RECORD? Recommend: keep.
Details: see "## 2026-10-19 16:42" below.

## 2026-10-19 16:42

### What changed
- `agentfly/install/packages.py` (new): `tool_environment()`, `inspect()`, `require()`, `confirm()`. Every file of every `*.dist-info` is hashed. Same version as the record: compared with the stored hashes. Version differs or new/removed dependency: compared with the distribution's own `RECORD`, and "name: changed from X to Y" is listed for the owner. No record, or one from before V3c: compared with `RECORD`, no prompt. Files no `RECORD` lists are named (links count as files; `__pycache__`, `_virtualenv.py`, `_virtualenv.pth`, `pipx_shared.pth`, `homebrew_deps.pth` are exempt). The base Python is never read.
- `cli/init.py`, `cli/uninstall.py`: `packages.require(...)` runs before the first password prompt (`uninstall` only when something is installed), then `confirm` on a version change (terminal only). `installer.status(..., current)` adds `"packages"` so an upgrade with untouched files is not "already intact"; `installer.install` re-hashes as root and stores `packages` in `hashes.json` (schema stays 1, so older records keep their hooks-backup data).
- `install/elevate.py`: `sudo -I -S -B -X pycache_prefix=/var/empty -c <bootstrap> <site> <tail>`. Interpreter: the bundled one when `"python" not in bad` (init) or `installer.python_intact` (uninstall); otherwise `realpath(sys.executable)`, the base interpreter, so the venv's `bin/python` and `pyvenv.cfg` are not trusted.
- `install/checks.py`: `package` line after `client` (changed/extra file fails, a version change warns, a source checkout is "not checked").
- R0 (`rules.py`) and the offline guard (`hook_client.py`), kept equal: `uv/tools/agentfly-recorder`, `pipx/venvs/agentfly-recorder`, `site-packages/agentfly`, `/cellar/agentfly`, `/homebrew/opt/agentfly`, `/local/opt/agentfly`, `.local/bin/agentfly`. R0 only: `uv tool|pipx|brew` install/upgrade/reinstall/uninstall/... when AgentFly is named, an operand is a file, URL or variable, or the call is bulk (`brew upgrade`, `--all`, `*-all`); unparseable text with such a verb is denied too.
- Docs: SPEC section 5 (R0 list), 7 (`init -g`, package check, `doctor`) and 10 (Detected, Known gaps); README "Installation".

### Checks run
- Planted-code test on a real venv (tests/test_root_command.py): the old command (`-I -B -m agentfly.cli`) writes the `.pth` and `.pyc` markers; the new one writes none and exits 0. Without `-X pycache_prefix` the unchecked-hash `.pyc` still runs, so that flag is what stops it. A planted `sitecustomize` never runs even in the control, because Homebrew's Python ships its own earlier on `sys.path`, so only its absence is asserted.
- `tool_environment()` is also run inside the exact root flags in that venv. Under `-I -S` on Homebrew's Python, `sys.prefix` and `sysconfig` name the base Python, which is why the environment is found from where `agentfly` was imported and never from them.
- tests/test_package.py: on a real `uv tool install` of the built wheel the check finds no problem (only `_virtualenv.*` is unlisted), names a planted `.so` and a changed module, and the sudo command line (minus `sudo`) runs `init --help` with the real dependencies.
- Read-only on the owner's real tool environment: 20 packages, 1378 files, no problem; the record's `packages` section would be about 150 KB.
- A second-opinion review of the plan found a blocker (the `sysconfig` point above), the pipx/Homebrew `.pth` files, the same-version deadlock, and gaps in the command rule. All were taken in.

### Deviations from the brief
1. Root does import a dependency: `agentfly.cli` -> `wipe` -> `recorder/localstore.py` -> `recorder/store.py:16` imports `neo4j` (and that needs `typing_extensions`). The bootstrap therefore appends the whole site folder to `sys.path`, and the gate covers every distribution. Making those imports lazy is outside this card's Touches; recommended follow-up.
2. A repair that replaces the bundled Python (a new pin) runs root on the base interpreter, not on the bundled one: the tree would be swapped under a running root process.
3. Command denials (`uv tool`, `pipx`, `brew`) are R0 only; the offline guard keeps the path guards. Please confirm that reading of "R0 and the offline guard".
4. `AGENTS.md` Testing section has no lines for the new tests (outside Touches); SPEC section 7 was edited although the brief's Touches names only 5 and 10.
5. Known false positives: `~/.local/bin/agentfly status` by full path is denied (the substring guard); `echo brew upgrade` is denied (R0 finds the program anywhere in argv, like the existing `brew services` rule).

### Not covered (SPEC section 10 says so)
The checker checks itself; the base Python (its `__pycache__` is writable by the user); `RECORD` is trusted on each new version; the first `init -g` after V3c on an older install has no stored reference; a file changed while the password prompt waits (root's re-hash records what it sees and protects nothing); a first install and a pin-change repair run on the base interpreter; a tool environment outside the default places is not guarded by R0 by path; Homebrew layout untried (no formula yet, `homebrew_deps.pth` is allowed from reading Homebrew's source only).

### Lead trial (I cannot run `sudo`)
1. `uv build && uv tool install --force dist/*.whl`, then `agentfly init -g`. In a second terminal during the password prompt: `ps -ax -o command | grep pycache_prefix` should show sudo with the interpreter and the flags (bundled Python from the second run on). Then `agentfly doctor`: every line ok, including `package`.
2. `echo "# x" >> ~/.local/share/uv/tools/agentfly-recorder/lib/python3.12/site-packages/agentfly/install/layout.py`, then `agentfly init -g` and `agentfly uninstall`: both stop before any prompt and name that file; `agentfly doctor` fails only `package`. Reinstall the wheel: `doctor` is ok again.
3. `agentfly uninstall` after a clean install: root deletes the interpreter it is running on. Expect exit 0, no traceback, `launchctl list | grep agentfly` empty.
4. The hook client changed (guard list): run `agentfly init -g` again so the installed copy has it. After a rebuild at the same version, the next `init -g` stops until the version is raised.

### For V5b (touches `agentfly/install/`)
`elevate.sudo_command(tail, *, site, python=None)` and `run_elevated(tail, stdin=None, *, python=None)` changed; `installer.status` takes `current`; `tests/conftest.py` has an autouse `tool_env` fixture that gives every test a small clean fake tool environment (`tests/install_helpers.py` `make_tool_env`).

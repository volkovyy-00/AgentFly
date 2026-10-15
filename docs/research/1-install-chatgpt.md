# Cursor Hooks Today

- **Hook files & precedence:** Cursor loads hooks from *multiple levels*. Project hooks live in `<project>/.cursor/hooks.json`; user hooks in `~/.cursor/hooks.json`. Enterprise (MDM/system) and team (cloud-managed) hooks also exist. All matching hooks run, and their responses are merged: any `deny` overrides `ask/allow`. Priority is **Enterprise > Team > Project > User**. Project-level hooks only run in *trusted* workspaces (if the user rejects trust, the project hook is skipped).  
- **Supported events:** Cursor agents fire a rich set of hook events. These include **agent session events** (`sessionStart`, `sessionEnd`, `subagentStart`, `subagentStop`), **tool events** (`preToolUse`, `postToolUse`, `postToolUseFailure`, plus file I/O: `beforeShellExecution`/`afterShellExecution`, `beforeMCPExecution`/`afterMCPExecution`, `beforeReadFile`/`afterFileEdit`), **prompt events** (`beforeSubmitPrompt`, `afterAgentResponse`, `afterAgentThought`), **compaction** (`preCompact`), **stop** (when agent thinks it’s done), and **tab events** (`beforeTabFileRead`, `afterTabFileEdit`). Recent releases (2025–2026) expanded this: e.g. CLI now supports `afterAgentThought`/`afterAgentResponse`, session start/end, compaction, and subagent hooks.  
- **Hook behavior & config:** Hooks are defined with commands or prompts, and may block actions by exit code or JSON. By default, Cursor treats exit code 0 as allow, exit 2 as deny (block), and *any other code as* **fail-open** (action proceeds). Hooks can specify a `timeout` (default ~platform-default, often 10–30s) and a `failClosed: true` flag to invert this (making failures or timeouts block the action). Global options (in `cursor.json`) include workspace trust enforcement and default timeouts.  

Recent changelogs highlight these hook features: April 2026 noted “hooks fire reliably” in CLI with `afterAgentThought/afterAgentResponse` support; January 2026 added session-start/end hooks, stop-hook loops, compaction, and subagent hooks, and enforced enterprise > team > project > user precedence for hooks. In October 2026, hooks could receive data via stdin (avoiding argument-length limits). In short, Cursor’s hook system now robustly supports project/user/enterprise hooks, many events, and merging of multiple hook sources.

# Packaging a Python CLI + Local Server

We need to ship `agentfly` (CLI & background recorder) to Mac/Linux developers.

- **pipx / pip (Python):** The Python Packaging Authority recommends using **pipx** for CLI apps. Pipx installs the tool in an isolated venv and exposes its console scripts on the PATH. E.g. `pipx install agentfly` yields a globally callable `agentfly` without polluting system site‑packages. Upgrading or uninstalling is easy (`pipx upgrade agentfly`, `pipx uninstall agentfly`). We should publish AgentFly on PyPI so `pipx` works seamlessly (like many Python CLIs such as Black, mypy, etc.).  
- **Homebrew formula/tap:** For macOS (and Linux via Linuxbrew), providing a Homebrew formula allows `brew install agentfly`. The formula can use `Language::Python::Virtualenv` to install dependencies (see example: the Datasette formula). Once in Homebrew, we can also define a service. This approach meets the “`brew install agentfly`” goal. It requires maintaining a formula (either in homebrew-core or a custom tap). Simon Willison’s blog shows how a Python package (Datasette) was packaged via a tap so that `brew install simonw/datasette/datasette` works. We should document a tap and possibly upstream it.  
- **Standalone executables:** Tools like **PyInstaller** bundle Python + all libs into a single executable per platform. This avoids requiring Python on the target system. Alternatively, **Pex** or **shiv** create self-contained Python zipapps (which still need a base Python interpreter). We could offer AgentFly binaries (via PyInstaller) for convenience, especially if some users lack a suitable Python. But note the large size and complexity of updates. At minimum, using pipx or brew is more straightforward.  
- **‘uv’ (Astral) alternative:** The new `uv` tool (Rust-backed pyenv/pip/pipx/poetry replacement) might install our package easily, but it’s still emerging. We can mention it as an option but it’s not yet mainstream.
  
**Service management:** The AgentFly recorder (FastAPI) should run as a background service. For Mac, we can use `launchd`: e.g. a LaunchAgent plist at `~/Library/LaunchAgents/io.agentfly.recorder.plist` that runs `agentfly server` on login. For Linux, a `systemd --user` unit (`~/.config/systemd/user/agentfly-recorder.service`) can be created. Homebrew offers `brew services start agentfly` which behind the scenes uses `launchd` or `systemd`. We should support `agentfly start`/`agentfly stop` commands to manage the service, and advise `brew services start agentfly` for persistence. On uninstall, ensure we stop and remove these service definitions.

# Global Hook Installation and Failure Modes

Looking at analogous tools:

- **Git hooks (pre-commit, Husky, etc.):** These typically fail-closed: if a hook script exits non-zero, the commit is blocked. However, many default shell pipelines are *fail-open* on errors (if an earlier command fails silently, grep sees empty input and passes). Strug City’s post (“Fail Closed”) shows that when a security hook can’t inspect (e.g. git fails), the default was to *allow* the commit – a dangerous fail-open bug. They fixed it by forcing bash `pipefail`, making such failures block the commit.  The principle is that *security guards should fail closed* (block) when in doubt.
- **Global Git hook managers:** Tools like pre-commit can install hooks globally, but these rely on Python and sometimes extra daemons. If the service backing a global hook is down, behavior varies – often the hook simply fails (which usually blocks since non-zero exit aborts the action).
- **Local proxies:** Consider something like `ssh-agent`: if down, SSH prompts for key or fails (often not critical). For AgentFly, our hooks will call a local server. We must choose default behavior if the server is unreachable or slow:
    - **Fail-open (per default):** Let the action proceed if AgentFly can’t answer. This avoids deadlock of the developer’s workflow. Cursor’s default is fail-open for unexpected hook exits.  
    - **Fail-closed for critical rules:** For high-risk checks (e.g. reading a `.env`), we may want *fail-closed* (block) if AgentFly doesn’t confirm safety. The Strug City analysis argues for this in security contexts. We could allow configuring each hook’s `failClosed`. Likely, v1 should default to open for usability, with an option for strict mode on secret files.  
- **Latency:** Synchronous hooks pause the agent until completion. Google’s Gemini docs warn: “Keep hooks fast” since each delay directly delays the agent. Our FastAPI server must respond quickly (e.g. in milliseconds). Network calls should be avoided (server is local), and rule checks should be lightweight.
- **Precedents (agent guard frameworks):** New AI guard tools (e.g. Snyk’s Guardrails, AWS Bedrock agents) follow similar hook patterns, often recommending timeouts and fail-open vs closed policies carefully. AgentFly should explicitly document that its default is non-blocking (fail-open) except where configured.

# Other Agent Hook Models

AgentFly should plan ahead for other agents:

- **Claude Code:** Uses `.claude/` config files: global `~/.claude/settings.json`, repo `.claude/settings.json`, local override `.claude/settings.local.json`, and enterprise policies. Hooks fire on events like `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, etc. Command-hooks read JSON from stdin and return a JSON with `"permissionDecision": "deny"` to block, or exit codes (0=allow,2=deny). Hooks always run (unlike soft prompts), so this is a close analog to Cursor hooks.  
- **Codex CLI (OpenAI):** Uses `.codex/` config. Both `hooks.json` and `config.toml` are supported in `~/.codex/` and in the repo root. For example, `~/.codex/hooks.json` or `~/.codex/config.toml` can define arrays like `[[hooks.PreToolUse]]`. Events include SessionStart, PreToolUse, PostToolUse, Stop, etc. The docs show JSON examples with fields like `command`, `timeout`, `statusMessage`. Behavior is similar: script outputs JSON or exit codes.  
- **Gemini CLI:** Added hooks in Jan 2026. Config goes in `.gemini/settings.json`. Example (see [63]) shows a `"BeforeTool"` hook that calls a shell script and returns `{"decision":"deny","reason":...}` to block, or `{"decision":"allow"}`. Events include BeforeTool, AfterAgent, Stop, etc. Hooks are synchronous, blocking the agent until done.  
- **Summary:** All these agents use JSON/TOML config files (global and project-local) to define hook events and scripts. They use exit codes or structured JSON (`{"permissionDecision": "deny"}` or `{"decision": "deny"}`) to control actions. This is essentially the same model as Cursor’s hooks. AgentFly’s design (posting actions to a local service that returns allow/deny) should translate well: in future we could add support for `.claude/` or `.gemini/` hook formats if needed. Current coverage (Cursor) is priority, but architecture is easily extended.

# Recommended Install/Packaging Design (AgentFly v1)

1. **Distribution:** Publish AgentFly on PyPI, enabling `pipx install agentfly` (recommended). Also create a Homebrew formula (or tap) to allow `brew install agentfly`. This satisfies “`brew install agentfly`”. Optionally, provide PyInstaller-built binaries for Mac/Linux (e.g. put in a GitHub release) for users without Python.
2. **Hook Registration:** On `agentfly init -g`, modify (or create) the user hooks file `~/.cursor/hooks.json`. For example:
   ```json
   {
     "hooks": {
       "BeforeReadFile": [{
         "type": "command",
         "command": "agentfly sanitize_read",
         "timeout": 5
       }],
       "BeforeShellExecution": [{
         "type": "command",
         "command": "agentfly check_cmd",
         "timeout": 5
       }]
     }
   }
   ```
   Each entry runs a short `agentfly` subcommand (passing sanitized JSON via stdin or args) that posts to the local recorder (127.0.0.1:8787). These CLI commands should drop file contents (for privacy) and let the server enforce any rules. On uninstall, `agentfly uninstall` should remove these entries from `hooks.json`. (Be careful to merge with any existing hooks, or use a sentinel comment so we know what to remove.)
3. **Background Service:** Provide `agentfly start`/`stop` commands. On start, AgentFly spins up the FastAPI recorder (serving localhost only). On Mac, installing via brew we can include a plist so that `brew services start agentfly` will run it on login (LaunchAgent). On Linux, we can create a `~/.config/systemd/user/agentfly.service` unit for systemd user. The tool should auto-setup the chosen service on `init` or first start. Ensure `agentfly stop` halts it. During upgrade, stop the old service, upgrade code, then restart.
4. **Upgrades/Cleanup:** `agentfly uninstall` should reverse all changes: stop and disable service, remove cursor hook entries, and if pipx-installed perhaps call `pipx uninstall agentfly`. If Homebrew, `brew uninstall agentfly` will remove the formula and its service via `brew services stop`.
5. **Fail Policy:** By default let hooks *fail-open* (so agent actions proceed if AgentFly can’t respond). For example, if the local server is down or a hook times out, we **allow** the action (with maybe a warning). For R1 (secret-read rule), advise users to enable strict mode: e.g. set `failClosed: true` for that hook so that if AgentFly is unreachable it will *block* the action. This dual-mode respects both security (fail-closed for secrets) and usability (fail-open otherwise).
6. **Step-by-step to Ship v1:**
   - Develop and test the Python CLI (`agentfly`), including `init`, `start`, `stop`, `uninstall`.
   - Build the FastAPI recorder to accept HTTP POST actions and enforce rules.
   - Write documentation: how to `pipx install agentfly` or `brew tap && brew install agentfly`, then `agentfly init -g`, then `agentfly start`.
   - Create a Homebrew tap/formula (possibly using `virtualenv_install_with_resources` as in Datasette) and a plist for `brew services`.
   - Test on macOS and Linux: ensure `agentfly start` truly launches service, hooks are invoked by Cursor, and `agentfly stop` cleans up.
   - Ensure `agentfly uninstall` cleans config and services.
7. **Risks to Monitor:**
   - **Hook conflicts:** Editing `hooks.json` could overwrite user’s custom hooks. We should merge carefully and document what we add. Perhaps wrap our hooks in a named block.
   - **Latency:** Synchronous hooks will slow agent response. Ensure all checks (on service) are fast (cache e.g. secret lists).
   - **Downtime:** If AgentFly crashes or isn’t started, agent may behave differently. We’ll default to allow actions, but users should know this caveat.
   - **Security:** The server must not serve remote requests (bind `127.0.0.1` only). Also, hook scripts run with user privileges, so malicious hooks (added by rogue code) could be dangerous – users must trust their own `.cursor/hooks.json`.
   - **Environment issues:** Python version changes or missing deps could break the CLI. A bundled binary avoids this but pipx/brew might occasionally have env issues.
   - **Upgrades:** Changes in hook schema or new rules (e.g. R2, R3) need migrations. Plan how to update `~/.agentfly/config` safely.

**Sources:** Cursor docs and changelogs; Homebrew and pipx best practices; Python packaging guides; agent hook examples (Claude, Codex, Gemini); and a security blog on fail-open vs closed.
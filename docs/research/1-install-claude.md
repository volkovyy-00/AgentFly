# AgentFly v1: Packaging, Global Install and Fail-Mode Design for a Local Cursor Agent Guard

**Ship AgentFly as a Python app in your own Homebrew tap, with a `service do` block. `agentfly init -g` should merge tagged entries into `~/.cursor/hooks.json` that point at a tiny, crash-proof hook shim in a stable user path. The default should be "fail open loudly", with an opt-in strict mode that sets Cursor's `failClosed: true` only on outbound-shell and secret-read gates.** The literal `brew install agentfly` (no tap prefix) is not possible today: homebrew-core's notability bar is far above the repo's current stars, so v1 has to be `brew install volkovyy-00/tap/agentfly`.\[1\]

## TL;DR
- **Install design:** use a custom tap formula built with `virtualenv_install_with_resources`, plus `brew services` (launchd on macOS, systemd user unit on Linux). `agentfly init -g` makes a merge-safe, backed-up edit to `~/.cursor/hooks.json`, pointing at a shim in `~/.local/share/agentfly/bin/`. That shim answers "allow" if AgentFly has been removed, so it never bricks Cursor. Cursor docs say user hooks are global for the local IDE and CLI, but they do not run in cloud agents.
- **Fail mode:** Cursor itself fails open on hook crashes and timeouts, but **blocks on invalid JSON or a schema-invalid reply from permission hooks**. It also documents a per-hook `failClosed` flag. Cursor's own hooks have known bugs: dropped denies, hard-locks when fail-closed, and timeouts on the Windows CLI. So the default should be fail-open with visible warnings and a `doctor` command. Strict mode adds `failClosed: true` only to `beforeShellExecution` and `beforeReadFile`.
- **Multi-agent:** Claude Code, Codex and Gemini CLI all use stdin-JSON / exit-code-2 hook models that are close enough for a single adapter-based hook binary. Config locations, event names, decision schemas and default timeouts differ, though. Codex additionally requires users to trust new hooks before they run.

---

## Key Findings

### 1. What the AgentFly repo looks like today (facts)
All facts here are from the README at https://github.com/volkovyy-00/AgentFly (main, accessed 2026-10-14) and its merged PRs.
- **Architecture:** `hooks/hook.py` runs for each step, drops file contents, posts to `127.0.0.1:8787` and "fails open". The `recorder/` folder holds a FastAPI server (`app.py`, `rules.py`, sessions, command cleaner, Neo4j store). `ui/` is a Vite + React app with a committed build in `ui/dist`, served at `/`.\[2\]
- **Setup:** setup is `uv sync` then `./install.sh`, which "writes .cursor/hooks.json (gitignored, machine-local)".\[2\] The user must mark the folder **trusted** in Cursor. Requirements are Python 3.12+ and uv, and the README says it was "verified on Cursor 3.5.17".\[2\]
- **Local state:**
  - `~/.config/flightrecorder/token` (a random token sent with every request, mode 600)\[2\]
  - `~/.config/flightrecorder/sessions.json`
  - `~/.config/flightrecorder/.env` (Neo4j credentials)\[2\]
  - `logs/events.jsonl` inside the repo
- **A documented foot-gun:** "Do not delete or move `hooks/hook.py` while `.cursor/hooks.json` still points at it. Python exits with code 2 when the file is missing, and Cursor treats exit code 2 as **deny**, which blocks every agent action."\[2\] This is the most important constraint for the global-install design.
- **Recent work:**
  - PR #4 (merged 2026-10-03) caps memory at 500 steps per session and adds `GET /api/steps?limit=N` (https://github.com/volkovyy-00/AgentFly/pull/4). \[3\]
  - PR #5 (merged 2026-10-03) serves `ui/dist` at `/` with explicit routes "so POST /hook can never be shadowed" (https://github.com/volkovyy-00/AgentFly/pull/5). \[4\]
- **Self-declared limits:** it stops only the *next* step; "Cursor's built-in web tools may bypass the hooks"; and "a determined agent can get around it" (for example `cat .en*`, DNS, tunnels).\[2\]

### 2. Cursor hooks today (facts)
Unless noted, everything in this section is from Cursor Docs, Hooks, https://cursor.com/docs/hooks (no date on the page; accessed 2026-10-14).

**Locations and precedence**
- **Enterprise (MDM):**
  - macOS: `/Library/Application Support/Cursor/hooks.json`\[5\]\[6\]
  - Linux/WSL: `/etc/cursor/hooks.json`\[6\]
  - Windows: `C:\ProgramData\Cursor\hooks.json`\[6\]
- **Team:** cloud-distributed (Enterprise only), synced "every thirty minutes".\[6\]
- **Project:** `<project-root>/.cursor/hooks.json`.\[6\]
- **User:** `~/.cursor/hooks.json`.\[6\]
- "Priority order (highest to lowest): Enterprise → Team → Project → User."\[6\]
- "All matching hooks from every source run, and Cursor merges their responses: any `deny` wins over `ask`, and `ask` wins over `allow`, regardless of source." `user_message` and `agent_message` values are concatenated.\[6\]
- **Implication (opinion):** an AgentFly deny from the user-level file can't be overridden by a project's allow.

**Working directory**
- Project hooks run from the project root.\[6\]\[7\]\[8\]
- User hooks run from `~/.cursor/`.\[6\]\[7\]\[8\]
- Enterprise hooks run from the enterprise config dir.\[6\]\[8\]
- Team hooks run from the managed hooks dir.\[6\]\[8\]
- `command` can be a shell string, absolute path or relative path.\[6\]

**Trust**
- "Project hooks run in any trusted workspace" and "Require the workspace to be trusted to run".\[6\] The docs don't state that user-level hooks need workspace trust (not found).
- This is exactly why moving AgentFly from `.cursor/hooks.json` to `~/.cursor/hooks.json` removes the per-repo trust and clone dependency.

**Reload and debugging**
- "Cursor watches `hooks.json` files and reloads them on save". Restarting is the fallback.\[6\]\[7\]
- There's a Hooks tab in **Customize** and a Hooks output channel.\[6\]

**Timeouts**
- Each hook has a `timeout` "in seconds", whose default is "platform default".\[6\] The actual default value: **not found** in the docs. A third-party PR re-checked the page on 2026-10-03 and noted the default timeout is still undocumented (https://github.com/Chemaclass/agnostic-ai/pull/1682, 2026-10-03).\[9\]

**Exit codes and failure behaviour**
- Exit `0` means: use the JSON. "For permission hooks (`beforeShellExecution`, `beforeMCPExecution`, `beforeReadFile`, `beforeTabFileRead`, `subagentStart`, `preToolUse`), invalid JSON or a response that doesn't match the hook's schema blocks the action."\[6\]
- Exit `2` blocks the action.\[6\]
- Any other exit code means "Hook failed, action proceeds (fail-open by default)".\[6\]
- `failClosed: true` makes "crash, timeout, non-zero exit code, no output" block.\[6\]

**Events (current list)**
- *Agent hooks:* `sessionStart`/`sessionEnd`, `preToolUse`/`postToolUse`/`postToolUseFailure`, `subagentStart`/`subagentStop`, `beforeShellExecution`/`afterShellExecution`, `beforeMCPExecution`/`afterMCPExecution`, `beforeReadFile`/`afterFileEdit`, `beforeSubmitPrompt`, `preCompact`, `stop`, `afterAgentResponse`/`afterAgentThought`.\[6\]\[10\]
- *Tab hooks:* `beforeTabFileRead`, `afterTabFileEdit`.\[6\]
- *App lifecycle:* `workspaceOpen`.\[6\]

**Which events can block, and what they return**
- **Permission (blocking):** `preToolUse`, `beforeShellExecution`, `beforeMCPExecution`, `beforeReadFile`, `beforeTabFileRead`, `subagentStart`.\[6\]\[11\]
  - `beforeShellExecution` and `beforeMCPExecution` return `permission: allow|deny|ask` plus `user_message` and `agent_message`.\[6\]\[7\]
  - For `preToolUse`, "`ask` is accepted by the schema but not enforced … today", and the hook can also return `updated_input`.\[6\]\[9\]
  - For `subagentStart`, `ask` is treated as deny.\[6\]
- **Can stop a prompt:** `beforeSubmitPrompt` returns `continue: false`.\[6\]
- **Fire-and-forget:** `sessionStart` ("does not wait for or enforce a blocking response"; it can return `env` and `additional_context`) and `sessionEnd`.\[6\]
- **Observational:** `preCompact`, `afterAgentThought`, `afterAgentResponse`, `afterShellExecution`, `afterMCPExecution`, `afterFileEdit`.\[6\]
- **Loop control:** `stop` and `subagentStop` can return `followup_message` (`loop_limit` defaults to 5).\[6\]

**Common input fields**
- `conversation_id`, `generation_id`, `model`, `model_id`, `model_params`, `hook_event_name`, `cursor_version`, `workspace_roots`, `user_email`, `transcript_path`.\[6\]
- Env vars: `CURSOR_PROJECT_DIR`, `CURSOR_VERSION`, `CURSOR_USER_EMAIL`, `CURSOR_TRANSCRIPT_PATH`, `CURSOR_CODE_REMOTE`, and `CLAUDE_PROJECT_DIR`.\[6\]
- **Privacy note:** `beforeReadFile` input includes `"content": "<file contents>"`, and `afterShellExecution` includes the full terminal `output`.\[6\]

**Cloud agents**
- Cloud agents run project, team and enterprise hooks.\[6\]
- "User-level hooks (`~/.cursor/hooks.json`) are not available in cloud agents."\[6\]
- `beforeMCPExecution`, `sessionStart`/`sessionEnd` and Tab hooks don't run there.\[6\]\[7\]
- **Implication (fact-based):** a global AgentFly install protects only the local IDE and CLI, not Cloud Agents.

**Cursor CLI**
- "They work the same way for the Cursor CLI as in Cursor itself. Hooks are loaded from ~/.cursor/hooks.json (user) and .cursor/hooks.json (project)" (Cursor staff, https://forum.cursor.com/t/cursor-cli-jan-8-2026/148374, 2026-01-09).\[12\]
- The same thread notes the CLI only supported shell hooks earlier in January 2026 (https://forum.cursor.com/t/cursor-cli-doesnt-send-all-events-defined-in-hooks/148316, 2026-01-08).\[13\]

**Claude Code compatibility**
- Cursor loads `.claude/settings.json`, `.claude/settings.local.json` and `~/.claude/settings.json` hooks when "Include Third-Party Plugins, Skills, and Other Configs" is enabled (https://cursor.com/docs/reference/third-party-hooks, accessed 2026-10-14).\[6\]\[14\]

**Partner program**
- The docs list MintMCP, Oasis Security, Runlayer, Corridor, Semgrep, Endor Labs, Snyk (Evo Agent Guard) and 1Password as hooks partners (https://cursor.com/docs/hooks, accessed 2026-10-14).\[6\]

**Changelog items relevant to AgentFly**

| Date / version | Change | Source |
|---|---|---|
| 2026-01-08 (CLI) | "Hooks now execute in parallel with merged responses"; "Hooks execution latency reduced by 10x"; `afterFileEdit` now provides `old_string` | https://cursor.com/changelog/cli-jan-08-2026 \[15\] |
| 2026-01-16 (CLI) | Hooks for session start/end, prompt and stop added | https://cursor.com/changelog/cli-jan-16-2026 \[16\] |
| 2.4, 2026-01-22 | stop, `beforeSubmitPrompt` prompt modification, PreToolUse/PostToolUse; "Hook commands now start 40x faster"; team and MDM hooks in CLI; Claude Code hook compatibility in CLI | https://cursor.com/changelog/2-4 \[17\] |
| CLI, 2026-05-20 | "Hooks accept payloads over stdin" | https://cursor.com/docs/cli/changelog \[18\] |
| 2026-07-28 | New cloud-agent hooks (`beforeSubmitPrompt`, `afterAgentResponse`, `afterAgentThought`, `stop`, `subagentStart` …) | https://cursor.com/changelog/page/3 \[19\] |
| CLI v2026.08.11 | Plugin hooks execute from installed plugins | https://cursor.com/docs/cli/changelog \[18\] |
| Week of 2026-09-28 | `preToolUse`/`postToolUse` receive `parent_tool_call_id`; `subagentStop` receives `child_conversation_id` | https://cursor.com/docs/release-notes \[20\] |
| 3.23, 2026-10-01 | Windows hooks pointing at extensionless scripts previously "opened a new console window, never received their input, and reported success without doing anything"; fixed | https://cursor.com/docs/release-notes \[20\] |
| 3.24, 2026-10-09 | Shell and MCP execution hooks now receive a `tool_use_id` matching `preToolUse`; every hook gets the `.jsonl` transcript in `transcript_path` | https://cursor.com/docs/release-notes \[20\] |

Renamed or deprecated hook events: **not found**.

**Known Cursor hook bugs that matter for a guard (facts, community reports)**
- **Race condition:** "responses from fast hooks to be ignored … When that hits a preToolUse hook returning {"permission":"deny"}, the deny gets dropped and the command runs". Still reproducible on Linux in Cursor 3.11.19 (https://forum.cursor.com/t/race-condition-silently-disables-hooks-that-exit-quickly/165818). \[21\]
- **Windows CLI timeouts:** in headless mode, "every hook invocation blocks its tool call for the FULL configured timeout", and lowering the timeout "silently disables deny-hooks" (https://forum.cursor.com/t/cli-hooks-block-each-tool-call-for-the-full-timeout-lowering-it-silently-disables-deny-hooks-windows/169942, 2026-09-05).\[22\]
- **Fail-closed hard-lock:** "Agent Shell tool calls intermittently fail closed with a Cursor-internal error" when `failClosed: true`, with `MainThreadShellExec not initialized` (https://forum.cursor.com/t/agent-shell-hard-locks-fail-closed-beforeshellexecution-mainthreadshellexec-not-initialized/165215, 2026-07-08).\[23\]
- **Request for a failure event:** a feature request says the workaround for that hard-lock "is failClosed: false, which means hook crashes silently allow the tool through" (https://forum.cursor.com/t/add-afterpretoolusefailure-hook-when-a-pre-tool-hook-itself-fails/168653). \[24\]
- **Unknown event names:** on cursor-agent 2026.10.01, "a workspace .cursor/hooks.json that registers an event name the CLI doesn't know stops the file's other hooks from running, including beforeShel[lExecution]" (https://github.com/aguil/agents/issues/239). \[25\]
- **`ask` not enforced:** "Right now hooks only enforce the deny permission" (Cursor staff, https://forum.cursor.com/t/the-cursor-hooks-did-not-execute-as-expected/155711, 2026-03-26).\[26\]
- **Imported Claude hooks fail open:** a Cursor forum thread, "cursor-agent imported Claude Code plugin hooks get a Cursor-shaped payload so PreToolUse gates fail open" (2026-09-27), reports that converted Claude Code hooks "are always `failClosed: false`, receive `tool_name: "Shell"` instead of `"Bash"`", and drop the legacy `{"decision": "block"}` shape (https://forum.cursor.com/t/cursor-agent-imported-claude-code-plugin-hooks-get-a-cursor-shaped-payload-so-pretooluse-gates-fail-open/173171; summarized at https://www.developersdigest.tech/blog/coding-agent-hooks-fail-open-vs-fail-closed-2026, 2026-10-09).
- **Cursor disabling git hooks:** Cursor's git extension forced `core.hooksPath=/dev/null` from 3.15.6, silently skipping pre-commit and Husky hooks (https://forum.cursor.com/t/git-hooks-silently-skipped-for-all-source-control-operations-since-3-15-6-git-extension-forces-core-hookspath-dev-null/167719). \[27\] This is a reminder that the host can silently change hook behaviour.

### 3. Packaging a Python CLI plus local server (facts)
**homebrew-core vs. a tap**
- homebrew-core notability requires "at least 30 forks, 30 watchers or 75 stars", or "90 forks, 90 watchers or 225 stars for a self-submission by the repository owner". "A code repository less than 30 days old is normally not eligible" (https://docs.brew.sh/Package-Acceptance-Policy, accessed 2026-10-14).\[1\]
- AgentFly shows 1 star and 0 forks (repo page, accessed 2026-10-14).\[2\]\[4\]

**Tap trust (Homebrew 6.0.0, 2026-06-11)**
- "Homebrew now requires taps … to be explicitly trusted before their code is evaluated or run" (https://brew.sh/2026/06/11/homebrew-6.0.0/, 2026-06-11).\[28\]\[29\]
- "Installing a fully qualified formula or cask name trusts only that item: `brew install user/repository/formula`". Installing by short name needs `brew tap` plus `brew trust --formula …` first (https://github.com/Homebrew/brew/blob/main/docs/Tap-Trust.md, last reviewed 2026-07-18).\[30\]

**Python formulas**
- "Applications must be installed into a Python virtual environment rooted in `libexec`", and "all the Python module dependencies … should be declared as `resource`s" (Homebrew "Python for Formula Authors", mirror at https://docs.w3cub.com/homebrew/python-for-formula-authors, accessed 2026-10-14).\[31\]
- `virtualenv_install_with_resources` "Creates a virtualenv in libexec, installs all resources … then installs the formula" (https://rubydoc.brew.sh/Language/Python/Virtualenv.html, accessed 2026-10-14).\[32\]

**Services**
- A `service do` block lets `brew services` generate launchd plists and systemd units (https://docs.brew.sh/Formula-Cookbook, accessed 2026-10-14).\[33\]\[34\]
- Without `sudo`, brew services operates "on `~/Library/LaunchAgents` or `~/.config/systemd/user` (started at login)" (https://docs.brew.sh/Manpage, accessed 2026-10-14).\[35\]\[36\]
- The launchd label is `homebrew.mxcl.<name>`. On Linux the unit is `homebrew.<name>.service` (example `homebrew.ollama.service`, https://github.com/orgs/Homebrew/discussions/6196, 2026-04).\[37\]\[38\]\[39\]

**Uninstall**
- After `brew uninstall`, "a homebrew.mxcl.postgresql@13.plist service still existed in ~/Library/LaunchAgents". A 2025-03-22 reply says it "just leaves the plist" (https://github.com/orgs/Homebrew/discussions/4659). \[40\]
- A formula uninstall hook: **not found**. In practice, `brew uninstall` will not clean `~/.cursor/hooks.json`.

**uv / pipx**
- `uv tool install` installs "user-wide" into an isolated environment and puts executables on PATH (by default `~/.local/bin`).\[41\]\[42\]
- `uv tool upgrade` respects install-time version constraints.\[41\]
- `uv tool uninstall` removes the tool's environment and executables (https://docs.astral.sh/uv/guides/tools/, accessed 2026-10-14; https://pydevtools.com/handbook/reference/uvx/). \[43\]

**Standalone binaries**
- PyInstaller one-file builds extract to a temp `_MEIxxxxxx` folder on every launch, so they are "a little slower to start up than the one-folder bundle" (https://pyinstaller.org/en/stable/operating-mode.html, PyInstaller 6.22.3 docs).\[44\]
- On macOS, a user reports signed and notarized one-file binaries "easily could take up to 11 seconds to start" because of per-run Apple verification. A maintainer-quoted line says "macOS isn't generally suited to onefile mode" (https://github.com/pyinstaller/pyinstaller/discussions/8167). \[45\]
- Status of Nuitka, shiv, PyOxidizer and python-build-standalone: **not researched in depth (not found in this session)**.

**Per-call interpreter cost**
- In one measurement on Linux with Python 3.13, "Ten runs of bare python3 -c pass took 0.14 s, about 14 ms". A 6,500-line hook.py took "about 87 ms per call", and "Compiling hook.py alone took about 47 ms" (https://github.com/Ajw2003/AjsClaudeCodeTools/issues/204, 2026-10-09).
- In escoffier-labs/brigade PR #1567 (merged 2026-09-30), a no-op hook call dropped from 392 ms to 62 ms. The old cost was "nearly all of it Python startup", and the new `brigade-hook` entry point runs without importing the full CLI (https://github.com/escoffier-labs/brigade/pull/1567).
- In akasecurity/ai-tc issue #631 (2026-09-30), bare `node -e ''` measured p50 110 ms / p95 118 ms and a full hook about 204–211 ms, while "Detection itself costs ~7 ms" (https://github.com/akasecurity/ai-tc/issues/631).

### 4. How comparable tools install global hooks, and what went wrong (facts)
**GitGuardian ggshield**
- `ggshield machine setup` "detects which agents you have installed and writes the correct hook configuration for each one". It writes `~/.cursor/hooks.json` for Cursor and `~/.claude/settings.json` for Claude Code, and supports a per-repo `-m local` mode.\[46\]
- It fails open by design: "This fail-open design keeps your AI coding tool usable when ggshield is misconfigured". `ggshield machine doctor` "reports whether each agent's hook is installed" (https://docs.gitguardian.com/ggshield-docs/integrations/ai-coding-tools/secret-scanning-for-ai-coding-tools, accessed 2026-10-14).\[46\]

**Other agent guards**
- **moat-kernel:** its installer writes "every entry with **failClosed: true**, since Cursor is fail-open by default", and reports moved binaries as stale and updates them in place (https://github.com/agentmoat/moat-kernel/pull/15, 2026-10-03).\[47\]
- **workit:** reversed course after an audit, to "Every event has failClosed: false. Cursor's failClosed can't tell a launcher failure from a policy decision", and pinned a local launcher instead of `npx …@latest` (https://github.com/BrainerVirus/workit/pull/233, Oct 2026).\[48\]
- **shiplino:** registers observe-only hooks with a 5 s timeout and deliberately never registers permission hooks, "where missing output means "deny"" (https://github.com/elephaant/shiplino/pull/56). \[49\]
- **Skylos:** "The hooks fail open on purpose", and records unchecked actions to `.skylos/cache/hook-fail-open.json`, surfacing them at stop (https://skylos.dev/use-cases/ai-coding-agent-hooks). \[50\]
- **Endor Labs:** documents `~/.cursor/hooks.json` for single developers and `/Library/Application Support/Cursor/hooks.json` via MDM for fleets (https://docs.endorlabs.com/agent-governance/cursor). \[5\]

**Git hook managers**
- lefthook, when a global `core.hooksPath` exists, renames the global `pre-commit` to `.old`: "Previous configuration has been erased". Husky overwrites the local `core.hooksPath` (https://github.com/evilmartians/lefthook/issues/1248). \[51\]
- "`prepare: husky` sets a repo-local core.hooksPath … which shadows the user's global hooks. The global secret scan never ran" (https://github.com/alex-mextner/HyperSummaryBot/pull/44). \[52\]
- **Lesson:** never replace or rename someone else's hook entry. Merge and tag your own.

**Expert guidance on fail modes**
- "fail closed when the action is irreversible or the threat is adversarial; fail open, loudly, when the hook is a convenience and an outage costs more than a miss" (Developers Digest, https://www.developersdigest.tech/blog/coding-agent-hooks-fail-open-vs-fail-closed-2026, 2026-10-09). This is an opinion piece. Only its Claude Code column was tested by the author.\[11\]

### 5. Other agents' hook models (facts)

| | Cursor | Claude Code | OpenAI Codex CLI | Gemini CLI |
|---|---|---|---|---|
| User config | `~/.cursor/hooks.json` | `~/.claude/settings.json` (`hooks` key) | `~/.codex/hooks.json` or `[hooks]` in `~/.codex/config.toml` | `~/.gemini/settings.json`\[6\]\[53\]\[54\] |
| Project config | `.cursor/hooks.json` (trusted workspace) | `.claude/settings.json`, `.claude/settings.local.json` | `<repo>/.codex/hooks.json` / `config.toml` (only if project layer trusted) | `.gemini/settings.json`\[6\]\[53\] |
| Managed | MDM paths + Team dashboard | Managed policy settings; `allowManagedHooksOnly` | `requirements.toml`; `allow_managed_hooks_only` | `/etc/gemini-cli/settings.json` (system) |
| Pre-tool event | `preToolUse` + `beforeShellExecution`/`beforeMCPExecution`/`beforeReadFile` | `PreToolUse` | `PreToolUse` | `BeforeTool` |
| Prompt event | `beforeSubmitPrompt` | `UserPromptSubmit` | `UserPromptSubmit` | `BeforeAgent` |
| Deny shape | top-level `{"permission":"deny"}` | `hookSpecificOutput.permissionDecision: "deny"` | `hookSpecificOutput.permissionDecision` or `{"decision":"block"}` | `{"decision":"deny","reason":…}` |
| Exit 2 | blocks | blocks | blocks | blocks |
| Default timeout | "platform default" (value not found) | 600 s (command) | 600 s | 60 s |
| Failure default | fail-open; invalid JSON on permission hooks blocks; `failClosed` opt-in | fail-open; `onFailure: "block"` since v2.1.295 (command and HTTP hooks only) | a PreToolUse error, timeout or malformed response can fail without blocking; no fail-closed switch documented; trust required | fail-open per docs: other exit codes proceed with original parameters, non-JSON stdout defaults to "Allow" |

Sources for the table:
- Cursor: https://cursor.com/docs/hooks (accessed 2026-10-14).
- Claude Code: https://code.claude.com/docs/en/hooks (accessed 2026-10-14). This page lists 30+ events, including `PermissionRequest`, `SessionStart`/`SessionEnd`, `Stop` and `SubagentStop`, and says "Hook entries merge across settings levels rather than replacing each other".\[55\] `onFailure: "block"` was added in v2.1.295 on 2026-10-08. With it, "a hook that can't start, times out, or exits with an unexpected code blocks the action instead of letting it through", for command and HTTP hooks only (per https://www.developersdigest.tech/blog/coding-agent-hooks-fail-open-vs-fail-closed-2026, 2026-10-09).
- Codex: https://developers.openai.com/codex/hooks (undated, accessed 2026-10-14):
  - "Non-managed hooks must be reviewed and trusted before they run … new or changed hooks are marked for review and skipped until trusted."\[11\]\[53\]
  - "Treat tool hooks as a useful guardrail, not a complete enforcement boundary."\[11\]\[53\]
  - For managed hooks, "a `PreToolUse` callback error, timeout, or malformed response can fail the hook without blocking the tool".
  - Events: PreToolUse, PermissionRequest, PostToolUse, PreCompact, PostCompact, UserPromptSubmit, SubagentStart, SubagentStop, Stop, Interrupt, SessionStart, SessionEnd.\[53\]\[56\]
- Gemini CLI: https://geminicli.com/docs/hooks/ (accessed 2026-10-14) gives precedence "Project … User … System … Extensions".\[57\] The 60 s timeout and fail-open default come from https://www.developersdigest.tech/blog/coding-agent-hooks-fail-open-vs-fail-closed-2026 (2026-10-09). That piece quotes the Gemini docs: for any other exit code "the interaction proceeds using original parameters", and non-JSON stdout means "the CLI will default to 'Allow'". It also notes that the `hookRunner.ts` source turns other non-zero, non-JSON exits into a deny, and reports that Gemini CLI v0.63.0 still ships while "most individual users moved to Antigravity CLI after the June transition".
- GitHub Copilot, Windsurf, Cline, Kiro, Amp and Factory hook models: **not researched (not found in this session)**. ggshield lists copilot, junie, kiro, vibe and vscode as hook targets, which suggests those hosts have hook systems (https://docs.gitguardian.com/ggshield-docs/integrations/ai-coding-tools/secret-scanning-for-ai-coding-tools). \[46\]

---

## Recommendations (opinion, grounded in the facts above)

### A. Packaging decision
1. **Primary channel: your own tap, `volkovyy-00/homebrew-tap`, with a `Formula/agentfly.rb`.** It uses `include Language::Python::Virtualenv`, `depends_on "python@3.12"` (or 3.13), all PyPI deps as `resource` blocks (generate them with `brew update-python-resources`), `virtualenv_install_with_resources`, and a `service do` block. Users run `brew install volkovyy-00/tap/agentfly`. Under 6.0.0 tap trust, that fully-qualified form trusts only that formula and works in one line.\[30\]
2. **Secondary channel: PyPI plus `uv tool install agentfly` and `pipx install agentfly`.** This is the same wheel, with the prebuilt `ui/dist` shipped as package data via `importlib.resources`. Linux users and non-Homebrew users get the same CLI.
3. **Do not ship PyInstaller one-file binaries in v1.** Startup extraction and macOS notarization latency would hit every hook call. Revisit a compiled hook client (Go or Rust, about 1–5 ms) only if measured p95 hook latency matters.
4. **Make the hook client separate and tiny.** Use a stdlib-only module (`agentfly_hook.py`: `json`, `urllib`/`http.client`, `socket`, no FastAPI or Neo4j imports) launched with `python -I -S`. This keeps per-call cost near the roughly 14 ms bare-interpreter floor instead of the 60–390 ms seen when hooks import a full CLI.
5. **Defer homebrew-core** until the repo clears 225 stars (self-submission) or 75 stars (third-party submission). Only then does literal `brew install agentfly` work.

### B. Exact files touched (macOS / Linux; Windows not in v1)

| Purpose | macOS | Linux | Written by |
|---|---|---|---|
| App venv (versioned) | `$(brew --prefix)/Cellar/agentfly/<ver>/libexec/` | `/home/linuxbrew/.linuxbrew/Cellar/agentfly/<ver>/libexec/` (or `~/.local/share/uv/tools/agentfly/`) | brew / uv |
| Stable app path | `$(brew --prefix)/opt/agentfly/` → current version | same | brew |
| CLI | `$(brew --prefix)/bin/agentfly` | same / `~/.local/bin/agentfly` | brew / uv |
| **Hook shim (stable)** | `~/.local/share/agentfly/bin/agentfly-hook` (POSIX sh, 0755) | same | `agentfly init -g` |
| Cursor hooks | `~/.cursor/hooks.json` (merged; backup `~/.cursor/hooks.json.agentfly-backup-<ts>`) | same | `init -g` |
| Config | `~/.config/agentfly/config.toml` (mode, port, rules) | same | `init -g` |
| Secrets | `~/.config/agentfly/token`, `~/.config/agentfly/neo4j.env` (dir 700, files 600) | same | recorder / `agentfly neo4j setup` |
| State | `~/.local/share/agentfly/sessions.json`, `events.jsonl`, `hook-failopen.jsonl` | same | recorder / shim |
| Service | `~/Library/LaunchAgents/homebrew.mxcl.agentfly.plist` | `~/.config/systemd/user/homebrew.agentfly.service` | `brew services` (via `agentfly start`) |
| Service (uv/pipx installs) | `~/Library/LaunchAgents/dev.agentfly.recorder.plist` | `~/.config/systemd/user/agentfly.service` | `agentfly start` |
| Logs | `$(brew --prefix)/var/log/agentfly.log` | same / `journalctl --user -u agentfly` | service |
| Migration | read then move `~/.config/flightrecorder/*` | same | `init -g` |

**Notes on the design**
- **XDG on macOS too.** I chose XDG paths on macOS as well, to match the repo's existing `~/.config/flightrecorder` habit and keep one code path. `~/Library/Application Support/agentfly` is an acceptable alternative.
- **Why a shim in a user path instead of pointing hooks.json at the Cellar or opt path:**
  - (a) Cellar paths change on every upgrade.
  - (b) If someone runs `brew uninstall` without `agentfly uninstall`, a missing Python target would exit 2 (the README's documented deny-everything trap). The `/bin/sh` shim checks `[ -x "$TARGET" ]` and otherwise prints `{"permission":"allow"}` with a one-line stderr warning, then exits 0.
  - (c) `failClosed` handling stays under your control.
- **hooks.json entries:** `init -g` writes one entry per event, each with an absolute path, an explicit `timeout`, and an identifying marker. Example: `"command": "/Users/me/.local/share/agentfly/bin/agentfly-hook cursor beforeShellExecution", "timeout": 5`. Ownership is detected by the `agentfly-hook` substring. The merge only appends to or replaces AgentFly-owned array items, preserves key order and other tools' entries, writes atomically (temp file plus rename), and keeps a timestamped backup. Re-running it is idempotent.
- **Events to register in v1:**
  - Permission gates: `beforeShellExecution`, `beforeReadFile`, `beforeMCPExecution`.
  - Lifecycle and audit: `afterFileEdit`, `sessionStart`, `sessionEnd`, `stop`.
  - Drop the duplicate `preToolUse` for Shell: Cursor fires both, and the 3.24 `tool_use_id` lets you dedupe if you keep it.
  - Do **not** register `beforeSubmitPrompt`, `afterAgentResponse` or `afterAgentThought`. They carry prompt, response and reasoning text, which contradicts the product's "no messages stored" promise.
  - Gate registration on `cursor --version` or the first-seen `cursor_version`, because an unknown event name can silently disable the whole file on some CLI builds.
- **Upgrade:** `brew upgrade` replaces the Cellar. The opt symlink and user shim stay valid, and `brew services` restarts the recorder.
  - `agentfly` should check a `schema_version` in config on start and rewrite hooks.json entries if the shim or flags changed.
  - On a mismatch, `agentfly doctor` (run by `start`) flags stale entries, like moat's "Stale" detection.
- **Uninstall:** `agentfly uninstall [--purge]` does the following, and the formula `caveats` tells users to run it **before** `brew uninstall`:
  1. Stops the service: `brew services stop agentfly`, or `launchctl bootout` / `systemctl --user disable --now` for uv installs.
  2. Removes only AgentFly-owned entries from `~/.cursor/hooks.json`, deleting the file only if it then contains no hooks.
  3. Removes the shim.
  4. With `--purge`, deletes the config and data dirs.
  - `init --remove` is an alias. If the user forgets, the shim's allow-if-missing behaviour plus `brew services cleanup` limits the damage.

### C. Fail-open vs. fail-closed
**Facts that constrain the choice**
- Cursor fails open on crash or timeout, but blocks on invalid or empty JSON from permission hooks.\[6\] That means a half-written stdout or a Python traceback is effectively a deny.
- `failClosed: true` exists, but it has a documented hard-lock bug and can't distinguish infrastructure failure from policy.
- A deny can be dropped by a race condition.
- Windows CLI timeouts can silently fail open.
- Peers split: ggshield, workit, shiplino and Skylos choose fail-open, while moat chooses fail-closed.

**Recommendation (opinion)**
1. **The hook client must never produce invalid output.** Wrap everything in `try/except BaseException`. Always print exactly one JSON object and exit 0, except for an explicit deny, which uses JSON `permission: deny` plus exit 0, not exit 2. Never let Python's own exit 2 (a missing file) reach Cursor.
2. **The default mode is `observe-and-guard`, fail-open loudly.**
   - Use a 300 ms connect and 1.5 s total budget to `127.0.0.1:8787`.
   - If the recorder is down, return `allow`, with `agent_message` / `user_message` saying "AgentFly recorder offline — actions are not being checked".
   - Append to `hook-failopen.jsonl`, and replay a count into the next session when the recorder comes back (like Skylos).
   - Set the hooks.json `timeout` to 5 s, so a hung client fails open quickly rather than at the platform default.
3. **An opt-in `strict` mode (`agentfly init -g --strict`) for security-sensitive users:**
   - Writes `failClosed: true` only on `beforeShellExecution` and `beforeReadFile`.
   - When the recorder is unreachable, the client applies a **stateless offline subset** of R1: deny commands matching the outbound list (`curl`, `wget`, `nc`, `scp`, `ssh`, `rsync`, `git push`, `gh`, `aws`, http one-liners, except localhost and private ranges). Everything else is allowed, so a dead recorder breaks exfiltration, not coding.
   - Never fail-closed on `afterFileEdit`, `sessionStart` or `stop`.
4. **Per-rule behaviour in config:** each rule declares `on_error: allow|deny`, and R1 defaults to `deny` in strict mode and `allow` otherwise.
5. **Don't rely on `ask`.** Cursor doesn't enforce it for `preToolUse`, and staff said only deny is enforced. Use deny with a clear `agent_message`.
6. **Visibility beats silence.**
   - `agentfly doctor` checks: service running, port bound, token present, hooks.json entries present and pointing at an executable shim, a Cursor version that supports the registered events, and a live synthetic hook round-trip.
   - The UI shows a red banner when a fail-open has happened since the last view.

### D. Step list to ship v1
1. **Refactor the repo into an installable package.** Create a `src/agentfly/` package with `cli.py` (Typer or argparse), `recorder/` (unchanged FastAPI), `hook_client.py` (stdlib-only), `adapters/cursor.py`, and `ui_dist/` as package data. Add the `[project.scripts] agentfly` and `agentfly-hook` entry points. Make Neo4j an optional extra (`agentfly[neo4j]`).
2. **Move state out of the repo:** use the XDG paths above, and migrate `~/.config/flightrecorder`. Replace the repo-relative `logs/events.jsonl` path.
3. **Harden the hook client:**
   - Guarantee valid JSON output in every case.
   - Enforce the timeout budget.
   - Keep dropping `content` and `output` fields.
   - Dedupe by `tool_use_id`.
   - Use session id = `conversation_id`.
   - Read the token at `~/.config/agentfly/token`.
   - Measure p50/p95 latency and target under 50 ms p95 locally.
4. **Write the CLI commands:**
   - `agentfly init -g [--strict] [--agent cursor]`: merge-safe hooks.json writer, shim writer, config, backup.
   - `agentfly start|stop|status`: delegate to `brew services` when `HOMEBREW_PREFIX/opt/agentfly` exists; otherwise write and load your own LaunchAgent (`RunAtLoad`, `KeepAlive`) or systemd user unit.
   - `agentfly doctor`.
   - `agentfly uninstall [--purge]`.
   - `agentfly open` (browser to 127.0.0.1:8787).
5. **Handle the port:** bind 127.0.0.1 only, and make the port configurable. On conflict, `start` fails with a clear message, and the shim reads the port from config. Keep the Host-header gate and the token on `POST /hook`.
6. **Build and release:** a GitHub Actions workflow builds the `ui/` once, builds the sdist and wheel, and publishes to PyPI on tag. A second job bumps the tap formula (url, sha256, `brew update-python-resources`) and runs `brew install --build-from-source`, `brew test` and `brew audit --strict` on macOS and Linux.
7. **Write the formula:** `service do` with `run [opt_bin/"agentfly", "serve"]`, `keep_alive true`, and `log_path var/"log/agentfly.log"`. The `caveats` tell the user to run `agentfly init -g` and `agentfly start`, and to run `agentfly uninstall` before `brew uninstall`. Add a `test do` block that pipes a fake `beforeShellExecution` payload through `agentfly-hook` with no server and asserts that the JSON allows it.
8. **Run an end-to-end matrix:** Cursor IDE and `cursor-agent` CLI on macOS (arm64) and Linux. Cover a trusted and an untrusted project, the recorder up and down, `--strict` on and off, an existing third-party `~/.cursor/hooks.json` (for example ggshield), an upgrade, and uninstall.
9. **Document the limits:** Cloud Agents are not covered, web tools may bypass hooks, the deny-race bug exists, and it is a tripwire, not a sandbox.
10. **Plan the post-v1 adapters:** `--agent claude-code` (merge into `~/.claude/settings.json`, `onFailure: "block"` in strict mode, `hookSpecificOutput` replies), `--agent codex` (`~/.codex/hooks.json`, telling the user to trust the hooks via `/hooks`), and `--agent gemini` (`~/.gemini/settings.json`, `BeforeTool`). One `agentfly-hook <agent> <event>` binary normalizes input to an internal `Step{agent, session, kind(shell|read|edit|mcp), target}` and renders each agent's decision shape. If Cursor imports Claude hooks, AgentFly will see events twice; detect `cursor_version` and skip, as shiplino does.

---

## Risks
- **Cursor API churn and bugs (high):**
  - A dropped deny under concurrency.
  - Fail-closed hard-locks.
  - Unknown events silently disabling a file.
  - Windows CLI timeout behaviour.
  - The timeout default is undocumented.
  - Mitigations: version-gated event registration, `doctor`, a CI smoke test against current Cursor builds, and keeping strict mode narrow.
- **False sense of security (high):** hooks don't cover Cloud Agents. A read secret has already reached the model, `cat .en*`, DNS and tunnels bypass R1, and Codex's own docs call hooks "not a complete enforcement boundary".\[6\]\[53\] Market AgentFly as a flight recorder and tripwire.
- **Bricking the agent (medium):** any invalid JSON or exit 2 on permission hooks blocks actions. Mitigations: the shim's allow-if-missing behaviour, the never-crash client, and tests that kill the recorder mid-call.
- **Clobbering other tools' hooks (medium):** git-hook managers have erased or shadowed each other's hooks. Mitigations: merge only tagged entries, atomic writes, backups, and handling a JSON file the user edits concurrently by re-reading before writing.
- **Privacy (medium):** Cursor sends file contents, shell output, prompts and reasoning to hooks. Keep content dropping in the client (before any network hop), don't register text events by default, and keep Neo4j off by default. `user_email` is available too; don't persist it unless the user opts in.
- **Local attack surface (medium):** any local process can hit 127.0.0.1:8787. Keep the token (mode 600) and Host checks, and consider a Unix domain socket in `~/.local/share/agentfly/` for the hook path. The agent could also try to edit `~/.cursor/hooks.json` or kill the service. Rule R0 ("protect the recorder's own files and process") is specified but not built, and should ship in v1.\[2\]
- **Performance (low–medium):** keep the Python client stdlib-only. Cursor's hooks are parallel since January 2026, but each permission hook is still on the critical path.
- **Packaging (low–medium):** the tap-only distribution means `brew install agentfly` without a prefix won't work until notability is met. `brew uninstall` leaves LaunchAgent plists behind. Python formula resources need upkeep on each dependency bump.
- **Platform (low for v1):** Windows hooks have had many issues (extensionless scripts fixed only in 3.23, PowerShell/bash mismatches).\[20\]\[58\] Declare Windows unsupported in v1. Cursor's Windows enterprise path is `C:\ProgramData\Cursor\hooks.json` if it's needed later.

## Caveats
- Many Cursor and Claude doc pages carry no publication date. They are cited as "accessed 2026-10-14" and may change without notice.
- Some facts come from community forum reports or third-party blogs (Developers Digest, GitHub PRs and issues), not vendor docs. They are flagged as such above.
- Not found in this research: Cursor's default hook timeout value; whether user-level hooks require any trust prompt; Homebrew formula uninstall hooks; and detailed hook models for Copilot, Windsurf, Cline, Kiro, Amp and Factory.

## Sources

1. [Homebrew Documentation: Package Acceptance Policy](https://docs.brew.sh/Package-Acceptance-Policy)
2. [GitHub - volkovyy-00/AgentFly: Flight Recorder for AI coding agents](https://github.com/volkovyy-00/AgentFly)
3. [AG-30: keep long sessions light, with landmarks in reach by volkovyy-00 · Pull Request #4 · volkovyy-00/AgentFly · GitHub](https://github.com/volkovyy-00/AgentFly/pull/4)
4. [AG-31: one page at /, /v2/ redirects by volkovyy-00 · Pull Request #5 · volkovyy-00/AgentFly · GitHub](https://github.com/volkovyy-00/AgentFly/pull/5)
5. [Deploy hooks for Cursor - Endor Labs Documentation](https://docs.endorlabs.com/agent-governance/cursor)
6. [Hooks | Cursor Docs](https://cursor.com/docs/hooks)
7. [cv usk on X: "# Cursor Features and Practical Usage 🪝 Want to bake "auto-format on edit" or "block dangerous commands" into the agent's behavior? Cursor Hooks let you intervene at each stage of the agent loop. 🏷️ Title: Agent Loop Interception (JSON) 🔗 URL: https://t.co/rycdmi85RH 📘 Overview… / X](https://x.com/cv_usk/status/2098238349081280611)
8. [Hooks](https://prod.cursor.com/docs/hooks)
9. [feat(hooks): run Cursor hooks on an assumed shell and timeout by Chemaclass · Pull Request #1682 · Chemaclass/agnostic-ai · GitHub](https://github.com/Chemaclass/agnostic-ai/pull/1682)
10. [AI Coding Assistant Hooks API - TrueFoundry Docs](https://www.truefoundry.com/docs/platform/cursor-hooks)
11. [Do Your Agent Hooks Fail Open? Claude Code vs Codex vs Cursor vs Gemini CLI](https://www.developersdigest.tech/blog/coding-agent-hooks-fail-open-vs-fail-closed-2026)
12. [Cursor CLI (Jan 8, 2026) - Release Discussions - Cursor - Community Forum](https://forum.cursor.com/t/cursor-cli-jan-8-2026/148374)
13. [Cursor CLI doesn't send all events defined in hooks - Help - Cursor - Community Forum](https://forum.cursor.com/t/cursor-cli-doesnt-send-all-events-defined-in-hooks/148316)
14. [Third Party Hooks](https://cursor.com/docs/reference/third-party-hooks)
15. [New CLI Features and Improved CLI Performance · Cursor](https://cursor.com/changelog/cli-jan-08-2026)
16. [CLI Agent Modes and Cloud Handoff · Cursor](https://cursor.com/changelog/cli-jan-16-2026)
17. [Subagents, Skills, and Image Generation · Cursor](https://cursor.com/changelog/2-4)
18. [Cursor CLI changelog](https://cursor.com/docs/cli/changelog)
19. [Changelog · Cursor](https://cursor.com/changelog/page/3)
20. [Release notes](https://cursor.com/docs/release-notes)
21. [Race condition silently disables hooks that exit quickly - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/race-condition-silently-disables-hooks-that-exit-quickly/165818)
22. [CLI hooks block each tool call for the full timeout; lowering it silently disables deny-hooks (Windows) - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/cli-hooks-block-each-tool-call-for-the-full-timeout-lowering-it-silently-disables-deny-hooks-windows/169942)
23. [Agent Shell hard-locks: fail-closed beforeShellExecution + MainThreadShellExec not initialized - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/agent-shell-hard-locks-fail-closed-beforeshellexecution-mainthreadshellexec-not-initialized/165215)
24. [Add afterPreToolUseFailure hook when a pre-tool hook itself fails - Feature Requests - Cursor - Community Forum](https://forum.cursor.com/t/add-afterpretoolusefailure-hook-when-a-pre-tool-hook-itself-fails/168653)
25. [hooks: an unknown event in Cursor's hooks.json silently disables the policy bridge · Issue #239 · aguil/agents](https://github.com/aguil/agents/issues/239)
26. [The cursor hooks did not execute as expected - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/the-cursor-hooks-did-not-execute-as-expected/155711)
27. [Git hooks silently skipped for all Source Control operations since 3.15.6 — git extension forces \`core.hooksPath=/dev/null\` - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/git-hooks-silently-skipped-for-all-source-control-operations-since-3-15-6-git-extension-forces-core-hookspath-dev-null/167719)
28. [\[Feature\] Submit unic to homebrew-core so installs don't need brew trust · Issue #376 · DevopsArtFactory/unic](https://github.com/DevopsArtFactory/unic/issues/376)
29. [Homebrew: 6.0.0](https://brew.sh/2026/06/11/homebrew-6.0.0/)
30. [brew/docs/Tap-Trust.md at main · Homebrew/brew · GitHub](https://github.com/Homebrew/brew/blob/main/docs/Tap-Trust.md)
31. [Python for Formula Authors - Homebrew - W3cubDocs](https://docs.w3cub.com/homebrew/python-for-formula-authors)
32. [Module: Language::Python::Virtualenv — Homebrew Ruby API](https://rubydoc.brew.sh/Language/Python/Virtualenv.html)
33. [Homebrew Documentation: Formula Cookbook](https://docs.brew.sh/Formula-Cookbook)
34. [brew/docs/Formula-Cookbook.md at master · Homebrew/brew · GitHub](https://github.com/Homebrew/brew/blob/master/docs/Formula-Cookbook.md?spm=a2c6h.13046898.publish-article.98.438a6ffakSFpsF&file=Formula-Cookbook.md)
35. [brew-services man](https://linuxcommandlibrary.com/man/brew-services)
36. [Homebrew Documentation: brew(1)](https://docs.brew.sh/Manpage)
37. [Service: add systemd support by SMillerDev · Pull Request #350 · Homebrew/homebrew-services](https://github.com/Homebrew/homebrew-services/pull/350/files)
38. [Homebrew Services Tutorial: Start, Stop & Manage Services on Mac (2025)](https://taphouse.multimodalsolutions.gr/guide/homebrew-services-tutorial)
39. [Environment Variables and \`brew services\` · Homebrew · Discussion #6196 · GitHub](https://github.com/orgs/Homebrew/discussions/6196)
40. [Uninstalling a formula should disable and remove its service · Homebrew · Discussion #4659](https://github.com/orgs/Homebrew/discussions/4659)
41. [Using tools](https://docs.astral.sh/uv/guides/tools/)
42. [uvx: Run Python CLI Tools in Isolated Environments](https://pydevtools.com/handbook/reference/uvx/)
43. [uv-doc/cards/tools/tool-list-uninstall.md at main · turboBasic/uv-doc](https://github.com/turboBasic/uv-doc/blob/main/cards/tools/tool-list-uninstall.md)
44. [What PyInstaller Does and How It Does It — PyInstaller 6.22.3 documentation](https://pyinstaller.org/en/stable/operating-mode.html)
45. [github.com](https://github.com/pyinstaller/pyinstaller/discussions/8167)
46. [Secret scanning for AI coding tools](https://docs.gitguardian.com/ggshield-docs/integrations/ai-coding-tools/secret-scanning-for-ai-coding-tools)
47. [host: cursor adapter and fail-closed hooks.json installer by iamdotk · Pull Request #15 · agentmoat/moat-kernel · GitHub](https://github.com/agentmoat/moat-kernel/pull/15)
48. [fix(cursor): run hooks through a pinned, fail-open local launcher by BrainerVirus · Pull Request #233 · BrainerVirus/workit · GitHub](https://github.com/BrainerVirus/workit/pull/233)
49. [feat(cursor): Cursor adapter with observe-only hooks by SudarshanDhage · Pull Request #56 · elephaant/shiplino · GitHub](https://github.com/elephaant/shiplino/pull/56)
50. [Claude Code Hooks for Security (Codex and Cursor Too)](https://skylos.dev/use-cases/ai-coding-agent-hooks)
51. [Unset core.hookspath in lefthook install · Issue #1248 · evilmartians/lefthook · GitHub](https://github.com/evilmartians/lefthook/issues/1248)
52. [chore(hooks): run the global git hooks from husky's hooks by alex-mextner · Pull Request #44 · alex-mextner/HyperSummaryBot · GitHub](https://github.com/alex-mextner/HyperSummaryBot/pull/44)
53. [Hooks | ChatGPT Learn](https://developers.openai.com/codex/hooks)
54. [AI agent hooks: the interface for governing AI agents — Speakeasy](https://www.speakeasy.com/resources/ai-agent-hooks)
55. <https://code.claude.com/docs/en/hooks>
56. [Codex CLI Guide 2026: Setup, Sandbox, AGENTS.md & MCP](https://blakecrosley.com/guides/codex)
57. [Gemini CLI hooks](https://geminicli.com/docs/hooks/)
58. [Cursor-agent (Windows): imported Claude Code hooks are composed as PowerShell but executed with bash, silently blocking every tool call - #5 by deanrie - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/cursor-agent-windows-imported-claude-code-hooks-are-composed-as-powershell-but-executed-with-bash-silently-blocking-every-tool-call/168129/5)

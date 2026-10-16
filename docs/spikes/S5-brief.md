# S5: does a brief reach the agent; hook dump; sudo re-run
Status: done (as of 2026-10-16 12:45)
Result: PASS (owner, 2026-10-16; smoke test only, D16 open). Brief used, not mentioned. Tool calls before the passing run: 8, 8 without; 2, 3 with (rule file); 3 via additional_context (n=1). One unknown event name disables a whole hooks.json. Subagents: own conversation_id, linked by parent_tool_call_id on every event. sudo -n: exit=1.
Evidence: logs/spike/s5-*.jsonl (gitignored; ids and key names only); Cursor 3.24.12 Hooks log 20261016T115343; sections below.
Needs owner: none. Owner's verdict 2026-10-16: pass (smoke test only; unlocks the pre-registered A/B; D16 stays open).
Details: see "## 2026-10-16 12:45" below.

## 2026-10-16 12:45

n = 2 per arm measures nothing about value. A pass only unlocks the pre-registered A/B (D16).
Setup: Cursor 3.24.12 desktop app, model Grok 4.7 High (chats 1-4), Grok 4.7 High Fast (sudo, subagents, chat 5; the model picker changed between chats, a confounder for chat 5).
Test folder `/tmp/af-fresh`: `app.py`, `tests/test_app.py`, `pyproject.toml` with pytest settings, and `scripts/check.sh`, the only command that passes (it sets an env var the test needs; plain `pytest` and `python3 -m unittest` fail).
Changed from the card: no Xcode Command Line Tools on this Mac, so no `make`; the entry point is `scripts/check.sh`, not `make check`. The first attempt with `./check.sh` in the folder root was void: the hook file did not load (below) and the agent found the script at once.

### 1. The brief
Text (`.cursor/rules/agentfly-context.mdc`, `alwaysApply: true`):
```
# AgentFly context for this project (from past sessions; no file contents)
- tests: `scripts/check.sh` (passed in 3 sessions)
- `pytest` failed twice here; `python3 -m unittest` failed once (missing setup)
- last sessions touched: app.py, tests/test_app.py
- no blocks in this project so far
```
The agent searches before it runs anything, so it ran exactly one shell command in every chat (`scripts/check.sh`, passed) and never tried `pytest`. Shell commands therefore cannot tell the arms apart; the measure used is **tool calls before the first passing run**, from `preToolUse` in the hook log.

| Chat | Delivery | Tool calls before passing run | Mentions brief |
|---|---|---|---|
| 1 | none | 8 (5 Grep, 3 Read) | n/a |
| 2 | none | 8 (5 Grep, 3 Read) | n/a |
| 3 | rule file | 2 (1 Grep, 1 Read) | no; its first search was the exact path `scripts/check.sh` (owner's screenshot) |
| 4 | rule file | 3 (2 Grep, 1 Read) | not checked (thoughts not captured) |
| 5 | sessionStart `additional_context` | 3 (2 Grep, 1 Read) | not checked |

Cursor's Hooks log shows the `additional_context` returned for chat 5. The forum report that it "never reaches the model" is not reproduced here (n = 1, different model variant).
Not controlled: Cursor also injects the owner's Claude Code plugin `sessionStart` context (below) into every chat, both arms alike.

### 2. Hook dump: which events fire (21 registered)
Cursor's own list of valid types (from its error message) equals the 21 in the docs: sessionStart sessionEnd preToolUse postToolUse postToolUseFailure subagentStart subagentStop beforeShellExecution afterShellExecution beforeMCPExecution afterMCPExecution beforeReadFile afterFileEdit beforeSubmitPrompt preCompact stop afterAgentResponse afterAgentThought beforeTabFileRead afterTabFileEdit workspaceOpen.
Seen: workspaceOpen, sessionStart, beforeSubmitPrompt, afterAgentThought, preToolUse, postToolUse, beforeReadFile, beforeShellExecution, afterShellExecution, subagentStart, subagentStop, afterAgentResponse, stop. Not triggered by these chats: sessionEnd, postToolUseFailure, MCP, afterFileEdit, preCompact, tab events.
- **Made-up event name (`afBogusEvent`): Cursor rejects the whole user hooks.json** ("Invalid user config: Unknown hook type … Failed to parse user hooks configuration", Hooks log only). None of the 21 hooks ran; the agent worked normally. Consequence for v1: AgentFly's system hooks.json must list only events the installed Cursor accepts, and `doctor` should read that log. A Cursor update that drops an event would switch AgentFly off silently.
- Cursor also runs hooks from `~/.claude/settings.json` ("claude-plugin config"): the owner's Claude Code plugins' `sessionStart` hooks ran in Cursor and returned `additional_context`. A third, user-writable hook source next to user and project hooks.
- Each new chat produced an extra `sessionStart` with its own conversation_id and no other events (often `workspace_roots: []`).
- `afterAgentThought` (`text`), `afterAgentResponse` (`text`, token counts) and `beforeSubmitPrompt` (`prompt`) carry content; the dump dropped it.

### 3. D9: duplicate file reads
A read fires `preToolUse` (tool_name Read, with `tool_use_id`) and `beforeReadFile` (no `tool_use_id`). `generation_id` is one value for the whole turn. **No field links the two events.**

### 4. Subagents (two runs, one foreground and one background each)
- Each subagent gets **its own conversation_id**. Neither fires its own `sessionStart`.
- **Every event inside a subagent carries `parent_tool_call_id`** (not in Cursor's docs), including preToolUse, beforeShellExecution and beforeReadFile. It equals the parent's `Task` `preToolUse` `tool_use_id` and `subagentStart.tool_call_id` (exact match, run 2).
- `subagentStart` fires in the parent chat with `parent_conversation_id`, `subagent_id`, `subagent_type` (general-purpose), `tool_call_id`, `is_parallel_worker` (false for both), `task`; 2.5 to 4.2 s before the child's first event.
- `subagentStop` fired **only for the foreground subagent**, with `child_conversation_id`. The background one fired none, in both runs. No field marks a subagent as background.
- Child events carry the same `workspace_roots` as the parent (no worktree isolation in this test).
- For S3 §5: option (c), the parent link, is available on every child event: the mark can follow `parent_tool_call_id` → `subagentStart.parent_conversation_id`. Option (b) (deny at `subagentStart`) was not tested.

### 5. S2 (d) sudo re-run
`sudo -v` in Terminal, then within a minute in a chat `sudo -n true; echo exit=$?`. First run inside Cursor's sandbox (`sandbox: true`): 127. The agent then re-ran it **outside the sandbox on its own, with no approval prompt** (owner confirmed; `sandbox: false` in the hook). Result: `sudo: a password is required`, `exit=1`. The Terminal's sudo login does not reach the agent's shell. D3 stands.

### Cleanup
`~/.cursor/hooks.json` removed (`s5.sh restore`); the rule file removed. `/tmp/af-fresh` keeps the test project and the fake `.env`. Scripts and logs: `/tmp/af-spike/s5-*`, copied to `logs/spike/`.

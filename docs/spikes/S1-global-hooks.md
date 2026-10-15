# S1: global hooks in a fresh folder; `ask` and allow messages

Status: done for the Cursor desktop app, 2026-10-15, in two runs. The `cursor-agent` half was not tested.
Plan: `docs/SYNTHESIS.md` §3 S1.

## Setup
- Cursor desktop app 3.24.12 (the AGENTS.md Hook facts were taken on 3.5.17).
- `cursor-agent`: not installed; not tested (owner uses the desktop app).
- Send-out target: `https://example.invalid` (R1 treats it as outbound). Do not use
  `203.0.113.1`: `is_local_host` treats the TEST-NET range as private, so R1 would not fire.
- `hooks.json`: `~/.cursor/hooks.json`, the five current events, each
  `<repo>/.venv/bin/python <repo>/hooks/hook.py`, timeout 5, written by `/tmp/af-spike/s1.sh real`.
  The repo's own `.cursor/hooks.json` was moved aside. For steps 5–7 the same file pointed at
  `/tmp/af-spike/stub.py` (throwaway, logs key names only).

## Results (Cursor desktop app)
| Check | Result |
|---|---|
| Events arrive from a fresh folder | Yes. Workspace `/private/tmp/af-fresh`, 6 events with the real hook (the Read prompt was sent twice): preToolUse 3, beforeReadFile 2, beforeShellExecution 1. |
| R1 deny shown | Yes. `curl … https://example.invalid` was denied. The agent reported "blocked by a session hook (R1)". The graph showed SECRET SEEN and the red BLOCKED step with a dashed line to R1. Screenshot is in the owner's chat, not in the repo. |
| Trust prompt | **None appeared in either run.** Run 1: the owner chose the folder inside the Cursor agent window. Run 2 (from scratch): the folder was opened with File > Open Folder. No prompt either way. |
| `tool_use_id` | On `preToolUse` and `beforeShellExecution`. Not on `beforeReadFile` or `afterFileEdit`. |
| `ask` | **Enforced for shell (2 of 2 trials).** Answering `ask` to `echo ask-test` paused the agent with "Hook requested approval: S1 ask-test: do you approve?" and Skip / Always Run / Run buttons (mode: Auto-review with Sandbox). Run was clicked and the command ran. Only `beforeShellExecution` was tested. The forum report "ask doesn't pause the agent" did not reproduce here. |
| `user_message` on allow | **Not shown** anywhere the owner could see (`echo msg-test`, 2 trials). |
| `agent_message` on allow | **Not used.** The agent did not say PINEAPPLE (2 trials). |
| MCP tool | None connected; not tested. |

## Run 2 (from scratch, same day)
Same steps, repeated after a restore. Results matched run 1:
- File > Open Folder on `af-fresh`: no trust prompt.
- Leak test: `curl` to `example.invalid` blocked by R1.
- `ask-test`: paused with the approval prompt again (second trial, so `ask` on shell is 2 for 2).
- `msg-test`: the command ran and returned `msg-test`; no visible `user_message`, no PINEAPPLE (2 for 2).
- Write, Read and Grep tools ran; the stub logged their key names. The AgentFly UI did not change during the stub steps, as expected (the stub never calls the recorder).
- `s1.sh restore` run: `~/.cursor/hooks.json` is gone and the repo's `.cursor/hooks.json` is back.

## Key names (never values), from the stub's log
Every payload carries `conversation_id`, `session_id`, `generation_id`, `hook_event_name`,
`model`, `cursor_version`, `workspace_roots`, `user_email`, `transcript_path` (null in some
events).

| Event | Keys specific to it |
|---|---|
| `beforeShellExecution` | `command`, `cwd`, `sandbox`, `tool_use_id` |
| `beforeReadFile` | `file_path`, `attachments`, **`content`** (full file text; the client must drop it) |
| `afterFileEdit` | `file_path`, **`edits`** (edit text; the client must drop it); no `tool_use_id` |
| `preToolUse` | `tool_name`, `tool_use_id`, `tool_input` |

`preToolUse.tool_input` keys, by tool (the stub logged key names, so tool names are inferred from the keys):
- Shell: `command`, `cwd`, `timeout`
- Read: `file_path`
- Write: `file_path`, **`content`** (file text)
- Grep: `file_path`, `pattern`. The pattern is user-supplied text and can carry a secret, so V2 keeps only `file_path`.
- MCP: not tested.

## Verdict
- **App: pass.** Events arrive from a folder that was never set up, and the curl is denied with the R1 message.
- **CLI: not tested.** SYNTHESIS §3 asks for both, so G1 is only half confirmed.
- **Trust:** no prompt appeared in either run, including with File > Open Folder. Whether the folder counted as trusted was not checked in Cursor's settings.

Effect on decisions:
- **D2:** a user-level global hooks file works in the app; no per-project step was needed.
- **D9:** `tool_use_id` exists on the two events that need merging, so de-duplication by `tool_use_id` is possible. `beforeReadFile` has none, so reads can't be merged that way. V2 keeps only `file_path` from `tool_input`.
- **D11:** `ask` works for shell commands, and an allow-with-message is invisible in Cursor. See D11.

# Hooks

How Flight Recorder plugs into Cursor hooks, what we verified on this machine,
and what the thin adapter does today.

Official Cursor reference: [cursor.com/docs/hooks](https://cursor.com/docs/hooks)

---

## Architecture

Cursor spawns a short-lived process per action (JSON on stdin → JSON on stdout).
Logic does **not** live under `.cursor/`.

```
Cursor agent
    → python3 recorder/hook_passthrough.py   (thin adapter)
        → append sanitized line to .cursor/hook-events.log
        → print {"permission":"allow"}
```

Later (SPEC §3): the same adapter will `POST` to `http://127.0.0.1:8787/hook`
and print the server’s allow/deny answer. Do **not** use a Unix socket for this —
hooks are one-shot; HTTP matches the local server + web UI on port 8787.

| Piece | Path | Role |
|---|---|---|
| Config | `.cursor/hooks.json` | Which events call the adapter (`version: 1` required) |
| Adapter | `recorder/hook_passthrough.py` | Stdlib only; sanitize, log, always allow |
| Install | `./install.sh` | Writes `hooks.json`, ensures script is executable |
| Log | `.cursor/hook-events.log` | Gitignored; one JSON object per line |

---

## Install / reload

```bash
./install.sh
```

Then:

1. Trust this project folder in Cursor if prompted.
2. Restart Cursor (or reload) if hooks do not appear.
3. Check **Settings → Hooks** and the **Hooks** output channel.
4. Trigger a file read and a shell command; inspect `.cursor/hook-events.log`.

Hook command (after install, no project `.venv` yet):

```text
python3 recorder/hook_passthrough.py
```

With a project venv, install prefers:

```text
.venv/bin/python recorder/hook_passthrough.py
```

Do **not** use `uv run` in the hook path (slow cold start). `timeout` in
`hooks.json` is `1` second.

---

## Events we wire

| Event | Can block? | Used for |
|---|---|---|
| `beforeShellExecution` | Yes | Commands (R1 network block later) |
| `beforeReadFile` | Yes | Sensitive file reads (session marking later) |
| `beforeMCPExecution` | Yes | External tool calls |
| `afterFileEdit` | No (observe only) | Record that a path was edited |

Optional later: `preToolUse` (broader; do not assume it is needed).

---

## Passthrough logger behaviour

1. Read JSON from stdin.
2. **Immediately drop** `content` (SPEC: `beforeReadFile` includes full file text).
3. Replace `afterFileEdit.edits` with a count placeholder; omit `tool_input`.
4. Append `{ "ts", "event" }` to `.cursor/hook-events.log`.
5. Print **only** `{"permission":"allow"}` on stdout (anything else can break Cursor).
6. Diagnostics go to stderr.

If JSON is invalid or the log write fails, still print allow (fail-open for this stage).

---

## Real input fields (Cursor 3.5.17 on this machine)

Confirmed by live log lines in this project:

**Common (all agent hooks):**

- `conversation_id` — session key (use this for the server)
- `session_id` — same value as `conversation_id`
- `generation_id`, `model`, `hook_event_name`, `cursor_version`
- `workspace_roots`, `user_email`, `transcript_path`

**`beforeShellExecution`:**

- `command` — full terminal command
- `cwd` — may be `""`
- `sandbox` — boolean

**`beforeReadFile`:**

- `file_path` — absolute path
- `attachments` — list
- `content` — present on the wire; **must never be logged or forwarded**

---

## Permission responses

### Documented values

| Event | `permission` |
|---|---|
| `beforeShellExecution`, `beforeMCPExecution` | `allow` \| `deny` \| `ask` |
| `beforeReadFile` | `allow` \| `deny` |

Deny shape (for later rules):

```json
{
  "permission": "deny",
  "user_message": "Blocked by rule R1: ...",
  "agent_message": "Blocked by rule R1: ... Do not retry with another tool or language. Stop and tell the user."
}
```

Exit code `2` also blocks. Invalid JSON can block. Default hook failure mode is
fail-open unless `failClosed: true`.

### Practical caveat (do not rely on auto-approve)

Returning `"allow"` means **this hook does not block**. It does **not** reliably
dismiss Cursor’s own approval UI (allowlist / Auto-review / sandbox).

Reported behaviour on recent Cursor builds:

- **`deny`** — reliable
- **`allow` / `ask`** — often ignored; Cursor’s own gates still prompt

For demos (SPEC §8): turn Cursor’s “ask before every command” style prompts
**off**, or the audience will think Cursor’s button blocked the action, not
Flight Recorder. When we enforce policy, depend on **`deny`**, not on `"ask"`.

---

## Checkpoint status

| Checkpoint | Status |
|---|---|
| Hooks fire + log + allow | **Done** (shell + file read verified) |
| Hard-coded deny stops a command | Not done |
| Server + R0/R1 | Not done |

---

## What is not covered by hooks

- Cursor built-in web tools may bypass these events.
- Tab completions use `beforeTabFileRead` / `afterTabFileEdit` (we do not wire them).
- When the future server is down, the adapter must fail open (`allow` + stderr warning).

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
    → python3 hooks/hook.py   (thin adapter)
        → drop unsafe fields, POST http://127.0.0.1:8787/hook
           (header X-Recorder-Token from ~/.config/flightrecorder/token)
        → print server JSON, or {"permission":"allow"} if unreachable
```

Later: the server applies R0/R1 and still answers in-process (no Neo4j wait).
Do **not** use a Unix socket — HTTP matches the local server + web UI on port 8787.

| Piece | Path | Role |
|---|---|---|
| Config | `.cursor/hooks.json` | Which events call the adapter (`version: 1` required); **not in git** |
| Adapter | `hooks/hook.py` | Stdlib only; sanitize, POST `/hook`, fail-open |
| Server | `recorder/app.py` | Host + token gates; always allow for now |
| Compat shim | `recorder/hook_passthrough.py` | Delegates to `hooks/hook.py` if an old config still points here |
| Install | `./install.sh` | Writes `hooks.json`, ensures script is executable |
| Log | `logs/events.jsonl` | Under gitignored `logs/` (local debug copy) |
| Token | `~/.config/flightrecorder/token` | Mode 600; written on server start |

The whole `.cursor/` directory is in `.gitignore`. Do not commit `hooks.json` —
paths and Python choice are machine-local. After clone (or after pulling
install changes), run `./install.sh` so Cursor has a fresh config.

**Footgun:** never delete the hook script while `hooks.json` still points at it.
Python exit code **2** (file missing) is treated as **deny** and can lock the agent.
Keep the compat shim so an outdated `hooks.json` that still names
`recorder/hook_passthrough.py` does not exit 2.

Project layout (uv skeleton): `hooks/`, `recorder/`, `web/`, `tests/`, `demo/`.

---

## Install / reload

```bash
uv sync
./install.sh   # required: writes gitignored .cursor/hooks.json
```

Then:

1. Trust this project folder in Cursor if prompted.
2. Restart Cursor (or reload) if hooks do not appear.
3. Check **Settings → Hooks** and the **Hooks** output channel.
4. Trigger a file read and a shell command; inspect `logs/events.jsonl`.

Hook command after install (prefer project venv when present):

```text
.venv/bin/python hooks/hook.py
```

Do **not** use `uv run` in the hook path (slow cold start). `timeout` in
`hooks.json` is `1` second.

**Before Checkpoint A / demos:** turn Cursor’s “ask before running commands”
style prompts **OFF** (SPEC §8).

---

## Events we wire

| Event | Can block? | Used for |
|---|---|---|
| `beforeShellExecution` | Yes | Commands (R1 network block later) |
| `beforeReadFile` | Yes | Sensitive file reads (session marking later) |
| `beforeMCPExecution` | Yes | External tool calls |
| `afterFileEdit` | No (observe only) | Record that a path was edited |
| `preToolUse` | Yes (allow/deny; can rewrite input) | Broader net: Shell, Read, Write, Task, MCP, searches, etc. |

`preToolUse` fires for many tools; expect overlap with the narrower hooks above.

---

## Helper behaviour

1. Read JSON from stdin.
2. **Immediately drop** `content` (SPEC: `beforeReadFile` includes full file text).
3. Replace `afterFileEdit.edits` with a count placeholder; omit `tool_input`.
4. `POST` the sanitized payload to `http://127.0.0.1:8787/hook` (0.5 s timeout,
   header `X-Recorder-Token`).
5. Print **only** the server permission JSON on stdout.
6. If the server is down or any error occurs: print `{"permission":"allow"}` and
   a warning on stderr (fail-open).
7. Optionally append `{ "ts", "event", "decision" }` to `logs/events.jsonl`.

Checkpoint A test rule T0 (`_T0_ENABLED` in `hooks/hook.py`) denied shell
commands containing `curl`. It is **disabled** after the decision in
`demo/NOTES.md`.

---

## Server (this stage)

```bash
uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787
```

- `GET /health` → `{"ok": true}` (Host check only).
- `POST /hook` → Host → token → Content-Type → JSON → `{"permission":"allow"}`.
- Listens on `127.0.0.1` only; token file mode `600`.

---

## Real input fields (Cursor 3.5.17 on this machine)

**Common:** `conversation_id`, `session_id` (same value), `generation_id`,
`model`, `hook_event_name`, `cursor_version`, `workspace_roots`, `user_email`,
`transcript_path`

**`beforeShellExecution`:** `command`, `cwd` (may be `""`), `sandbox` (bool)

**`beforeReadFile`:** `file_path`, `attachments`; `content` must never be logged

**`preToolUse`:** `tool_name`, `tool_input` (omitted in log), `tool_use_id`, `cwd`

Session key for the server: `conversation_id`.

---

## Permission responses

| Event | `permission` |
|---|---|
| `beforeShellExecution`, `beforeMCPExecution` | `allow` \| `deny` \| `ask` |
| `beforeReadFile`, `preToolUse` | `allow` \| `deny` (`"ask"` not enforced for `preToolUse`) |

Exit code `2` also blocks. **`deny` is reliable; `allow`/`ask` often are not**
(Cursor’s own allowlist / Auto-review can still prompt). Depend on **`deny`**
for policy.

---

## Checkpoint status

| Checkpoint | Status |
|---|---|
| Hooks fire + log + allow | **Done** |
| Hard-coded deny stops a command | **Done** — decision **continue** (`demo/NOTES.md`) |
| Server + token gates (always allow) | **Done** |
| Server + R0/R1 | Not done |

---

## What is not covered by hooks

- Cursor built-in web tools may bypass these events.
- Tab completions use `beforeTabFileRead` / `afterTabFileEdit` (not wired).
- When the future server is down, the adapter must fail open (`allow` + stderr warning).

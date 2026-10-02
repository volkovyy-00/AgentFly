# Hooks

How AgentFly plugs into Cursor hooks, what we verified on this machine,
and what the thin adapter does today.

Official Cursor reference: [cursor.com/docs/hooks](https://cursor.com/docs/hooks)

---

## Architecture

Cursor spawns a short-lived process per action (JSON on stdin → JSON on stdout).
Logic does **not** live under `.cursor/`.

```
Cursor agent  (or fake_agent.py)
    → python3 hooks/hook.py   (thin adapter)
        → drop unsafe fields, POST http://127.0.0.1:8787/hook
           (header X-Recorder-Token from ~/.config/flightrecorder/token)
        → print server JSON, or {"permission":"allow"} if unreachable
            → recorder/app.py: mark session, R1 decide, allow/deny
```

Do **not** use a Unix socket — HTTP matches the local server + web UI on port 8787.

| Piece | Path | Role |
|---|---|---|
| Config | `.cursor/hooks.json` | Which events call the adapter (`version: 1` required); **not in git** |
| Adapter | `hooks/hook.py` | Stdlib only; sanitize, POST `/hook`, fail-open |
| Server | `recorder/app.py` | Host + token gates; mark/decide; R1 deny |
| Rules | `recorder/rules.py` | `Rule` list; `mark` then `decide`; `WATCH_ONLY` |
| Sessions | `recorder/sessions.py` | Memory + `~/.config/flightrecorder/sessions.json` |
| Names | `recorder/names.py` | Sensitive paths + local hosts (pure) |
| Clean | `recorder/clean.py` | SPEC §4 command cleaner; `CLEAN_COMMANDS` (default on) |
| Memory | `recorder/memory.py` | In-memory steps for `GET /api/steps` (page) |
| Neo4j | `recorder/store.py` | Background MERGE writer; `--counts` / `--clear` |
| Creds | `recorder/config_env.py` | Hand-parse `~/.config/flightrecorder/.env` |
| Check DB | `recorder/check_db.py` | `verify_connectivity` → `connected` |
| Replay | `fake_agent.py` + `demo/scenario.json` | Pipe events through the helper (no Cursor) |
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

Project layout (uv skeleton): `hooks/`, `recorder/`, `web/`, `ui/`, `tests/`,
`demo/`.

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
- `POST /hook` → Host → token → Content-Type → JSON → mark session → R1 decide →
  allow or deny. Sessions persist in `~/.config/flightrecorder/sessions.json`.
- Listens on `127.0.0.1` only; token file mode `600`.
- R1 message (exact): `Blocked by rule R1: a secret was read earlier in this
  session, and now data is being sent out.` `WATCH_ONLY` turns blocks into
  warnings (allow + warned verdict).
- Decision stays in-process (never waits on Neo4j). R0 is not implemented yet.

---

## Replay without Cursor (`fake_agent.py`)

Pipes events from `demo/scenario.json` into `hooks/hook.py` the same way Cursor
would. First stdout line is `SIMULATION (not a real agent)`.

```bash
uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787   # separate terminal
uv run python fake_agent.py
uv run python fake_agent.py --scenario demo --session my-id
uv run python fake_agent.py --scenario clean_sample
```

| Flag | Default | Meaning |
|---|---|---|
| `--scenario` | `demo` | Key in `demo/scenario.json` |
| `--session` | new uuid | Sets `conversation_id` / `session_id` on every event |

**`demo` scenario:** read README (allowed) → read `.env` with fake `content`
(allowed; content must be dropped before log/POST) → `curl` to ntfy (blocked by R1).
Exit 0 only if every step matches its `expect`.

**Server down:** helper fail-opens to allow; last step expect is `blocked` →
exit non-zero and stderr `WARNING: recorder unreachable` (no traceback).

**`clean_sample`:** holds the cleaning fixture command
`curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1` (expect allowed;
used later for command-cleaning tests).

Format details: module docstring of `fake_agent.py`.

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

## Command cleaning (SPEC §4)

`recorder/clean.py` redacts shell commands before they are stored (options kept,
values → `<arg>`, project-relative paths kept, hosts reduced to website names,
env assigns → `NAME=<removed>`, hard-to-parse → `<program> <unparsed>`).

- Helper for the save path: `command_for_storage(cmd, project_root)`.
- **Default on.** Disable with `CLEAN_COMMANDS=0` (or `false` / `no` / `off`)
  in the process environment when starting uvicorn. Off stores the **raw**
  command — can leak secrets into Neo4j later; debugging only.
- Listed in `.env.example`. Call `command_for_storage` when saving steps.

## Neo4j background store

After each `/hook` answer, a cleaned `StepRecord` is enqueued to Neo4j
(`recorder/store.py`). The decision path never waits on the driver.

- Constraints + `MERGE` on `id` for Session/Step/File/Command/Host/Rule.
- `DELETE` only via `uv run python -m recorder.store --clear`.
- `uv run python -m recorder.check_db` → `connected` (failures print the
  exception class name only, never the password).
- Queue full → drop + warning. Write failures → warning with error class only.
- Live tests in `tests/test_store.py` skip when Aura is unreachable.
- Creds file: `~/.config/flightrecorder/.env`. On this machine Aura needed
  `neo4j+ssc://` (not `neo4j+s://`) because of TLS cert verification; see
  `.env.example`. Restart the recorder after changing the URI.
- Verified: `check_db` → `connected` with `neo4j+ssc://`; background writes
  land in Aura. Restart uvicorn so the running process reloads the env.

## Live graph (`web/index.html`, `ui/`, + memory API)

- Current page: [`web/index.html`](web/index.html) at `/` (Part A). New page:
  [`ui/`](ui/) build served at `/v2/` (Vite + React; a timeline of the last 20
  steps it has seen; `/v2/?mock=1` replays a sample session with no server).
  Server memory: [`recorder/memory.py`](recorder/memory.py) (Part B).
- `GET /` serves the HTML (Host check only; no token).
- `GET /v2/` serves the committed `ui/dist` build (same Host gate; assets under
  `/v2/assets/...`).
- `GET /api/steps` → `{session, steps}` for the **most recent** session,
  last 10 cleaned steps from process memory. `?all=1` returns the full list
  for that session (checks only).
- Step object fields: `order`, `kind` (`read|shell|edit|tool`), `verdict`
  (`allowed|blocked|warned`), `tool`, `file`, `sensitive`, `command`, `host`,
  `rule` (nullables as needed). Built from `StepRecord` in `apply_rules`
  (sync append) — Neo4j enqueue stays separate and async.
- Empty state: `{"session": null, "steps": []}`. Memory clears on server
  restart (lifespan).
- Wrong Host → 403. No Cypher from the page.
- Demo: start uvicorn → `uv run python fake_agent.py` → open
  `http://127.0.0.1:8787/` — expect `.env` amber and blocked step → R1.
- UI-only rehearsal without the API: `web/index.html?mock=1` (file:// OK).
- UI local dev: `npm --prefix ui run dev` proxies `/api` to
  `http://127.0.0.1:8787` with `changeOrigin` so the Host gate accepts it.

---

## Checkpoint status

| Checkpoint | Status |
|---|---|
| Hooks fire + log + allow | **Done** |
| Hard-coded deny stops a command | **Done** — decision **continue** (`demo/NOTES.md`) |
| Server + token gates (always allow) | **Done** |
| R1 secret-then-network | **Done** |
| Replay script `fake_agent.py` | **Done** |
| Checkpoint B (live R1 deny) | **Done** — decision **continue** (`demo/NOTES.md`) |
| Command cleaning (`recorder/clean.py`) | **Done** (toggle `CLEAN_COMMANDS`, default on) |
| Neo4j background store | **Done** (`neo4j+ssc://` on this host; `check_db` connected) |
| Live graph page + `/api/steps` | **Done** (memory; Host only) |
| R0 protect recorder | Not done |

---

## What is not covered by hooks

- Cursor built-in web tools may bypass these events.
- Tab completions use `beforeTabFileRead` / `afterTabFileEdit` (not wired).
- When the recorder is down, the adapter fails open (`allow` + stderr warning).
  `fake_agent.py` then exits non-zero if a step expected `blocked`.

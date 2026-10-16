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
    → python3 hooks/hook.py   (thin shim for agentfly/hook_client.py)
        → strip content, POST http://127.0.0.1:8787/hook
           (header X-Recorder-Token from ~/.config/agentfly/token)
        → print server JSON, or the offline guard's answer if the recorder is down
            → agentfly/recorder/app.py: mark session, R1 decide, allow/deny
```

Do **not** use a Unix socket — HTTP matches the local server + web UI on port 8787.

| Piece | Path | Role |
|---|---|---|
| Config | `.cursor/hooks.json` | Which events call the adapter (`version: 1` required); **not in git** |
| Hook client | `agentfly/hook_client.py` | Stdlib only; strip, POST `/hook`, offline guard when the recorder is down |
| Shim | `hooks/hook.py` | What `./install.sh` wires; runs the hook client (goes away with V3) |
| Server | `agentfly/recorder/app.py` | Host + token gates; mark/decide; R1 deny |
| Rules | `agentfly/recorder/rules.py` | `Rule` list; `mark` then `decide`; `WATCH_ONLY` |
| Sessions | `agentfly/recorder/sessions.py` | Memory + `~/.local/share/agentfly/sessions.json` |
| Names | `agentfly/recorder/names.py` | Sensitive paths + local hosts (pure) |
| Clean | `agentfly/recorder/clean.py` | SPEC §4 command cleaner; `CLEAN_COMMANDS` (default on) |
| Memory | `agentfly/recorder/memory.py` | In-memory steps for `GET /api/steps` (page) |
| Neo4j | `agentfly/recorder/store.py` | Background MERGE writer; `--counts` / `--clear` |
| Creds | `agentfly/recorder/config_env.py` | Hand-parse `~/.config/agentfly/neo4j.env` |
| Check DB | `agentfly/recorder/check_db.py` | `verify_connectivity` → `connected` |
| Replay | `fake_agent.py` + `demo/scenario.json` | Pipe events through the helper (no Cursor) |
| Compat shim | `recorder/` folder at the repo top | A one-file forwarder for a stale `hooks.json`; it delegates to the shim above |
| Install | `./install.sh` | Writes `hooks.json`, ensures script is executable |
| Log | `~/.local/share/agentfly/logs/events.jsonl` | Hook log (folder 700, file 600); no commands, no file text |
| Offline count | `~/.local/share/agentfly/logs/offline-count` | One byte per call the offline guard answered; `/health` shows the size |
| Token | `~/.config/agentfly/token` | Mode 600; written on server start |

The whole `.cursor/` directory is in `.gitignore`. Do not commit `hooks.json` —
paths and Python choice are machine-local. After clone (or after pulling
install changes), run `./install.sh` so Cursor has a fresh config.

**Footgun:** never delete the hook script while `hooks.json` still points at it.
Python exit code **2** (file missing) is treated as **deny** and can lock the agent.
Keep the compat shim so an outdated `hooks.json` that still names the old forwarder
does not exit 2.

Project layout: `agentfly/` (hook client, recorder, CLI), `hooks/`, `ui/`, `tests/`,
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
4. Trigger a file read and a shell command; inspect `~/.local/share/agentfly/logs/events.jsonl`.

Hook command after install (prefer project venv when present):

```text
.venv/bin/python hooks/hook.py
```

Do **not** use `uv run` in the hook path (slow cold start). `timeout` in
`hooks.json` is `1` second.

**Before Checkpoint A / demos:** turn Cursor’s “ask before running commands”
style prompts **OFF** (hackathon demo setup,
`docs/archive/SPEC-hackathon.md` §8).

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

## Hook client behaviour

Called as `agentfly-hook <agent> <event>`; with no arguments (today's `hooks.json`) it acts as
`cursor` and reads the event from the payload. If the `<event>` argument and the payload's
`hook_event_name` differ, the argument wins and stderr says so. An unknown agent gets allow,
exit 0 and a warning on stderr.

1. Read stdin as bytes. Anything that is not a JSON object (empty, malformed, non-UTF-8,
   a 5000-digit number, JSON nested 100,000 deep) goes to the offline guard on its raw text.
2. Strip, at every depth: `content`, `output` and `edits` (`afterFileEdit.edits` becomes a
   count). `tool_input` is dropped; only a file tool's `file_path` is kept. An MCP call keeps
   only the server and tool names (`mcp_server_name`, `tool_name`; unverified on Cursor
   3.24.12). Only `beforeShellExecution` keeps its `command`, and only in the request body.
3. `POST` the stripped payload to `http://127.0.0.1:8787/hook`, header `X-Recorder-Token`.
   The port is fixed (D25): the client reads no environment variable and no port file.
   Wait budget 0.5 s in total (connect and answer).
4. Print **only** the permission JSON on stdout, and always exit 0.
5. Append `{ts, event, decision}` to the hook log. The log keeps no command text.
6. If the recorder is down, slow, or answers with an error: the **offline guard** (SPEC §9)
   answers. It denies outbound commands (`curl`, `wget`, `nc`, `scp`, `ssh`, `rsync` unless
   the host is local or private; `gh`, `aws`, `git push`; a `python`/`python3`/`node` command
   that mentions `http`), also when wrapped in `bash -c`, `env` or `sudo`, and any command that
   names an AgentFly folder or a `hooks.json`. The message says to run `agentfly start`. It
   allows everything else and logs the call with `offline: true`.

Checkpoint A's temporary test rule T0 (a hard-coded `curl` deny) was removed from the hook
client after the decision in `demo/NOTES.md`.

---

## Server (this stage)

```bash
uv run agentfly serve              # or: AGENTFLY_PORT=N uv run agentfly serve (--port wins)
```

- `GET /health` → `{"ok": true, "offline_guard_count": N}` (Host check only). `N` is how many
  calls the hook client's offline guard answered (advisory; read from the count file).
- `POST /hook` → Host → token → Content-Type → JSON → mark session → R1 decide →
  allow or deny. Sessions persist in `~/.local/share/agentfly/sessions.json`.
- Listens on `127.0.0.1` only; token file mode `600`.
- R1 message (exact): `Blocked by rule R1: a secret was read earlier in this
  session, and now data is being sent out.` `WATCH_ONLY` turns blocks into
  warnings (allow + warned verdict).
- Decision stays in-process (never waits on Neo4j). R0 is not implemented yet.

---

## Replay without Cursor (`fake_agent.py`)

Pipes events from `demo/scenario.json` into `agentfly/hook_client.py` the same way Cursor
would. First stdout line is `SIMULATION (not a real agent)`.

```bash
uv run agentfly serve   # separate terminal
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

**Server down:** the offline guard answers (a `curl` is denied), so the last step may still
match; `fake_agent.py` prints `WARNING: recorder unreachable` on stderr and exits non-zero.

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

`agentfly/recorder/clean.py` redacts shell commands before they are stored (options kept,
values → `<arg>`, project-relative paths kept, hosts reduced to website names,
env assigns → `NAME=<removed>`, hard-to-parse → `<program> <unparsed>`).

- Helper for the save path: `command_for_storage(cmd, project_root)`.
- **Default on.** Disable with `CLEAN_COMMANDS=0` (or `false` / `no` / `off`)
  in the process environment when starting uvicorn. Off stores the **raw**
  command — can leak secrets into Neo4j later; debugging only.
- Listed in `.env.example`. Call `command_for_storage` when saving steps.

## Neo4j background store

After each `/hook` answer, a cleaned `StepRecord` is enqueued to Neo4j
(`agentfly/recorder/store.py`). The decision path never waits on the driver.

- Constraints + `MERGE` on `id` for Session/Step/File/Command/Host/Rule.
- `DELETE` only via `uv run python -m agentfly.recorder.store --clear`.
- `uv run python -m agentfly.recorder.check_db` → `connected` (failures print the
  exception class name only, never the password).
- Queue full → drop + warning. Write failures → warning with error class only.
- Live tests in `tests/test_store.py` skip when Aura is unreachable.
- Creds file: `~/.config/agentfly/neo4j.env`. On this machine Aura needed
  `neo4j+ssc://` (not `neo4j+s://`) because of TLS cert verification; see
  `.env.example`. Restart the recorder after changing the URI.
- Verified: `check_db` → `connected` with `neo4j+ssc://`; background writes
  land in Aura. Restart uvicorn so the running process reloads the env.

## Live graph (`ui/` + memory API)

- Page: the [`ui/`](ui/) build at `/` (Vite + React; a timeline of the 20 most
  recent steps with, above them, a summary box and up to 5 flagged older steps;
  `/?mock=1` replays a sample session without an agent).
  Server memory: [`agentfly/recorder/memory.py`](agentfly/recorder/memory.py) (Part B).
- `GET /` serves the committed `ui/dist` build (Host check only; no token); its
  assets are under `/assets/`. Both send `Cache-Control: no-cache`. If `ui/dist`
  is missing the server logs a warning and `/` is a plain 404: run
  `npm --prefix ui run build`, then restart the server (the page is
  registered once, at start-up).
- `/v2/` (also `/v2` and `/v2/index.html`) answers 307 to `/`, query string
  kept; any other `/v2/...` path is a 404.
- `GET /api/steps` → `{session, steps}` for the **most recent** session,
  last 10 cleaned steps from process memory. `?all=1` returns every retained
  step for that session (checks only). Memory keeps at most 500 steps per
  session (oldest dropped; order numbers keep counting).
- `GET /api/steps?limit=N` (1 to 50; a larger count is 50) returns the last N
  steps plus three more fields:
  - `hidden`: counts of the session's steps outside that window, including steps
    dropped by the 500 cap: `total`, `read`, `shell`, `edit`, `tool`,
    `blocked`, `warned`. `blocked` and `warned` overlay the kind counts; they are
    not a partition.
  - `flagged`: up to 5 older landmark steps in total, ascending by order, same
    step shape: the step that made R1 mark the session once it is outside the
    window, then the newest blocked or warned steps outside it (a step that is
    both appears once). `hidden.blocked` can exceed the blocked steps in
    `flagged`; the counts are truthful and the cap is for drawing.
  - `marked_order`: the order of the step that made R1 mark the session (not the
    first step with `sensitive`, which misses `cat README.md .env`), or `null`.
    After a server restart the session is still marked but memory is empty, so
    it is `null` and the counts start from zero.
  - `limit` must be ASCII digits and at least 1; anything else (`limit=`, `0`,
    `-1`, `abc`, `+5`) is 400 `{"detail": "bad limit"}`. A repeated key takes the
    last value. With `all=1`, `limit` wins. Without `limit` the body has only
    `session` and `steps`.
- Step object fields: `order`, `kind` (`read|shell|edit|tool`), `verdict`
  (`allowed|blocked|warned`), `tool`, `file`, `sensitive`, `command`, `host`,
  `rule` (nullables as needed). Built from `StepRecord` in `apply_rules`
  (sync append) — Neo4j enqueue stays separate and async.
- Empty state: `{"session": null, "steps": []}`; with `limit`, also
  `hidden` (all zeros), `flagged: []` and `marked_order: null`. Memory clears
  on server restart (lifespan).
- Wrong Host → 403. No Cypher from the page.
- Demo: start uvicorn → `uv run python fake_agent.py` → open
  `http://127.0.0.1:8787/` — expect `.env` amber and blocked step → R1.
- UI-only rehearsal without an agent: `/?mock=1` (needs the recorder or `npm --prefix ui run dev`).
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
| Command cleaning (`agentfly/recorder/clean.py`) | **Done** (toggle `CLEAN_COMMANDS`, default on) |
| Neo4j background store | **Done** (`neo4j+ssc://` on this host; `check_db` connected) |
| Live graph page + `/api/steps` | **Done** (memory; Host only) |
| R0 protect recorder | Not done |

---

## What is not covered by hooks

- Cursor built-in web tools may bypass these events.
- Tab completions use `beforeTabFileRead` / `afterTabFileEdit` (not wired).
- When the recorder is down, the offline guard answers (see "Hook client behaviour"): outbound
  and guard-path commands are denied, everything else is allowed and logged.

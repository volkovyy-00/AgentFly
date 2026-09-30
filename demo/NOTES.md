# Checkpoint A notes (SPEC §7)

Date: 2026-09-30
Cursor version: 3.5.17

## Preconditions

- [x] Cursor “ask before running commands” style prompts treated as off for this test
- Hook helper: `hooks/hook.py` (T0 was enabled for the test, then disabled)
- Log path: `logs/events.jsonl`
- Config: `.cursor/hooks.json` (gitignored; from `./install.sh`) →
  `.venv/bin/python hooks/hook.py` (or `python3 hooks/hook.py`)

## Test prompt / command

```
curl -s -o /dev/null -w '%{http_code}' https://example.com
```

(Also exercised via agent Shell; command string contained `curl`.)

## Results

| Check | Result |
|---|---|
| Command blocked in Cursor? | **yes** |
| External host got 0 new requests? | **yes** (command never ran) |
| Event in `logs/events.jsonl` with `decision: deny`? | **yes** |
| `user_message` visible in UI? | **yes** — reject text: `Blocked by test rule T0 (Checkpoint A).` |
| `agent_message` visible / followed by agent? | **yes** — agent received the block and did not complete the curl |
| What the agent said next | Reported the hook denial; did not retry successfully in that turn |

## Decision (SPEC §7)

- [x] **continue** — hook fires and deny stops the command
- [ ] **watch-only** — hook fires but deny is ignored
- [ ] **replay** — hooks do not fire at all

Decision: **continue**

## After decision

1. `_T0_ENABLED = False` in `hooks/hook.py` (T0 code left for reference, inactive).
2. Check: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` — **passed** (with T0 still on during the test run; re-verify after disable).

## Lockout note

Deleting the hook script while `hooks.json` still pointed at it caused Python exit code 2 → Cursor deny on all gated tools. Fix: never remove the script before updating `hooks.json`; exit 2 ≡ deny.

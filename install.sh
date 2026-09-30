#!/usr/bin/env bash
# Wire Cursor project hooks to hooks/hook.py.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
  echo "warning: no .venv found; using system python3: $PYTHON" >&2
  echo "         run 'uv sync' later for the recorder server." >&2
else
  echo "error: need .venv/bin/python or python3 on PATH" >&2
  exit 1
fi

HOOK_SCRIPT="$ROOT/hooks/hook.py"
if [[ ! -f "$HOOK_SCRIPT" ]]; then
  echo "error: missing $HOOK_SCRIPT" >&2
  exit 1
fi
chmod +x "$HOOK_SCRIPT"

mkdir -p "$ROOT/.cursor" "$ROOT/logs"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  CMD=".venv/bin/python hooks/hook.py"
else
  CMD="python3 hooks/hook.py"
fi

cat > "$ROOT/.cursor/hooks.json" <<EOF
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      { "command": "$CMD", "timeout": 1 }
    ],
    "beforeReadFile": [
      { "command": "$CMD", "timeout": 1 }
    ],
    "beforeMCPExecution": [
      { "command": "$CMD", "timeout": 1 }
    ],
    "afterFileEdit": [
      { "command": "$CMD", "timeout": 1 }
    ],
    "preToolUse": [
      { "command": "$CMD", "timeout": 1 }
    ]
  }
}
EOF

mkdir -p "$HOME/.config/flightrecorder"
chmod 700 "$HOME/.config/flightrecorder" 2>/dev/null || true

echo "Installed Cursor hooks -> $ROOT/.cursor/hooks.json"
echo "  command: $CMD"
echo "  log file: $ROOT/logs/events.jsonl"
echo ""
echo "Next:"
echo "  1. Trust this folder in Cursor (if prompted)."
echo "  2. Restart Cursor or reload if hooks do not appear."
echo "  3. Open the Hooks output panel; trigger a file read and a shell command."
echo "  4. Inspect logs/events.jsonl"

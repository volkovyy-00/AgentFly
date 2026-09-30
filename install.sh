#!/usr/bin/env bash
# Wire Cursor project hooks to the passthrough logger.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON=""
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

HOOK_SCRIPT="$ROOT/recorder/hook_passthrough.py"
if [[ ! -f "$HOOK_SCRIPT" ]]; then
  echo "error: missing $HOOK_SCRIPT" >&2
  exit 1
fi
chmod +x "$HOOK_SCRIPT"

mkdir -p "$ROOT/.cursor"

# Prefer project venv (AGENTS.md: do not use `uv run` in the hook path).
# Cursor runs project hooks from the project root.
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  CMD=".venv/bin/python recorder/hook_passthrough.py"
else
  CMD="python3 recorder/hook_passthrough.py"
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
    ]
  }
}
EOF

mkdir -p "$HOME/.config/flightrecorder"
chmod 700 "$HOME/.config/flightrecorder" 2>/dev/null || true

echo "Installed Cursor hooks -> $ROOT/.cursor/hooks.json"
echo "  command: $CMD"
echo "  log file: $ROOT/.cursor/hook-events.log"
echo ""
echo "Next:"
echo "  1. Trust this folder in Cursor (if prompted)."
echo "  2. Restart Cursor or reload if hooks do not appear."
echo "  3. Open the Hooks output panel; trigger a file read and a shell command."
echo "  4. Inspect .cursor/hook-events.log"

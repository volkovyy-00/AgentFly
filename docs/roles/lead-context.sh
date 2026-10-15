#!/usr/bin/env bash
# SessionStart hook for the lead only (wired by docs/roles/lead-settings.json).
# Prints the lead's state as plain text for Claude's context. Always exits 0.
# The 9,000-char STATE cap keeps the whole output under the 10,000-char hook cap.
root="$(cd "$(dirname "$0")/../.." && pwd)"
state="$root/docs/STATE.md"
source=$(cat 2>/dev/null | tr ',' '\n' | sed -n 's/.*"source" *: *"\([a-z]*\)".*/\1/p' | head -n 1)

echo "AgentFly lead context (session source: ${source:-unknown}). This session is the AgentFly lead; the role file is docs/roles/lead.md."
if [ ! -f "$state" ]; then
  echo "lead-context: docs/STATE.md not found under $root"
  exit 0
fi
chars=$(wc -c < "$state" | tr -d ' ')
if [ "$chars" -ge 9000 ]; then
  echo "FAIL: docs/STATE.md is $chars chars (cap 9000), so it is not injected. Read it with the Read tool and shorten it."
else
  echo "--- docs/STATE.md ---"
  cat "$state"
fi
echo "--- docs/roles/state-check.sh ---"
"$root/docs/roles/state-check.sh" 2>&1 | tail -n 12
echo "--- git log --oneline -5 ---"
git -C "$root" log --oneline -5 2>&1
exit 0

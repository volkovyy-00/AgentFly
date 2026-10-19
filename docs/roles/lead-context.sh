#!/usr/bin/env bash
# SessionStart hook for the lead only (wired by docs/roles/lead-settings.json).
# Prints the lead's state as plain text for Claude's context. Always exits 0.
# Claude Code keeps only a 2,000-char preview of hook output of 10,000 chars or more, so the
# whole output is built first and its tail is shortened when the total would reach the cap.
root="$(cd "$(dirname "$0")/../.." && pwd)"
state="$root/docs/STATE.md"
source=$(cat 2>/dev/null | tr ',' '\n' | sed -n 's/.*"source" *: *"\([a-z]*\)".*/\1/p' | head -n 1)
cap=9900

head="AgentFly lead context (session source: ${source:-unknown}). This session is the AgentFly lead; the role file is docs/roles/lead.md."
if [ ! -f "$state" ]; then
  echo "$head"
  echo "lead-context: docs/STATE.md not found under $root"
  exit 0
fi
chars=$(wc -c < "$state" | tr -d ' ')
if [ "$chars" -ge 9000 ]; then
  body="FAIL: docs/STATE.md is $chars chars (cap 9000), so it is not injected. Read it with the Read tool and shorten it."
else
  body="--- docs/STATE.md ---
$(cat "$state")"
fi
check=$("$root/docs/roles/state-check.sh" 2>&1)
log=$(git -C "$root" log -5 --format='%h %<(70,trunc)%s' 2>&1 | sed 's/ *$//')
tail="--- docs/roles/state-check.sh ---
$(printf '%s\n' "$check" | tail -n 12)
--- git log -5 ---
$log"
out="$head
$body
$tail"
if [ "$(printf '%s' "$out" | wc -c | tr -d ' ')" -ge "$cap" ]; then
  # Keep STATE whole; shorten the tail to the check's verdict line.
  out="$head
$body
--- docs/roles/state-check.sh (shortened: output near the hook cap; run it and git log yourself) ---
$(printf '%s\n' "$check" | tail -n 1)"
fi
printf '%s\n' "$out"
exit 0

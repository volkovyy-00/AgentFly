#!/usr/bin/env bash
# Lead tool: make a card's worktree and branch from main and print the owner's start command.
# Usage: docs/roles/dispatch.sh <card> <slug>   e.g. docs/roles/dispatch.sh V8b recorder-fields
# Never starts claude (docs/roles/lead.md). Stops before changing anything when a check fails.
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: $0 <card> <slug>" >&2; exit 2; }
card="$1"
lower=$(printf '%s' "$card" | tr '[:upper:]' '[:lower:]')
branch="ag-$lower-$2"
root="$(cd "$(dirname "$0")/../.." && pwd)"
wt="$root/.claude/worktrees/$branch"
brief="docs/briefs/$card.md"
min_gib=5  # a worktree's .venv plus a trial merge's (docs/learnings.md)

stop() { echo "dispatch: $*" >&2; exit 1; }
[ "$(git -C "$root" symbolic-ref --short -q HEAD)" = "main" ] || stop "run from the main checkout on main"
git -C "$root" cat-file -e "main:$brief" 2>/dev/null || stop "$brief is not committed on main"
git -C "$root" diff --quiet main -- "$brief" || stop "$brief has uncommitted changes; commit them first"
git -C "$root" rev-parse -q --verify "refs/heads/$branch" >/dev/null && stop "branch $branch already exists"
[ -e "$wt" ] && stop "$wt already exists"
free_gib=$(df -g "$root" | awk 'NR == 2 {print $4}')
[ "$free_gib" -ge "$min_gib" ] || stop "only ${free_gib} GiB free (need $min_gib); remove merged worktrees first"
line=$(grep -m 1 '^You are a worker on card' "$root/$brief" || true)
[ -n "$line" ] || stop "$brief has no \"You are a worker on card …\" line"
case "$line" in *"$wt"*) ;; *) stop "the worker line in $brief does not name $wt" ;; esac

git -C "$root" worktree add -q -b "$branch" "$wt" main
# A failed install leaves nothing behind, so the same command can simply be run again.
# (Explicit checks, not an ERR trap: macOS's bash 3.2 does not fire it for a failed subshell.)
undo() {
  git -C "$root" worktree remove --force "$wt"
  git -C "$root" branch -q -D "$branch"
  stop "$1 failed; worktree and branch removed"
}
(cd "$wt" && uv sync -q) || undo "uv sync"
if grep -E '^- (Touches|\*\*May touch)' "$root/$brief" | grep -q 'ui/'; then
  npm --prefix "$wt/ui" ci --silent || undo "npm ci"
fi

echo "Worktree $wt on $branch ($(git -C "$wt" rev-parse --short HEAD)); ${free_gib} GiB were free."
echo
echo "Start the worker in a new terminal:"
echo "  cd $wt && claude --permission-mode plan"
echo "Then paste:"
echo "  ${line//this brief/$brief}"

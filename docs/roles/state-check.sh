#!/usr/bin/env bash
# Read-only check that the lead's files agree with each other, git and disk.
#   state-check.sh                                 check; exit 1 on any FAIL
#   state-check.sh drift "<flight>" "<pending>" N  compare the lead's memory with the files
#   state-check.sh --write-index                   regenerate the index block in DECISIONS.md
# STATE= and DECISIONS= override the file paths (for tests).
set -u
root="$(cd "$(dirname "$0")/../.." && pwd)"
STATE="${STATE:-$root/docs/STATE.md}"
DECISIONS="${DECISIONS:-$root/docs/DECISIONS.md}"
fails=0
warns=0
fail() { echo "FAIL: $*"; fails=$((fails + 1)); }
warn() { echo "WARN: $*"; warns=$((warns + 1)); }

# IDs such as D2 or V1, one per word, sorted.
ids() { tr ',;·' '   ' | tr ' ' '\n' | grep -E '^[A-Z][0-9]+[a-z]?$' | sort -u | xargs; }
section() { awk -v h="$1" 'index($0, "## " h) == 1 {f = 1; next} /^## / {f = 0} f' "$STATE"; }
proposed() {
  awk '/^## D[0-9]+\./ {id = $2; sub(/\.$/, "", id)}
       /^Status:/ && id != "" {s = $2; gsub(/[*,:]/, "", s); if (s == "proposed") print id; id = ""}' "$DECISIONS" | ids
}
index_lines() {
  awk '/^## D[0-9]+\./ {id = $2; sub(/\.$/, "", id); t = $0; sub(/^## D[0-9]+\. */, "", t)
                        if (length(t) > 60) t = substr(t, 1, 57) "..."}
       /^Status:/ && id != "" {s = $2; gsub(/[*,:]/, "", s); d = ""
                               if (match($0, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/)) d = " " substr($0, RSTART, RLENGTH)
                               if (s != "approved") d = ""
                               print "- " id " " s d " · " t; id = ""}' "$DECISIONS"
}
flight() { section "In flight" | grep -E '^- [A-Z][0-9]+' | sed 's/^- //' | ids; }
waiting() { section "Waiting on owner" | grep -cE '^[0-9]+\.'; }
pending_in_state() { grep -m 1 '^Pending decisions:' "$STATE" | cut -d: -f2- | ids; }

if [ "${1:-}" = "--write-index" ]; then
  tmp="$DECISIONS.tmp.$$"
  index_lines > "$tmp.idx"
  awk -v idx="$tmp.idx" '/^<!-- index:start/ {print; while ((getline l < idx) > 0) print l; skip = 1; next}
                         /^<!-- index:end/ {skip = 0} !skip' "$DECISIONS" > "$tmp" && mv "$tmp" "$DECISIONS"
  rm -f "$tmp.idx"
  echo "index written: $(index_lines | wc -l | tr -d ' ') decisions"
  exit 0
fi

if [ "${1:-}" = "drift" ]; then
  want_f=$(echo "${2:-}" | ids); want_p=$(echo "${3:-}" | ids); want_w="${4:-}"
  have_f=$(flight); have_p=$(proposed); have_w=$(waiting)
  [ "$want_f" = "$have_f" ] || fail "flight: you said [$want_f], files say [$have_f]"
  [ "$want_p" = "$have_p" ] || fail "pending: you said [$want_p], DECISIONS.md says [$have_p]"
  [ "$want_w" = "$have_w" ] || fail "waiting: you said [$want_w], STATE.md says [$have_w]"
  [ "$fails" -eq 0 ] && echo "drift: PASS" || echo "drift: FAIL"
  [ "$fails" -eq 0 ]
  exit
fi

[ -f "$STATE" ] || { echo "FAIL: $STATE not found"; exit 1; }
[ -f "$DECISIONS" ] || { echo "FAIL: $DECISIONS not found"; exit 1; }

lines=$(wc -l < "$STATE" | tr -d ' ')
chars=$(wc -c < "$STATE" | tr -d ' ')
[ "$lines" -le 60 ] || fail "STATE.md has $lines lines (cap 60)"
[ "$chars" -lt 9000 ] || fail "STATE.md has $chars chars (cap 9000)"

if grep -q '^Pending decisions:' "$STATE"; then
  sp=$(pending_in_state); dp=$(proposed)
  [ "$sp" = "$dp" ] || fail "pending decisions: STATE says [$sp], DECISIONS.md says [$dp]"
else
  fail "STATE.md has no 'Pending decisions:' line"
fi

if grep -q '^<!-- index:start' "$DECISIONS"; then
  have=$(awk '/^<!-- index:start/ {f = 1; next} /^<!-- index:end/ {f = 0} f' "$DECISIONS")
  [ "$have" = "$(index_lines)" ] || fail "DECISIONS.md index is stale; run state-check.sh --write-index"
else
  fail "DECISIONS.md has no index block"
fi

while IFS= read -r p; do
  [ -n "$p" ] || continue
  case "$p" in /*) f="$p" ;; *) f="$root/$p" ;; esac
  [ -e "$f" ] || warn "in-flight path missing: $p"
done <<EOF
$(section "In flight" | grep -E '^- [A-Z][0-9]+' | tr '·' '\n' | sed 's/^ *//; s/ *$//; s/`//g' | grep '/')
EOF

# An in-flight branch whose diff from main touches a lead file would bring an old copy back at merge.
for b in $(section "In flight" | grep -E '^- [A-Z][0-9]+' | awk -F' · ' '{print $4}' | tr -d '`'); do
  git -C "$root" rev-parse -q --verify "refs/heads/$b" >/dev/null || continue
  touched=$(git -C "$root" diff --name-only "main...$b" -- docs/STATE.md docs/BOARD.md docs/DECISIONS.md docs/learnings.md)
  [ -z "$touched" ] || warn "branch $b changes lead file(s) against main:" $touched
done

for pid in $(grep -oE 'pid [0-9]+' "$STATE" | awk '{print $2}' | sort -u); do
  kill -0 "$pid" 2>/dev/null || warn "pid $pid in STATE.md is not running"
done
for p in $(grep -oE '/tmp/[A-Za-z0-9._/-]*[A-Za-z0-9_-]' "$STATE" | sort -u); do
  [ -e "$p" ] || warn "$p in STATE.md does not exist"
done

head_sha=$(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo "?")
last=$(git -C "$root" log -1 --format=%h -- docs/STATE.md 2>/dev/null)
since=$(git -C "$root" rev-list --count "${last:-HEAD}..HEAD" 2>/dev/null || echo "?")
git -C "$root" diff --quiet -- docs/STATE.md 2>/dev/null || warn "STATE.md has uncommitted changes"
echo "info: HEAD $head_sha · STATE.md last committed in ${last:-never}, $since commits ago · flight=[$(flight)] waiting=$(waiting)"

if [ "$fails" -eq 0 ]; then
  echo "state-check: OK ($warns warnings)"
else
  echo "state-check: FAIL ($fails failures, $warns warnings)"
  exit 1
fi

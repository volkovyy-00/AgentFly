#!/usr/bin/env bash
# Install the Neo4j credentials file OUTSIDE the project.
#
# Usage: scripts/setup_credentials.sh <downloaded-aura-file> [--force]
#
# - Copies the file to ~/.config/flightrecorder/.env (folder 700, file 600).
# - Never prints values. Only key names and permissions are shown.
# - The original file is left where it is: delete it yourself when done.
set -euo pipefail

SRC="${1:-}"
FORCE="${2:-}"
DIR="$HOME/.config/flightrecorder"
DEST="$DIR/.env"
REQUIRED=(NEO4J_URI NEO4J_USERNAME NEO4J_PASSWORD)

if [[ -z "$SRC" || ! -f "$SRC" ]]; then
  echo "usage: $0 <downloaded-aura-file> [--force]" >&2
  exit 1
fi

if [[ -e "$DEST" && "$FORCE" != "--force" ]]; then
  echo "$DEST already exists. Use --force to overwrite." >&2
  exit 1
fi

mkdir -p "$HOME/.config"
mkdir -p "$DIR"
chmod 700 "$DIR"

# Write with a restrictive umask so the file is never briefly world-readable.
( umask 077 && cp "$SRC" "$DEST" )
chmod 600 "$DEST"

# Portable permission check (macOS: -f %Lp, Linux: -c %a).
file_mode() { stat -f %Lp "$1" 2>/dev/null || stat -c %a "$1"; }

status=0
echo "Folder mode: $(file_mode "$DIR") (want 700)"
echo "File mode:   $(file_mode "$DEST") (want 600)"

for key in "${REQUIRED[@]}"; do
  if grep -q "^${key}=." "$DEST"; then
    echo "  found:   $key"
  else
    echo "  MISSING: $key" >&2
    status=1
  fi
done

exit "$status"

#!/usr/bin/env bash
# Start the AgentFly lead. Workers never use this file.
# The role (lead.md) goes into the system prompt, so it survives /clear and
# compaction; lead-settings.json adds the SessionStart hook for this launch only.
# Usage: docs/roles/lead.sh [more claude args, e.g. --resume]
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
exec claude --append-system-prompt-file "$root/docs/roles/lead.md" \
  --settings "$root/docs/roles/lead-settings.json" \
  --name agentfly-lead "$@"

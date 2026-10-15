---
description: AgentFly lead only. Write the handoff files and commit on main.
argument-hint: [phase label]
disable-model-invocation: true
---
Handoff for phase "$ARGUMENTS". If this session is not the AgentFly lead (started with docs/roles/lead.sh), stop and say so.
Follow the "Handoff" section of docs/roles/lead.md. Reply with only the commit SHA, the last line of docs/roles/state-check.sh, and anything not captured in the files.

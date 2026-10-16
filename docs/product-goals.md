# AgentFly product goals

## What AgentFly is today
A hackathon project: Cursor hooks send every agent action (file reads, shell commands, MCP calls, edits) to a local recorder that applies rules (one hard-coded rule, R1) and answers allow/deny before the action runs. A React + XYFlow page shows the live trail; steps can optionally be written to Neo4j. It only works inside its own cloned repo.

## Where it should go
Watch and protect any Cursor project on my machine, with rules I can change easily and a UI I enjoy looking at.

## Goals

### G1. Install once, protected everywhere
- Target flow: `brew install agentfly` -> `agentfly init -g` -> `agentfly start` -> open any project in Cursor and it is watched and protected.
- No cloning AgentFly and no working inside its repo.
- Clean upgrade and uninstall that removes the hooks.
- Done when: a fresh project opened in Cursor is protected with no per-project setup.

### G2. Configurable rules, ideally in plain language
- Move hard-coded rules (R1, outbound tools, sensitive file names) into a rules file.
- Three rule outcomes: block, warn, highlight.
- Add or change rules in plain language ("block npm publish after reading .env"); I see the generated rule and approve it before it is saved.
- Done when: I can add a new rule without touching Python code.

### G3. A much better UI
- A UI that is clear and good-looking, not just a refreshed Vite page.
- Must show the live trail, why something was blocked or flagged, and past sessions.
- Must stay readable in long sessions.
- Done when: I'd be happy to show it in a demo video as-is.

### G4. Memory / context layer across sessions (experimental)
- Use the graph for more than storage: summarise actions across sessions and possibly give the agent useful context in later sessions.
- First question is feasibility and value, not building it.
- Done when: I have a clear yes/partly/no with one small experiment to prove it.

## Hard constraints (non-negotiable)
- The watched agent must never be able to edit, disable or weaken its own rules.
- No secrets or file contents stored; anything beyond that needs my explicit decision.
- Blocking decisions stay fast and local (no waiting on network or database).
- Everything runs locally on my machine.

## Out of scope for now
- Teams, central dashboards, cloud sync, SSO.
- Agents other than Cursor (keep the design open for Claude Code later).

## Priority order
G1 install, G2 rules, G3 UI, G4 memory (experiment only).

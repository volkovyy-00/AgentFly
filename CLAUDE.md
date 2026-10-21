# CLAUDE.md

@AGENTS.md

## Roles
- A session's role is set when it starts. The lead is started with `~/Projects/AgentFly-process/docs/roles/lead.sh`; every other session is a worker on one card.
- Process files (briefs, reports, decisions, the lead's files) live in a private repo next to this one, `~/Projects/AgentFly-process` (D31). This repo holds the product only.
- A worker follows AGENTS.md and its card brief (`~/Projects/AgentFly-process/docs/briefs/<card>.md`). It does not read that repo's `docs/roles/`, `docs/STATE.md` or other cards' reports.
- A worker finishes a card by writing the report described in `~/Projects/AgentFly-process/docs/reports/README.md`, by that absolute path, and does not commit it. Its branch here carries code only.
- Specs and plans a skill writes (superpowers puts them under `docs/superpowers/`) go in `~/Projects/AgentFly-process/docs/superpowers/` instead, uncommitted, like the report.
- Call the project owner "the owner" in every file you write (author lines too). Never write their name.
- Only the lead edits and commits in the private repo. A git pre-commit hook rejects process files staged here (anything under `docs/` but `docs/media`, and `.claude/commands`).

# Compact instructions
Keep: your role and card, files you own or changed, decisions by ID (D-numbers) and their status, open questions for the owner, next actions. Drop raw tool output, file contents and logs; they are in the repo.

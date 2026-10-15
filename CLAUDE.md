# CLAUDE.md

@AGENTS.md

## Roles
- A session's role is set when it starts. The lead is started with `docs/roles/lead.sh`; every other session is a worker on one card.
- A worker follows AGENTS.md and its card brief. It does not read `docs/roles/`, `docs/STATE.md` or other cards' reports.
- A worker finishes a card by writing the report described in `docs/reports/README.md`.
- Call the project owner "the owner" in every file you write (author lines too). Never write their name.
- Only the lead edits `docs/STATE.md`, `docs/BOARD.md`, `docs/DECISIONS.md` and `docs/learnings.md`. A git pre-commit hook rejects them on any branch other than main.

# Compact instructions
Keep: your role and card, files you own or changed, decisions by ID (D-numbers) and their status, open questions for the owner, next actions. Drop raw tool output, file contents and logs; they are in the repo.

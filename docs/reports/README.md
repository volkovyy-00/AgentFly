# Worker reports

Each card gets one report: `docs/reports/<card>.md`, committed on the card's branch.
Lines 1–6 are the current status. Overwrite them on every update; never append there.
The lead reads only `head -n 6`, so keep each field to 300 characters or fewer.

```
# <card>: <title>
Status: in progress | blocked | done (as of YYYY-MM-DD HH:MM)
Result: What works and what does not.
Evidence: Commit SHA, check command and pass count, test names, file paths.
Needs owner: none | one question, with your recommended answer.
Details: see "## YYYY-MM-DD HH:MM" below.
```

Below line 6: one `## YYYY-MM-DD HH:MM` section per update, newest first, with the full
evidence (pasted command output, paths). Spike reports (`docs/spikes/<id>.md`) use the same top block.

Before you set `Status: done`, review your own branch: in Claude Code run `/code-review high` on the
diff `main...HEAD`. Fix a finding only inside your card's Touches/May-touch list; list every other
finding, and any you chose not to fix, under the newest `##` section with one line on why. A Cursor
worker without `/code-review` says so in that section.

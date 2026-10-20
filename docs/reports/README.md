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

Before you set `Status: done`, once the implementation is complete and the AGENTS.md check passes,
close the card in this order in Claude Code, without waiting to be asked:
1. Run `/final-verification` on the whole branch diff (`main...HEAD`, not only uncommitted changes).
   Its simplify step changes only files your branch already changed. Commit the result.
2. Then run `/code-review high` on the diff `main...HEAD`.
Fix a finding only inside your card's Touches/May-touch list; list every other finding, and any you
chose not to fix, under the newest `##` section with one line on why. Paste the final-verification
verdict there too. A Cursor worker without these skills says so in that section.

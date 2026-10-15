# Red-team: the lead's long-memory setup

15 Oct 2026, Claude Code 2.1.300, tree at `aa3e7f2`. Tags: **[seen]** = I checked it on this machine today; **[docs]** = taken from lead-context.md §3; **[inferred]** = a hypothesis with a test below.

**Verdict.** State-in-files is the right idea. But today the design depends on three rituals the model has to remember (handoff, restart prompt, "only the lead writes"), and **nothing checks** whether those files agree. Two loading gaps already exist, and so do several disagreements between files. The fixes are one git hook, one check script and one role-gated session hook. Slash commands are optional on top.

## 1. What gets lost, and when
| Event | Lost | Still there |
|---|---|---|
| `/clear` | Everything since the last STATE write. The research's hook matches `compact` only, so **nothing is injected after `/clear`** (source `clear`). The restart depends on the owner pasting the prompt. | CLAUDE.md, files on disk |
| Auto/idle compaction | Talk-only facts (approvals said in chat but not yet written down, a worker's verbal status). The hook re-injects STATE **as of the last handoff** and labels it "current". The new summary and an older STATE then disagree, and nothing marks which one is older. | CLAUDE.md, `# Compact instructions`, 5 recent files [docs] |
| Usage limit → Codex/Cursor | Hooks, slash commands and CLAUDE.md. Codex and Cursor read only AGENTS.md, which never mentions `docs/roles/lead.md` or STATE. The limit gives no warning, so no handoff runs. `autoContinueAtUsageLimit: true` is set in `~/.claude/settings.json` [seen], so the Claude lead may **resume by itself** after the reset while Codex is already writing STATE. That makes two writers. [inferred] | git, docs |
| Away for a day | Idle compaction fires at about 54 min if the session is over 200K [docs]. Machine state goes stale silently: pid 34143 is alive now [seen], but a reboot kills it, and the reboot also empties `/tmp`. **`/tmp/af-spike/s1.sh` and `s2.sh` are the only copies of the S5 prerequisite** (STATE line 24). | — |

## 2. Disagreements between files (found today, not hypothetical)
1. **DECISIONS.md line 3** says "Status of every entry: **proposed**", but the body has D1, D4, D10, D14 and D20 approved [seen]. The header contradicts the body.
2. **BOARD.md has no per-card status.** Its header still says "spikes S1–S5 may start now", and S1/S2 being done appears only in STATE [seen]. Handoff step 2 in lead.md ("BOARD agrees with STATE") was not done at the first handoff. "Collapse done cards" can't work without a status field.
3. **S2 report vs STATE**: S2-tamper.md line 3 says "cleanup (`s2.sh restore`) pending", while STATE says "Looks like s2.sh restore was already run" [seen]. That's a guess from the lead written as a finding.
4. **AGENTS.md Hook facts** say Cursor 3.5.17; the installed version is 3.24.12 (`Info.plist`) [seen]. The only place this is recorded is in STATE's "risks" section.
5. **Approved changes not applied**: D10 says "Changes: AGENTS.md Working rules", but AGENTS.md has no heredoc rule. D14 says "Changes: SPEC.md §3, §4", but SPEC has no SQLite [seen]. AGENTS.md tells every worker that "SPEC.md is the source of truth", so until V1 lands, a worker follows rules from before the approvals.
6. **Report format has three versions**: lead.md says `Result/Evidence/Needs owner`; the proposed design adds `Status`; the actual S1/S2 reports start with `Status:` + `Plan:` [seen]. Also, `docs/reports/` does not exist yet.
7. **Size cap**: lead.md says under 9,000 chars; the research says under 10,000; the hook truncates with `head -c 9000`. If it truncates, it **drops the bottom of STATE, where "Next 3 actions" lives**, without saying so.
8. **"Last commit" line**: STATE can't contain the SHA of its own commit, so the line holds a grep instruction. It's correct today (`aa3e7f2`, parent `0e6b8a6`), but it's a ritual where a computed value would do.
9. These **match** today: STATE's pending list equals the proposed set in DECISIONS (D2 D3 D5–D9 D11–D13 D15–D19), and there are 0 commits since STATE [seen]. A script can keep them matching (fix 2).
10. The proposed **one-line DECISIONS index** would be a third copy of each status, after the status line and STATE. Generate it; don't hand-write it (fix 6).

## 3. What grows without limit
- DECISIONS.md (502 lines, 34 KB, append-only, replaced entries stay) and BOARD.md (414 lines, 21 KB). Fine while nothing auto-loads them; never `@import` them.
- Reports: one per card, so the count grows. The lead reads only top blocks, so that's OK as long as the top block has a fixed size.
- STATE's "Decisions changed since last handoff (first handoff: all of these)" section is an append log inside a file meant to be overwritten.
- `docs/learnings.md`: no owner prunes it. Cap it at 50 lines and never import it.
- Compact-summary log (the PostCompact idea): **skip it.** Transcripts already sit in `~/.claude/projects/-Users-volkovyy-Projects-AgentFly/` (79 entries [seen]). Committing summaries copies chat content, possibly including secrets, into git.
- Auto memory: there's no `memory/` dir yet [seen]. It's keyed by repo, so lead and workers share one `MEMORY.md` [docs, inferred for worktrees], and it loads into every session.

## 4. Role leakage
- **A committed `.claude/settings.json` reaches every worktree.** An ungated hook gives workers the lead's STATE, which is Daniel's persona lesson. **A committed `.claude/commands/handoff.md` reaches every worktree too.** If a worker runs it, it overwrites STATE **on its own branch**. If main's STATE hasn't changed since the fork, `git merge` **takes the worker's STATE silently, with no conflict.** The same goes for BOARD and DECISIONS.
- `.claude/settings.local.json` is ignored only through `~/.config/git/ignore` [seen], not through the repo's `.gitignore`. It doesn't exist in worktrees, so a lead started from a worktree gets no hook and no warning.
- `~/.claude/settings.json` or `~/.claude/commands` would fire in **every project**. Elsewhere, `docs/STATE.md` would be missing (hook error) or would belong to another project (wrong state injected).
- Worktrees live in `.claude/worktrees/` **inside** the main checkout. CLAUDE.md lookup walks up the tree, so a worker probably loads both its branch's CLAUDE.md and main's current one [inferred; test: `/memory` in a worktree session].
- `crossSessionInbound: "accept"` [seen] lets other sessions send messages into the lead, which goes against the quiet policy [inferred].
- `.DS_Store` and `docs/.DS_Store` are untracked and not ignored [seen], so a `git add docs` at handoff would commit them.

## 5. Stale or wrong STATE: there's no detection today
Nothing compares STATE with git, DECISIONS, worktrees or processes. §6.6 of the research ("ask the lead to list cards from STATE") relies on the model checking itself. Fix 2 below replaces it with a script.

## 6. Loading gap (the biggest single finding)
CLAUDE.md says "Project rules live in AGENTS.md (read it first)", which is prose, **not `@AGENTS.md`**. AGENTS.md loads only when there is **no** CLAUDE.md [docs], so **no Claude session (lead or worker) gets the project rules automatically.** It reads them only if the model decides to. They also don't come back after compaction. Note: AGENTS.md line 6 contains `@SPEC.md`, so importing AGENTS.md also pulls in SPEC.md (21 KB). Either accept that, or change it to plain `SPEC.md`.

## 7. Hook failure modes (research §6.4 command)
- `cd … && echo && head … && echo && git log`: if any step fails (git missing, `safe.directory` problem, not a repo), the exit code is non-zero, and stdout that was already printed may be dropped (only exit 0 stdout is reliably injected [docs, inferred for partial output]). The script must always `exit 0` and print its own error line.
- Missing STATE (old branch, other project): `head` error, nothing injected, no error visible to the user.
- Over 10,000 chars: replaced by a path plus a 2,000-char preview [docs]. At 9,000 chars `head -c` also cuts multibyte `✅`/`→` in half. **Refuse instead of truncating.**
- A `$CLAUDE_PROJECT_DIR` path containing a space is fine when quoted. Unquoted, it is exactly F1 from S2 (exit 2 → everything denied in Cursor). Quote every expansion.
- The hook belongs to the settings snapshot at session start, so adding it mid-session does nothing until a restart or a `/hooks` review [inferred].

## Minimum fixes, ranked (cheap and mechanical first)
1. **Import the rules.** Add the line `@AGENTS.md` to CLAUDE.md.
   Test: `claude -p --disallowedTools "Read,Bash,Grep,Glob" "Without tools: what HTTP timeout does AGENTS.md give the hook helper? Say UNKNOWN if AGENTS.md is not in your context."` Today it should answer `UNKNOWN`; after the fix, `about 0.5 s`.
2. **`scripts/state-check.sh`** (read-only, under 60 lines, exit 1 on any FAIL). It checks: STATE has 60 lines or fewer and 9,000 chars or fewer; the commit count since STATE last changed (`git rev-list --count $(git log -1 --format=%H -- docs/STATE.md)..HEAD`) is 0, and BOARD/DECISIONS are not dirty; the `Pending decisions:` line in STATE equals the awk-derived proposed set in DECISIONS; every path and worktree under `## In flight` exists (`git worktree list`); every `pid N` is alive; every `/tmp/...` path exists. It also prints the commit hash (this replaces the "Last commit" line).
   Test: `scripts/state-check.sh` → `OK lines=55 chars=4072 since=0 pending=15 inflight=0`. Negative test: `sed 's/D19$/D19 D4/' docs/STATE.md > /tmp/s.md && STATE=/tmp/s.md scripts/state-check.sh; echo $?` → `FAIL: D4 pending in STATE, approved in DECISIONS` then `1`.
3. **Git pre-commit hook** (`git config core.hooksPath scripts/git-hooks`, shared by all worktrees; works for Cursor and Codex workers too). On any branch other than `main`, it rejects staged `docs/STATE.md`, `docs/BOARD.md` and `docs/DECISIONS.md`. On `main`, it runs `state-check.sh` when one of them is staged. It always rejects `.DS_Store`.
   Test: `git worktree add -q /tmp/wt-t -b wt-t && echo x >> /tmp/wt-t/docs/STATE.md && git -C /tmp/wt-t commit -qam t; echo $?` → `pre-commit: docs/STATE.md is lead-only (branch wt-t)` then `1`. Clean up with `git worktree remove --force /tmp/wt-t && git branch -D wt-t`.
4. **One role-gated session hook**, committed in `.claude/settings.json`, `SessionStart` matcher `startup|clear|compact|resume`, running `"$CLAUDE_PROJECT_DIR"/scripts/lead-context.sh`. If `AGENTFLY_ROLE` is not `lead`, it exits 0 silently. Otherwise it prints `STATE as of <Updated>`, STATE itself (or only its path if it's over 9,000 chars), the state-check output and `git log --oneline -5`, and always exits 0. The lead starts with `alias lead='AGENTFLY_ROLE=lead claude'`. This makes the hook opt-in, the same everywhere, independent of settings.local.json, and it covers `/clear`.
   Test: `echo '{}' | AGENTFLY_ROLE=lead CLAUDE_PROJECT_DIR="$PWD" scripts/lead-context.sh | wc -c` → under 10000, exit 0. Without the variable, the output is `0`. With `CLAUDE_PROJECT_DIR=/tmp/nope` it prints one line `lead-context: docs/STATE.md not found` and exits 0. With `ln -s "$PWD" "/tmp/a b"` and `CLAUDE_PROJECT_DIR="/tmp/a b"`, the output is the same as the first case.
5. **Fix today's disagreements once.** DECISIONS line 3 → "Status: see each entry". Add a `- **Status:**` line to each of the 14 BOARD cards and update the header. Have the S2 cleanup checked and fixed in both the report and STATE. Add `.DS_Store` to `.gitignore`. Rename the STATE line to `Pending decisions: D2 …`.
   Tests: `grep -c '^- \*\*Status:\*\*' docs/BOARD.md` → `14`; `git status --porcelain | grep -c DS_Store` → `0`.
6. **Generate views; don't copy them.** Generate the DECISIONS index with `awk '/^## D[0-9]+\./{id=$2;sub(/\.$/,"",id)} /^Status:/&&id{print id,($0~/approved/?"approved":"proposed");id=""}' docs/DECISIONS.md`, as a `/decisions` command or inside state-check, not as hand-written lines.
   Test: today this prints 20 lines, 5 of them `approved`.
7. **Make the setup survive reboots and tool switches.** Move `/tmp/af-spike/*.sh` to `logs/spike/` (already gitignored).
   Test: `git check-ignore -v logs/spike/s1.sh` → `.gitignore:6:logs/`.
   Rules for lead.md: (a) write STATE **when something changes** (card dispatched or finished, decision approved), not only at handoff, because limit switches give no warning; (b) quit the Claude lead before a Codex lead takes over, because of auto-continue; (c) after more than 1 h away, run `/clear` (fix 4 re-injects STATE) instead of continuing in a compacted chat. Make slash commands thin wrappers ("follow lead.md § Handoff") so Codex can follow the same text.
8. **Optional:** add `"autoMemoryEnabled": false` to `.claude/settings.json` to keep one shared, unreviewed memory out of every worker [verify the key with `/config`].
   Test: `ls ~/.claude/projects/-Users-volkovyy-Projects-AgentFly/memory` stays absent.

**Skip:** the PostCompact log; a hand-written decision index; a `/restart-lead` paste (fix 4 replaces it); hooks in `~/.claude`; hooks in settings.local.json for anything the lead depends on.

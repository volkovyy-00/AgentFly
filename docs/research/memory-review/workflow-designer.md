# Lead/worker workflow: file set and rituals (workflow-designer, 2026-10-15)
Tags: [Daniel] Starwatch file · [docs] code.claude.com (checked via Context7 today) · [measured] Anthropic engineering article · [anecdote] Shankar · [inferred] mine · [checked] run on this machine today. LC§n = docs/research/lead-context.md section.

## 0. The whole set (3 edits, 4 new files, 0 hooks committed)
| File | Committed | Loaded by | Change |
|---|---|---|---|
| `CLAUDE.md` | yes | every Claude session | role-neutral (§7); `@AGENTS.md` instead of "read it first" |
| `AGENTS.md` | yes | every Claude (via import) and Cursor session | +7-line "Report" section (§1) — do it inside V1 (D17 owns AGENTS.md) or as a lead edit Yevhenii approves |
| `docs/roles/lead.md` | yes | lead only, on demand | add "Start", "Drift check"; extend "Handoff" (§4–6) |
| `docs/roles/drift-check.sh` | yes, new | lead only | mechanical drift + index check (§6) |
| `.claude/commands/{lead,handoff,catchup}.md` | yes, new | nobody until typed | 3-line pointers into lead.md (§4) |
| `.claude/settings.json` | yes, new | every session | `{"autoMemoryEnabled": false}` (§7) |
| `docs/learnings.md` | yes, new at first phase end | on demand | §3 |
No CHANGELOG, no docs/reports/TEMPLATE.md, no `agent` setting, no committed hook.
Why AGENTS.md is imported: CLAUDE.md exists, so Claude reads AGENTS.md only if it obeys the pointer [docs memory, LC§3]. Cost: AGENTS.md line 6 has `@SPEC.md`, which then imports SPEC.md too (419 lines [checked]). Change that to plain "SPEC.md" in V1, or accept it.

## 1. Worker report: `docs/reports/<card>.md`
Template lives as the AGENTS.md "Report" section, verbatim below. Cursor and Claude workers both load AGENTS.md, so no worker ever needs lead.md to find it; a separate TEMPLATE.md would need a pointer in AGENTS.md anyway [inferred].
```
## Report (every card): docs/reports/<card>.md in your worktree, commit it on your branch
Lines 1-6 are the current status; overwrite them on every update, never append there.
  # <card>: <title>
  Status: in progress | blocked | done (as of YYYY-MM-DD HH:MM)
  Result: <=300 chars. What works and what does not.
  Evidence: <=300 chars. Commit SHA, check command + pass count, test names, file paths.
  Needs Yevhenii: none | <=300 chars, one question with your recommended answer.
  Details: see "## YYYY-MM-DD HH:MM" below. Newest section first; nothing above line 7 but the above.
```
- Fields and caps come from Daniel's parser (`Result`/`Evidence`/`Needs Daniel`, cut at 650/600/500 chars; `none` hides Needs) [Daniel] `project_tracker/model.py` `report_fragments()`. I tighten to 300 each so the block stays under ~1,000 chars [inferred].
- Divergence from Daniel: his parser read the *last* `## ` section (append at bottom). Latest-on-top lets the lead read with `head -n 6`, no parser [inferred]. Same idea as Anthropic's progress file read at every session start [measured] harnesses article.
- How the lead reads it before merge: STATE.md's in-flight row holds the absolute report path in the worktree; the lead runs `head -n 6 <that path>`, or after a commit `git show <branch>:docs/reports/<card>.md | head -n 6` (worktrees share refs) [inferred]. Spikes keep `docs/spikes/<id>.md` with their existing `Status:` line.
- Yevhenii pastes "V2 report ready" to the lead, never the transcript (main pollution source, LC§6.1).

## 2. BOARD collapse and DECISIONS index (lead is the only writer of both, lead.md "Owns")
**BOARD.md.** At handoff, a done card's body is deleted and one line added to `## Done` directly under the status paragraph:
`- S1 ✅ 2026-10-15 · docs/spikes/S1-global-hooks.md · changed D9 D11 · body: git show aa3e7f2:docs/BOARD.md`
The body survives in git; the line names the last commit that still had it. Basis: Daniel's control room hid completed cards until selected [Daniel] tracker README; Anthropic's harness kept done items as a flag, not prose [measured] harnesses article. Also drop the "Revision N applies your review" paragraphs once older than one revision (they are in git log).
**DECISIONS.md.** One line per decision under the intro, before `---`:
`- D1 approved 2026-10-15 · Yevhenii · option A, sudo by default`
`- D2 proposed · lead · system hooks.json, root-owned`
Format: `- D<n> <status> [date] · <who decided> · <=60-char gist>`. Status is the first word of the body's `Status:` line (proposed | approved | replaced). "Who" records provenance: Yevhenii only on his explicit yes, else `lead` [Daniel] learnings "Record provenance of decisions". Consistency is not trusted to care: `drift-check.sh` (§6) diffs index statuses against the body `Status:` lines and must print `INDEX OK` before the handoff commit. Today's 20 body statuses parse cleanly with that awk [checked].

## 3. docs/learnings.md
- Daniel's format: `## <topic>` then bullets `- **Imperative rule.** What happened, with numbers/dates.` One bullet ≤2 lines [Daniel] docs/learnings.md.
- Writer: lead only, at handoff, from worker reports' Details and Yevhenii's corrections. Workers do not write it; a lesson goes in their report's Details. Never auto-loaded, never imported [docs memory size; LC§6.1].
- Cap ~80 lines. When a lesson becomes a standing rule, move it into AGENTS.md (workers) or lead.md (lead) and delete it here, so there is one copy [inferred].

## 4. Slash commands: committed `.claude/commands/`, all `disable-model-invocation: true`
| Option | Worktrees get it | Versioned | Leak to workers | Verdict |
|---|---|---|---|---|
| `.claude/commands/` committed | yes (tracked) | yes | name in `/` menu only | **choose** |
| `~/.claude/commands/` | yes | no | same, plus every other project on the Mac | no |
| gitignored local dir | no (untracked files don't reach worktrees; `.worktreeinclude` could copy them) [docs worktrees] | no | none | lost if the checkout is recloned |
| `claude --agent lead` | n/a | yes | none | no: its prompt **replaces** Claude Code's system prompt; and the `agent` key in settings.json is exactly Daniel's every-session-is-HoS trap [docs sub-agents; Daniel] |
With `disable-model-invocation: true` the model never loads or auto-runs them [docs slash-commands], so in a worker they cost nothing and fire only if someone types them. The real leak would be a hook or setting that injects STATE into workers; none is committed. Each command is a pointer, so the ritual text lives once, in lead.md, readable by Codex/Cursor too.
`.claude/commands/lead.md`
```
---
description: Yevhenii only. Start this session as the AgentFly lead.
disable-model-invocation: true
---
You are the AgentFly lead for this session. Read docs/roles/lead.md and follow its "Start" section. $ARGUMENTS
```
`.claude/commands/handoff.md`
```
---
description: Lead only. Write the handoff files and commit; Yevhenii then runs /clear.
argument-hint: [phase label]
disable-model-invocation: true
---
Handoff for phase "$ARGUMENTS". Follow the "Handoff" section of docs/roles/lead.md. Reply with only the commit SHA, the drift-check.sh output, and anything not captured in the files. Then stop.
```
`.claude/commands/catchup.md`
```
---
description: Lead only. Drift check after compaction or a pause, then read what changed.
disable-model-invocation: true
---
Follow the "Drift check" section of docs/roles/lead.md. Before calling any tool, write your three answers from memory. On FAIL stop and tell Yevhenii to run /clear then /lead. On PASS read the top 6 lines of each in-flight report, run git log --oneline <last handoff SHA>..HEAD, and tell Yevhenii in 5 lines what changed and what you propose. Wait for his go.
```
lead.md additions: **Start** = "Read STATE.md; if `git log --grep=^handoff -1` is older than reports/commits since, say STATE may be stale and read those first; read in-flight report heads; `git log --oneline -15`; 5-line status; wait." (LC§6.3). **Handoff** = existing 5 steps + collapse done cards (§2) + learnings (§3) + `drift-check.sh` with the lead's own values must PASS and print INDEX OK. Also: STATE.md is updated whenever a card changes status, not only at handoff, so a crash loses nothing [measured] harnesses "update progress file after each feature"; [Daniel] "a coordinator handover then lost nothing".

## 5. /compact vs /clear vs handoff
| Situation | Do | Basis |
|---|---|---|
| Worker reports in | `/catchup` is not needed; lead reads the report head, updates STATE.md | LC§6.2 |
| Mid-phase, `/context` shows messages dominating, continuity needed | `/compact` (CLAUDE.md compact section steers it), then `/catchup` | [docs] costs, best-practices |
| Auto-compaction or idle compaction happened anyway | `/catchup`; FAIL → `/clear`, `/lead` | [docs] context-window |
| Phase boundary; corrected twice; lead re-argues a settled D | `/handoff` → `/clear` → `/lead` | [docs] best-practices; [measured] harnesses |
| Leaving > 45 min (work, sleep) | `/handoff` → `/clear` before leaving; `/lead` on return. A cleared session is under the 200K idle-compaction floor, so nothing is summarised behind your back, and `/clear` is free | [docs] settings `idleCompaction` (>200K, ~54 min idle); costs |
| Usage limit / switch to Codex or Cursor | If Claude still answers, `/handoff` first. In the other tool paste plain text: `You are the AgentFly lead for this session. Read docs/roles/lead.md and follow its "Start" section.` Start's staleness step covers a missed handoff | [Daniel] learnings "Be ready to switch runtimes"; story.md 00:25 |
| Safety net | `/autocompact 400k` in the lead only | [docs] model-config; 400k is judgement (LC§6.2) |
Never type `/handoff` or `/lead` in a worker. Built-ins (`/clear`, `/compact`) can't be run by the model; Yevhenii types them [docs slash-commands].

## 6. Drift test (mechanical)
Prompt (= `/catchup`, or paste in any tool): "Drift check. Without using any tool, write: FLIGHT: <in-flight card IDs> · APPROVED: <approved D-IDs> · WAITING: <number of items Yevhenii owes>. Then run `bash docs/roles/drift-check.sh "<FLIGHT>" "<APPROVED>" <WAITING>` and paste its output."
Pass rule: the script prints `PASS` (exact set equality for FLIGHT and APPROVED, equal count for WAITING) and `INDEX OK`. Anything else = FAIL → `/clear`, `/lead`. No judgement involved; Yevhenii checks the memory line was written before the tool call. APPROVED is chosen because re-arguing settled decisions is the costliest drift (LC§6.6).
`docs/roles/drift-check.sh` core (ran PASS/FAIL correctly in bash and zsh against today's files [checked]):
```
f=$(awk '/^## In flight/{f=1;next} /^## /{f=0} f' docs/STATE.md | grep -oE '^- [SV][0-9]+' | cut -c3- | sort | xargs)
a=$(awk '/^## D[0-9]+\./{id=$2;sub(/\./,"",id)} /^Status:/{s=$2;gsub(/[*,]/,"",s);if(s=="approved")print id}' docs/DECISIONS.md | sort | xargs)
w=$(awk '/^## Waiting/{f=1;next} /^## /{f=0} f' docs/STATE.md | grep -cE '^[0-9]+\.')
s() { tr ' ' '\n' <<<"$1" | sort | xargs; }
[ "$(s "$1")" = "$f" ] && [ "$(s "$2")" = "$a" ] && [ "$3" = "$w" ] && echo PASS || echo "FAIL: file has flight=[$f] approved=[$a] waiting=$w"
diff <(grep -E '^- D[0-9]+ ' docs/DECISIONS.md | awk '{print $2,$3}') <(awk '/^## D[0-9]+\./{id=$2;sub(/\./,"",id)} /^Status:/{s=$2;gsub(/[*,]/,"",s);print id,s}' docs/DECISIONS.md) && echo "INDEX OK"
```
It needs two STATE.md format rules: in-flight rows start `- <card> ·`; Waiting items are numbered `1.` lines (already true).

## 7. Keeping the lead persona out of workers and Cursor agents
"A project settings file made every Claude session start as head of staff, workers included. Start roles explicitly per session." [Daniel] learnings. Applied:
1. **CLAUDE.md role-neutral.** Replace "Lead role: see docs/roles/lead.md" with "Your role is given in the first message of the session. With none, you are a worker on one card: follow AGENTS.md." Reword `# Compact instructions` neutrally: "Keep: your role and card, files you own, decisions by ID, open questions for Yevhenii, next actions. Drop tool output and file contents." Today's text speaks only for the lead and every worker loads it [docs memory; LC§1].
2. **Role only in the first prompt.** Lead: `/lead`. Worker brief line 1: "You are a worker on card <ID> in <worktree>. Follow AGENTS.md. Do not read docs/roles/, docs/STATE.md or other cards' reports." Same line for Cursor agents (Cursor loads AGENTS.md, not .claude/).
3. **No `agent` key in any settings file, no `--agent lead`** (§4) [docs settings `agent` = every session in the project].
4. **Auto memory off for the repo:** `.claude/settings.json` = `{"autoMemoryEnabled": false}`. All worktrees of one repo share one auto-memory dir, loaded at every start [docs glossary "Auto memory"], so a lead-written note would reach every worker. No AgentFly memory dir exists yet [checked]. State belongs in STATE.md anyway.
5. **Optional compact hook, lead checkout only:** if wanted, put LC§6.4's SessionStart `compact` hook in `.claude/settings.local.json` of the main checkout. It is git-ignored on this Mac by `~/.config/git/ignore` [checked], so it is never committed. Do not list it in `.worktreeinclude`. Whether a session in `.claude/worktrees/<x>` reads the parent checkout's local settings is [inferred] no. Check once with `/hooks` in the first worker. Without the hook, `/catchup` after compaction does the same job by hand.
6. **One-time leak test** in a new worker: ask "What is your role, and what is in docs/STATE.md?" Pass = "worker on <card>" and it has not read STATE.md.

# How the AgentFly lead should handle its growing context

Researched 15 Oct 2026. Every claim is tagged:
- **[docs]** official Claude Code documentation, fetched today
- **[measured]** a published experiment or measurement
- **[Daniel]** written in the Starwatch repo (`/tmp/starwatch`)
- **[anecdote]** one practitioner's experience
- **[inferred]** my reasoning, not stated by any source

Raw copies of the sources are in `research/src/`.

---

## 1. Short answer

Context pollution of a long-running lead is real and expected. The fix is **not** a bigger instruction file or a growing log. Keep the lead's *state* in a few small files on disk, so the lead's conversation can be thrown away at any time without losing anything. Then restart it on purpose at phase boundaries, instead of letting automatic compaction decide what to keep.

Your ideas, assessed:
- **AGENTS.md/CLAUDE.md:** yes, but short (under 200 lines) and only stable rules. It is loaded into every session, workers included, so the lead's role does not belong there.
- **Changelog:** not needed for the lead. `git log` plus `DECISIONS.md` already do that job. A separate changelog becomes a second copy of the truth.
- **Contributing logs:** keep worker reports short, with the latest status on top. Never auto-load growing logs.

---

## 2. Daniel's evidence (Starwatch)

What the repo **says**:

- **One head of staff (HoS), one canonical task list.** "The head of staff keeps decisions and the canonical `TODO.md`; workers get a written brief, their own Git worktree and a report file. Nobody else edits the task list." [Daniel] `docs/learnings.md`, "Agent orchestration".
- **Not one long chat.** "I ran the night as a head of staff with workers, not as one long chat… keep my decisions, the canonical task list and the evidence straight." [Daniel] `docs/story.md`, around line 54.
- **Reports in files, read on a heartbeat.** "Every worker reported to a file under `docs/reports/`, and the head of staff read those files on a heartbeat." [Daniel] `docs/story.md`, around line 56.
- **A fixed report format, read from the latest section only.** The control room's parser takes only the **last `## ` section** of each `docs/reports/hos-*.md` and pulls three lines: `Result:`, `Evidence:` and `Needs Daniel:`, each capped at 500–650 characters. [Daniel] `archive/workspace/project_tracker/model.py`, `report_fragments()`. Worker lanes came only from TODO's current `## In flight` section, and "Historical reports remain evidence and never create worker lanes." [Daniel] `archive/workspace/project_tracker/README.md`.
- **Quiet policy.** Unsolicited worker pings to the HoS were turned off: "Reports and a shared board are enough; interruptions cost more than they deliver." [Daniel] `docs/learnings.md`. The control room held messages by default ("absent/unknown policy defaults to quiet"). [Daniel] `archive/workspace/project_tracker/README.md`, "Quiet policy".
- **Notify once.** A timer checked readiness every two minutes, notified the app-building session exactly once, then disabled itself. [Daniel] `docs/learnings.md`, `docs/story.md`.
- **The HoS session was replaceable.** "When the Claude session hit its usage limit at 00:25, the same head-of-staff instructions moved to a Codex profile in minutes." [Daniel] `docs/learnings.md`. Also: "In the production run one coordinator owned the ledger… A coordinator handover then lost nothing." [Daniel] same section.
- **Persona opt-in.** "A project settings file made every Claude session start as head of staff, workers included. Start roles explicitly per session." [Daniel] `docs/learnings.md`.
- **The human's context matters too.** The control room rendered `TODO.md` as a Kanban "so I could see the state without reading thirty files". [Daniel] `docs/story.md`, around line 62.
- **Record decision provenance.** "An agent's runtime constraint is not the user's decision. The board recorded who decided what." [Daniel] `docs/learnings.md`.

What the repo **does not show**:
- The public history is a clean publish. The first commit is `d3bd607`, 9 Oct 2026 06:42 (UTC+2), "Publish Starwatch hackathon source". The night's `TODO.md`, the `docs/reports/hos-*.md` files and any HoS transcripts are not in the repo.
- So there is **no written evidence** of how often the HoS compacted, whether it was cleared, or whether its context got polluted. Searching `docs/`, the README, CONTRIBUTING and `archive/` for compact/compaction/clear/context window/fresh session found nothing relevant.
- **[inferred]** A single HoS running for about 8 hours with dozens of workers almost certainly passed through compaction or a reset at least once. The usage-limit switch at 00:25 was a forced cold restart. It worked "in minutes" *because* the state lived in `TODO.md`, the decisions and the report files, not in the chat. Daniel's design makes pollution survivable rather than preventing it.

---

## 3. Claude Code mechanics (official docs, fetched 15 Oct 2026)

### Context size and when auto-compact fires
- Opus 4.7 and later run with a **1M-token window by default**. Opus 4.6 reaches 1M only through `opus[1m]`, otherwise 200K. [docs] model-config, "Extended context".
- Models with a native 1M window **auto-compact at about 967K tokens** by default. Opus 4.6 without 1M compacts at 200K. [docs] model-config, "Default auto-compact thresholds".
- You can compact earlier with `/autocompact 400k` (accepts 100K–1M), `--autocompact` for one launch, or `autoCompactWindow` in settings. [docs] model-config, "Set the auto-compact window".
- **Idle compaction:** an interactive terminal session over **200K tokens**, idle for **about 54 minutes**, is compacted automatically before its prompt cache expires. It is on by default; turn it off with `"idleCompaction": false`. [docs] settings-reference, `idleCompaction`. **This matters for you:** a lead left open while you're at work can be compacted without you choosing to.

### Quality degrades as context fills
- "LLM performance degrades as context fills. When the context window is getting full, Claude may start 'forgetting' earlier instructions or making more mistakes." [docs] best-practices.
- Chroma tested 18 models, including Claude 4: "performance grows increasingly unreliable as input length grows", even on simple tasks. [measured] Chroma, *Context Rot*, July 2025. This predates current Opus versions, so the trend is measured but the exact curve for your model is not.
- **[inferred]** On Opus with 1M context, the risk is no longer *running out*. It is the lead quietly getting worse long before the 967K compaction point. Don't rely on the default threshold.

### What compaction keeps
After compaction [docs] context-window, "What survives compaction":
- **Re-injected from disk:** the project-root CLAUDE.md, unscoped rules, auto memory and the plan-mode plan.
- **Re-read:** up to five recently modified files the session touched. Files over 5,000 tokens come back as a path only.
- **Summarized away:** everything said only in conversation, plus earlier hook-injected context.
- **Run again:** `SessionStart` hooks with matcher `compact`, whose output is added to the compacted context.
- "If an instruction disappeared after compaction, it was given only in conversation… Add conversation-only instructions to CLAUDE.md to make them persist." [docs] memory.

### Controls
- `/compact <focus>` steers the summary. A `# Compact instructions` section in CLAUDE.md does the same for every compaction. [docs] costs, best-practices.
- `/clear [name]` empties context and costs nothing. `/resume` returns to the old session. [docs] commands, costs.
- `/rewind` → "Summarize from here / up to here" compacts only part of the conversation. [docs] best-practices.
- `/context` shows what is using space. `/btw` asks a side question without adding it to history. `/recap` gives a one-line summary without replacing history. [docs] commands, interactive-mode.
- "If you've corrected Claude more than twice on the same issue in one session… Run `/clear` and start fresh… A clean session with a better prompt almost always outperforms a long session with accumulated corrections." [docs] best-practices.
- Once a spec is complete, "start a fresh session to execute it". [docs] best-practices.
- `/compact` on a large context is itself a large request, while `/clear` is free. [docs] costs.

### CLAUDE.md / AGENTS.md
- "Target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence." **`@imports` don't reduce cost**, because imported files load at launch. [docs] memory, "Size".
- CLAUDE.md is "context, not enforced configuration". [docs] memory.
- Editing CLAUDE.md mid-session **doesn't apply** until `/clear`, `/compact` or a restart. [docs] prompt-caching.
- `AGENTS.md` is read only when no `CLAUDE.md` exists in the working directory or above it (requires v2.1.277 or later). Otherwise make CLAUDE.md import it. [docs] memory, "AGENTS.md".
- **Auto memory** is on by default. Its `MEMORY.md` loads at every start, first 200 lines or 25KB. [docs] memory. Know it exists, because it can quietly carry stale lead notes.

### Hooks you can use
- `SessionStart` with matcher `compact` (input `source: "compact"`): its stdout or `additionalContext` is injected after compaction. Output is capped at **10,000 characters**; anything longer becomes a file path plus a 2,000-character preview. [docs] hooks-guide, "Re-inject context after compaction"; hooks reference.
- `PreCompact` (matcher `manual`/`auto`) can **only block** compaction and cannot add context. `PostCompact` receives `compact_summary`, useful for saving the summary to a file. [docs] hooks reference.
- Docs advice: write injected text as factual statements ("The board is docs/BOARD.md"), not "system instructions", which can trigger prompt-injection defences. [docs] hooks reference.

### Subagents
- Each subagent "starts with a fresh, isolated context window. It doesn't see your conversation history". Verbose work stays there and only a summary returns. [docs] sub-agents, best-practices.
- Your workers are **separate sessions** in worktrees, which is even stronger isolation. The lead's context only grows by what you paste in or what it reads.

---

## 4. Anthropic engineering and practitioner guidance

- **Context engineering** [docs-level guidance, Anthropic engineering blog]: context is a finite "attention budget". The three levers for long tasks are **compaction**, **structured note-taking** ("your custom agent maintaining a NOTES.md file… After context resets, the agent reads its own notes and continues") and **sub-agents** that return "a condensed, distilled summary… (often 1,000–2,000 tokens)". Prefer "just in time" loading through file paths over loading everything up front. Larger windows will still "be subject to context pollution".
- **Long-running harnesses** [measured, internal experiments described qualitatively]: "compaction isn't sufficient". What worked was an initializer that writes a feature list, an `init.sh` and a `claude-progress.txt`. Every later session reads the progress file and `git log`, works **one feature at a time**, commits, and updates the progress file, so a fresh context window can "quickly understand the state of work". The feature list was JSON with only a `passes` field to edit, because "the model is less likely to inappropriately change or overwrite JSON".
- **Multi-agent research system** [measured]: the lead "saves its plan to Memory… since if the context window exceeds 200,000 tokens it will be truncated". Agents "summarize completed work phases and store essential information in external memory before proceeding to new tasks… spawn fresh subagents with clean contexts while maintaining continuity through careful handoffs". Subagents write outputs to the filesystem and "pass lightweight references back to the coordinator" to avoid a "game of telephone". Multi-agent systems used about 15× the tokens of chat.
- **"Document & Clear"** [anecdote, Shrivu Shankar]: avoid auto-compaction ("opaque, error-prone"). The default is `/clear` plus a `/catchup` command that reads the branch's changed files. For big tasks, the agent dumps plan and progress to a `.md`, you `/clear`, and the new session reads it.
- **Agreement across sources:** Anthropic docs, Anthropic engineering, Daniel and the practitioner all converge on *state in files, context disposable, summaries from workers, deliberate resets*. Only the practitioner says to avoid compaction entirely. The docs treat `/compact <focus>` as a legitimate tool.

---

## 5. Your ideas, assessed

| Idea | Verdict | Why |
|---|---|---|
| Well-kept AGENTS.md/CLAUDE.md | **Yes, small and stable** | Loaded in every session and re-injected after compaction [docs], so it's the right home for durable rules. Keep it under 200 lines [docs]. Don't put the lead persona there: workers in worktrees load it too, which is Daniel's "persona opt-in" lesson [Daniel]. Don't `@import` big docs, because imports load at launch [docs]. Mid-session edits don't apply until restart [docs]. |
| Changelog | **Skip it** | `git log` is the changelog (Anthropic's harness reads `git log` at session start) [measured]. `DECISIONS.md` covers the "why". A third log copies both and goes stale [inferred]. |
| Contributing logs | **Yes as worker reports, no as a growing auto-loaded log** | Use Daniel's format: latest status on top, `Result:`/`Evidence:`/`Needs:` lines, details lower down [Daniel]. The lead reads the top only. An append-only log that is auto-loaded grows the lead's base context every session [inferred from docs on load cost]. |
| What's missing | **A short, overwritten state file** | This is the piece that makes restarts cheap: Anthropic's `claude-progress.txt`/NOTES.md [measured], Daniel's `TODO.md` "In flight" [Daniel], Shankar's dump-to-md [anecdote]. |

---

## 6. Recipe for the AgentFly lead

### 6.1 Files

| File | Who writes | Loaded how | Size rule |
|---|---|---|---|
| `CLAUDE.md` (or `AGENTS.md` imported from it) | you or the lead, rarely | **auto, every session**, workers too | ≤ 100 lines: project purpose, hard constraints, test command, "never push", where the docs are, `# Compact instructions`. No role text, no history. |
| `docs/roles/lead.md` | you | **on demand**: first line of every lead session | ≤ 80 lines: lead duties, the restart ritual below, the report format, the rule "only the lead edits BOARD/DECISIONS". |
| `docs/STATE.md` (new) | lead only, **overwritten, never appended** | read at start; injected after compaction by hook | ≤ 60 lines and under 10,000 characters (hook cap). Phase; cards in flight (card → worker → worktree → report path); waiting on the owner; last 3 decisions by ID; next 3 actions; last commit SHA; timestamp. |
| `docs/BOARD.md` | lead only | on demand | cards; done cards collapse to one line each. |
| `docs/DECISIONS.md` | lead only, append-only | on demand, **never auto-loaded** | one-line index at top (`D4: offline guard default, approved by the owner 15 Oct`); details below; record who decided (Daniel's lesson). |
| `docs/SYNTHESIS.md` | lead | on demand, reference only | frozen once approved. |
| `docs/reports/<worker>-<card>.md` | each worker | lead reads the **top block only** | top block ≤ 10 lines: `Status:` (done / blocked / in progress), `Result:`, `Evidence:` (commit, test command + count, screenshot path), `Needs owner:` (or `none`), `Details:` (pointer to section). |
| `docs/learnings.md` | lead, at phase ends | on demand | lessons only, like Daniel's. |

Notes:
- Pasting a worker's whole transcript into the lead is the main pollution source in your setup [inferred]. Paste "S1 done, see docs/reports/S1-lead.md" instead, and let the lead read the top block.
- Commit `STATE.md` with the board at each phase end, so `git log` doubles as the history.

### 6.2 When to compact, clear, or restart

| Situation | Do | Basis |
|---|---|---|
| A worker finished; the lead updates the board | nothing special | — |
| Mid-phase, context getting big, you need continuity | `/compact keep: open cards, pending approvals, decisions taken today by ID; drop: file dumps, logs, tool output` | docs |
| **Phase boundary** (e.g. S1–S5 done → V-cards; each V wave done) | **Handoff + `/clear`** (ritual below) | docs ("fresh session to execute"), Anthropic harness, Daniel |
| You corrected the lead twice on the same point, or it re-litigates a settled decision | handoff + `/clear` | docs |
| Leaving the lead idle for an hour or more (e.g. you're at work) | ask for a handoff first. Otherwise idle compaction may summarize it for you once it's over 200K | docs (idleCompaction) |
| Safety net | `/autocompact 400k` for the lead model | the setting is in the docs; **400k is my judgement**, not a documented optimum |

### 6.3 Handoff ritual (paste to the lead)

```
Handoff time. Before I clear you:
1. Overwrite docs/STATE.md (≤60 lines): phase; cards in flight (card → worker → worktree → report path → status); what is waiting on me; decisions taken since last handoff by ID; next 3 actions in order; last commit SHA; timestamp.
2. Append any new decisions to docs/DECISIONS.md with who decided; update BOARD.md; add lessons to docs/learnings.md if any.
3. Commit those docs on main with message "handoff: <phase>".
4. Reply with only: the commit SHA and anything that is NOT captured in those files.
```

Then run `/clear` (or `/clear lead-<phase>` to name the old session), and start the new one with:

```
You are the AgentFly lead. Read docs/roles/lead.md, then docs/STATE.md, then the top block of each report listed under "in flight", then `git log --oneline -15`. Do not read SYNTHESIS.md or full reports unless a card needs them. Tell me in 5 lines where we are and what you will do next; wait for my go.
```

### 6.4 Hook (verified against the docs, not tested on your machine)

`.claude/settings.json` in the AgentFly repo:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          { "type": "command",
            "command": "cd \"$CLAUDE_PROJECT_DIR\" && echo 'Current lead state follows (docs/STATE.md):' && head -c 9000 docs/STATE.md && echo && git log --oneline -5" }
        ]
      }
    ]
  }
}
```

Caveats:
- This file sits in the repo, so **worker sessions get it too**. That's harmless (they see STATE), but if you want it lead-only, put it in `.claude/settings.local.json` in the lead's checkout. Docs: it is "gitignored when Claude Code saves a setting to it"; if you create it by hand, check it's in `.gitignore`, so it stays out of commits and worktrees.
- `$CLAUDE_PROJECT_DIR` is the documented project-root variable for hooks. Confirm with `/hooks` after adding.
- Optional: a `PostCompact` hook can save `compact_summary` to `docs/.compact-log/` for auditing. Docs say it receives that field.
- `PreCompact` cannot inject anything; it can only block.

### 6.5 CLAUDE.md compact section (paste)

```markdown
# Compact instructions
When compacting, keep: cards in flight with worker and report path, decisions approved or pending by ID (D-numbers), what is waiting on the owner, next actions. Drop raw tool output, file contents and log excerpts — they are in the repo. The source of truth is docs/STATE.md, docs/BOARD.md, docs/DECISIONS.md.
```

### 6.6 Signs the lead is polluted
- It asks about, or contradicts, a decision already in DECISIONS.md.
- It loses track of which worker has which card, or mixes up worktrees.
- You've corrected the same thing twice [docs].
- It cites a file or line that has changed since.
- `/context` shows messages dominating, or `/usage` flags "long context".
- After any compaction, ask: "From docs/STATE.md only, list cards in flight and pending approvals." If its answer differs from the file, clear it.

---

## 7. Sources (all opened successfully on 15 Oct 2026)

- Claude Code, context window and what survives compaction: https://code.claude.com/docs/en/context-window
- Claude Code, model config (1M context, auto-compact thresholds, /autocompact): https://code.claude.com/docs/en/model-config
- Claude Code, memory (CLAUDE.md size, imports, AGENTS.md, auto memory): https://code.claude.com/docs/en/memory
- Claude Code, best practices (context degrades, /clear after two corrections): https://code.claude.com/docs/en/best-practices
- Claude Code, hooks guide (SessionStart compact re-inject): https://code.claude.com/docs/en/hooks-guide
- Claude Code, hooks reference (PreCompact/PostCompact, 10,000-char cap): https://code.claude.com/docs/en/hooks
- Claude Code, costs (/compact vs /clear cost, compact instructions in CLAUDE.md): https://code.claude.com/docs/en/costs
- Claude Code, prompt caching (CLAUDE.md edits apply only after restart): https://code.claude.com/docs/en/prompt-caching
- Claude Code, settings reference (`idleCompaction`): https://code.claude.com/docs/en/settings-reference
- Claude Code, subagents: https://code.claude.com/docs/en/sub-agents
- Anthropic, Effective context engineering for AI agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, Effective harnesses for long-running agents: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic, How we built our multi-agent research system: https://www.anthropic.com/engineering/multi-agent-research-system
- Chroma, Context Rot (18 models): https://research.trychroma.com/context-rot
- Shrivu Shankar, How I use every Claude Code feature ("Document & Clear"): https://blog.sshh.io/p/how-i-use-every-claude-code-feature
- Starwatch: `docs/learnings.md`, `docs/story.md`, `archive/workspace/project_tracker/README.md`, `archive/workspace/project_tracker/model.py` (github.com/1vecera/starwatch)

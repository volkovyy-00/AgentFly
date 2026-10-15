# Long-memory setup for the AgentFly lead and workers

15 Oct 2026 · Claude Code 2.1.300 · Opus 5.5 (1M window, auto-compact ≈967K).
Inputs: `docs/research/lead-context.md` (LC) and four reviews in `docs/research/memory-review/`:
`repo-auditor.md` (A), `docs-verifier.md` (B), `workflow-designer.md` (C), `red-team.md` (D).
Tags: [docs] live docs, URL given · [checked] run on this machine · [Daniel] Starwatch · [measured] Anthropic engineering · [inferred] judgement.

## 0. Blocking finding
**CLAUDE.md does not import AGENTS.md.** `CLAUDE.md:3` names it in prose only. A CLAUDE.md exists, so Claude
sessions never auto-load AGENTS.md: no check command, secret rules or "one step at a time" for lead or workers,
and nothing comes back after compaction [checked A; docs memory#when-claude-code-reads-agents-md]. Adding
`@AGENTS.md` also imports SPEC.md (AGENTS.md:6 has an un-backticked `@SPEC.md`; imports recurse 4 hops [docs
memory#import-additional-files]): +568 lines / 30k chars per session, and SPEC is the stale hackathon spec (D17).
With `@SPEC.md` written as `` `SPEC.md` `` the cost is +149 lines / 9k chars (~2.2k tokens) [checked A].

## 1. Design in one paragraph
State lives in a few small repo files; the lead's chat is disposable [LC§1; measured harnesses; Daniel].
The lead role is **opt-in per launch**: `docs/roles/lead.sh` starts Claude with `--append-system-prompt-file
docs/roles/lead.md` (survives compaction and /clear, [docs] context-window#what-survives-compaction "system prompt
still applies") and `--settings docs/roles/lead-settings.json`, whose SessionStart hook re-injects STATE.md on
startup, /clear, compaction and resume. Nothing that workers load carries the role or the hook. A check script
turns "do the files agree?" into a command, and a git pre-commit hook stops any branch other than main from
committing lead files. Slash commands are thin pointers into lead.md so Codex/Cursor can follow the same text.

## 2. Files
| File | Writer | Loaded by / when | Cap | Status |
|---|---|---|---|---|
| `CLAUDE.md` | Yevhenii/lead, rarely | every Claude session, auto + after compaction | ≤20 lines | edit: `@AGENTS.md`, role-neutral |
| `AGENTS.md` | V1 card | Cursor auto; Claude via import | V1 decides | 1-token loading fix only (§6) |
| `docs/roles/lead.md` | Yevhenii/lead | lead only: system prompt via lead.sh | ≤80 lines / 6k chars | rewrite |
| `docs/roles/lead.sh` | — | Yevhenii runs it to start the lead | — | new |
| `docs/roles/lead-settings.json` | — | lead only, via `--settings` | — | new |
| `docs/roles/lead-context.sh` | — | SessionStart hook in lead only | output <9,500 chars | new |
| `docs/roles/state-check.sh` | — | lead on demand, hook, pre-commit | — | new |
| `docs/roles/git-hooks/pre-commit` | — | git, every worktree (`core.hooksPath`) | — | new |
| `docs/STATE.md` | lead, overwrite | lead: injected by hook | ≤60 lines, <9,000 chars | 2 format lines |
| `docs/DECISIONS.md` | lead | on demand; index = first ~25 lines | index generated | add index, fix line 3 |
| `docs/BOARD.md` | lead | on demand | done card = 1 line | rule only; applied at next handoff |
| `docs/reports/README.md` | — | worker reads it when the brief says | template ≤15 lines | new |
| `docs/reports/<card>.md` | worker | lead reads `head -n 6` | top block ≤1,000 chars | per card |
| `docs/learnings.md` | lead at handoff | on demand, never imported | ≤80 lines | new, seeded |
| `.claude/commands/{handoff,restart-lead,catchup}.md` | — | listed in every session's `/` menu, run only when typed | ≤8 lines | new |
| `.claude/settings.json` | — | every session | — | new: `autoMemoryEnabled: false` |
| `.gitignore` | — | git | — | add `.DS_Store` |

Startup cost: lead today 2.1k chars auto. After: CLAUDE.md+AGENTS.md ≈9.6k, lead.md ≈5k system prompt,
hook ≈6k (STATE + check + git log) → ≈21k chars ≈5k tokens, all of it state the lead needs. Workers: ≈11k chars
(rules only, no role, no STATE) [A for sizes; inferred for totals].

## 3. Rituals (full text goes in lead.md; commands point there)
- **Start / restart** (`docs/roles/lead.sh`, then `/restart-lead`): the role is already in the system prompt and
  STATE already injected. The lead runs `state-check.sh`, reads `head -n 6` of each in-flight report, then
  `git log --oneline <handoff>..HEAD`, says where things stand in 5 lines, and waits for "go". In Codex/Cursor, paste:
  "You are the AgentFly lead. Read docs/roles/lead.md, follow its Start section."
- **Keep STATE live**: overwrite STATE.md when a card is dispatched or finished or a decision is approved, not only at
  handoff. Usage limits give no warning [D; measured harnesses "update progress after each feature"; Daniel].
- **/handoff**: overwrite STATE → BOARD (collapse done cards) and DECISIONS agree → `state-check.sh --write-index`
  → `state-check.sh` = OK → learnings → commit `handoff: <phase>` → reply with the SHA and anything not in the files.
- **/catchup** (after any compaction or a pause): drift test below, then read what changed.
- **Drift test** [C+D]: before any tool call, the lead writes `FLIGHT: … · PENDING: … · WAITING: n` from memory,
  then runs `state-check.sh drift "<flight>" "<pending>" <n>`. PASS = exact set match. FAIL → handoff is
  not trusted; Yevhenii runs `/clear` (the hook re-injects STATE) and `/restart-lead`. No judgement involved.

| Situation | Do | Basis |
|---|---|---|
| Worker reports in | lead reads `head -n 6`, updates STATE | Daniel report parser; C |
| Mid-phase, context large, need continuity | `/compact`, then `/catchup` | [docs] costs |
| Auto- or idle-compaction happened | `/catchup` | [docs] settings-reference#idlecompaction |
| Phase end; corrected twice; re-argues a settled D | `/handoff` → `/clear` → `/restart-lead` | [docs] best-practices |
| Leaving > 45 min | `/handoff` → `/clear` (under the 200K idle floor; /clear is free) | [docs] costs, idleCompaction |
| Usage limit → Codex/Cursor | `/handoff` if possible; **quit the Claude lead** (`autoContinueAtUsageLimit: true` is set [checked D]) | D |
| Safety net | `autoCompactWindow: 400000` in lead-settings.json | [docs] model-config; 400k is [inferred] |

## 4. Where the reviews disagreed, and the pick
1. **Where lead-only hooks live.** LC§6.4 and C: `.claude/settings.local.json`. B: worktree sessions read the
   main checkout's local file ([docs] settings#keep-personal-settings-out-of-a-repository: "In a worktree, it uses
   the file at the main checkout's root"; I re-read it). D: committed hook gated on `AGENTFLY_ROLE`. B: `--agent lead`
   or `--settings`. **Pick `--settings` via lead.sh.** No file a worker loads holds the hook. Env vars leak into any
   `claude -p` the lead starts from Bash. `--agent lead` makes "lead" a subagent the model can delegate to (no
   frontmatter switch stops this [docs sub-agents]), and keeping the default prompt with an empty body is documented
   only for JSON `--agents`.
2. **Role text.** C: first message (`/lead`). Pick `--append-system-prompt-file`: it survives compaction and /clear
   [docs B §3], so no "re-read your role" step. Codex/Cursor fall back to C's paste line.
3. **Commands location.** C: committed, `disable-model-invocation: true`. D: a worker running /handoff could
   overwrite STATE and merge cleanly. Every location reaches worktrees anyway: untracked `.claude/commands`
   reads through ([docs] worktrees#what-worktrees-share-with-the-main-checkout), and `~/.claude` reaches every
   project. **Pick committed + D's pre-commit guard** (mechanical, also covers Cursor/Codex workers).
4. **DECISIONS index.** C: hand-written + diff check. D: generated, never hand-written. Yevhenii asked for an index
   at the top. **Pick: generated in place** between markers by `state-check.sh --write-index`; check fails if stale.
5. **Hook matcher.** LC: `compact`. D: `startup|clear|compact|resume`. **Pick D**: covers /clear, so restart needs no paste.
6. **Report reading.** Daniel reads the last section; C reads the top. **Pick top** (`head -n 6`, no parser) [C].
7. **Truncation.** LC: `head -c 9000`. D: that drops "Next 3 actions" without warning. **Pick refuse**: if STATE is
   over 9,000 chars, the hook prints the path and a FAIL line. Over 10,000 chars becomes a path + 2,000-char
   preview, and Claude is not told to read it [docs hooks#json-output].
8. **PostCompact summary log.** LC optional; D skip (transcripts already exist; it would copy chat into git). **Skip.**
9. **Auto memory.** A, C, D: on, empty, shared by all worktrees [docs memory#auto-memory]. **Off** in `.claude/settings.json`.
10. **idleCompaction.** Left **on**: STATE re-injection + /catchup make it survivable, and it avoids a large
    cache-write on return [inferred]. Turn it off in lead-settings.json if drift tests fail after idle periods.

## 5. state-check.sh (read-only; exit 1 on FAIL)
Checks: STATE ≤60 lines and <9,000 chars · `Pending decisions:` in STATE = set of `Status: proposed` in DECISIONS ·
each `- <card> ·` row under `## In flight` names a report path or worktree that exists · `pid N` alive · `/tmp/…`
paths exist (warn) · DECISIONS index block = bodies · info: commits since STATE last changed, HEAD SHA (replaces the
hand-kept "Last commit" line [D]). Modes: `drift <flight> <pending> <n>`, `--write-index`.
Pre-commit: on a branch other than main, reject staged `docs/{STATE,BOARD,DECISIONS}.md`, `docs/learnings.md`;
on main, run state-check if STATE is staged; always reject `.DS_Store`. Bypass is `--no-verify` (Yevhenii only).

## 6. Changes, file by file (diff summary)
- `CLAUDE.md`: `@AGENTS.md`; "role is given at launch; without one you are a worker on one card, follow AGENTS.md
  and your brief; do not read docs/roles/ or docs/STATE.md"; reports → `docs/reports/README.md`; neutral
  `# Compact instructions`. Removes the lead pointer and the lead-only compact text (leak [A D2]).
- `AGENTS.md:6`: `Read @SPEC.md first.` → ``Read `SPEC.md` first.`` (loading only; keeps SPEC out of every session).
  **Needs your yes.** Proposed for V1, not applied: a "Report" section (C §1), Cursor 3.24.12, D10/D14 changes.
- `docs/roles/lead.md`: rewrite: Owns, Rules, Start, Keep STATE live, Handoff, Drift check, When to compact/clear,
  Tool switch, BOARD collapse rule, report format (Status/Result/Evidence/Needs Yevhenii/Details).
- New: `docs/roles/{lead.sh, lead-settings.json, lead-context.sh, state-check.sh, git-hooks/pre-commit}`,
  `.claude/commands/{handoff,restart-lead,catchup}.md`, `.claude/settings.json`, `docs/reports/README.md`, `docs/learnings.md`.
- `docs/STATE.md`: add a `Pending decisions: D2 …` line; in-flight row format `- <card> · <worker> · <worktree> ·
  <branch> · <report>`; drop the "Last commit" line (the hook prints HEAD). Facts unchanged.
- `docs/DECISIONS.md`: line 3 → "Status: see each entry's Status line"; add the generated index block. Bodies untouched.
- `docs/BOARD.md`: no edit now (no card edits this session); collapse at the next handoff.
- `.gitignore`: `.DS_Store`. Local only (not committed): `git config core.hooksPath docs/roles/git-hooks`;
  copy `/tmp/af-spike/` → `logs/spike/` (gitignored) so a reboot doesn't lose the S5 scripts, and point STATE at it.

## 7. Tests (Phase 3)
Hook by hand: `echo '{"source":"compact"}' | CLAUDE_PROJECT_DIR=$PWD docs/roles/lead-context.sh | wc -c` < 9,500, exit 0;
missing STATE → one line, exit 0; path with a space. Live: `claude -p --settings docs/roles/lead-settings.json`
asked for a STATE fact with tools disabled → answers; without `--settings` → UNKNOWN (proves workers don't get it).
Import: same no-tools question about AGENTS.md before/after. state-check: OK today; negative case → FAIL, exit 1.
Pre-commit: throwaway worktree commit of STATE → rejected. `git check-ignore` for `.DS_Store`, `logs/spike/`.
/handoff dry run: follow its steps without committing. `/hooks` is interactive: Yevhenii runs it in `lead.sh`.

Results (applied 15 Oct, before commit): all of the above passed [checked]. Interactive `lead.sh` on 2.1.300 kept the role
after /clear and /compact (a lead.md-only fact was recalled and placed "in my system prompt"). With
`.claude/settings.json` moved aside, /memory showed Auto-memory true; with it, false, and the hook fired in both runs,
so `--settings` merges (2.1.301). **`/hooks` (2.1.301) does not list hooks that come from `--settings`**, although they
fire: verify with the transcript line `SessionStart:startup hook success: AgentFly lead context …` instead.

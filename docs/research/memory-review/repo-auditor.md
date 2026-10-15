# Memory audit: AgentFly repo (repo-auditor, 2026-10-15)

Scope: read-only audit of every file that acts as memory for the lead, Claude workers and Cursor agents. HEAD = aa3e7f2 ("handoff: spikes S1+S2 done"). The working tree is clean apart from untracked `docs/research/lead-context.md` and `.DS_Store`. Sizes are `wc -l`/`wc -c`. Tokens are estimated as chars/4.
Tags: [verified] = checked on this machine. [docs] = code.claude.com via Context7, fetched today. [unverified] = not tested.

## Direct answers

**1. Does CLAUDE.md import AGENTS.md? No.** The whole of `CLAUDE.md:3` is the prose line `Project rules live in AGENTS.md (read it first) and SPEC.md.` The file has no line starting with `@`. So **AGENTS.md is not auto-loaded in Claude sessions** [verified]: this audit session's injected context contained only CLAUDE.md and `~/.claude/rules/context7.md`. Docs: AGENTS.md is read "if your repository has one and no CLAUDE.md". Otherwise you import it, or set **/config → Project instructions** to read both [docs, glossary]. `~/.claude/settings.json` has `pluginConfigs."cc-plugin-agents-md@builtin".options.instructionFiles = "claude-md-or-agents-md"`. That looks like the "either-or" value of this setting, so AGENTS.md is skipped because CLAUDE.md exists [inferred from the docs plus the observed context].
- `AGENTS.md:6` reads `Read @SPEC.md first.` This `@SPEC.md` is in plain prose, not in a code span, so it **would be a transitive import** if AGENTS.md were loaded as memory. AGENTS.md's other `@` strings are inside backticks (`:26-28`, `:103`, `:112`), so they are not imports. SPEC.md has no imports. Its only `@` is `u:p@x.com` in backticks at `SPEC.md:156`.
- Cost of adding `@AGENTS.md` to CLAUDE.md: +149 lines / 8,985 chars (AGENTS.md) and +419 lines / 20,991 chars (SPEC.md, pulled in transitively) = **+568 lines / 29,976 chars, about 7.5k tokens**, in every session (lead and workers) and again after every compaction. That is nearly 3× the docs' "under 200 lines" guidance. Putting `@SPEC.md` in backticks would make the extra cost +149 lines / 8,985 chars (about 2.2k tokens).
- Content risk: `AGENTS.md:6-7` makes SPEC.md "the source of truth … stop and ask". But SPEC.md is the hackathon spec that D17 and card V1 plan to replace (`SYNTHESIS.md:53`, `DECISIONS.md:415-429`). Importing it as is would put a stale source of truth in every session.

**2. Lead startup cost**
| Load | Lines | Chars | ~Tokens |
|---|---|---|---|
| CLAUDE.md (auto) | 8 | 431 | 108 |
| ~/.claude/CLAUDE.md (auto, empty file) | 0 | 0 | 0 |
| ~/.claude/rules/context7.md (auto, unscoped user rule) | 10 | 1,679 | 420 |
| Auto memory MEMORY.md | none: `memory/` dir exists (since 2026-09-30) but is empty | 0 | 0 |
| **Auto total today** | **18** | **2,110** | **~530** |
| …if CLAUDE.md adds `@AGENTS.md` (pulls in @SPEC.md) | 586 | 32,086 | ~8.0k |
| …if `@AGENTS.md` added and `@SPEC.md` de-linked | 167 | 11,095 | ~2.8k |

Not memory, but also injected at startup, after /clear and after compaction: the superpowers plugin's `SessionStart` hook (matcher `startup|clear|compact`), which injects the using-superpowers skill (SKILL.md is 3,192 chars, so ~0.8k tokens or more) [verified hook config].

On-demand reads under `docs/roles/lead.md:30-31` "Starting from zero" (cumulative):
lead.md 1,983 → + STATE 4,072 → + BOARD 21,400 = **27,455 chars (~6.9k tok)**. Adding "the decisions it points to" in full (DECISIONS 34,065, which has no index, so in practice the lead reads the whole file) brings it to **61,520 (~15.4k)**. Adding the spike reports S1 4,780 + S2 11,647 brings it to **77,947 (~19.5k)**. If the lead also follows CLAUDE.md's "read AGENTS.md first" with SPEC.md: **107,923 (~27k)**. If it follows `BOARD.md:77` into SYNTHESIS §3 (whole file 34,457): **~142k chars (~35.6k tok)**. BOARD is 79% of the minimum read and mostly holds future V-card specs.

**3. What a Claude worker in a fresh git worktree gets**
- Tracked memory files (`git ls-files`): CLAUDE.md, AGENTS.md, SPEC.md, all of `docs/**` except the untracked lead-context.md, and `ui/.gitignore`. **Nothing under `.claude/` or `.cursor/` is tracked.**
- Auto-loaded: CLAUDE.md (431 chars), user rules (1,679), the superpowers hook, and the **shared** auto memory. Docs: "All worktrees of the same repository share one auto memory directory" [docs]. So anything the lead's auto memory saves later would reach every worker, and the reverse too. It is empty today.
- Workers also auto-load the lead-only text in `CLAUDE.md:5` ("Lead role: see docs/roles/lead.md (workers ignore it)") and the lead's `# Compact instructions` at `CLAUDE.md:7-8`, which name STATE/BOARD/DECISIONS as the source of truth. Workers **do not** get AGENTS.md (check command, approved deps, secret rules, "one step at a time") unless they choose to read it.
- Not in a fresh worktree: `.claude/` is gitignored-by-absence and empty (`skills/` and `worktrees/` are empty dirs). Docs say untracked `.claude/skills|agents|commands` read through from the main checkout [docs], but there are none. There is no `.claude/settings.json` or `settings.local.json`, so there are no project hooks. `.claude/scheduled_tasks.lock` is a stale lock (pid 13499, 2026-10-02), excluded only via `.git/info/exclude:9`. `.cursor/` is gitignored (`.gitignore:7`), so a fresh worktree has no `.cursor/hooks.json` and project-level recorder hooks do not fire there. Only global hooks (S1/S2) would fire.
- Cursor agents: there are no `.cursor/rules/`, `.cursorrules`, `*.mdc` or `~/.cursor/rules/` [verified]. Cursor reads root AGENTS.md natively [unverified here]. Whether Cursor expands `@SPEC.md` is [unverified]. Cursor's own per-project state lives in `~/.cursor/projects/Users-volkovyy-Projects-AgentFly{,-worktrees-ag-29-motion-and-polish}/` (transcripts, canvases), which is not shared with Claude. The ag-29 Cursor worktree directory no longer exists. `git worktree list` shows only main. `~/.claude/projects/` has no AgentFly worktree dirs, so no Claude worktree worker has run here yet.

**4. Unbounded growth.** Every lead doc entered git in **one commit** (aa3e7f2, +3,005 lines), so git has no growth rate yet. The figures below come from the files' own revision notes.
- `DECISIONS.md` (502 lines / 34,065): append-only by design (`:5` "changes only through a new entry that replaces it"). Revisions 1→3 came in two days (10-14→10-15). S1/S2 added about 10 "S2 result"/"S1 result" paragraphs, roughly 0.5–1.5k chars each (`:60,79,102,140,162,213,238,298,483`). With S3–S5 and the V1–V9 approvals, expect it to grow by 15–30k chars [inferred]. It has no one-line index, so every read costs the full 34k.
- `BOARD.md` (414 / 21,400): the revision changelog at the top (`:7-27`) grows each revision. Done cards are not collapsed yet.
- `docs/superpowers/plans|specs|intents/`: 4 cards (AG-28..31) produced 12 files, 11,989 lines and **704,560 chars, about 176k chars per card**. One plan alone is 153,309 chars. These are never auto-loaded, but any pointer to them is expensive.
- `docs/research/`: new files per topic (9 files, 238k chars including the untracked lead-context.md). Add-only.
- `docs/reports/` **does not exist yet** but would add one file per card.
- Bounded: STATE.md (55 lines / 4,072, under lead.md's 60 lines / 9,000 chars), CLAUDE.md, lead.md.

## Inventory (writer → loader / when → size → last change → notes)
| Item | Writer | Loaded by / when | Lines/chars | Last change |
|---|---|---|---|---|
| CLAUDE.md | lead/Yevhenii | all Claude sessions, auto at start + re-injected after compact | 8 / 431 | aa3e7f2 10-15 22:32 |
| AGENTS.md | workers (AG cards), V1 planned | Cursor: auto [unverified]; Claude: on demand only | 149 / 8,985 | 71b5225 10-03 (stale, see C1–C3) |
| SPEC.md | AG cards; V1 to rewrite | on demand (via AGENTS) | 419 / 20,991 | 71b5225 10-03 (hackathon spec) |
| README.md / HOOKS.md | AG cards | on demand | 241/9,912 · 300/13,383 | 10-03 |
| docs/roles/lead.md | Yevhenii | lead, on demand (pointer in CLAUDE.md) | 31 / 1,983 | aa3e7f2 |
| docs/STATE.md | lead (overwrite) | lead on demand at start; no hook injects it yet | 55 / 4,072 | aa3e7f2, says "Updated 22:31", matches HEAD |
| docs/BOARD.md | lead | on demand | 414 / 21,400 | committed in aa3e7f2; file mtime 21:25 |
| docs/DECISIONS.md | lead | on demand | 502 / 34,065 | aa3e7f2 |
| docs/SYNTHESIS.md | lead | on demand (lead.md:8, BOARD:77) | 499 / 34,457 | mtime 10-15 07:54 |
| docs/product-goals.md | Yevhenii | on demand; only SYNTHESIS:7 points to it | 45 / 2,521 | mtime 10-14 |
| docs/spikes/S1, S2 | lead + Yevhenii | on demand | 64/4,780 · 87/11,647 | aa3e7f2 |
| docs/superpowers/** | worker sessions (AG-28..31) | on demand | 11,989 / 704,560 | 10-03 |
| docs/research/*.md | research runs | on demand | 9 files / ~238k | lead-context.md untracked |
| demo/NOTES.md | hackathon | on demand (AGENTS.md:149) | 103 / 3,896 | c9411ba 09-30 |
| ~/.claude/CLAUDE.md | user | all sessions, auto | 0 / 0 (empty) | 2026-04-14 |
| ~/.claude/rules/context7.md | user | all sessions, auto (unscoped) | 10 / 1,679 | 2026-08-08 |
| ~/.claude/settings.json | user | all sessions | no `hooks`, no `autoMemoryEnabled` key, so auto memory is ON by default; `autoCompactWindow` and `idleCompaction` unset | 10-15 22:34 |
| auto memory `…-AgentFly/memory/` | Claude (auto) | all sessions + all worktrees, MEMORY.md first 200 lines/25KB | empty | dir created 09-30 |
| .cursor/hooks.json | install.sh | Cursor, main checkout only (gitignored) | 22 lines / 536 | 10-04 |
| .cursor/hook-events.log | hook | nobody (log) | 75,697 chars | 09-30 |
| .superpowers/sdd/ | superpowers | — (self-ignoring `*`) | empty | 10-03 |
| ~/.claude/RTK.md, hooks/rtk-rewrite.sh | user | not loaded (not imported; no hooks configured) | 964 chars | 03-06 |

## Contradictions and duplication (both sides quoted)
- **C1 Stale versions.** `AGENTS.md:131` "Real input fields seen on this machine (Cursor 3.5.17)", also `HOOKS.md:168` and `README.md:56`, vs `DECISIONS.md:79` "Cursor 3.24.12". STATE.md:48 already flags this. V1 is to fix it.
- **C2 Source of truth.** `AGENTS.md:6-7` "Read @SPEC.md first. It is the source of truth." vs `SYNTHESIS.md:53` "SPEC.md is still the hackathon spec" and D17 (`DECISIONS.md:425-429`) "Almost every v1 card would disagree with today's SPEC". CLAUDE.md:3 sends every Claude session to both files.
- **C3 Work order.** `AGENTS.md:34-38` gives the hackathon stage order ("hooks logging, then a hard-coded deny…"), but `BOARD.md:54-72` sets the v1 lanes. Rule model: `AGENTS.md:57` "Do not build a condition language" vs `SYNTHESIS.md:44-47` "AGENTS.md must change" (D10 approved with change, `DECISIONS.md:248` "Changes: AGENTS.md 'Working rules'"). AGENTS.md has not been updated.
- **C4 Where worker results go.** `lead.md:18` "A worker finishes a card by writing `docs/reports/<card>.md`" vs `BOARD.md:46-48` "Evidence goes in the PR description … Spike cards … Results go in `docs/spikes/<id>.md`". `docs/reports/` does not exist. lead-context.md 6.1 suggests `docs/reports/<worker>-<card>.md` with a 5-field top block, while lead.md:19 has 3 fields.
- **C5 Decision status header.** `DECISIONS.md:3` "Status of every entry: **proposed, waiting for the owner's approval.**" vs `DECISIONS.md:39,107,248,356,488`, where D1, D4, D10, D14 and D20 are "approved (2026-10-15)". `SYNTHESIS.md:3` "Status: proposal. Nothing here is approved." is stale for the same reason. SYNTHESIS §2 ("Section 2 below is its index", `:12-13`) duplicates DECISIONS and is not updated when a decision is approved.
- **C6 Board status.** `BOARD.md:3` "spikes S1–S5 may start now" and the S1/S2 sections (`:79-117`) have no done marker, vs `STATE.md:6-7` "S1 passed (app only)", "S2 passed". This breaks lead.md handoff step 2 ("Update DECISIONS.md and BOARD.md so they agree with STATE.md").
- **D1 Duplication.** Spike steps appear in both `SYNTHESIS.md §3 (:304-438)` and `BOARD.md:77-160`. The board summary appears in both `SYNTHESIS.md §4 (:440)` and BOARD.md. The revision changelog appears in both `DECISIONS.md:10-25` and `BOARD.md:7-27`. The handoff ritual appears in both `lead.md:23-28` and `lead-context.md:146-154` (lead.md: STATE ≤9,000 chars; lead-context: "under 10,000"; also, lead.md drops `docs/learnings.md`, which does not exist). The compact instructions are in both `CLAUDE.md:7-8` and `lead-context.md:191-192`; CLAUDE.md adds "machine state".
- **D2 The lead role leaks to workers.** `CLAUDE.md:5` and the compact block at `:7-8` are auto-loaded by every worker. lead-context.md:109 itself warns "Don't put the lead persona there: workers in worktrees load it too".

## Risks for the long-memory design
1. Auto memory is ON, empty and unmonitored. It is shared across all worktrees, and nothing in STATE or the handoff checks it.
2. Nothing re-injects STATE.md after compaction: there is no `.claude/settings*.json`, and the lead-context.md 6.4 hook is not installed. Only CLAUDE.md survives compaction.
3. Fixing Q1 naively (`@AGENTS.md`) costs about 7.5k tokens per session and imports the stale SPEC. Rewrite AGENTS.md/SPEC (V1) first, or import a trimmed AGENTS.md and de-link `@SPEC.md`.

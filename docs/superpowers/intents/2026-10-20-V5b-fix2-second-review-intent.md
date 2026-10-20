# Intent: V5b-fix2, second review round for V5b
Ticket: V5b-fix2 (`git show main:docs/briefs/V5b-fix2.md`) | Author: the owner | Date: 2026-10-20 | Status: approved (2026-10-20); revised and re-approved 2026-10-20 (criterion 3, triggers)

## Problem
See V5b-fix2 Summary. A rules file `rules check` accepts can still slow a hook past the client's
0.5 s or leave a SPEC §5 secret unmarked; `init -g` calls a wrongly owned file intact; one long shell
word makes the recorder answer with an error.

## Proposed outcome
Hook cost is bounded for every accepted file by construction; R1's minimum is proven from the
patterns, not samples; long words are handled; `init -g` never calls an untrusted file intact.

## Success criteria
See V5b-fix2 Acceptance criteria. Added by the interview:
1. The new matcher equals today's (kept in tests as an oracle) on random patterns (anchored,
   unanchored, leading, trailing and inner `**`), at both `_glob` and `Pattern.matches` level
   (including `~/`, `/`, `..`, `//`, case).
2. A test that counts real matching steps fails when the counter is removed; its shape is one the
   faster matcher cannot flatten.
3. A file at `MAX_WORK` with no floating folder pattern (folder names between two `**`) and no
   command list whose entries share a program and first word never reaches the meter's budget on a
   command where every name-and-pattern test has length product n×m < 256 and each simple command
   names at most one listed program, at any depth, also one that parses only partly: counted steps
   are at most `MAX_WORK` × candidates (the budget is derived from the command). Other files may
   reach it on long, deep or many-command input; they fail closed and `rules check` warns. (Narrowed
   2026-10-20: five floating patterns cost 239k steps at 20 deep; re-pricing would only move the
   breaking depth.)
4. Under the default rules, `bash -c` naming 300 paths 60 deep is answered in under 0.2 s
   (measured and reported; about 146 ms expected once long words are guarded).
5. The exact R1 check agrees with brute-force enumeration on toy families and with today's sample
   grid; its load-time cost is measured and reported (aim about 20 ms for the default).
6. An edited, untrusted rules file keeps its bytes and mode after `init -g`, exit 0, one notice line.

## Affected users and systems
`agentfly/recorder/` (rulefile, rules, clean, store, app), `agentfly/install/` (installer, checks),
`agentfly/cli/` (init, rules_check), their tests, AGENTS.md "Testing", one SPEC §5 sentence.

## Constraints
Branch `ag-v5b-rules-file` only, no push, no merge of main. D27/D28 text unchanged. HOOKS.md and
SPEC §7/§8 are the lead's. `check(action, session)` keeps its shape. `MAX_WORK` and weights unchanged.

## Decisions
- Cost: a matcher whose cost does not grow with folder depth unless a run of parts sits between two
  `**` (an unanchored pattern counts the implicit leading one), plus a per-hook step counter as the
  guarantee.
- At the cap: R0 and R1 are never stopped by the counter; an unfinished `block` rule gives a deny
  with the limit text (a real rule object, not R1's text); an unfinished `warn`/`highlight` is
  skipped and logged. An unfinished `after` (trigger) of a block rule counts as fired; one of a
  warn or highlight rule is skipped and logged. A trigger's loss lasts the chat, so a block
  trigger fails closed, and a lost warn or highlight costs little. (Changed 2026-10-20 from "any
  other rule counts as fired".) `block` rules, their triggers included, run before the rest;
  `/health` gets a field only after a hit.
- R1 folder patterns whose cost grows with depth are refused (anchor it or use a separate rule);
  depth-free ones like `~/.aws/config` stay. The reason is cost.
- R1 minimum: an exact check that R1's names minus its exceptions contain every SPEC §5 secret name,
  with a work cap (over it R1 is refused as too complex to check: fail closed), class meaning taken
  from `fnmatch`, one table for `spec_secret` and the families, case-folded characters only, and an
  error that names the SPEC bullet missed.
- Long words: over 1,024 characters skip the disk check, `OSError`/`ValueError` are caught, and a
  string comparison replaces `relative_to`, in `clean._project_relative`,
  `store.relative_file_path` and `store.py`'s `.exists()`. `clean.py`'s baseline
  (`_split_keeping_seps`, `shlex`) is trimmed where cheap, to widen the counter's window.
- Install: `init -g` writes only bytes it has checked and never changes the trust of bytes it has
  not. Current bytes but untrusted: rewritten. Edited and untrusted: untouched, notice in
  `DEFAULT_IN_FORCE` words. Edited and trusted: notice on every run. One trust predicate in
  `rulefile`; one notice helper for the user and the root path.
- `rules check <link>` judges the active file itself when the link lands on it.

## Out of scope
See V5b-fix2 "Not included". Cost growing with the number of words (reported). `init.py`'s
bad-default-after-password and "Quit and reopen Cursor" on a rules-only refresh: fix if cheap, else note.

## Risks
- The time window is narrow: the budget (180k steps at 300 words) plus the cleaning baseline must
  stay under 0.2 s at 60 deep. The design removes the charge overhead, hoists `expanduser` and trims
  `clean.py` as planned steps, and stops to ask if the measured worst case stays over 0.2 s.
- The new matcher could quietly change what matches. A bug in the exact check. Hostile `?`/`[…]`
  patterns could make the exact check slow. The `bash -c` margin is about 54 ms.

## Open questions
- (you) The R1 narrowings: depth-growing folder patterns refused (Option C vs. names only) and
  degenerate misses like `.env.`. Recommended C as built; in the report's "Needs owner" (300-char
  pointer, detail under Details).
- (spec, resolved in the design) The budgets (derived from the command; 180k pattern steps at 300
  words), the exact check's work cap (2M state-steps, with a fast path for default spellings), the
  `/health` field (`rules_limit`).

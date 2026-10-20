# Intent: V5b-fix2, second review round for V5b
Ticket: V5b-fix2 (`git show main:docs/briefs/V5b-fix2.md`) | Author: the owner | Date: 2026-10-20 | Status: approved (2026-10-20)

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
3. An accepted full-size file (at `MAX_WORK`) never reaches the counter's cap on a 300-word command
   20 folders deep (the calibrated shape); at 60 deep only time is checked.
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
- At the cap: R0 and R1 run outside the counter; an unfinished `block` rule gives a deny with the
  limit text (a real rule object, not R1's text); an unfinished `warn`/`highlight` is skipped and
  logged; an unfinished `after` of any other rule counts as fired (a trigger is never lost); `block`
  rules are evaluated first, in `mark()` too; `/health` gets a field only after a hit.
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
- The cap's window is narrow (about 0.43 µs a step): at least about 150k steps (a full-size file of
  167 names on 300 words) and at most about 200k (98 ms baseline at 60 deep plus the cap under
  0.2 s). Aim 170-180k.
- The new matcher could quietly change what matches. A bug in the exact check. Hostile `?`/`[…]`
  patterns could make the exact check slow. The `bash -c` margin is about 54 ms.

## Open questions
- (you) The R1 narrowings: depth-growing folder patterns refused (Option C vs. names only) and
  degenerate misses like `.env.`. Recommended C as built; in the report's "Needs owner" (300-char
  pointer, detail under Details).
- (spec) The exact cap inside 170-180k; the exact check's work cap (about 300k steps); the `/health`
  field's name.

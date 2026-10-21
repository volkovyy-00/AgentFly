# Intent: V5b-fix2, second review round for V5b
Ticket: V5b-fix2 (`git show main:docs/briefs/V5b-fix2.md`) | Author: the owner | Date: 2026-10-20 | Status: approved (2026-10-20); revised and re-approved 2026-10-20 (criterion 3, triggers); revised 2026-10-20 to the owner's changes in the brief at main 67efc8d (meter, triggers, warn, D27), awaiting the lead's check

## Problem
See V5b-fix2 Summary. A rules file `rules check` accepts can still slow a hook past the client's
0.5 s or leave a SPEC §5 secret unmarked; `init -g` calls a wrongly owned file intact; one long shell
word makes the recorder answer with an error.

## Proposed outcome
Hook cost is bounded for every accepted file: by construction for every pattern that does not
float, and by a per-hook meter for those that do; R1's minimum is judged by pattern structure, not
samples; long words are handled; `init -g` never calls an untrusted file intact.

## Success criteria
See V5b-fix2 Acceptance criteria. Added by the interview:
1. The new matcher equals today's (kept in tests as an oracle) on random patterns (anchored,
   unanchored, leading, trailing and inner `**`), at both `_glob` and `Pattern.matches` level
   (including `~/`, `/`, `..`, `//`, case).
2. A test that counts real matching steps fails when the counter is removed; its shape is one the
   faster matcher cannot flatten.
3. Only floating patterns (folder names between two `**`; an unanchored pattern counts a leading
   one) are metered. Any other pattern costs at most its static work per candidate, at any depth,
   also on a command that parses only partly: counted tests are at most `MAX_WORK` × candidates and
   no rule is left unfinished. A file with floating patterns may reach the meter's fixed budget on
   long, deep input; it fails closed for block rules and `rules check` warns.
4. Under the default rules, `bash -c` naming 300 paths 60 deep is answered in under 0.2 s
   (measured and reported; about 146 ms expected once long words are guarded).
5. A brute-force test over a small alphabet finds no R1 the structural rule accepts that misses a
   secret name; the old sample grid, kept in the tests, agrees on every accepted fixture.
6. An edited, untrusted rules file keeps its bytes and mode after `init -g`, exit 0, one notice line.

## Affected users and systems
`agentfly/recorder/` (rulefile, rules, clean, store, app), `agentfly/install/` (installer, checks),
`agentfly/cli/` (init, rules_check), their tests, AGENTS.md "Testing", two SPEC §5 sentences (D27).

## Constraints
Branch `ag-v5b-rules-file` only, no push, no merge of main. D27/D28 text unchanged. HOOKS.md and
SPEC §7/§8 are the lead's. `check(action, session)` keeps its shape. `MAX_WORK` and weights unchanged.

## Decisions
- Cost (owner 2026-10-20, brief at 67efc8d): a matcher whose cost does not grow with folder depth
  unless the pattern floats, and a command-list index; a meter on floating patterns and command
  lists, in one pass (no severity passes), with one fixed budget priced from measured time.
  ("… and command lists": owner 2026-10-21, after Task 6's gate found accepted command-list files
  at 0.27 to 2 s a hook. A bucket is charged one step an entry and one a word before it is walked,
  a run of key probes one step for four; an unfinished highlight is still skipped.)
- At the limit: R0 and R1 are never metered and their answers stand. A `block` rule left unfinished
  (its trigger or its check) denies this hook with the limit message (a real rule object, not R1's
  text) and records no trigger; a `warn` rule left unfinished answers `ask` on a shell command with
  the limit message; an unfinished highlight is skipped and logged. `/health` gets a field only
  after a hit. (Supersedes "a block trigger counts as fired" and the two passes.)
- `path_except` may not hold floating patterns, in any rule.
- R1 minimum (D27 as changed 2026-10-20): structural, no automaton. For each SPEC §5 family, R1's
  `after.path` holds one pattern `P` or `P*Q` (no `?`, `[`, second `*`), P a prefix of the family's
  literal start and Q a suffix of its literal end (exact `.env`: |P|+|Q| ≤ 4). R1 may not hold
  floating folder patterns (`.ssh/**`; `~/.ssh/**` loads). One table for `spec_secret` and the
  families; the error names the SPEC bullet missed.
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
- The time window is narrow: unmetered tests at `MAX_WORK` (about 70 ms at 300 words), the
  floating budget and the cleaning baseline must stay under 0.2 s at 60 deep. The design hoists
  `expanduser` and trims `clean.py` as planned steps, and stops to ask if the measured worst case
  stays over 0.2 s.
- The new matcher could quietly change what matches. The `bash -c` margin is about 54 ms.

## Open questions
- (spec, resolved in the design) The floating budget (`FLOAT_STEPS`, priced at 20 ms of the slowest
  step, start value 40,000), the unfinished warn trigger (not recorded, as for block), the `/health`
  field (`rules_limit`).

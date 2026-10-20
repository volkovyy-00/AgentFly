# V5b-fix: Review fixes for V5b (trusted rules file, R1 minimum, default refresh, hook cost, ask end to end)
Status: done (as of 2026-10-20 18:58)
Result: The recorder believes the active rules file only if it is a plain, root-owned file nobody else can write; R1 cannot be dropped or weakened (D27); init -g writes the checked default and refreshes an unedited older one (D28); a 300-word hook stays near 0.1 s at the largest accepted file.
Evidence: Branch ag-v5b-rules-file, 9 commits 87f6f4b..c4efc51 plus this report. AGENTS.md check: ruff clean, 4123 passed, 5 skipped (V5b: 3846), green 3 times under load. final-verification: READY TO COMMIT. /code-review high: 8 findings, 1 fixed. Nothing pushed.
Needs owner: One question: should `agentfly uninstall` keep a copy of an edited rules.toml? Today it deletes it with the folder (V5b design). I recommend yes, as for hooks.json, in a small card. Other items for the lead are under "Gaps".
Details: see "## 2026-10-20 18:58" below.

## 2026-10-20 18:58

### What was built (in the brief's order)

1. **Flaky test.** `test_hundreds_of_slash_patterns_...` no longer names a clock. It counts calls of
   `rulefile._glob` (at most patterns x words) and that is the proof; a work bound, not a time bound.
2. **Trusted file.** `rulefile._trusted_bytes` opens the active file once (`O_NOFOLLOW`, `O_NONBLOCK`,
   `O_NOCTTY`, `O_CLOEXEC`), runs `fstat` on that descriptor (regular file, owned by `ACTIVE_OWNER_UID`,
   `mode & 0o022 == 0`) and reads the same descriptor, so nothing can be swapped between check and
   read. A link (also a dangling one), a named pipe, a folder, a wrong owner and a group- or
   world-writable file each give the default and one reason line (at most 400 characters, always
   ending "the packaged default rules are in force"). The recorder (`rules.load_active`), `doctor`
   (`checks.check_rules`) and `rules check|test` with no FILE (or FILE = the active file) all read it
   through `load_active_file`; a draft elsewhere is not trust-checked. `agentfly start` prints
   `rules: <problem>` to stderr and `status` a `rules:` line; exit codes did not change.
   `ACTIVE_OWNER_UID` is 0 in production; the conftest sets the test's own user and umask 022 and a
   fresh-process test asserts the production value is root.
3. **D27.** `rulefile.load_bytes` is the one reader (decode, size, parse, minimum, budget; a scan test
   pins that no production module calls `rulefile.parse`). The minimum: R1 present, `after_then`,
   `block`; `after` holds only event/path/path_except and fires on read and shell; `then` is exactly
   `event = ["shell"]` and `command_class = "outbound"`; every exception is one of SPEC section 5's two
   shapes (`.env...` ending `.example`/`.sample`/`.template`, `id_rsa...` ending `.pub`; no `/`); and
   R1's `after` marks all 474 names of a generated grid (families x tails, a one-character sweep,
   literals) on seven path forms and shell words. The error names the first unmarked name. Dead code
   removed: the "no rule R1" lint, `missing_r1` in `doctor`, `build_ruleset(fallback_secret=...)`.
4. **Install read and D28.** `installer._packaged_default` reads `default.toml` once, compares its
   sha256 with the wheel's RECORD hash (`packages.recorded_hash`) and requires a clean `load_bytes`,
   before anything is changed. `rules_state` is missing / current / older / edited / blocked:
   missing and older are written (older: "replaced the unedited default rules in ...; restart the
   recorder (`agentfly stop`, `agentfly start`) to apply them"), an edited file is kept with one
   notice line, a link or folder is refused before any repair. `rulefile.SHIPPED_DEFAULTS` holds the
   sha256 of the four `default.toml` files the branch has carried (the three earlier ones are
   fixtures in `tests/fixtures/shipped_defaults/`); a test pins the newest hash. `doctor` warns only on
   an unedited older default.
5. **Cost.** Per-word memos (`_candidates`, `_folded_name`, `_folded_segments`, `_first_positions`,
   `_last_positions`, `_hosts_of`, `parsed_is_outbound`), the slash-pattern walk stops early, and a work
   budget in `_parse`: `MAX_WORK = 200` units (a clause with path patterns 2; a name pattern 1; a slash
   pattern 4, plus 12 per `**` (one more if unanchored), plus 1 per part past the fourth; command and
   host lists nothing; R1's `after` twice). The packaged default uses 31. `rules check` refuses a file
   over the limit naming the heaviest rule.
6. **The rest.** `rules check` refuses `[!x]*`, `*[a-z]*`, `?*`, `[a-z]`, `/`, `./` as match-everything
   patterns; `rules test` on a file with no tests exits 1; the hook client prints a shell-warn `ask`
   answer unchanged (tested through the real client, with non-ASCII text); `/health.rules_problem`
   says the default is in force. AGENTS.md (Commands, Rule shape, Testing, including the three wheel
   tests V5b left out) and SPEC section 5 are updated.

### Commits (oldest first)

```
87f6f4b V5b-fix: the slash-pattern cost test counts work instead of seconds
5ff45ed V5b-fix: the recorder only believes an active rules file its owner alone can write
0f8c2cc V5b-fix: a rules file cannot drop or weaken R1 (D27)
f3e5639 V5b-fix: init -g writes only the checked default, and refreshes an unedited older one (D28)
685a055 V5b-fix: a rules file cannot make a hook miss its 0.5 s wait
28fd6c0 V5b-fix: patterns of wildcards only, rules test with no tests, ask through the client, docs
c6113b2 V5b-fix: final-verification cleanups (simplify pass)
97faa2b V5b-fix: fixes from the final-verification audit
c4efc51 V5b-fix: fix from /code-review high
```

`git diff --shortstat fe3386e..HEAD`: 31 files, +2595 / -188. Every file is inside the brief's Touches
list (`agentfly/recorder/`, `agentfly/install/`, `agentfly/cli/`, their tests, AGENTS.md, SPEC.md).
`cli/init.py`, `agentfly/rules/default.toml`, HOOKS.md, SPEC sections 7/8, DECISIONS, STATE and BOARD
are untouched on purpose.

### Acceptance criteria

| Criterion | Evidence |
|---|---|
| A link, a file not owned by root, a group/world-writable file is not loaded; the default runs and `/health`, `/api/rules`, `doctor`, `start`, `status` say why | `tests/test_rules_trust.py` (link, dangling link, wrong owner, 664, 666, named pipe, folder; each through `/health`, `/api/rules`, `doctor`, `start`/`status`, `rules check|test`; a child recorder over real HTTP). Smoke with real recorders below |
| D27: a missing, weakened or exempted R1 is refused, `rules check` exits 1 naming R1; `.env*` for `.env`/`.env.*` and added names or a reworded message load | `tests/test_rules_minimum.py`: 34 weakened files, each refused by `rules check` (exit 1, "rule R1"), `rules test` and the recorder; 9 accepted variants; the default passes; the check does not read `default.toml` |
| `init -g` writes only a RECORD-hash-checked, cleanly parsing default; replaces an unedited older one (restart message); keeps an edited one with one notice; `doctor` warns only on an unedited older default; the current hash is pinned | `tests/test_install_rules.py` (each earlier fixture refreshed; edited and broken-but-edited kept; changed-after-check, unparsable, weak and not-in-RECORD defaults refused before any write; link/folder refused), `tests/test_rules_shipped.py`, `tests/test_doctor.py`, `tests/test_package.py::test_the_wheels_record_lists_the_default_rules_and_init_would_write_them` |
| Largest accepted file: 300-word hook well inside 0.5 s; a larger file refused; no test bounds seconds tighter than it can hold (3x green under load) | `tests/test_rules_cost.py`; table below; 3 runs under load below |
| Client prints the shell-warn `ask` unchanged; `/health.rules_problem` says the default is in force; `[!x]*`, `*[a-z]*` refused; `rules test` with no tests exits 1 | `tests/test_hook_client.py` (two ask tests through the real client), `test_rules_trust.py`, `test_rulefile.py::test_a_path_pattern_that_matches_everything_is_refused` (20 patterns), `test_rules_cli.py` |
| AGENTS.md check green; demo replay byte-identical, also from the wheel | Check below; `test_package.py::test_the_demo_replays_with_byte_identical_answers_from_the_wheel` and `test_step_fields.py::test_the_deny_answer_is_byte_for_byte_what_it_was` pass unchanged |

### Command output

```
$ uv run ruff check . && uv run ruff format --check . && env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -n auto --dist loadgroup
All checks passed!
198 files already formatted
4123 passed, 5 skipped, 8 warnings in 136.58s (0:02:16)
```

Baseline before this card: 3846 passed, 5 skipped. The 277 new tests are in `test_rules_trust`,
`test_rules_minimum`, `test_rules_cost`, `test_rules_shipped`, and in the files listed above.

Three runs of the same line while a second copy of the suite looped in the same worktree (about
twice as slow, the point of the test):

```
run 1: 4123 passed, 5 skipped, 8 warnings in 306.96s (0:05:06)
run 2: 4123 passed, 5 skipped, 8 warnings in 278.63s (0:04:38)
run 3: 4123 passed, 5 skipped, 8 warnings in 290.19s (0:04:50)
loader: 4123 passed, 5 skipped in 263 s, 285 s, 288 s and 144 s (its fourth run, mostly alone)
```

Smoke test with real recorder processes (`agentfly serve` on its own port, temporary HOME, real HTTP):
a read of `.env`, then `curl https://x.com`. The reason is `/health.rules_problem`.

```
missing file (default)       curl-after-.env=deny  problem=None
clean 644 file (own uid)     curl-after-.env=deny  problem=None
group-writable 664           curl-after-.env=deny  problem='...: can be written by group or others (mode 0664); review what it says fi...'
world-writable 666           curl-after-.env=deny  problem='...: can be written by group or others (mode 0666); ...'
symbolic link                curl-after-.env=deny  problem='...: is a symbolic link; the recorder does not read a rules file through a...'
named pipe                   curl-after-.env=deny  problem='...: is not a regular file; the packaged default rules are in force'
R1 weakened to warn          curl-after-.env=deny  problem='...: rule R1: severity must stay "block" (it is \'warn\') (D27); the package...'
R1 missing                   curl-after-.env=deny  problem='...: rule R1: missing. Every rules file carries R1, the rule that blocks a...'
```

The real CLI on draft files (never the real rules file):

```
rules check agentfly/rules/default.toml   exit 0   ok: 2 rules ... plus R0, which is built in
rules check no-r1.toml                    exit 1   rule R1: missing. Every rules file carries R1 ...
rules check warn-r1.toml                  exit 1   rule R1: severity must stay "block" (it is 'warn') (D27)
rules check prod-pem.toml                 exit 1   rule R1: exception 'prod.pem' must be .env... ending in ...
rules check tmp-exempt.toml               exit 1   rule R1: exception '/tmp/**' names a folder; R1 judges the file name only
rules check oversized.toml                exit 1   asks for too much matching work per hook (233 units; at most 200); the heaviest is rule m ...
rules test  no-tests.toml                 exit 1   no tests to run; add [[rule.test]] tables to the rules
rules test  (the default)                 exit 0
```

### What a hook costs (this Mac, 300-word command, the whole hook through `apply_rules`, best of 5)

Words are `--oN=/Users/x/<folders>/fN.py@/x/yN`, so each word has three candidates to look at. These are
the shapes `tests/test_rules_cost.py` times (`@wallclock`, asserted only against the client's own
0.5 s, best of three), each filled to the limit.

| Shape (work units) | 20 folders deep | 40 folders deep |
|---|---|---|
| packaged default alone (31) | 46 ms | |
| 56 rules, one name pattern each (199) | 97 ms | 126 ms |
| one rule, a list of 167 name patterns (200) | 112 ms | 137 ms |
| 10 slash patterns with one `**` (193) | 68 ms | 96 ms |
| 5 floating slash patterns (173) | 89 ms | 144 ms |
| 3 floating patterns with several `**` (189) | 74 ms | 116 ms |
| 7 long slash patterns, ten parts and a name (194) | 93 ms | 153 ms |
| 198 rules whose 200-entry command lists name the command's own program (31) | 82 ms | 106 ms |

Before this card (V5b as it was): 200 one-pattern rules took about 1.0 s per decision on glued words,
and 20 rules of 200 slash entries (107 KB, accepted then) 3.6 s. Two shapes the first version of the
budget let through were found by the independent audit and fixed (see below): 198 command lists on the
command's own program took 1.1 s at work 31, and nine rules of a 100-part pattern 1.0 s on 40-folder
words. My first measurement of command lists used entries whose program the command did not have, so
it called them free; that was the gap.

Depth is the one thing the file does not control and the budget does not model: the worst shape I
could build (seven rules of one ten-part pattern each, 300 words) takes 0.11 s at 20 folders, 0.29 s at
40 and 0.46 s at 60. A hook past the client's wait falls to the offline guard (D4), as for a very long
command. Weights are a fit to these measurements; where a shape disagreed with a weight, the
measurement won (the part weight was added after the audit found it).

### final-verification (pasted)

```
## Final verification

Smoke test — real recorders on their own ports for 8 rules-file states, and the real rules CLI on
  seven files: all behave as designed (tables above), before and after the audit fixes.
Test suite — before simplify 4085 passed, 5 skipped; after simplify 4085 passed, 5 skipped (123 s,
  was 161 s); after the audit fixes 4123 passed, 5 skipped. ruff check and format clean.
Simplified — c6113b2, 9 files already on the branch: _wildcards_only is one regex (checked against the
  old function on 2.4 million strings), load_bytes checks in one place and hashes once, a never-passed
  build_ruleset argument and an unreachable floor removed, the installer hashes through
  rulefile.sha256_of, shared test helpers (list_line, ruleset_of, name_list_file), and
  test_install_rules.py stubs the install's smoke run and byte-compile (50 s serial -> 1 s for that
  file; test_install_flow.py still runs them). A reading of the active file through os.fdopen was
  tried and reverted: a folder then failed with the wrong message.
Audit — 4 findings from one cold subagent, each checked against the code first:
  1. Command lists on the command's own program were not charged and scanned the rest of the command
     per entry (1.1 s per hook from a file accepted at work 31): confirmed, fixed (97faa2b).
  2. Slash patterns were charged without their length (nine rules of a 100-part pattern: 1.0 s on
     40-folder words): confirmed, fixed (pruned walk, early refusal, 1 unit per part past the fourth).
  3. R1's exceptions were judged on sample names, so `*-prod.example` hid `credentials-prod.example`:
     confirmed, fixed (exceptions must be exactly SPEC section 5's two shapes). My own "narrower
     exception" test (`*.pem.example`) was such a hole and is now a refused case.
  4. `init -g` calls an install "intact" when rules.toml has the current bytes but a wrong owner or
     mode: confirmed, NOT fixed. It is the same bytes-only "intact" every other file in the folder
     gets, `doctor` fails and names the exact chmod, and a fix is new behaviour (a rewrite of a file
     with the right bytes) the brief does not ask for.

Verdict: READY TO COMMIT
```

### Simplify reviewers: applied and skipped

Four read-only reviewers (reuse, simplification, efficiency, altitude) ran on `fe3386e..HEAD`. Applied:
the items under "Simplified" above. Skipped, one line each:

- A per-action matching context instead of process-wide memos (altitude): a redesign of `Clause.matches`
  and every caller; the memos work at 300 words and the limits are documented.
- The memos keep command text after the decision and are bounded by entries, not bytes (efficiency; one
  10 MB command leaves about 21 MB resident until 2048 other words come): typical commands are about
  1 MB; a length guard would trade memory for the cost the memos exist to remove. Noted as a gap.
- D28's "current / older / edited" is judged in `rules_state`, `is_older_default` and `check_rules`, and
  the trust read is not shared with the installer (altitude): a refactor with no behaviour change.
- `RuleFile` has no "checked" marker, so `build_ruleset` accepts a file from `parse` (altitude): a scan
  test pins that no production module calls `parse`; a type change touches every test helper.
- `_with_minimum` skips the R1 grid when an error text starts with "rule R1", which also matches rules
  named R10 to R19 (altitude): the file is refused either way and R1's weakness shows once that rule is
  fixed.
- Moving the repeated `rec`, `start()` and `rules_file` fixtures and the shipped-fixture glob into
  conftest or `rules_helpers`, parametrizing near-duplicate install tests, one helper for the
  `rules_problem` line in `start` and `status`, `rules_state(current)` taking the RECORD hash itself
  (reuse, simplification): churn in files that other tests import, no effect on behaviour.

### /code-review high (pasted result, 8 findings)

Fixed (c4efc51):

- `_wildcards_only` missed `/`, `//`, `./` and `./.` (no `*`, yet every path): now refused like `[!x]*`;
  `~/` and `/etc/` still load. `test_rulefile.py`, 5 new cases.

Not fixed, one line each:

- The default `npm-publish-after-env` rule misses `npx npm@latest publish`, `pnpm`, `yarn`,
  `npm $(echo publish)`: new spellings of `npm publish` are V5c, excluded by the brief.
- `host_not_in` reads any dotted word (`out.txt`) as a host: `names.hosts_in_command` is V5b's host
  detection, shared with R1's outbound class and the offline guard; changing it changes R1's answers and
  needs its own card.
- `command = "npm publish"` matches `npm run publish` and `echo npm publish`: that is the documented V5b
  meaning (the program, then the extra words in any order, SPEC section 5); a subcommand position needs a
  SPEC change.
- `_ALARMS` in `memory.py` lists blocked and warned only, so a highlighted step may fall out of the
  live page's `flagged` list: `memory.py` is outside this card's Touches and I did not verify it; for
  the lead (page contract).
- `names.is_sensitive` is a shim over the active rule set, and `store.build_step_record` runs R1's
  `after` more than twice per shell hook: V5b's structure; the budget's "twice" is a fit to the
  whole-hook measurement, not a count of passes, so the table above is the truth.
- Event and path extraction exists in `rulefile`, `rules` (R0 also reads `path`, `target_file`,
  `attachments`) and `store`: V5b's structure; a refactor outside this card. A `write` rule on a
  `target_file` key is the real gap; for the lead.
- `agentfly uninstall` deletes an edited rules.toml with the folder, no backup (the "Needs owner"
  question): V5b design, tested; where a copy goes is a decision.

### Design choices to flag (the lead may disagree)

- The trust check is applied to the active file and to any FILE that is the active path; other files are
  drafts and get no check, so `rules check FILE` never says "ok" for the active file the recorder refuses.
- R1's exceptions are exactly SPEC section 5's two shapes. An owner who adds secret names of their own
  cannot give them an exception (they can still list the names; marking more is harmless). This is
  stricter than the first draft of D27 ("plain `.example`/`.sample`/`.template`/`.pub`") because only
  this shape provably hides no name SPEC counts as secret.
- `default.toml` is not edited (the brief: only if D27 needs it).
- `ACTIVE_OWNER_UID` is a module attribute read at call time, as `ACTIVE_RULES` is; no flag or variable
  moves it.

### Gaps

- `cli/init.py` is untouched, so: an intact `init -g` re-run prints no notice about an edited file (there
  is nothing newer to apply); a bad packaged default is refused only by root's `install()`, after the
  password; a rules-only refresh still prints "Quit and reopen Cursor".
- `default.toml`'s header still says it is copied once; editing it would add a shipped hash.
- HOOKS.md (about lines 147-165) describes the old `rules_problem` text. SPEC section 8's line about the
  old shell-warn answer is stale (also in V5b's report). Both are the lead's.
- The trust check does not look at the folder above the file (the installer makes it root's) or at ACLs.
- Cost grows with path depth and command length beyond the calibrated 20 folders and 300 words (see the
  note under the table).
- `main` has never had `default.toml`, so three of the four hashes in `SHIPPED_DEFAULTS` are branch
  history, not releases; harmless.
- `[.][e][n][v]` (single-character classes) is refused as having no literal; spell it `.env`. An R1
  spelled `r1` is not R1 (ids are compared exactly, as `rules.py` does).
- Not in this card: new spellings of `npm publish` (V5c), offline-guard backing for file rules, merging
  into an edited file (V7), a page view of rules, SPEC sections 7/8 (lead).

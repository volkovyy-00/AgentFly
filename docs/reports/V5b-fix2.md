# V5b-fix2: Second review round for V5b (hook-cost bound, R1's minimum on every name, honest "intact", long words)
Status: in progress (as of 2026-10-21 10:35)
Result: One per-hook budget bounds floating patterns (now also within one walk) and command lists; R1's minimum is structural; long words never raise; every saved path encodes; init -g rewrites only checked bytes. Review and audit findings fixed inside Touches; CR1 is outside them.
Evidence: Branch ag-v5b-rules-file at e43239e (11 fix commits 49f6988..e43239e after the simplify 69c9d0e). Check: ruff clean, 4452 passed, 5 skipped. Smoke summary in the newest section. Nothing pushed.
Needs owner: CR1, a security gap in sessions.py (outside this card): a fallback-linked subagent can miss a later R1 mark. Recommended: fix in the next card that may touch sessions.py (OR the parent's mark and triggers into an already-pending Task record).
Details: see "## 2026-10-21 10:35" below.

### Final verification and code review

The controller ran the final whole-card review (ready to merge, minors only), `/final-verification`
(smoke OK; simplify commit 69c9d0e, behaviour-preserving; the audit found A1-A4) and `/code-review
high` on `main...HEAD` (CR1-CR10). This wave fixes the findings inside the card's Touches, each with a
test that failed first (except M3, text only). Hook answers, deny bytes, the demo replay and stored
values are unchanged for everything that worked before; `MAX_WORK`, `WORK_*`, `FLOAT_STEPS`, `DIV`,
`MAX_PATH_WORD` and the meter's prices are unchanged.

| Finding | Fix | Commit |
|---|---|---|
| A1: one floating walk overspent the meter (one `.ssh/**` on a path 800,000 folders deep: left -1,555,004, 0.84 s) | `_place_middle` reads what the meter has left before each block's walk and charges as soon as the walk passes it (one integer compare per start), so the meter ends at most one start's work below 0. The repro now ends at -2 (0.25 s, the default rules alone 0.20 s). The counting test's steps are 45,004 (were 45,086). Test: `test_rules_meter.py::test_a_walk_stops_once_it_has_spent_what_the_meter_has_left` (50,000 folders: -99,002 before, -2 after) | 49f6988 |
| A2: a Read/Write path the history cannot encode lost the row and `/api/steps` answered 500 | A path that does not encode is "outside" whether `resolve()` failed or succeeded (macOS resolves U+DC80..U+DCFF), and the base name is stored with **U+FFFD for each lone surrogate** (`store._storable`; a path that encodes keeps its exact value). `<ws>/a/\udcff/b` is saved `b` (as `a/\ud800/b` was), `<ws>/x/\udcff` and `<ws>/x/\ud800` as `\ufffd`. Tests: `test_long_words.py::test_a_read_path_the_history_cannot_encode_still_reaches_it_and_the_page` (3 cases), the updated `test_an_unencodable_absolute_path_is_saved_as_its_base_name` and `test_a_word_the_system_cannot_encode_is_not_a_path`. Closes residual 10 | f3f40c4 |
| Final M2: the sensitive-word branch looked up a 60 kB program word (0.52 s) | `store._word_path`: a word over `MAX_PATH_WORD` is saved by its base name without asking the system, as `_is_file_in` already did (same value as before: such a word is outside the project). Test: `test_long_words.py::test_a_long_program_word_naming_a_secret_is_not_looked_up`. Closes residual 11's first half | f3f40c4 |
| CR3 / A4: a broken rule `R10` hid R1's D27 errors | `_with_minimum` matches `"rule R1:"`. Test: `test_rules_minimum.py::test_a_broken_rule_whose_id_starts_like_r1_does_not_hide_r1s_errors` (R10, R1x, R2 control; R1 as warn and R1 missing) | eb69442 |
| CR5: `rules check` said "(file given)" for the active path itself | The label comes from `rulefile.is_active_path`. Test: `test_rules_trust.py::test_rules_check_calls_the_active_file_so_however_it_is_given` | e6832a0 |
| CR6: with the packaged default damaged and the active file refused, the start-up error said "the packaged default rules are in force" | `rules._refusal` ends the line with the default's own reason ("the packaged default rules cannot be used: ...") when the default is damaged. Test: `test_rules_load.py::test_a_refused_active_file_on_a_damaged_default_does_not_claim_the_default_is_in_force` | 58f5930 |
| CR7: a link or folder at the rules path was refused only after the password | `installer.check_packaged_default` raises root's own `_blocked` error first. Test: `test_install_cli.py::test_a_link_or_folder_at_the_rules_path_stops_init_before_the_password` (link, folder; no sudo, no prompt). Closes the "`blocked` reaches the password prompt" gap | 8119f73 |
| Final M4: the limit log line held the whole chat id | At most 80 characters (`chat[:80]`). Test: `test_rules_limit.py::test_the_log_line_holds_at_most_80_characters_of_the_chat_id` (10,002 characters) | 07f1e58 |
| Final M6: `LIMIT_MESSAGE` promised "`rules check` names the heavy ones" (false for a probe-heavy list) | "... may name the heavy ones"; spec §4.3 and §4.4 follow. Test pins the text: `test_rules_limit.py::test_the_limit_message_does_not_promise_that_rules_check_names_every_heavy_rule`. Closes residual 4's message half (the list still has no lint line) | 5692dbb |
| Final M3 (no test): stale text | `app.py`'s budget comment names command lists too; `test_rules_meter.py`'s "spent meter" comment; the spec's two `Status:` lines are one (revision 4, and what it changed) | 0e4906e |
| CR2 / final M1: a trigger held only through a parent (or the workspace fallback) is re-evaluated by `mark`; if the meter ran out there the hook got the limit answer | Fixed, cleanly: `decide` already receives the effective session (`SessionStore.apply_mark` returns `effective(stored)`), so `rules._outcome` runs the check for a rule whose trigger that session holds even when `mark` left it unfinished. What `mark` records is unchanged; `sessions.py` is untouched. Test: `test_rules_limit.py::test_an_inherited_trigger_left_unfinished_in_mark_is_judged_as_held` (a subagent of a parent holding a heavy block trigger, on a heavy `echo` its `then` does not match: allow, was the limit deny; a chat without the trigger still gets the limit deny); spec §4.3 says so | de89ead |
| AGENTS.md "Testing" | Lines for each new test, the counting test's 45,004 | e43239e |

### Listed, not fixed (one line each, with why)

- **CR1 `sessions.py:298` (security gap, for the lead and the owner).** The pending Task record is a
  one-time snapshot of the parent's mark and triggers. When a chat holding only a non-R1 trigger starts
  a Task and is marked afterwards, a child reached only through the 30-minute workspace fallback
  inherits the trigger but not the mark, so R1 does not block its `curl`. Custom rules only (the
  default's npm-publish trigger also marks). Reproduced by the code review. `sessions.py` is outside
  this card's Touches. Recommended fix: when the call is already pending, OR the parent's current
  `marked` and `triggers` into the pending record (a few lines in `record_call`), with a test; in the
  next card that may touch `sessions.py`.
- **CR4 `store.py:413`**: R1's `after` runs three times per shell hook (`mark`, `is_sensitive` per
  word, `reads_secret`); the measured hooks are well under budget, and reuse needs plumbing from `app`
  to `store`.
- **CR8 `rules.py:467`**: the `RULES` list and `deny_messages` are test-only leftovers; removing them
  touches tests of earlier cards.
- **CR9 `rulefile.py:458`**: `Parsed`'s hash is not cached; `Parsed` lives in `normalize.py`, outside
  Touches.
- **CR10 `rulefile.py:641`**: `os.path.expanduser("~")` reads `$HOME`, against AGENTS.md's "reads no
  environment" wording; pre-existing, and the wording is the lead's.
- **A3**: a root-owned 0600 edited rules file: as root `init -g` says "kept your edited rules file",
  but the user-run recorder cannot read it and runs the default; every unprivileged `init -g` asks for
  the password (residual 7). Needs a decision on what `unknown` means, not a few lines.
- **Final M5**: `distinct_candidates` keeps 64 `Parsed` trees (memory only, same scale as the argv memos).
- **Final M7**: `_anchored_hint` advises anchoring for patterns already anchored (`/etc/**/ssl/**`)
  and for `/a/**/b/**`, which anchoring does not fix; message quality only.
- A file whose every rule is broken and that has no R1 does not also say "R1 missing" (`_with_minimum`
  treats "no rules read" as "refused before its rules were read"); it is refused all the same.

### Changes an edited rules file may notice

Each makes an existing edited file fall back to the packaged default (`rules_problem` set, `doctor`
fails the rules line, `rules check` exits 1), or makes a hook answer the limit:
- R1 with a floating folder pattern (`.ssh/**`, `**/x/**`) is refused (anchor it: `~/.ssh/**`).
- A floating pattern in any `path_except` is refused.
- An R1 spelled as a union of narrow patterns that together cover a secret family, but no one of them
  covers it, is refused (D27 by structure, residual 9).
- Command lists now count against the hook's rules limit (owner 2026-10-21): a crafted heavy list on a
  long command gets the limit deny (block), `ask` (warn) or is skipped (highlight).

### Command output

```
$ uv run ruff check . && uv run ruff format --check . && env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -n auto --dist loadgroup
All checks passed!
209 files already formatted
4452 passed, 5 skipped, 8 warnings in 143.47s (0:02:23)      (at e43239e; 4437 at 69c9d0e)
```

Smoke test (`scratchpad/final/smoke_test.py`, the controller's):

```
SMOKE SUMMARY
reviewer pem x8, 300 words 60 deep                            30.7 ms  allow
reviewer json x10, 300 words 60 deep                          31.7 ms  allow
floating block rule, 300 words 60 deep                        41.9 ms  deny  AgentFly's rules took too long to check this action (the rul
same file, marked chat + curl                                 18.4 ms  deny  Blocked by rule R1: a secret was read earlier in this sessio
bipartite command lists x198 block, 300 words                 37.2 ms  deny  AgentFly's rules took too long to check this action (the rul
default, bash -c 300 paths 60 deep                            12.2 ms  allow
default, .env read then curl with a 300-char word              0.0 ms  deny  Blocked by rule R1: a secret was read earlier in this sessio
default, echo a 300-char word                                  0.0 ms  allow
default, .env read then curl with a 5000-char word             0.0 ms  deny  Blocked by rule R1: a secret was read earlier in this sessio
default, echo a 5000-char word                                 0.0 ms  allow
1 passed in 3.52s
```

## 2026-10-21 09:40" below.

## 2026-10-21 09:40

### What was built (in the brief's order)

Four parts, 13 tasks (plus an inserted Task 6b), each reviewed. Every code file is inside the brief's
Touches list (`agentfly/recorder/`, `agentfly/install/`, `agentfly/cli/`, their tests, AGENTS.md
"Testing", SPEC §5's D27 paragraph, and this card's `docs/superpowers/` files). `default.toml`,
`sessions.py`, `memory.py`, HOOKS.md, DECISIONS, STATE, BOARD and learnings are untouched.

1. **The cost bound** (Tasks 1-6b, `rulefile.py`, `rules.py`, `app.py`).
   - **Matcher.** A slash pattern is split at each `**` into a head, a tail and middle blocks. Only a
     pattern with a middle block *floats* (`.ssh/**` does not; `a/**/b` and `**/x/**` do). A pattern
     that does not float compares each part once, at any depth. The old walk is kept in
     `tests/glob_oracle.py` and the new matcher answers as it did on 20,000 seeded random cases.
   - **Meter.** `rules.one_hook()` gives each hook one budget, `FLOAT_STEPS = 45,000`, priced from
     measured time so a whole budget of the slowest step is about 20 ms. A floating pattern charges
     `1 + n*m // 256` per `fnmatch` compare and 1 per start and bare `*`; `WorkLimit` is raised past
     the budget.
   - **Command lists** (owner 2026-10-21, Task 6b): a bucket of the command index is charged its weight
     before it is walked, and key probes cost a step for four. Real shapes are never charged.
   - **Command index.** A list is looked up by program, then by the entry's rarest extra word, and a
     hook holds the views of its simple commands once (no global LRU). Old cost of the reviewer's
     198 x 200 `cat wN` file on 150 joined commands: 7.7 s; now about 50 ms.
   - **Engine.** One pass. An unfinished block rule gives the `rules limit` deny (R0 and R1 keep their
     answers, R1's mark is still set); an unfinished warn on a shell command asks; an unfinished
     highlight is skipped; an unfinished trigger is recorded nowhere. `/health` gains `rules_limit`
     only after a hit, and the log line names the chat and rule ids, never command text.
   - **Refusals and lint.** A floating pattern in any `path_except` is refused; `rules check` warns
     about a floating `path` pattern and about a command list whose heaviest bucket weighs over 20.
2. **Long words** (Tasks 7-8, `clean.py`, `store.py`). A word or path over the system's name limit, a
   word over 1,024 characters, a lone surrogate, a NUL and a link loop no longer raise (string
   containment replaces `relative_to`). `clean.py` was then trimmed by profile (a regex pass for
   quotes and separators, `shlex` only when a segment needs it), outputs byte-identical.
3. **D27 by structure** (Tasks 9-10, `rulefile.py`, SPEC §5). SPEC §5's six bullets are one table
   (`SECRET_FAMILIES`); `covers` judges R1's `after` by pattern shape; R1 may hold no floating folder
   pattern. The sample grid moved to `tests/r1_grid.py` as a second opinion; a brute force over 1,000
   random lists finds no accepted R1 that misses a secret name.
4. **Install** (Tasks 11-12, `installer.py`, `init.py`, `rules_check.py`). `rulefile.trust_problem` is
   the recorder's trust test alone, shared with the installer. `rules_state` gains `untrusted` (rewritten)
   and `unknown` (root decides); an edited file is never written, chowned or chmodded and gets a
   notice, also on an intact re-run as the user. `rules check <link to the active file>` judges the
   active file. Both `init.py` gaps from V5b-fix are closed: a bad packaged default stops before the
   password, and a rules-only refresh asks for a recorder restart, not a Cursor restart.
5. **Close** (Task 13). AGENTS.md "Testing" lines (one per new test file, `tests/r1_grid.py` in the R1
   line, and edits to Cost, R1 minimum, Rules file, Trusted file and Install); spec §8's Install line
   amended (ruling R-n, below); this report.

### Commits (oldest first)

```
84421a0..fd1a734   intent, design, plan and plan-review fixes (docs/superpowers/)
81fbd3d V5b-fix2: a glob whose cost does not grow with depth unless the pattern floats
e94f446 V5b-fix2: a per-hook meter on floating patterns, priced from measured time
573a6a3 V5b-fix2: command lists are looked up by program and rarest word
2436b40 V5b-fix2: a hook holds the views of its simple commands, not a fixed-size memo
dde17c8 V5b-fix2: an unfinished block rule denies, an unfinished warn asks, and neither records a trigger
66e7610 V5b-fix2: the recorder meters each hook and reports the rules limit
5edef16 V5b-fix2: floating exceptions are refused, rules check warns about floating patterns, and the count is tested
646218d V5b-fix2: command lists count against the rules limit (owner 2026-10-21)
06b1bdc V5b-fix2: a long word or path never raises and is not quadratic
2fb6dc8 V5b-fix2: a link loop never raises, and an unencodable path is saved by its base name
cd9708c V5b-fix2: the cleaner's baseline is trimmed (outputs byte-identical)
92c468a V5b-fix2: SPEC section 5's secret names come from one table
0fe4062 V5b-fix2: R1's minimum is judged by pattern structure (D27)
c0d217e V5b-fix2: init -g rewrites only known bytes, and never calls an untrusted rules file intact
84f8412 V5b-fix2: rules check through a link judges the active file
ade67ce V5b-fix2: AGENTS.md testing lines and the report draft
69c9d0e V5b-fix2: simplify (final verification)
(the final fixes: see the newest section)
```

`git diff --shortstat efa9848..84f8412` (V5b-fix's last commit to this card's last code commit): 26
files, +5368 / -322, docs/superpowers included. Commit trailers carry the model that wrote each
commit (ruling R-f).

### Acceptance criteria

| Criterion | Evidence |
|---|---|
| Any accepted file (the reviewer's two shapes included): a 300-word hook with paths 60 deep under 0.2 s; `bash -c` with 300 such paths under the default; a counting test fails if the bound is removed | Measurements below: slowest 116 ms (Task 8 gate) and 108 ms (re-run at this head), `bash -c` 11 ms at 60 deep. `tests/test_rules_cost.py::test_a_hook_stops_at_the_budget_and_the_count_proves_it`, `test_a_file_without_floating_patterns_is_never_metered`; `tests/test_rules_limit.py::test_a_heavy_command_list_stops_at_the_budget_and_the_count_proves_it` (each fails with `_charge` a no-op) |
| R0's and R1's answers at the limit; a file `block` rule unfinished denies with the limit message and records no trigger (a restart judges as before); a padded shell command with a `warn` unfinished asks; `/health` and the log say so; a 167-name list on 300 words of 30 characters gets no limit deny | `tests/test_rules_limit.py` (28 test functions) |
| A quoted word of 300 or 5,000 characters (with and without `/`) gets the short word's answer, R1 still blocks after a `.env` read, and the step reaches history | `tests/test_long_words.py` (28 cases; 17 of the first 24 failed on the old code) |
| The three dodge files and an R1 with `.ssh/**` are refused naming R1; the default, added names, `.env*`, `.*`, `*pem`, `~/.ssh/**` load; a brute force finds no accepted R1 that misses a secret name | `tests/test_rules_minimum.py` (`test_the_brief_dodge_files_are_refused_naming_r1`, `test_the_brief_loading_list_loads`, `test_r1s_floating_folder_patterns_are_refused`, `test_brute_force_...`: 399 accepted, 601 refused, 561 names) |
| `init -g` rewrites current bytes in a file that is not exactly ours; an intact re-run with an edited file prints the one-line notice; `rules check <link to the active file>` judges the file the recorder loads | `tests/test_install_rules.py` (rewrite of mode 0664, 0600 and a wrong owner; untrusted edit kept; notice after the pinned line), `tests/test_rules_trust.py::test_rules_check_through_a_link_to_the_active_file_judges_the_active_file` |
| AGENTS.md check green 3x with a second copy of the suite running; demo replay byte-identical, also from the wheel | Command output below |

### Command output

```
$ uv run ruff check . && uv run ruff format --check . && env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -n auto --dist loadgroup
All checks passed!
208 files already formatted
4437 passed, 5 skipped, 8 warnings            (before this card: 4123 passed, 5 skipped)
```

Three runs of the same line while a second copy of `uv run pytest -q -n auto --dist loadgroup` looped
in the same worktree (load average 20-27 on this Mac, so each run took about twice as long):

```
run 1: 4437 passed, 5 skipped, 8 warnings in 226.24s (0:03:46)
run 2: 4437 passed, 5 skipped, 8 warnings in 239.98s (0:03:59)
run 3: 4437 passed, 5 skipped, 8 warnings in 263.22s (0:04:23)
loader: 4437 passed, 5 skipped in 237.05 s, 248.29 s and 267.39 s (a fourth run was stopped with the load)
```

The loader ran with `PYTHONDONTWRITEBYTECODE=1` too, as AGENTS.md says a stray `.pyc` would break
`test_nothing_is_written_next_to_the_client`; the load is the same.

```
$ uv run pytest tests/test_package.py tests/test_step_fields.py -q
31 passed, 1 warning in 63.00s
```

`test_the_demo_replays_with_byte_identical_answers_from_the_wheel` and
`test_the_deny_answer_is_byte_for_byte_what_it_was` pass unchanged. Nothing was skipped.

### Measurements (spec §9)

All times are the whole hook through `Recorder.run` (`apply_rules`: mark, decide, the step record), best
of three after a warm run, on this Mac. **None of them is a true idle figure**: the load average was
2.0-3.4 from other sessions in every run (the "re-run" column is this card's final head, load 3.1-3.4,
with my own processes stopped), so idle is a little faster. They are measurements, not test bounds.

**300-word commands, 60 folders deep** (ms):

| Shape | Task 6 gate | Task 8 before | Task 8 after | Re-run, final head |
|---|---|---|---|---|
| reviewer's `*/*/*/*/*/*/*/kN.pem` x 8 | 107.6 | 107.7 | 31.2 | 31.4 |
| reviewer's `*/*/secretN/*.json` x 10 | 109.1 | 103.8 | 33.4 | 31.8 |
| floating shape at the limit (5 x `d*/d*/d*/zN/**`; the limit deny) | 114.9 | 113.2 | 40.6 | 40.3 |
| many rules with one name pattern | 144.9 | 142.2 | 71.2 | 70.8 |
| one long list of names | 155.7 | 153.1 | 82.4 | 85.1 |
| slash patterns with one `**` | 103.1 | 99.6 | 28.8 | 31.5 |
| floating slash patterns | 103.9 | 101.6 | 28.8 | 28.4 |
| floating patterns with several `**` | 100.5 | 98.7 | 24.4 | 26.9 |
| long slash patterns | 102.2 | 100.3 | 28.7 | 29.2 |
| 198 rules of `cat wN` on `command(60)` | 98.8 | 100.2 | 38.0 | 26.7 |
| same list, `command(60)` cut into 10 / 50 / 150 simple commands | 103 / 110 / 129 | 101 / 112 / 134 | 30 / 39 / 56 | 30 / 38 / 57 |
| same list, 10 / 50 / 150 joined `cat zN y` | 8.3 / 24.4 / 67.2 | 6.2 / 21.8 / 58.2 | 6.6 / 21.5 / 55.2 | 7.8 / 22.3 / 55.9 |
| 167-name list, 30-character names, flat | 65.1 | 54.8 | 45.5 | 43.1 |
| **167-name list, 30-character names, 60 deep** (slowest) | 252.1 | 180.7 | **116.3** | **107.7** |
| the packaged default | 94.0 | 94.3 | 21.7 | 22.0 |

The Task 6 gate ran before Task 7 and Task 8; "Task 8 before" is the head just before the cleaner was
trimmed. The slowest shape is mostly the cleaner's `Path.resolve` of 300 long absolute words that do
not exist (about 62 % of the profiled hook), not matching.

**Crafted command-list files** (198 rules, `rules check` accepts them all; ms):

| Shape | Unmetered (advisor, Task 6) | Metered, Task 6b gate | Re-run, final head | Answer now |
|---|---|---|---|---|
| pairs of 21 words, 75 x `cat u_i u_k n_m` | 271 | 44.8-47.9 | 38.6-39.2 | limit deny (block) / skipped (highlight) |
| bipartite `cat aI bJ`, 13 x `cat a0..a19 zK` | 407-420 | 43.9-46.3 | 35.0-37.4 | limit deny (block) / `ask` (warn) / skipped (highlight) |
| four-word entries 5x5x4x2, 42 commands | 1,174 | 34.1 | 27.2 | limit deny |
| nine-word entries, two keys, 75 commands | 2,066 | 31.8 | 27.6 | limit deny |
| 30 present + 1 absent, 9 commands | 1,067 | 31.8 | 24.7 | limit deny |
| must allow: 198 x `cat wN` on 150 `cat zN y` | | 69.3 | 56.3 | allow |
| must allow: 198 x `cat w a0..a199` on 100 `cat w x` | 5,558 before Task 3 | 29.6 | 20.0 | allow |
| must allow: realistic 20 x 15 `git push ...` on 75 `git push origin bK` | | 31.5 | 22.4 | allow |

So the owner's decision turned crafted files at 0.27-2.07 s a hook into 32-48 ms with the limit
answer, and left every real shape unchanged. Informative, beyond the 300-word criterion: 198 x
`cat wN` on 1,000 `cat zN y` (3,000 words) takes 343 ms; cost grows with command size (residual 1).

**`bash -c` with 300 paths under the default rules:**

| Depth | Before Task 7 | After Task 7 | After Task 8 | Re-run, final head |
|---|---|---|---|---|
| 20 | 315 ms (then `OSError`) | 26-30 ms | 6.7 ms | 6.7 ms |
| 60 | 2,528 ms (then `OSError`) | 124-126 ms | 10.8 ms | 10.9 ms |

The spec expected about 150 ms at 60 deep.

**The meter's price** (Task 2, load about 1.9, 300 words, 60 deep, unlimited meter, three runs):

| Shape | Steps | Time | Per step |
|---|---|---|---|
| A: 5 x `d*/d*/d*/zN/**`, no match (the slowest) | 906,000 | 387-398 ms | 0.427-0.440 us |
| B: 5 x `p{i}/**/x{i}.txt` | 38,100 | 14.8-15.6 ms | 0.387-0.411 us |
| C: `*a*b*c/**/z` on 255-character segments | 124,800 | 17.1-17.4 ms | 0.137-0.139 us |

`FLOAT_STEPS` = 20 ms / 0.440 us = 45,454, rounded down to **45,000**; a meter of 45,000 on shape A
runs out in 19.69 ms (best of three). **`DIV` stays 256**: a long compare costs about a third of its
price (C against A), so long compares are over-priced, not under. The heavy rule spends 306,000 steps
on `command(20)` and 906,000 on `command(60)`. For command lists (the advisor's measurement, not
repeated): about 0.35 us per entry step of a one-word rest, 0.09 us for a long rest, at most 0.4 us a
probe; the charge is 1 per entry and word, and 1 per four probes.

**D27 load time** (Task 10, best of five): `_coverage_problems` on the default's R1, 13.7 us; the whole
`_minimum_problems`, 22.4 us; `load_bytes(default)` with the D27 cache cleared, 0.96 ms (of which
`parse` 0.85 ms). The old grid took 39.5 ms.

**The margin at 60 deep against 0.2 s.** The slowest accepted-file shape is the 167-name list on
30-character absolute names 60 deep: 116 ms in Task 8's gate and 108 ms in the final re-run, so
84-92 ms (42-46 %) under 0.2 s, on a machine that was not idle. The next two are 85 and 71 ms (name
lists); every slash-pattern and command-list shape is under 60 ms, and the limit-hit shape is 40 ms.
The packaged default is 22 ms. The margin is much smaller for commands past 300 words: the cost is
linear in the command (343 ms at 3,000 words on the 198-list shape).

### Residuals (spec §9 and what the tasks found)

1. **Cost grows with command size; the floating budget does not**, so a long floating-heavy command
   reaches the limit sooner. A line of 3,000 words under 198 command-list rules takes about 0.34 s.
   Before Task 8 the cleaner cost about 2.6 us a character (a `bash -c` script of about 190 kB passed
   0.5 s alone); after it a 71 kB script takes 11 ms. Not re-measured at 190 kB.
2. **R1 and name lists are never stopped**, so very long names cost what they take. The 167-name list
   on 60-deep 30-character absolute words is 108-116 ms, about 62 % of it `Path.resolve` in the
   cleaner (300 `realpath` walks of 61 parts); a byte-identical shortcut would need to reason about the
   filesystem, and Task 8 did not take it.
3. **The list charge is conservative by design.** A step of a long rest takes about 0.09 us against
   0.35 us for a one-word rest, so a long rest is charged up to about 4x its time, and a crafted file
   with long entries reaches the limit sooner than its time needs.
4. **A probe-heavy list reaches the limit with no lint line.** 198 rules of `pI kJ` (a bucket weight of
   1 each, many keys per program) are charged by probes, not buckets, so `rules check` prints nothing
   and the limit message's "rules check names the heavy ones" is not true for it.
5. **`198 x cat wN` on `command(60)` is charged 9,900 of the 45,000 steps** (200 key probes a rule, a
   step for four) and still allows (ruling R-j). Such a file plus heavy floating patterns reaches the
   limit sooner than the floating patterns alone.
6. **`init -g`'s `untrusted` is stricter than the recorder's trust rule.** It means "not exactly the
   layout owner's and mode 0644", while the recorder loads a root:admin 0640 file, so `init -g` may
   rewrite known bytes that `doctor` calls fine, and asks for the password to do it.
7. **`unknown` is always bad for an unprivileged run**, so an edited root 0600 file asks for the
   password on every `init -g` (spec-mandated; root then decides with the full state).
8. **An unfinished warn trigger is not recorded**, so it is lost if the user lets the command run.
9. **D27 refuses some covering unions** (a union such as `.env.[!s]*` plus `.env.s`), by design.
10. **A last-part lone surrogate in a Read or Write path** is still saved as it is, so the history row
    fails to write (`local store write failed: UnicodeEncodeError`, the hook answer is unaffected) and
    `/api/steps` carries it. This predates the card (ruling R-m); a lone surrogate in an earlier part
    is now saved by the base name and works. A NUL in a middle part (`a/\x00/b`) is now saved whole
    (it was `b`); harmless.
11. **`store.py`'s sensitive-token branch** calls `relative_file_path` with no length guard (a 60 kB
    word takes 0.52 s there); `build_step_record` re-splits the cleaned command through
    `names.words` (about 9 ms of 45 ms profiled).
12. **`a\ ` repeated** grows super-linearly past 100 kB (pre-existing, downstream of tokenising).
13. Measured on a loaded machine, not an idle one (see the note above the tables).

### Decisions taken during the card

**The owner, 2026-10-21 (after the brainstorm-advisor's note).** Command-list entry checks count
against the same per-hook budget as floating patterns, and an unfinished highlight list is skipped
(allowed, logged). This supersedes the brief's "meter only floating patterns". The advisor's numbers:
accepted crafted command-list files cost 0.27-2.07 s a hook before (pairs of 21 words 271 ms,
bipartite 407-420 ms, four-word entries 1.17 s, nine-word entries 2.07 s), and 32-48 ms after, with
the limit answer; the rules a real owner writes are never charged. Cost if wrong: a legitimate, very
large command list could reach the limit on a long command and its block rule would deny; the charge
is up to about 4x conservative (residual 3).

**The controller's rulings** (R-a to R-n), one line each, with what it costs if wrong:
- **R-a** Task 2 routes every meter charge through one function (`_charge`) and exposes a no-op `_tally`
  for counting real steps, because Task 6 needs both and no earlier task named them. Cost: small
  rework in `rulefile`.
- **R-b** Task 10 also repoints Task 9's new test and the other readers of the old grid at
  `tests/r1_grid.py`. Cost: none beyond a test import.
- **R-c** If `FLOAT_STEPS` were priced so high that the heavy shape no longer exhausted it on
  `command(20)`, the limit tests could patch it. Not needed (306,000 steps against 45,000). Cost:
  limit tests on a smaller budget than production.
- **R-d** Task 13's implementer does Steps 1-5 and 7; the controller runs the final whole-branch review,
  `/final-verification` and `/code-review high`. Cost: one extra review pass.
- **R-e** The plan's "stop and ask" points (a command list over 0.2 s at Task 6, any shape over 0.2 s at
  Task 8) are real stops. Cost: a pause. Task 6's gate stopped; the owner decided above.
- **R-f** Each commit keeps the `Co-Authored-By` trailer of the model that wrote it (Sonnet or Opus
  5.5), not the plan's fixed Opus line. Cost: a reword of trailers before merge, if the lead wants
  them uniform.
- **R-g** Task 3 keeps the per-simple-command views for one hook, memoized per `Parsed` inside
  `rulefile`, instead of a global LRU that thrashed above 512 distinct commands. Cost: one more memo
  shape in `rulefile`.
- **R-h** R1's `secret` in `mark` stays unguarded; Task 10's refusal of floating R1 patterns closes the
  window where a widened R1 could raise `WorkLimit` out of `mark`. Cost: an intermediate commit range
  with a crash path, never merged alone.
- **R-i** At Task 6's gate the implementer still commits Steps 1-2 and runs the full check, and adds two
  command-list shapes to the timings. Cost: two extra timings.
- **R-j** "198 x `cat wN` on `command(60)`" is charged its probes (9,900 steps) and still allows; the
  advisor's prices stay and a test pins the charge. Cost: such a file plus heavy floating patterns
  reaches the limit sooner (residual 5).
- **R-k** A run of fewer than 4 key probes makes no `_charge` call (a charge of 0 on a spent meter would
  raise and starve cheap rules). Cost: none, at most three dictionary look-ups.
- **R-l** `RuntimeError` is added to the resolve guards in `clean._resolved` and
  `store._resolved_or_tidied`, because spec §2 goal 2 ("no word or path makes the hook raise") binds
  over §5's literal exception tuple. Cost: none (`RuntimeError` from `resolve` only means a link loop).
- **R-m** In `store`'s fallback a path that does not encode as UTF-8 counts as outside the root, so it is
  saved by its base name as before; the older last-part-surrogate case predates the card. Cost: that
  older history-row failure stays until a later card (residual 10).
- **R-n** Spec §8's "edited, untrusted file keeps its bytes and mode, `init -g` exits 0 and prints the
  notice" means the intact re-run. On a repair run `assert_locked` still fails closed (bytes
  untouched, repair undone); `lock_problems` is not weakened (security-sensitive, outside the brief).
  The spec line is amended in this change. Cost: after an upgrade a user with an untrusted edited file
  sees a lock error, not the friendlier notice, until a later card.

### Gaps for the lead

- **The brief's Cost sentence**: "meter only floating patterns" becomes "meter floating patterns and
  command-list entry checks" (owner 2026-10-21, Task 6b). The brief is the lead's to edit.
- **SPEC §5, "What a file may cost"** (SPEC.md about lines 346-353) is stale in four ways:
  1. the rules limit (`FLOAT_STEPS`, its deny, `ask` as warn, highlight skipped) is not described;
  2. "command and host lists cost almost nothing ..." must gain "... and count against the hook's
     rules limit";
  3. `path_except` refusing floating patterns is not mentioned;
  4. "about 0.1 s ... about 0.3 s at 40 folders" is out of date: the measured figures are 22-116 ms at
     60 deep. SPEC §5's D27 paragraph (edited here, as the brief allows) now says "the rules limit", a
     phrase §5 does not define until the first three are written. SPEC.md:342 is over the wrap width.
- **HOOKS.md**: a `rules_limit` line for `/health`. HOOKS.md lines 147-149 name one extra key,
  `rules_problem`, and say a healthy recorder sends exactly three; `rules_limit` (one line, at most 400
  characters, only after a hit since the recorder started) needs its line. README and HOOKS text for
  `/health`, and `doctor` (which ignores the new key), were not touched.
- **AGENTS.md outside "Testing"** (this card may edit only that section): the Commands "Rules" bullet and
  "Rule shape" say nothing of the rules limit or of floating patterns; D27's description there is still
  true but no longer says "structural".
- **R-n's repair-path behaviour, and a conflict that predates the card.** `assert_locked` (and
  `doctor`'s lock check) refuses the whole system folder when any file in it can be written by group or
  others, and as root with a layout owner when a file is not owned by the system user. So during any
  repair or upgrade an edited rules file at mode 0664 stops `init -g` with "can be written by group
  or others" (exit 1, rolled back, file untouched, pinned by
  `test_a_group_writable_edit_with_other_work_to_do_stops_the_repair_and_is_not_touched`), and an
  edited root:admin 0640 file (which the recorder loads) also fails `lock_problems` on repair. The
  friendly notice is reached in production only on the intact path. A later card should decide whether
  the lock check may let a trusted edited rules file through.
- **`blocked` reaches the password prompt.** A link or folder at the rules path is refused by root's
  `_blocked` error after the password, not before it (the user-side pre-check covers the packaged
  default, not `blocked`).
- **Task 7's last-part lone-surrogate history gap** (residual 10).
- **Carried from V5b-fix, still open** (untouched by the brief): `default.toml`'s header still says it
  is copied once; HOOKS.md (about lines 147-165) describes the old `rules_problem` text; the trust
  check does not look at the folder above the file or at ACLs.
- **Spec housekeeping** (this card's own file): the design has two `Status:` lines (rev 3 still says
  "floating only"); §4.5 says "a few dictionary operations" for look-ups that are unmetered; `app.py`'s
  comment at line 301 still says the budget is for floating patterns only.

### Deferred minors

Not fixed; for the final review to triage. One line each, by task (the controller's ledger has the
full list and the reviewers' reasons).

- T1: the anchored `/etc/ssl/private/k*` case in `test_rules_matcher` proves nothing (0 <= 4); add `/etc/ssl/**` at 60 deep. The random compiled-pattern test has no sanity band on its True count.
- T2: the compare price is duplicated inline in the matcher's hot loop; no test that the meter resets when `WorkLimit` escapes `metered()`; `distinct_candidates` keeps 64 whole `Parsed` trees (4 would do).
- T2: `FLOAT_STEPS` = 45,000 sits at the edge: a reviewer's rerun measured 20.17 ms against "at most 20 ms"; 44,000 would give margin.
- T2: head and tail are charged together before the walk, not after each block (overshoot is still at most one block's walk).
- T3: identical command indexes are built once per clause (198 x on a shared list, about 110 ms at load, 9.5 MB); `_Simple.argv` is unused; `_entry_follows` and `_key_lookups` are no-op seams on the hot path; `glob_oracle` has an inconsistent docstring and no upper-case or wrapper programs.
- T4: no test of warn ordering under the limit, nor of a heavy block before R1 when R1 does not fire; `_note_unfinished` relies on `assert` (gone under `python -O`).
- T5: the isolation test asserts nothing about isolation; the chat id is unbounded in the log line (`app.py:255`); the warn-on-non-shell `none` path is uncovered; the `rec` fixture is copied a fifth time.
- T6: refusal and lint messages quote the case-folded pattern (`.SSH/**` shown as `.ssh/**`); the "anchor it" advice does not fix `/a/**/b/**` and is shown for already-anchored floating patterns (`/etc/**/ssl/**`, `~/**/.ssh/**`); no R1-named or `then`-clause case in the floating-exception test; `rules check` help does not mention the refusal or lint; `HEAVY_LIST` duplicates `HEAVY_PATTERNS`.
- T6b: no repo test runs the index oracle under a large meter; the R0 half of the heavy-list R0/R1 test runs no list rule; a comment in `test_rules_meter.py:371` says "spent meter" for `Meter(left=0)`.
- T7: the timing test cannot tell the guard from no guard (the structural test covers it); `test_a_step_with_a_long_word_builds_whatever_the_system_says` asserts only the kind.
- T8: the shlex space set is written three times in `clean.py`; no repo test pins `_shell_words` to `shlex.split` (shown equal on about 1.4M inputs in a scratch run); a dead `or 0` at `clean.py:186`.
- T9: the casefold test checks only `start`, not `end` or `unless`; the bullet strings are paraphrased against SPEC §5's.
- T10: a vacuous `meter.left == FLOAT_STEPS` assert (`test_rules_minimum.py:509`) and a duplicate parameter id in `[*ACCEPTED, *LOADING]`; no regression test that a slash pattern (`/**/*.pem`) never covers a family; `test_rules_minimum` imports `command` from `test_rules_cost`.
- T11: `problem.split("; ", 1)[0]` depends on the recorder wording's punctuation (`installer.py:168`); `rules_state` and `_not_exactly_ours` run up to 3 times in `install()`; tests patch `rules_owner_uid` rather than build a layout owner that differs from the file's.
- T12: the `rules check` label says "(file given)" for the active path itself and "(the active file)" via a link; `load` calls `named()` again after `choose_file`; no tests for a link to another file, a hard link to the active one, `unknown` not triggering the pre-check, or the Cursor line on a first install; `OLDER_DEFAULT` duplicates `SHIPPED`; `status()` spells its own state set instead of `RULES_WRITTEN | {...}`.

### final-verification and /code-review

Not run yet: the controller runs `/final-verification` and `/code-review high` on `main...HEAD` and
updates the status line and this section. The AGENTS.md check above is green at 84f8412 plus the
AGENTS.md and spec edits of ade67ce (the newest section has the results).

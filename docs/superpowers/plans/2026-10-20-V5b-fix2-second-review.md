# V5b-fix2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every rules file `rules check` accepts gets a bounded hook cost: by construction for
patterns that do not float, and by a per-hook meter for those that do. R1's minimum is judged by
pattern structure. Long words never break a hook. `init -g` never calls an untrusted rules file
intact.

**Architecture:**
- A depth-independent glob and a command-list index. A per-hook meter (`ContextVar`) charges
  floating patterns only, against one fixed budget priced from measured time. The hook runs in one
  pass, as today. R0 and R1 never touch the meter.
- D27 by a structural rule (`P` or `P*Q` per SPEC §5 family), with no automaton and no new module.
- A shared trust predicate that the installer uses.

**Tech Stack:** Python 3.12, standard library only (`contextvars`, `fnmatch`), pytest with xdist.

**Spec:** `docs/superpowers/specs/2026-10-20-V5b-fix2-second-review-design.md` (revision 3). The
intent is `docs/superpowers/intents/2026-10-20-V5b-fix2-second-review-intent.md`, and the brief is
`git show main:docs/briefs/V5b-fix2.md` (main 67efc8d). Executors read the spec. Section numbers
below (§4.2 …) are the spec's. This plan supersedes 1f33d06's on the brief's five cost points and
D27.

## Global Constraints

- **Git:** branch `ag-v5b-rules-file` only. Never push; never merge main.
- **Commit messages:** each starts `V5b-fix2: ` and ends with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Files that stay unedited:**
  - D27 and D28 text, DECISIONS, STATE, BOARD, learnings, HOOKS.md and SPEC §7/§8;
  - `agentfly/recorder/sessions.py`, `memory.py` and `default.toml`.
- **No new module in `agentfly/`.** New test files and test helpers are fine.
- **Unchanged values and interfaces:**
  - `MAX_WORK = 200` and every `WORK_*` weight;
  - `Rule(id, severity, message, check)`, with `check(action, session)`.
- **Pinned answers:**
  - the healthy `/health` answer is exactly `ok`, `offline_guard_count` and `last_hook_at`;
  - the demo replay answers stay byte-identical, also from the wheel;
  - the deny answer's bytes stay pinned (`tests/test_step_fields.py`).
- **Logging:** no request body, command text or file content in any log line.
- **Dependencies:** none new. Tests do not use the real rules file (the conftest redirects
  `rulefile.ACTIVE_RULES`).
- **Names in files:** call the project owner "the owner" in every file written.
- **Check command**, run before each commit that touches code:
  `uv run ruff check . && uv run ruff format --check . && env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -n auto --dist loadgroup`.
  While a task is in progress, run only that task's test files. The full line runs at the end of
  each Part.
- **Wallclock tests:** a test that names `perf_counter` or `monotonic` carries `@wallclock`
  (`tests/helpers.py`).
- **Spec values:**
  - `DIV = 256`; an `fnmatch` compare costs `1 + n * m // DIV`, a bare `*` compare and a middle-block
    start cost 1;
  - `FLOAT_STEPS` starts at 40,000 and is priced in Task 2 so that a whole budget of the slowest
    step costs at most 20 ms;
  - `LIMIT_ID = "rules limit"`; `/health` field `rules_limit`.

## Review Focus

These are inputs the spec implies but no acceptance criterion names. Each has a test in the task
that owns it.

1. **Parent and subagent.** A subagent whose block trigger is left unfinished leaves no trigger in
   the subagent's chat or its parent's, also after a restart (Task 5).
2. **Merged steps.** A shell action whose `preToolUse` and `beforeShellExecution` halves merge into
   one step, with one half denied by the rules limit, shows `rules limit` as the step's rule and
   carries its messages (Task 5).
3. **Unparseable commands.** A command the grammar cannot parse (an unbalanced quote) that names
   `.env` still marks the chat. Its `loose` words are walked once (Task 2).
4. **Non-ASCII words and paths.** A Read of a `file_path` holding a 300-character emoji name in a
   real workspace gets the same answer and step as a short name (Task 7).
5. **A recorder restart after a limit hit.** A fresh recorder start (`lifespan`) has no
   `rules_limit` in `/health`. Tests on the same worker that pin three keys must not see a hit from
   an earlier test (Task 5).

---

## Part 1: cost (§4)

### Task 1: A depth-independent matcher, `floating`, and the old `_glob` as an oracle

**Files:**
- Modify: `agentfly/recorder/rulefile.py`
  - § `_glob`;
  - § `Pattern` (gains block fields and `matches(path, name=None, home=None)`);
  - § `compile_pattern`;
  - § `Clause._path_hit` (calls `expanduser` once).
- Create: `tests/glob_oracle.py` (a verbatim copy of today's `_glob` and `Pattern.matches`, as
  `old_glob` and `old_matches`).
- Create: `tests/test_rules_matcher.py`.
- Update: `tests/test_rules_cost.py` and `tests/test_rulefile.py`, the two `counting` wrappers (see
  the update step below).

**Interfaces:**
- Produces:
  - `rulefile._glob(pattern: Sequence[str], segments: Sequence[str], blocks: _Blocks | None =
    None) -> bool`. It has the same answers and the same two-argument call as today (blocks are
    computed from `pattern` when None). The check order is pinned: head, then tail, then middle
    blocks (§4.1).
  - `rulefile.floating(pattern: Pattern) -> bool`: true when the pattern has a run of non-`**`
    parts with `**` on both sides; an unanchored pattern counts an implicit leading `**`.
  - `Pattern.matches(self, path: str, name: str | None = None, home: str | None = None) -> bool`.
    `home` is the folded home folder; when it is None, the method calls `os.path.expanduser("~")`
    as today.
  - `Pattern` keeps the fields `text`, `name_only`, `anchor` and `parts`. The block fields are
    private to `rulefile` (the builder names them).

- [ ] **Step 1: Write the oracle tests.** In `tests/test_rules_matcher.py`, using
  `random.Random(5)`:
  - `test_the_new_glob_answers_as_the_old_one_on_random_patterns`: 20,000 cases.
    - Patterns: 1 to 8 parts drawn from `**`, `*`, `?`, `a`, `b`, `a*`, `[ab]`, `[!a]`, `x?`.
    - Paths: 0 to 12 segments drawn from `a`, `b`, `ab`, `x1`, `c`.
    - Both anchored and unanchored.
    - Assert that the new `_glob` (anchored form) equals `old_glob` for every case.
  - `test_pattern_matches_answers_as_before_on_real_paths`: compare `compile_pattern(p).matches`
    with `old_matches` for each of these patterns:
    `~/.aws/config`, `~/.ssh/`, `/etc/ssl/private/*`, `cfg/x.txt`, `cfg/**/x.txt`,
    `**/a/**/b/**/x`, `/a/b/**/c/d/e/f`, `.env`, `*.PEM`.
    and each of these paths:
    `~/.aws/config`, `$HOME/.ssh/id`, `/etc/ssl/private/k`, `a/../cfg/x.txt`, `//cfg//x.txt`,
    `/Users/X/CFG/x.TXT`, `/a/b/q/c/d/e/f`, `x.pem`.
  - `test_floating_is_true_only_with_a_run_between_two_stars`, parametrized:
    - true: `.ssh/**`, `a/**/b`, `**/x/**`, `cfg/**/x.txt`, `src/**/gen.py`;
    - false: `~/.aws/config`, `~/.aws/**`, `~/.ssh/**`, `/etc/ssl/private/*`, `a/b`,
      `**/secret.txt`, `/a/**/b`, `.env`, `*/*/*/*/*/*/*/k0.pem`, `*/*/secret0/*.json`.
  - `test_a_pattern_that_is_not_floating_compares_each_part_once_whatever_the_depth`: patch
    `fnmatch.fnmatchcase` with a counter. For `/etc/ssl/private/k*`, unanchored `x/y.txt` and
    `*/*/secret0/*.json` on paths of 20 and 60 segments, assert that the count is at most the
    number of parts. A bare `*` calls nothing.
  - `test_the_tail_is_checked_before_a_middle_block`: for `p0/**/x0.txt` on a 60-segment path whose
    segments are all `p0` and whose last is `f.py`, `fnmatch.fnmatchcase` is called at most 2
    times.
- [ ] **Update these existing tests in this task** (their behaviour stays the same):
  - the `counting` wrapper of `tests/test_rules_cost.py::test_a_hook_at_the_limit_makes_no_more_pattern_tests_than_the_units_allow`
    gains `home: str | None = None` and passes it on;
  - the `counting` wrapper of `tests/test_rulefile.py::test_hundreds_of_slash_patterns_against_hundreds_of_words_do_one_test_per_pair`
    takes `(*args)`;
  - `tests/test_rulefile.py`'s exhaustive `_glob` comparison and
    `test_a_pattern_longer_than_the_path_tries_no_part` stay as they are and must pass, since the
    two-argument call is kept.
- [ ] **Step 2: Run them and see them fail.** Run
  `uv run pytest tests/test_rules_matcher.py -q`. The expected failure is a missing `floating`, and
  a counting test over the bound.
- [ ] **Step 3: Implement.**
  - Split the parts into blocks at `**` in `compile_pattern`.
  - Rewrite `_glob` (§4.1): an exact match when there is no `**`; otherwise a head at the start, a
    tail at the end, and the middle blocks placed greedily at their leftmost position. Keep the
    early "too short" refusal.
  - A bare `*` part skips `fnmatch`.
  - `Clause._path_hit` passes `home` computed once per `matches` call of the clause.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_matcher.py tests/test_rulefile.py tests/test_rules_cost.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: a glob whose cost does not grow with depth unless the
  pattern floats`.

### Task 2: The meter on floating patterns, distinct candidates, the budget's price

**Files:**
- Modify: `agentfly/recorder/rulefile.py` (a new "meter" section after "patterns"; the floating
  path of `_glob`/`Pattern.matches` charges; `Clause._words_hit` walks distinct candidates).
- Create: `tests/test_rules_meter.py`.

**Interfaces:**
- Consumes: Task 1's matcher and `floating`.
- Produces (all in `rulefile`):
  - `DIV: int = 256` and `FLOAT_STEPS: int` (start 40,000; priced in Step 5).
  - `class WorkLimit(Exception)`.
  - `@dataclass class Meter`, with fields `left: int` and `unfinished: list[str]` (default empty),
    and `note(rule_id: str) -> None`, which appends an id once.
  - `@contextmanager metered(meter: Meter) -> Iterator[Meter]` and `current_meter() -> Meter |
    None`.
  - `compare_cost(n: int, m: int) -> int`, which returns `1 + n * m // DIV`. (Not `test_…`: a test
    module that imports it would collect it.)
  - `distinct_candidates(parsed: Parsed) -> tuple[str, ...]`: memoized, in first-seen order, over
    `parsed.all_commands()`.
  - Only a floating pattern charges, by §4.2's prices: each middle-block start tried costs 1, each
    compare made costs `compare_cost(len(segment), len(part))`, a bare `*` compare costs 1. The
    steps go to a local counter and to the meter after each block. A charge that takes `left` below
    0 raises `WorkLimit`. With no meter set, nothing is charged or raised.

- [ ] **Step 1: Write the failing tests** in `tests/test_rules_meter.py`.
  - `test_a_compare_costs_one_step_below_256_and_more_above`:
    - `compare_cost(25, 10) == 1`
    - `compare_cost(64, 32) == 9`
    - `compare_cost(250, 200) == 196`
  - `test_patterns_that_do_not_float_never_charge`: inside `metered(Meter(left=1))`, on
    `tests.test_rules_cost.command(60)`, the default R1's `after`, a clause of the reviewer's
    `*/*/*/*/*/*/*/k0.pem` … `k7.pem`, one of `*/*/secret0/*.json` … `secret9/*.json`, and one of
    167 name patterns all run with no raise, and `left == 1` after.
  - `test_a_floating_pattern_charges_its_starts_and_compares`: inside a meter of 100, unanchored
    `x/**` on the path `p/q/x` leaves `left == 94` (3 starts, 3 compares).
  - `test_past_the_budget_every_floating_test_raises`: a meter of 5 and `x/**` on a 20-segment path
    raises `WorkLimit`; a second test of the same pattern on `x` raises too; a name pattern on the
    same meter does not.
  - `test_without_a_meter_nothing_is_charged_or_raised`: a floating clause on a 300-word command,
    60 deep, under no meter, raises nothing.
  - `test_a_partly_parsed_command_is_walked_once_per_distinct_candidate`: `cat 'x ; cat a b` (an
    unbalanced quote). Start with `distinct_candidates.cache_clear()`. Count `Pattern.matches` calls
    with a monkeypatch: one per distinct candidate per pattern.
  - `test_an_unparseable_command_naming_env_still_marks` (Review Focus 3): the default R1's `after`
    matches `cat 'x .env`.
- [ ] **Update this existing test in this task:**
  `tests/test_rules_cost.py::test_a_word_is_worked_out_once_however_many_clauses_look_at_it`.
  Clauses now read the memoized distinct tuple, so `_candidates` is called once per word:
  - assert `_candidates` misses `== words + 1`;
  - assert `distinct_candidates.cache_info().hits >= clauses - 1`, in place of the `_candidates`
    hit count;
  - the `_folded_name` assertion stays.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_rules_meter.py -q`.
- [ ] **Step 3: Implement** in `rulefile`:
  - the `ContextVar` for the meter;
  - `_words_hit` iterates `distinct_candidates(parsed)`;
  - `Pattern.matches` still calls `_folded_segments` once per pattern: only `expanduser` is hoisted.
    `tests/test_rulefile.py::test_one_path_is_resolved_once_however_many_patterns_look_at_it`
    counts 49 memo hits and must pass unchanged;
  - the floating path of the matcher charges as above; a pattern that is not floating takes a path
    with no charge call at all.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_meter.py tests/test_rules_matcher.py tests/test_rulefile.py tests/test_rules_cost.py -q`.
  Expected: all pass.
- [ ] **Step 5: Price the budget.** A scratch script (not committed) measures µs per step, best of
  three, idle, with an unlimited meter, on 300 words at 60 deep under:
  - 5 × `d*/d*/d*/zN/**` with words that end `…/d1/d2/d3/z0/f.py` (the walk runs);
  - 5 × `p{i}/**/x{i}.txt` with matching tails (literal middle parts);
  - one `*a*b*c/**/z` on segments of 255 characters (long `fnmatch` compares).

  Set `FLOAT_STEPS` to the largest multiple of 1,000 whose cost at the slowest of the three is at
  most 20 ms. If a long compare costs much over its price per step (`compare_cost` steps at the
  short-compare rate), re-measure `DIV` and say so; keep 256 otherwise. Record the numbers for the
  report.
- [ ] **Step 6: Commit.** Message: `V5b-fix2: a per-hook meter on floating patterns, priced from
  measured time`.

### Task 3: The command-list index

**Files:**
- Modify: `agentfly/recorder/rulefile.py`: § `Clause` (an index built in `__post_init__`, and
  `_command_hit`).
- Test: `tests/test_rules_meter.py` (add), and `tests/test_rules_cost.py` (the existing entry tests
  must stay green).

**Interfaces:**
- Produces: `Clause.command` keeps its type, `tuple[tuple[str, ...], ...]`. The index is a private
  field built from it, with `field(hash=False, compare=False, repr=False)` (`Clause` is hashed by an
  `lru_cache`). Answers are identical. Command lists are not metered (brief).
- The builder adds one seam a test can count: the per-entry check of the remaining extras (today's
  `_last_positions` test) as a module-level function, and index look-ups through it or a counter
  beside it.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_index_answers_as_the_old_loop`: a verbatim copy of today's `_command_hit` goes into
    `tests/glob_oracle.py` as `old_command_hit`. For 3,000 seeded random cases (lists of 1 to 30
    entries of 1 to 3 words from `cat a b c npm publish x`, commands of 1 to 6 simple commands
    joined by `;`), the answers are equal.
  - `test_a_command_naming_200_programs_looks_up_the_smaller_side`: a list `p0 x` … `p199 x`, and
    a command `p0 p1 … p199 y`. At most `200 + 1` look-ups and entry checks, and the answer is no
    match.
  - `test_198_rules_of_200_cat_entries_on_150_cat_commands_check_few_entries`: the shape
    `command_list_on_one_program` of `tests/test_rules_cost.py`, on 150 `;`-joined `cat zN y`
    commands. The `zN` words match no entry, so the answer is allow, and the counted entry checks
    are 0.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_rules_meter.py -q`.
- [ ] **Step 3: Implement the index** of §4.7, built in `Clause.__post_init__` (with
  `object.__setattr__`, since `Clause` is frozen), not in `_clause`: `tests/test_rulefile.py` (about
  line 506) and `tests/test_rules_cost.py` (about line 278) build `Clause` directly.
  - the map is program → first extra word (or `None`) → entries;
  - per simple command and per listed program at its first position, iterate the smaller of that
    program's keys and the distinct words after it.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_meter.py tests/test_rules_cost.py tests/test_npm_publish_entry.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: command lists are looked up by program and first
  word`.

### Task 4: The engine. One pass, the limit rules, unfinished rules

**Files:**
- Modify: `agentfly/recorder/rules.py`: § `mark`, § `winning_rule`, § `find_rule`, and a
  `one_hook` helper.
- Create: `tests/test_rules_limit.py`.
- Modify: `tests/test_rules_cost.py::match_rule(i, body)` gains `severity: str = "highlight"`, so
  the existing callers do not change.

**Interfaces:**
- Consumes: Task 2's `Meter`, `metered`, `current_meter`, `WorkLimit` and `FLOAT_STEPS`.
- Produces (in `rules`):
  - `LIMIT_ID: str = "rules limit"` and `LIMIT_MESSAGE: str` (§4.3's wording).
  - `LIMIT_RULE: Rule` (severity `block`) and `LIMIT_WARN_RULE: Rule` (severity `warn`), with the
    same id and message, and the check `_never_fires(action, session) -> False`.
  - `@contextmanager one_hook() -> Iterator[rulefile.Meter]`: `metered(Meter(left=FLOAT_STEPS))`,
    reading `rulefile.FLOAT_STEPS` at each call, so a test can monkeypatch a small budget.
  - `find_rule(LIMIT_ID)` returns `LIMIT_RULE`. Neither limit rule is ever in `RuleSet.rules`.
  - With no meter (pure tests, `rules test`), `mark` and `winning_rule` behave exactly as today.
    `cli/rules_test.py` does not change.

`mark`, for each `after_then` rule other than R1 whose id the chat does not hold yet:
- `WorkLimit` while its `after` runs: `meter.note(rule.id)`, and the trigger is **not** recorded,
  for every severity (§4.3).
- R1's mark is computed as today.

`winning_rule`, one pass in file order ("unfinished" means the id is in `meter.unfinished` already,
from `mark`, or `WorkLimit` is raised by its check, which then notes it):
```
limit_block = False; best = None
for rule in rules:
    if limit_block and rule.id != MARK_RULE: continue    # only R1 can still change a deny
    outcome = fired | not fired | unfinished
    if rule.severity == "block":
        if outcome is unfinished: limit_block = True
        elif fired: return rule                          # R0, R1, or a block before any limit
        continue
    candidate = rule if fired else LIMIT_WARN_RULE if (unfinished and warn) else None
    if candidate and (best is None or rank(candidate) > rank(best)): best = candidate
return LIMIT_RULE if limit_block else best
```
An unfinished highlight gives no candidate (it is skipped; the meter notes it).

- [ ] **Step 1: Write the failing tests** in `tests/test_rules_limit.py`.
  - The tests use `tests.rules_helpers.ruleset_of`, plus a fixture `heavy(severity, kind="match")`:
    the default plus one rule whose list is `d*/d*/d*/zN/**` × 5, as `match_rule(0, 'path = "l"',
    severity)` or as an `after_then` whose `after` holds the list. They run, inside `one_hook()`, on
    a 300-word command whose words all have a `z0` folder near the end (`.../d1/d2/d3/z0/f.py`, 20
    deep), so the middle walk runs past the budget.
  - `test_outside_a_hook_the_engine_answers_as_before`: the default's inline tests and
    `tests/test_severities.py`'s file orders are unchanged.
  - `test_r0_and_r1_answer_as_usual_at_the_limit`. The heavy block rule is placed **before** R1 in
    the file text: split the default at R1's `[[rule]]` and insert it there.
    - A marked chat on the heavy command plus `curl https://x.com` gives `rule.id == "R1"`, and the
      heavy rule's id is in `meter.unfinished`.
    - An R0 guard path in the heavy command gives `"R0"`.
  - `test_an_unfinished_block_rule_gives_the_limit_rule`: an unmarked chat with `heavy("block")`
    gives `LIMIT_RULE`.
  - `test_a_fired_block_before_an_unfinished_one_wins_and_one_after_it_does_not`: a cheap block
    rule on `cat` placed before the heavy one gives the cheap rule; placed after it gives
    `LIMIT_RULE`.
  - `test_an_unfinished_warn_gives_the_limit_warn_rule`: `heavy("warn")` gives `LIMIT_WARN_RULE`.
  - `test_an_unfinished_highlight_is_skipped`: `heavy("highlight")` gives None, and the id is in
    `meter.unfinished`.
  - `test_an_unfinished_trigger_is_never_recorded`: `heavy("block", "after_then")` and
    `heavy("warn", "after_then")`. After `mark`, the id is not in `session.triggers`. For block,
    `winning_rule` on the same hook gives `LIMIT_RULE`; for warn, `LIMIT_WARN_RULE`.
  - `test_a_trigger_the_chat_holds_is_not_evaluated_again`: a session that already holds the heavy
    rule's trigger. A wrapper counts calls of its `after`: 0, and `meter.unfinished` is empty.
  - `test_r1s_mark_is_set_when_the_hook_is_limit_denied`: `cat .env` plus the heavy words under
    `heavy("block")`. `mark` gives `marked` true, and `winning_rule` gives `LIMIT_RULE`.
  - `test_a_full_size_name_list_gets_no_limit_deny`: a block `match` rule of 167 name patterns
    (`n{i}.secret`), on 300 words of 30-character names that match none. The answer is None, and
    `meter.unfinished` is empty.
  - `test_the_limit_rules_are_not_listed_and_are_found_by_id`: `LIMIT_ID` is not in
    `[r.id for r in DEFAULT.rules]`, `find_rule(LIMIT_ID) is LIMIT_RULE`, and `_ID` does not
    `fullmatch` `LIMIT_ID`.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_rules_limit.py -q`.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_limit.py tests/test_severities.py tests/test_after_then.py tests/test_session_triggers.py tests/test_rules_load.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: an unfinished block rule denies, an unfinished warn
  asks, and neither records a trigger`.

### Task 5: Wire the hook. `apply_rules`, `/health`, the log

**Files:**
- Modify:
  - `agentfly/recorder/app.py`: § `apply_rules`, § `health`, and § `lifespan`, which resets the
    new counter where it resets `_last_hook_at`. Plus the module-level counter itself.
- Test:
  - add to `tests/test_rules_limit.py`;
  - `tests/test_app.py`, whose health tests must stay green.

**Interfaces:**
- Consumes: Task 4's `one_hook`, `LIMIT_ID`, `LIMIT_RULE` and `LIMIT_MESSAGE`.
- Produces: `/health` gains `"rules_limit": str` only after a hit, at most
  `rulefile.MAX_PROBLEM_CHARS` long, with the format of §4.4. Its log line is a `logger.warning`
  holding the chat id, the unfinished ids, and the answer the limit gave (`deny`, `ask` or `none`).

`apply_rules` keeps today's order. `store.apply_mark` and `decide` run inside `with one_hook() as
meter:`; after them, a non-empty `meter.unfinished` is logged and counted. The step record and the
enqueues are unchanged.

- [ ] **Step 1: Write the failing tests**, through `tests.recorder_harness.Recorder` and
  `fastapi.testclient`.
  - `test_the_recorder_denies_with_the_limit_message_in_both_fields`: with `heavy("block")`,
    `rec.run` gives `permission == "deny"`, a `user_message` of `LIMIT_MESSAGE`, and an
    `agent_message` of `LIMIT_MESSAGE + BLOCK_TAIL`.
  - `test_a_padded_shell_command_with_an_unfinished_warn_asks`: with `heavy("warn")`, `rec.run`
    gives `permission == "ask"` with `LIMIT_MESSAGE` and `LIMIT_MESSAGE + SKIP_TAIL`. With
    `rulefile.FLOAT_STEPS` monkeypatched to 10 (one path cannot spend the real budget) and the heavy
    warn rule on `read`, a Read of a 20-deep `…/d1/d2/d3/z0/f.py` gives `{"permission":"allow"}`,
    and its step has `rule_id == "rules limit"` and the verdict `warned`.
  - `test_a_limit_deny_records_no_trigger_and_a_restart_judges_as_before` (Review Focus 1): with
    `heavy("block", "after_then")` whose `then` is `curl`, a subagent linked to a parent by
    `parent_tool_call_id` (as `tests/test_subagent_mark.py` does) runs the heavy command: deny with
    the limit message. Neither chat's `triggers` holds the id. After `rec.restart()`, `curl
    https://x.com` in each chat is allowed.
  - `test_health_says_rules_limit_only_after_a_hit`:
    - before the hit, the keys are exactly `{"ok", "offline_guard_count", "last_hook_at"}`;
    - after it, `rules_limit` starts with `"rules limit reached by 1 hook(s)"` and names the rule
      id;
    - the client is `with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as client:`,
      since a bare `TestClient(app)` does not run `lifespan`;
    - `lifespan` activates the rules it loads, so `heavy(...)` is activated after the client is
      entered;
    - the line is at most 400 characters.
  - `test_the_log_line_names_the_chat_and_rules_and_no_command_text`: with `caplog`, one warning
    naming the chat, the rule id and `deny`. The marker word `zz-secret-marker`, planted in the
    command, is absent.
  - `test_a_merged_pair_with_a_limit_half_shows_the_limit_rule` (Review Focus 2): send
    `preToolUse` Shell, then `beforeShellExecution` with one `tool_use_id`, as
    `tests/test_step_merge.py` does, under `heavy("block")`. The single step's `rule_id ==
    "rules limit"`, and its messages are the limit's.
  - `test_a_fresh_start_forgets_the_limit_hit` (Review Focus 5): after a hit inside one `with
    TestClient(app_module.app, base_url="http://127.0.0.1:8787")` block, a second such block, which
    runs `lifespan` again, answers `/health` with exactly the three keys.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_rules_limit.py -q`.
- [ ] **Step 3: Implement** the hook context, the counter and its `lifespan` reset, the log line
  and the `/health` field.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_limit.py tests/test_app.py tests/test_step_fields.py tests/test_step_merge.py tests/test_history_mark.py tests/test_subagent_mark.py tests/test_rules_cli.py tests/test_rules_api.py tests/test_after_then.py -q`.
  Expected: all pass, and the deny bytes are unchanged.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: the recorder meters each hook and reports the rules
  limit`.

### Task 6: `path_except` refuses floating patterns, the lint, the counting tests, the measurement

**Files:**
- Modify:
  - `agentfly/recorder/rulefile.py`: § `_parse` / § `_clause` (the `path_except` refusal and the
    lint lines);
  - `tests/test_rules_cost.py`: new shapes and tests, docstrings updated so that the "holds by
    construction" tests say what they bound (tests, not time).
- Test: `tests/test_rules_cost.py`, `tests/test_rules_cli.py`, `tests/test_rulefile.py`.

**Interfaces:**
- Consumes: `floating` (Task 1), the meter (Task 2), the engine and wiring (Tasks 4 and 5).
- Produces:
  - an error for a floating `path_except` pattern in any rule, in §4.6's wording, starting
    `rule <id>: `;
  - a lint line for each floating pattern in a rule's `path`, in §4.4's wording, starting
    `rule <id>: `.

  The default carries no lint (`test_the_packaged_default_meets_the_minimum` still asserts
  `lint == ()`).

- [ ] **Step 1: Add the tests.**
  - In `tests/test_rulefile.py`, `test_a_floating_exception_is_refused_in_any_rule`, parametrized
    over `.ssh/**`, `a/**/b` and `**/x/**` in a `match` rule's `path_except`: refused, naming the
    rule. With `~/.ssh/**` or `*.bak` it loads.
  - In `tests/test_rules_cost.py`, the new shape `"reviewer's floating block rule"`: 5 ×
    `d*/d*/d*/zN/**` in a block `match` rule.
  - `test_a_hook_stops_at_the_budget_and_the_count_proves_it`, under that shape at 300 words and 20
    deep, through `Recorder.run`:
    - patch `fnmatch.fnmatchcase` with a counter, and count bare-`*` parts and middle-block starts
      through the matcher's seam;
    - the answer is the limit deny;
    - the counted steps are at most `FLOAT_STEPS` plus one block's walk (the path's segments times
      the block's parts);
    - with the meter's charge monkeypatched to a no-op (the bound removed), the count is over
      `FLOAT_STEPS`.
  - `test_a_file_without_floating_patterns_is_never_metered`. It is parametrized over the `FULL`
    shapes that are not floating, plus `/opt/p{i}/x{i}.txt`, unanchored `p{i}/x{i}.txt`, and the
    reviewer's `*/*/*/*/*/*/*/kN.pem` × 8 and `*/*/secretN/*.json` × 10:
    - included: "many rules with one name pattern", "one long list of names", "slash patterns
      with one **" (anchored, head and tail) and "long slash patterns" (tail only);
    - excluded: "floating slash patterns" and "floating patterns with several **". A test asserts
      that `floating` is true for every pattern of those two shapes.

    At 300 words, at 20 and 60 deep, and on a partly parsed form of `command()` (append ` 'x`),
    running `mark` and `winning_rule` inside `rules.one_hook()`:
    - no rule is left unfinished and the meter's `left` is unchanged;
    - the counted tests are at most `MAX_WORK * C`, with `C = len(distinct_candidates(...))`.
  - `test_rules_check_warns_about_floating_patterns`: `rules check` exits 0 and prints the `warn:`
    line for a file with one floating `path` pattern.
- [ ] **Step 2: Run them, implement the refusal and the lint, run again.** Run
  `uv run pytest tests/test_rules_cost.py tests/test_rules_cli.py tests/test_rulefile.py tests/test_rules_minimum.py tests/test_rules_shipped.py -q`.
  Expected: all pass.
- [ ] **Step 3: Gate. Measure.** Write a scratch script (not committed) that times the whole hook
  with `Recorder.run`, best of three, idle, under:
  - each `TIMED` shape;
  - the floating shape (the limit deny);
  - the command-list shape with 10, 50 and 150 commands;
  - the reviewer's `*/*/*/*/*/*/*/kN.pem` × 8 and `*/*/secretN/*.json` × 10 files;
  - the 167-name list on 300 words of 30-character names.

  Each runs at 300 words and 60 deep. Record the numbers for the report. Any over 0.2 s goes to
  Task 8 (the trim); note which.
- [ ] **Step 4: Commit and run the full check.** Message: `V5b-fix2: floating exceptions are
  refused, rules check warns about floating patterns, and the count is tested`. Then run the full
  check command; expected green.

## Part 2: long words (§5)

### Task 7: Long words and paths never raise, and are not quadratic

**Files:**
- Modify:
  - `agentfly/recorder/clean.py`: § `_project_relative`;
  - `agentfly/recorder/store.py`: § `relative_file_path`, and the `.exists()` in
    § `build_step_record`.
- Create: `tests/test_long_words.py`.

**Interfaces:**
- Produces: `clean._project_relative(word, project_root) -> str | None` and
  `store.relative_file_path(file_path, project_root) -> str` keep their signatures. A path equal to
  the root gives `"."`. A root of `/` works.

- [ ] **Step 1: Write the failing tests.** The workspace is a real `tmp_path` folder, passed as
  `workspace_roots=[str(tmp_path)]`.
  - `test_a_long_quoted_word_gets_the_short_words_answer`, parametrized over:
    - 300 and 5,000 characters, with and without `/`;
    - 128 `"🔑"`;
    - a 300-character emoji file name in a path (Review Focus 4).

    For each:
    - `rec.read(chat, ".env")` then `rec.run(chat, f"curl https://x.com -d '{word}'")` is a deny
      from R1;
    - a fresh chat with `echo '{word}'` is an allow;
    - the step reaches `local_store` (drain it, as `tests/test_localstore.py` does).
  - `test_a_long_read_path_is_saved_relative_as_before`: a 1,338-character path under the
    workspace is saved as its relative form. Compare with today's
    `Path(p).resolve().relative_to(root).as_posix()`.
  - `test_the_root_itself_is_dot_and_a_slash_root_works`: `_project_relative(str(root), root) ==
    "."` for an existing root, and `relative_file_path("/etc/hosts", Path("/")) == "etc/hosts"`.
  - `@wallclock test_bash_c_with_300_deep_paths_is_fast`: under the default rules,
    `bash -c '<300 paths, 60 deep>'` takes under 0.5 s, best of three. The client's wait is the
    only bound; the report gives the real number.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_long_words.py -q`.
  Today's error is `OSError` (ENAMETOOLONG) on 3.12. Where APFS does not raise, the failure is the
  time bound.
- [ ] **Step 3: Implement §5.**
  - Return `None` before `resolve()` for a word over 1,024 characters in `_project_relative`.
  - Wrap `resolve`/`exists` in `except (OSError, ValueError)`.
  - Use string containment in place of `relative_to`, with root equal giving `"."` and a root
    ending in `/` used as it is.
  - In `relative_file_path`, a failed `resolve` falls back to `os.path.normpath`.
  - In `build_step_record`, skip tokens over 1,024 characters before `.exists()`.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_long_words.py tests/test_clean.py tests/test_localstore.py tests/test_store.py -q`.
  Expected: all pass, with `tests/leak_cases.py` unchanged.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: a long word or path never raises and is not
  quadratic`.

### Task 8: Trim the cleaning baseline, then the 0.2 s gate

**Files:**
- Modify: `agentfly/recorder/clean.py` (§ `_split_keeping_seps`, § `shlex` use, the remaining
  `resolve` calls), only where a profile shows the time.
- Test: `tests/test_clean.py`, `tests/leak_cases.py` (unchanged, and they must stay green).

- [ ] **Step 1: Profile.** Run `python -m cProfile -s cumtime` on a scratch script running the
  whole hook (`Recorder.run`) on Task 7's `bash -c` command and on `tests.test_rules_cost.command(60)`
  under the default. Note the top five costs. (R1 runs twice per shell hook today, in `mark` and in
  `build_step_record`; if it is in the top five, reusing `mark`'s answer where the chat was not yet
  marked is a candidate.)
- [ ] **Step 2: Trim.** Do only changes that keep every `clean.py` output byte-identical. Check with
  a scratch comparison: 2,000 seeded random commands, using `tests/leak_cases.py` words plus
  `tests/cases.py` commands, give old and new `clean_command` outputs that are equal.
- [ ] **Step 3: Pass the tests.** Run `uv run pytest tests/test_clean.py tests/test_leak*.py -q`.
  Expected: all pass.
- [ ] **Step 4: Gate.** Re-run Task 6's measurement script and Task 7's `bash -c`. Each must be under
  0.2 s at 60 deep. **If any stays over 0.2 s, stop and ask the lead with the numbers.** Do not
  change `MAX_WORK`, `FLOAT_STEPS`'s 20 ms price, or `DIV`.
- [ ] **Step 5: Commit and run the full check.** Message: `V5b-fix2: the cleaner's baseline is
  trimmed (outputs byte-identical)`. Then run the full check command; expected green.

## Part 3: D27 by structure (§6)

### Task 9: One table for "secret"

**Files:**
- Modify: `agentfly/recorder/rulefile.py`: § the R1 minimum (`Family`, `SECRET_FAMILIES`,
  `EXEMPTIONS`, `spec_secret`).
- Test: `tests/test_rules_minimum.py` (add).

**Interfaces:**
- Produces (in `rulefile`):
  - `Family`, a `@dataclass(frozen=True)` with fields `bullet: str` (SPEC §5's words), `start: str`,
    `end: str`, `exact: bool` and `unless: tuple[str, ...]`.
  - `SECRET_FAMILIES: tuple[Family, ...]`: the six families of §6.1, in that order.
  - `spec_secret(name: str) -> bool`, reading the table.
  - `EXEMPTIONS`, derived from the table, with the same value as today.

- [ ] **Keep, in this task:** the markers `the minimum for R1 (D27)` and `---- files` in
  `rulefile.py` (`test_the_minimum_does_not_read_default_toml` slices between them).
- [ ] **Step 1: Write the test.** `test_spec_secret_from_the_table_answers_as_before`: a copy of
  today's `spec_secret` goes into the test file. The two agree on `SECRET_NAMES`, on every name of
  today's `_secret_names` grid built without the filter, and on 20,000 seeded random names drawn
  from `.env`, `.`, `pem`, `key`, `id_rsa`, `credentials`, `pub`, `example` and random letters.
- [ ] **Step 2: Implement, and pass.** Run `uv run pytest tests/test_rules_minimum.py -q`.
- [ ] **Step 3: Commit.** Message: `V5b-fix2: SPEC section 5's secret names come from one table`.

### Task 10: The structural rule, R1's folder patterns, SPEC §5

**Files:**
- Modify:
  - `agentfly/recorder/rulefile.py`: § `_minimum_problems`; `_unmarked` and the sample grid leave
    the module;
  - `SPEC.md` §5: D27's paragraph only (§6.4).
- Create: `tests/r1_grid.py`: the grid moved from `rulefile` (`_FAMILIES`, `_TAILS`, `_SWEEP`,
  `_LITERALS`, `_FOLDERS`, `SECRET_NAMES`, and `unmarked(after: Clause) -> tuple[str, ...]`, today's
  `_unmarked` without the cache).
- Test:
  - `tests/test_rules_minimum.py`: new tests, and the changes listed below;
  - `tests/test_rules_cost.py`: `test_the_work_of_a_file_that_is_refused_is_not_also_judged_by_the_r1_grid`
    is renamed "…by the R1 check" and reads the new cache.

**Interfaces:**
- Consumes: Task 9's `Family` and `SECRET_FAMILIES`, Task 1's `floating`.
- Produces (in `rulefile`):
  - `covers(text: str, family: Family) -> bool`: the rule of §6.2 on one case-folded name pattern.
  - `_coverage_problems(after: Clause) -> tuple[str, ...]`, `lru_cache(16)`: one error per family
    with no covering pattern in `after.path`, and one per floating pattern in `after.path`, in §6.2's
    and §6.3's wording, each starting `rule R1: `.
  - `_minimum_problems` keeps its other checks (kind, severity, events, the exception shape, the
    `then`) and calls `_coverage_problems` in place of `_unmarked`.

- [ ] **Step 1: Write the failing tests** in `tests/test_rules_minimum.py`.
  - `test_covers_follows_the_shape_rule`, parametrized over §6.2's examples, true and false, per
    family.
  - `test_the_brief_dodge_files_are_refused_naming_r1`: the three files of the brief, through
    `rules check`. Each exits 1, and stderr has `rule R1:` with the family's bullet.
  - `test_the_brief_loading_list_loads`: the default, a file that only adds names, `.env*` in place
    of `.env` and `.env.*`, `.*` in place of both, `*pem` in place of `*.pem`, and the default plus
    `~/.ssh/**`. Each has no error.
  - `test_brute_force_finds_no_accepted_r1_that_misses_a_secret_name` (the brief's test), with
    `random.Random(27)`:
    - per family, its covering shapes from §6.2's examples; and a pool of near misses: `.env.?*`,
      `.env.[!s]*`, `.env.s`, `?*.pem`, `*.pe?`, `prod.pem`, `id_rsa`, `id_rsa.*`, `credentials`,
      `credentials?*`, `.env*.env`, `*.*`, `x*`;
    - 1,000 R1 name lists. Each starts with one covering shape per family, chosen at random; then 0
      to 2 of them are swapped for a random near miss, and 0 to 3 near misses are added. Each list
      gets the default's exceptions, or `.env.local*.example` and `id_rsa_work*.pub`, or none;
    - names: for each family, its start, then every string of up to 2 characters over `.`, `e`,
      `s`, `x`, ` ` and `_`, then its end, and the same with each `unless` ending; only those
      `spec_secret` counts;
    - for every list that `load_bytes` accepts, R1's `after` marks every name as a read, and 20
      seeded names per list as the shell word `cat '<name>'`;
    - at least 100 lists are accepted and at least 100 refused.
  - `test_r1s_floating_folder_patterns_are_refused`: `.ssh/**`, `a/**/b` and `**/x/**` added to
    R1's names are refused with §6.3's text. `~/.aws/config`, `~/.aws/**`, `~/.ssh/**` and
    `/etc/ssl/private/*` load.
  - `test_the_grid_finds_nothing_unmarked_in_any_accepted_file`: for every `ACCEPTED` entry and the
    brief's loading list, `r1_grid.unmarked(after) == ()`.
- [ ] **Change these existing tests in this task:**
  - `test_the_packaged_default_meets_the_minimum` and
    `test_the_names_the_check_judges_by_are_the_ones_spec_section_5_counts` read
    `tests.r1_grid.SECRET_NAMES`;
  - `test_the_error_names_a_name_that_is_left_unmarked` becomes `test_the_error_names_the_bullet`:
    a list without `credentials*` gives one error naming the `credentials` bullet; `*.example` as an
    exception gives the exception-shape error;
  - `test_a_literal_exemption_is_refused_for_its_shape_and_for_what_it_hides` becomes
    `…_for_its_shape`: the shape error only;
  - the per-clause cache test (about lines 262-265) reads
    `rulefile._coverage_problems.cache_info().misses == 1`;
  - every `WEAKENED` entry stays refused and every `ACCEPTED` entry loads, unchanged.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_rules_minimum.py -q`.
- [ ] **Step 3: Implement** §6.2 and §6.3, move the grid to `tests/r1_grid.py`, and edit SPEC §5
  (§6.4: the structural sentence in place of "Judged on those names, …", and the floating-pattern
  sentence).
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_minimum.py tests/test_rulefile.py tests/test_rules_load.py tests/test_rules_cli.py tests/test_rules_trust.py tests/test_rules_cost.py tests/test_rules_shipped.py tests/test_doctor.py -q`.
  Expected: all pass.
- [ ] **Step 5: Measure the load time.** A scratch script times `load_bytes` of the default, best
  of five. Record the number for the report.
- [ ] **Step 6: Commit and run the full check.** Message: `V5b-fix2: R1's minimum is judged by
  pattern structure (D27)`. Then run the full check command; expected green.

## Part 4: install (§7)

### Task 11: Shared trust test; `untrusted`, `unknown`, and the notice

**Files:**
- Modify:
  - `agentfly/recorder/rulefile.py`: § `_trusted_bytes` (split out the helper);
  - `agentfly/install/installer.py`: § `rules_state`, § `status`, § `install` and § `_write_rules`;
  - `agentfly/cli/init.py`: § `_as_user`.
- Test:
  - `tests/test_install_rules.py` (add, and change
    `test_an_intact_install_with_an_edit_says_only_that_nothing_changed`);
  - `tests/test_rules_trust.py` (must stay green).

**Interfaces:**
- Produces:
  - `rulefile.trust_problem(path: Path, uid: int) -> str | None`: the recorder's trust test with no
    read, the same wording.
  - `installer.rules_owner_uid(layout: Layout) -> int`: `layout.owner[0]`, or `os.getuid()` when the
    owner is None.
  - `installer.rules_state(layout, wanted) -> str`: one of `missing`, `current`, `untrusted`,
    `older`, `edited`, `unknown` and `blocked`.
    - `untrusted` is the current bytes in a file that is not exactly a regular file owned by
      `rules_owner_uid`, mode `0o644`.
    - `unknown` is a `PermissionError` on open when not running as root. As root, an `OSError`
      gives `edited`, as today.
  - `installer.rules_notice(layout: Layout, wanted: str | None) -> str | None`:
    - None unless the state is `edited`;
    - for a trusted file, the existing kept text;
    - for an untrusted one, the §7 text, with the reason from `trust_problem` and
      `rulefile.DEFAULT_IN_FORCE`.

- [ ] **Step 1: Write the failing tests** in `tests/test_install_rules.py`, with the existing
  `layout` and `archive` fixtures.
  - `test_current_bytes_that_are_not_exactly_ours_are_rewritten`, parametrized over mode `0o664`,
    mode `0o600`, and a wrong owner (monkeypatch `installer.rules_owner_uid` to
    `os.getuid() + 1`). After `do_install`:
    - `fingerprint` changed (a new inode);
    - the bytes are the default;
    - a message names the reason and asks for `agentfly stop`, `agentfly start`.
  - `test_an_edited_untrusted_file_keeps_its_bytes_and_mode_with_a_notice`: an edited file at mode
    `0o664`. After `do_install`, the bytes and mode are unchanged, `changed` is false, and the
    messages are the pinned line plus the notice containing `DEFAULT_IN_FORCE`.
  - `test_an_intact_install_with_an_edit_says_only_that_nothing_changed` is renamed
    `…prints_the_kept_notice_after_the_pinned_line`. It now expects
    `["already installed and intact; nothing changed", "kept your edited rules file …"]`.
  - `test_init_as_the_user_prints_the_notice_without_a_password`: call `init._as_user` with
    `installer.status` returning `set()`, and `capsys`. Stdout has the pinned line, then the
    notice. `elevate.run_elevated` is not called (monkeypatch it to fail).
  - `test_an_unreadable_file_is_unknown_and_counts_as_work_for_root`: `chmod 0o000` (skip as root).
    `rules_state` is `unknown`, and `"rules"` is in `status`.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_install_rules.py -q`.
- [ ] **Step 3: Implement.**
  - `_trusted_bytes` and `trust_problem` share one private `_trust_fd(path, uid) -> int` that opens
    and checks, with the caller closing.
  - The installer's comment states §7's principle.
  - `install()` writes for `missing`, `older` and `untrusted`, and its messages use `rules_notice`
    in both the intact and the changed returns.
  - `_as_user` prints the notice after the pinned line.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_install_rules.py tests/test_rules_trust.py tests/test_install_cli.py tests/test_doctor.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: init -g rewrites only known bytes, and never calls an
  untrusted rules file intact`.

### Task 12: `rules check <link to the active file>`, and `init.py`'s two small gaps

**Files:**
- Modify: `agentfly/cli/rules_check.py` (§ `load`). `agentfly/cli/init.py` changes only if each gap
  takes a few lines.
- Test: `tests/test_rules_trust.py` (add).

- [ ] **Step 1: Write the failing test.** `test_rules_check_through_a_link_to_the_active_file_judges_the_active_file`.
  A clean active file and a symbolic link to it in `tmp_path`. `rules check LINK` exits 0 and
  prints the active path. With the active file group-writable, it exits 1, and the message names
  the active path and "written by group or others", not "symbolic link".
- [ ] **Step 2: Implement.** In `load`, when `is_active_path(path)`, read `rulefile.ACTIVE_RULES` with
  `load_active_file` and name `ACTIVE_RULES` in the messages.
- [ ] **Step 3: Look at the two gaps.**
  - For "a bad packaged default is caught only after the password": can `_as_user` call
    `installer._packaged_default(current)` before `ensure_confirmed`, in about three lines?
  - For "a rules-only refresh says Quit and reopen Cursor": can `_as_root` print the Cursor line only
    when something other than the rules changed?

  Do each one that fits, with a test in `tests/test_install_cli.py`. Otherwise write one line on it
  for the report.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_trust.py tests/test_install_cli.py tests/test_rules_cli.py -q`.
- [ ] **Step 5: Commit and run the full check.** Message: `V5b-fix2: rules check through a link
  judges the active file`. Then run the full check command; expected green.

## Close the card

### Task 13: AGENTS.md, measurements, verification, report

**Files:**
- Modify: `AGENTS.md`. Only the "Testing" section changes:
  - lines for `tests/test_rules_matcher.py`, `tests/test_rules_meter.py`, `tests/test_rules_limit.py`
    and `tests/test_long_words.py`;
  - edits to the Cost, R1 minimum (structural rule, brute force, `tests/r1_grid.py`), Rules file
    (floating exceptions refused) and Install lines, to match the new behaviour.
- Create: `docs/reports/V5b-fix2.md` (format: `docs/reports/README.md`).

- [ ] **Step 1: Update AGENTS.md "Testing".** One short paragraph per new file, in its current style.
- [ ] **Step 2: Run the full check three times under load.** Run the check command 3× while a second
  copy of `uv run pytest -q -n auto --dist loadgroup` loops in another shell. Paste the pass counts.
- [ ] **Step 3: Check the demo replay.** Run
  `uv run pytest tests/test_package.py tests/test_step_fields.py -q`. Expected: the byte-identical
  tests pass, also from the wheel.
- [ ] **Step 4: Gather the measurements** of the spec's §9 from Tasks 2, 6, 7, 8 and 10, with the
  residuals of §9.
- [ ] **Step 5: Write the report**, with all of this in it:
  - top block, plus a `## YYYY-MM-DD HH:MM` section;
  - "Needs owner": none expected (the owner settled the R1 narrowings in the brief); anything the
    gates of Tasks 2, 6 and 8 stopped on goes here;
  - every gap and residual;
  - gaps for the lead: HOOKS.md's `rules_limit` line, and SPEC §5's "What a file may cost" (the
    rules limit, with its deny and ask, and `path_except` refusing floating patterns);
  - the margin at 60 deep against 0.2 s, from the measurements.
- [ ] **Step 6: Run `/final-verification`** on `main...HEAD`, then commit its result. Then run
  `/code-review high` on `main...HEAD`. Fix a finding only inside the brief's Touches; list the
  others with one line each.
- [ ] **Step 7: Commit the report and stop.** Message: `V5b-fix2: report`. Do not start another
  card.

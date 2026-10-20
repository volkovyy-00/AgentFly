# V5b-fix2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every rules file `rules check` accepts gets a hook-cost bound that holds by construction. R1's minimum is proven from pattern structure. Long words never break a hook. `init -g` never calls an untrusted rules file intact.

**Architecture:**
- A depth-independent glob, plus a per-hook meter (`ContextVar`) whose budgets come from the command. R0 and R1 are counted but never stopped, and the hook runs in two severity passes.
- An exact, automaton-based coverage proof for R1's name lists, with a literal fast path.
- A shared trust predicate that the installer uses.

**Tech Stack:** Python 3.12, standard library only (`contextvars`, `fnmatch`), pytest with xdist.

**Spec:** `docs/superpowers/specs/2026-10-20-V5b-fix2-second-review-design.md`. The intent is
`docs/superpowers/intents/2026-10-20-V5b-fix2-second-review-intent.md`, and the brief is
`git show main:docs/briefs/V5b-fix2.md`. Executors read the spec. Section numbers below (§4.2 …)
are the spec's.

**For the lead's check (one choice outside the brief's file list):** Task 11 puts the D27 coverage
engine in a new module, `agentfly/recorder/namecover.py`. The brief's Touches names
`agentfly/recorder/` with a list of files that does not include it. If the lead prefers, the same
code goes at the end of `rulefile.py` under a `# ---- D27 coverage` banner, with no other change to
the plan.

## Global Constraints

- **Git:** branch `ag-v5b-rules-file` only. Never push; never merge main.
- **Commit messages:** each starts `V5b-fix2: ` and ends with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Files that stay unedited:**
  - D27 and D28 text, DECISIONS, STATE, BOARD, learnings, HOOKS.md and SPEC §7/§8;
  - `agentfly/recorder/sessions.py`, `memory.py` and `default.toml`.
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
  - `DIV = 256`, `HOOK_WORDS = 300`, `HOOK_CANDIDATES = 900`;
  - pattern budget `MAX_WORK × max(C, 900)`; command budget `2 × MAX_RULES × max(W, 300)`;
  - `D27_STEPS = 600_000`; `LIMIT_ID = "rules limit"`; `/health` field `rules_limit`.

## Review Focus

These are inputs the spec implies but no acceptance criterion names. Each has a test in the task
that owns it.

1. **Parent and subagent.** A trigger that fires in pass 2 (a warn or highlight trigger) still
   reaches the parent chat and survives a restart, as it did before the two passes (Task 5).
2. **Merged steps.** A shell action whose `preToolUse` and `beforeShellExecution` halves merge into
   one step, with one half denied by the rules limit, shows `rules limit` as the step's rule and
   carries its messages (Task 5).
3. **Unparseable commands.** A command the grammar cannot parse (an unbalanced quote) that names
   `.env` still marks the chat. Its `loose` words are counted once (Task 2, Task 5).
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
    - true: `.ssh/**`, `a/**/b`, `**/x/**`, `cfg/**/x.txt`;
    - false: `~/.aws/config`, `~/.aws/**`, `/etc/ssl/private/*`, `a/b`, `/a/**/b`, `.env`.
  - `test_a_pattern_that_is_not_floating_compares_each_part_once_whatever_the_depth`: patch
    `fnmatch.fnmatchcase` with a counter. For `/etc/ssl/private/k*` and unanchored `x/y.txt` on
    paths of 20 and 60 segments, assert that the count is at most the number of parts. A bare `*`
    calls nothing.
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

### Task 2: The meter (pattern steps), distinct candidates, `unstoppable`

**Files:**
- Modify: `agentfly/recorder/rulefile.py` (a new "meter" section after "patterns"; `Pattern.matches`
  and `Clause._words_hit` charge).
- Create: `tests/test_rules_meter.py`.

**Interfaces:**
- Consumes: Task 1's matcher.
- Produces (all in `rulefile`):
  - `DIV: int = 256`, `HOOK_CANDIDATES: int = 900`, `HOOK_WORDS: int = 300`.
  - `class WorkLimit(Exception)`.
  - `@dataclass class Meter`, with:
    - fields `pattern_left: int`, `command_left: int`, `unfinished: list[str]` and
      `limit_deny: bool = False`;
    - `classmethod for_action(action: Mapping[str, Any]) -> Meter`, which gives the budgets of
      §4.2. For a shell action, `C` and `W` are counted over `distinct_candidates` and the distinct
      words of `normalize(command)`; any other action gets the floors.
  - `test_cost(n: int, m: int) -> int`, which returns `1 + n * m // DIV`.
  - `charge_patterns(steps: int) -> None` and `charge_commands(steps: int) -> None`. They do
    nothing with no meter set. They raise `WorkLimit` when a budget goes below 0, unless they are
    inside `unstoppable()`.
  - `@contextmanager metered(meter: Meter) -> Iterator[Meter]`.
  - `@contextmanager unstoppable() -> Iterator[None]`.
  - `distinct_candidates(parsed: Parsed) -> tuple[str, ...]`: memoized, in first-seen order, over
    `parsed.all_commands()`.

- [ ] **Step 1: Write the failing tests** in `tests/test_rules_meter.py`.
  - `test_a_test_costs_one_step_below_256_and_more_above`:
    - `test_cost(25, 10) == 1`
    - `test_cost(64, 32) == 9`
    - `test_cost(250, 200) == 196`
  - `test_without_a_meter_nothing_is_charged_or_raised`: a clause on a 300-word command under no
    meter raises nothing.
  - `test_a_name_pattern_test_is_charged_once_in_total`: a meter of 10 pattern steps, a clause with
    3 name patterns, one candidate of 5 characters. After `Clause.matches`, `pattern_left == 7`.
  - `test_the_memoized_charge_equals_the_per_pattern_sum`: for 50 seeded random lists of patterns
    and name lengths 1 to 300, the clause's charge for length `n` is
    `sum(test_cost(n, len(p)) for p in names)`.
  - `test_a_partly_parsed_command_is_walked_once_per_distinct_candidate`: `cat 'x ; cat a b` (an
    unbalanced quote). Count `Pattern.matches` calls with a monkeypatch: one per distinct candidate
    per pattern.
  - `test_unstoppable_charges_count_but_never_raise`: a meter of 1. Inside `unstoppable()`, charge
    5: no raise, and `pattern_left == -4`. A later stoppable charge raises `WorkLimit`.
  - `test_the_budgets_come_from_the_command`:
    - `tests.test_rules_cost.command()` has 301 words (`cat` and 300) and 901 distinct candidates,
      so `Meter.for_action` of it gives `pattern_left == 180_200` and `command_left == 120_400`.
    - Of a 600-word command: `pattern_left == MAX_WORK * C`, with
      `C = len(distinct_candidates(normalize(cmd)))`.
    - Of a Read: `MAX_WORK * 900` and `2 * MAX_RULES * 300`.
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
  - the `ContextVar`s for the meter and for "stoppable";
  - `_words_hit` iterates `distinct_candidates(parsed)`;
  - for name patterns, the clause keeps a per-instance dict from `n` to the summed charge, and
    charges once per candidate (§4.2). The dict is a dataclass field with `field(default_factory=
    dict, hash=False, compare=False, repr=False)`, because `Clause` is hashed by `_unmarked`'s
    `lru_cache`;
  - slash patterns add their actual segment charges to a local counter, and middle-block starts
    charge 1 each;
  - one `charge_patterns` call per candidate per clause.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_meter.py tests/test_rules_matcher.py tests/test_rulefile.py tests/test_rules_cost.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: a per-hook meter of pattern steps, charged by length`.

### Task 3: The command-list index and command steps

**Files:**
- Modify: `agentfly/recorder/rulefile.py`: § `Clause` (a compiled index built in `_clause`, and
  `_command_hit`).
- Test: `tests/test_rules_meter.py` (add), and `tests/test_rules_cost.py` (the existing entry tests
  must stay green).

**Interfaces:**
- Consumes: Task 2's `charge_commands`.
- Produces: `Clause.command` keeps its type, `tuple[tuple[str, ...], ...]`. The index is a private
  field built from it. Answers are identical.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_index_answers_as_the_old_loop`: a verbatim copy of today's `_command_hit` goes into
    `tests/glob_oracle.py` as `old_command_hit`. For 3,000 seeded random cases (lists of 1 to 30
    entries of 1 to 3 words from `cat a b c npm publish x`, commands of 1 to 6 simple commands
    joined by `;`), the answers are equal.
  - `test_a_command_hitting_200_programs_is_charged_by_the_smaller_side`: a list `p0 x` … `p199 x`,
    and a command `p0 p1 … p199 y`. The charged command steps are at most `200 + 1`, and the answer
    is no match.
  - `test_198_rules_of_200_cat_entries_on_150_cat_commands_stay_inside_the_budget`: the shape
    `command_list_on_one_program` of `tests/test_rules_cost.py`, on 150 `;`-joined `cat zN y`
    commands. The `zN` words match no entry, so every rule reads every command. Inside
    `rules.one_hook`, no `WorkLimit` is raised and the answer is allow.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_rules_meter.py -q`.
- [ ] **Step 3: Implement the index** of §4.5, as a `Clause` field with `hash=False,
  compare=False`, built in `_clause`:
  - the map is program → first extra word (or `None`) → entries;
  - per simple command and per listed program at its first position, iterate the smaller of that
    program's keys and the distinct words after it;
  - charge 1 per look-up and 1 per entry examined.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_meter.py tests/test_rules_cost.py tests/test_npm_publish_entry.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: command lists are looked up by program and first word,
  and metered`.

### Task 4: The engine. One hook, two passes, the limit rule, R1 once

**Files:**
- Modify: `agentfly/recorder/rules.py`:
  - § `_compose` (R1 wrapped in `unstoppable`);
  - § `mark`;
  - § `winning_rule`;
  - § `decide`;
  - § `find_rule`;
  - § `block_messages` (unchanged, but now reached for `LIMIT_RULE`).
- Create: `tests/test_rules_limit.py`.

**Interfaces:**
- Consumes: Task 2's `Meter`, `metered`, `unstoppable` and `WorkLimit`.
- Produces (in `rules`):
  - `LIMIT_ID: str = "rules limit"`.
  - `LIMIT_MESSAGE: str`: the spec's §4.3 wording.
  - `LIMIT_RULE: Rule`: severity `block`; its check is `_never_fires(action, session) -> False`.
  - `@dataclass class Hook`, with fields `meter: rulefile.Meter`, `secret: bool` and
    `phase: str = "block"` (`"block"` or `"rest"`).
  - `@contextmanager one_hook(action: Action, rules: RuleSet | None = None) -> Iterator[Hook]`.
    It sets the meter from `Meter.for_action`, and evaluates `secret` once, unconditionally,
    inside `unstoppable()`.
  - `current_hook() -> Hook | None`.
  - Outside a hook, `mark` and `winning_rule` behave exactly as today: every severity, no meter.
    `agentfly rules test` stays outside a hook, and `cli/rules_test.py` is not changed.
  - Inside a hook, `mark(action, session, rules)` runs:
    - phase `block`: R1, from `hook.secret`, plus the block triggers;
    - phase `rest`: the warn and highlight triggers.
  - Inside a hook, `winning_rule` runs:
    - phase `block`: R0 and the block rules only;
    - phase `rest`: warn, then highlight.
  - `find_rule(LIMIT_ID)` returns `LIMIT_RULE`, and `LIMIT_RULE` is never in `RuleSet.rules`.

`winning_rule` in phase `block`, where "fire" means `rule.check` returned true:
```
unfinished = False; held = None
for rule in block rules (R0 first, then file order):
    try fired = rule.check(...)
    except WorkLimit: unfinished = True; hook.meter.unfinished.append(rule.id); continue
    if not fired: continue
    if not unfinished: return rule            # today's tie-break
    if rule.id in (R0, R1): return rule        # never changed by the limit
if unfinished: hook.meter.limit_deny = True; return LIMIT_RULE
return None
```

`mark` on a `WorkLimit` inside a trigger:
- a block rule's trigger counts as fired, and its id is appended to `unfinished`;
- a warn or highlight trigger is skipped, and its id is appended. The comment says the loss lasts
  the chat (§4.3).

- [ ] **Step 1: Write the failing tests** in `tests/test_rules_limit.py`.
  - First, `tests/test_rules_cost.py::match_rule(i, body)` gains `severity: str = "highlight"`, so
    the existing callers do not change.
  - The tests use `tests.rules_helpers.ruleset_of`, plus a fixture `heavy(severity)`: the default
    plus one `match_rule(0, 'path = "l"', severity)` whose list is `d*/d*/d*/zN/**` × 5. They run on
    a 300-word command whose words all have a `z0` folder near the end (`.../d1/d2/d3/z0/f.py`), so
    the tail matches and the middle walk runs.
  - `test_outside_a_hook_the_engine_answers_as_before`: the default's inline tests and
    `tests/test_severities.py`'s file orders are unchanged.
  - `test_r0_and_r1_answer_as_usual_at_the_limit`:
    - with `heavy("block")`, a marked chat on the heavy command plus `curl https://x.com` gives
      `rule.id == "R1"`;
    - an R0 guard path in the heavy command gives `"R0"`.
  - `test_an_unfinished_block_rule_gives_the_limit_rule`: an unmarked chat with `heavy("block")`
    gives `LIMIT_RULE`, and `hook.meter.limit_deny` is true.
  - `test_an_unfinished_warn_or_highlight_is_skipped`: with `heavy("warn")` and
    `heavy("highlight")`, the winner is None and the id is in `unfinished`.
  - `test_a_block_trigger_counts_as_fired_and_a_warn_trigger_does_not`: an `after_then` with the
    heavy `after`, at block and at warn. After `mark` in a hook, `id in session.triggers` is true
    for block and false for warn.
  - `test_a_heavy_highlight_cannot_starve_a_block_rule`: a file with a heavy highlight rule first
    and a cheap block rule (`.env` read) second. The answer is the block rule.
  - `test_r1_is_evaluated_once_per_hook_even_in_a_marked_chat`: count calls of the R1 `after`
    through a wrapper. Exactly 1 per hook, and `hook.secret` is true for `cat .env` in an
    already-marked chat.
  - `test_the_limit_rule_is_not_listed_and_is_found_by_id`: `LIMIT_ID` is not in
    `[r.id for r in DEFAULT.rules]`, `find_rule(LIMIT_ID) is LIMIT_RULE`, and `_ID` does not
    `fullmatch` `LIMIT_ID`.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_rules_limit.py -q`.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_limit.py tests/test_severities.py tests/test_after_then.py tests/test_session_triggers.py tests/test_rules_load.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: one hook, two passes, a real limit rule, R0 and R1
  never stopped`.

### Task 5: Wire the hook. `apply_rules`, the step record, `/health`, the log

**Files:**
- Modify:
  - `agentfly/recorder/app.py`: § `apply_rules`, § `health`, and § `lifespan`, which resets the
    new counter where it resets `_last_hook_at`. Plus the module-level counter itself.
  - `agentfly/recorder/store.py`: § `build_step_record`.
- Test:
  - add to `tests/test_rules_limit.py`;
  - `tests/test_app.py`, whose health tests must stay green.

**Interfaces:**
- Consumes: Task 4's `one_hook`, `Hook.phase`, `current_hook`, `LIMIT_ID` and `LIMIT_RULE`.
- Produces: `/health` gains `"rules_limit": str` only after a hit, at most
  `rulefile.MAX_PROBLEM_CHARS` long, with the format of §4.3. Its log line is a `logger.warning`
  holding the chat id, the ids, and whether the limit deny went out.

`apply_rules` order (§4.3):
1. `observe`;
2. phase `block`: `apply_mark`, then `decide`;
3. phase `rest`: `apply_mark` again, then `decide` only if pass 1 gave `allow`;
4. `marks = marks1 or marks2`;
5. `build_step_record` and the enqueues.

Steps 2 to 5 run inside `with one_hook(payload) as hook`. `build_step_record` uses
`current_hook().secret` in place of its own `reads_secret(payload)` when a hook is open.

- [ ] **Step 1: Write the failing tests**, through `tests.recorder_harness.Recorder` and
  `fastapi.testclient`.
  - `test_the_recorder_denies_with_the_limit_message_in_both_fields`: with `heavy("block")`,
    `rec.run` gives `permission == "deny"`, a `user_message` of `LIMIT_MESSAGE`, and an
    `agent_message` of `LIMIT_MESSAGE + BLOCK_TAIL`.
  - `test_health_says_rules_limit_only_after_a_hit`:
    - before the hit, the keys are exactly `{"ok", "offline_guard_count", "last_hook_at"}`;
    - after it, `rules_limit` starts with `"the rules limit was reached on 1 hooks"` and names the
      rule id;
    - the line is at most 400 characters.
  - `test_the_log_line_names_the_chat_and_rules_and_no_command_text`: with `caplog`, one warning
    naming the chat and the rule id. The marker word `zz-secret-marker`, planted in the command,
    is absent.
  - `test_a_marked_chats_shell_step_still_shows_the_secret_file`: after `cat .env` twice in one
    chat, the second step's record has `file_sensitive` set.
  - `test_a_pass_two_trigger_reaches_the_parent_and_survives_a_restart` (Review Focus 1): a warn
    `after_then` whose trigger fires in a subagent. Linked by `parent_tool_call_id`, as
    `tests/test_subagent_mark.py` does. After `rec.restart()` the parent's `triggers` holds it.
  - `test_a_merged_pair_with_a_limit_half_shows_the_limit_rule` (Review Focus 2): send
    `preToolUse` Shell, then `beforeShellExecution` with one `tool_use_id`, as
    `tests/test_step_merge.py` does, under `heavy("block")`. The single step's `rule_id ==
    "rules limit"`, and its messages are the limit's.
  - `test_a_fresh_start_forgets_the_limit_hit` (Review Focus 5): after a hit, a new
    `TestClient(app)` (which runs `lifespan`) answers `/health` with exactly the three keys.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_rules_limit.py -q`.
- [ ] **Step 3: Implement** the `apply_rules` order above, the counter and its `lifespan` reset, and
  the `/health` field.
- [ ] **Step 4: Pass the tests.** Run
  `uv run pytest tests/test_rules_limit.py tests/test_app.py tests/test_step_fields.py tests/test_step_merge.py tests/test_history_mark.py tests/test_subagent_mark.py tests/test_rules_cli.py tests/test_rules_api.py tests/test_after_then.py -q`.
  Expected: all pass, and the deny bytes are unchanged.
- [ ] **Step 5: Commit.** Message: `V5b-fix2: the recorder runs the two passes under one meter and
  reports the rules limit`.

### Task 6: The lint, the counting tests, and the non-floating bound

**Files:**
- Modify:
  - `agentfly/recorder/rulefile.py`: § `_parse` (lint lines);
  - `tests/test_rules_cost.py`: new shapes and tests, docstrings updated so that the "holds by
    construction" tests no longer claim to bound work.
- Test: `tests/test_rules_cost.py`, `tests/test_rules_cli.py`.

**Interfaces:**
- Consumes: `floating` (Task 1), the meter (Task 2), the index (Task 3), and the engine and wiring
  (Tasks 4 and 5).
- Produces two lint strings, each starting `rule <id>: `:
  - one for a floating pattern, in the wording of §4.3;
  - one for a command list with two entries sharing a program and first word: `rule X: command
    entries 'a b …' and 'a b …' share 'a b'; on many-command input this may reach the rules limit`.

  The default carries no lint (`test_the_packaged_default_meets_the_minimum` still asserts
  `lint == ()`).

- [ ] **Step 1: Add the shapes and tests to `tests/test_rules_cost.py`.**
  - New shapes:
    - `"reviewer's floating block rule"`: 5 × `d*/d*/d*/zN/**` in a block `match` rule, at
      `MAX_WORK`;
    - `"command lists of 198 rules on one program"`: the existing one, reused with 150 joined
      commands.
  - `test_a_hook_stops_at_the_budget_and_the_count_proves_it`, under the floating shape at 300
    words and 20 deep:
    - patch `fnmatch.fnmatchcase` with a counter;
    - the answer is the limit deny;
    - the counted real calls are at most `MAX_WORK * 900`;
    - with `rulefile.charge_patterns` and `rulefile.charge_commands` monkeypatched to no-ops (the
      bound removed), the count is over `MAX_WORK * 900`.
  - `test_a_non_floating_file_never_reaches_the_budget`, parametrized over every existing `FULL`
    shape plus `/opt/p{i}/x{i}.txt` and unanchored `p{i}/x{i}.txt`. At 300 words, at 20 and 60
    deep, and on a partly parsed form of `command()` (append ` 'x`):
    - no rule is left unfinished;
    - the counted steps are at most `MAX_WORK * C`.
  - `test_rules_check_warns_about_floating_patterns_and_shared_first_words`: `rules check` exits 0
    and prints both `warn:` lines.
- [ ] **Step 2: Run them, implement the lint, run again.** Run
  `uv run pytest tests/test_rules_cost.py tests/test_rules_cli.py tests/test_rules_minimum.py -q`.
  Expected: all pass.
- [ ] **Step 3: Gate. Measure.** Write a scratch script (not committed) that times the whole hook
  with `Recorder.run`, best of three, idle, under:
  - each `TIMED` shape;
  - the floating shape;
  - the command-list shape with 10, 50 and 150 commands;
  - the reviewer's `*/*/*/*/*/*/*/kN.pem` × 8 and `*/*/secretN/*.json` × 10 files.

  Each runs at 300 words and 60 deep. Record the numbers for the report. Any over 0.2 s goes to
  Task 8 (the trim); note which.
- [ ] **Step 4: Commit and run the full check.** Message: `V5b-fix2: rules check warns about shapes
  that can reach the rules limit; the count is tested`. Then run the full check command; expected
  green.

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

- [ ] **Step 1: Profile.** Run `python -m cProfile -s cumtime` on a scratch script running
  `clean.clean_command` on Task 7's `bash -c` command and on `tests.test_rules_cost.command(60)`.
  Note the top five costs.
- [ ] **Step 2: Trim.** Do only changes that keep every `clean.py` output byte-identical. Check with
  a scratch comparison: 2,000 seeded random commands, using `tests/leak_cases.py` words plus
  `tests/cases.py` commands, give old and new `clean_command` outputs that are equal.
- [ ] **Step 3: Pass the tests.** Run `uv run pytest tests/test_clean.py tests/test_leak*.py -q`.
  Expected: all pass.
- [ ] **Step 4: Gate.** Re-run Task 6's measurement script and Task 7's `bash -c`. Each must be under
  0.2 s at 60 deep. **If any stays over 0.2 s, stop and ask the lead with the numbers.** Do not
  change `MAX_WORK` or a budget formula.
- [ ] **Step 5: Commit and run the full check.** Message: `V5b-fix2: the cleaner's baseline is
  trimmed (outputs byte-identical)`. Then run the full check command; expected green.

## Part 3: D27 by structure (§6)

### Task 9: One table for "secret"

**Files:**
- Create: `agentfly/recorder/namecover.py` (see "For the lead's check" at the top). It holds `Family`
  for now. It imports nothing from `rulefile`, so that `rulefile` can import it with no cycle.
- Modify: `agentfly/recorder/rulefile.py`: § the R1 minimum (`EXEMPTIONS`, `spec_secret`).
- Test: `tests/test_rules_minimum.py` (add).

**Interfaces:**
- Produces:
  - `namecover.Family`, a `@dataclass(frozen=True)` with fields `bullet: str` (SPEC §5's words),
    `start: str`, `end: str`, `exact: bool` and `unless: tuple[str, ...]`.
  - `rulefile.SECRET_FAMILIES: tuple[Family, ...]`: the six families of §6.1, in that order.
  - `spec_secret(name: str) -> bool`, reading the table.
  - `EXEMPTIONS`, derived from the table, with the same value as today.

- [ ] **Step 1: Write the test.** `test_spec_secret_from_the_table_answers_as_before`: a copy of
  today's `spec_secret` goes into the test file. The two agree on `SECRET_NAMES`, on every name of
  today's `_secret_names` grid built without the filter, and on 20,000 seeded random names drawn
  from `.env`, `.`, `pem`, `key`, `id_rsa`, `credentials`, `pub`, `example` and random letters.
- [ ] **Step 2: Implement, and pass.** Run `uv run pytest tests/test_rules_minimum.py -q`.
- [ ] **Step 3: Commit.** Message: `V5b-fix2: SPEC section 5's secret names come from one table`.

### Task 10: `fnmatch` tokens, class membership, the alphabet

**Files:**
- Modify: `agentfly/recorder/namecover.py` (created in Task 9).
- Create: `tests/test_namecover.py`.

**Interfaces:**
- Produces (in `namecover`):
  - `tokens(pattern: str) -> tuple[str, ...]`: each token is a literal character, `"?"`, `"*"` or a
    class `"[...]"`, split as `fnmatch.translate` splits it. An unclosed `[` is the literal `"["`.
  - `accepts(token: str, char: str) -> bool`: for a class, `fnmatch.fnmatchcase(char, token)`; for a
    literal, equality; for `?`, true.
  - `alphabet(patterns: Iterable[str], extra: Iterable[str]) -> tuple[str, ...]`: the
    representatives of §6.3, each with `c.casefold() == c`, and never `/` or `\x00`.

- [ ] **Step 1: Write the failing tests.**
  - `test_tokens_split_as_fnmatch_does`. The test holds a small reference matcher over tokens:
    backtracking, where `*` takes any run and every other token takes one character it `accepts`.
    For `[]]x`, `[!]]`, `[a-]`, `[z-a]`, `a[b`, `\\*`, `*.pem` and 2,000 seeded random patterns
    over `[]!a-z\\*?.`, with 200 random names each over the same characters, the reference
    matcher's answer equals `fnmatch.fnmatchcase(name, p)`.
  - `test_the_alphabet_separates_every_class`: for 500 random class tokens, every character in
    `range(0x20, 0x250)` that is fixed by case folding has a representative with the same
    `accepts` answer, for every token.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_namecover.py -q`.
- [ ] **Step 3: Implement**, and pass the tests.
- [ ] **Step 4: Commit.** Message: `V5b-fix2: fnmatch tokens and a finite alphabet for the D27
  proof`.

### Task 11: The exact coverage search

**Files:**
- Modify: `agentfly/recorder/namecover.py`.
- Test: `tests/test_namecover.py`.

**Interfaces:**
- Consumes: Task 9's `Family`, and Task 10.
- Produces:
  - `@dataclass(frozen=True) class Coverage`, with fields `witness: str | None`, `family: Family |
    None`, `too_complex: bool` and `steps: int`.
  - `check(families: Sequence[Family], marks: Sequence[str], exceptions: Sequence[str], *, limit:
    int, try_limit: int = 20_000) -> Coverage`. `marks` and `exceptions` are case-folded name
    patterns (no `/`). A `witness` of None with `too_complex` false means every family name is
    marked.
  - The unit is one NFA state-step (§6.3), and `steps` reports it.

The search order is pinned (§6.3), per family:
1. each exception alone: a shared name is a miss;
2. each mark alone, within `try_limit` (over that limit the try just fails): the first that covers
   the family settles it;
3. only then the union search.

All steps count against `limit`.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_search_equals_brute_force_on_toy_families`, for 300 seeded cases:
    - families over the letters `abcde` (start and end of up to 2 letters, random `exact`, `unless`
      of up to 2 endings);
    - marks and exceptions of 1 to 4 random patterns over `abcde*?[`;
    - brute force over every string of up to 7 letters.

    `check(...).witness is None` exactly when brute force finds no miss. A found witness is a real
    miss, and is no longer than the shortest brute-force miss.
  - `test_the_three_dodges_are_found` (the brief's files):
    - the `.env.[!s]*` chain gives the witness `.env.` or a name starting `.env.s`;
    - `credentials` + `credentials[!$ ]*` gives a name starting `credentials`;
    - `.env.?` … up to 15 `?` gives a name starting `.env.`.
  - `test_a_hostile_pattern_is_too_complex_at_the_limit` (no seconds bound):
    - the marks are the default's six names with `.env.*` replaced by `*a` followed by 150 `?`, so
      the `.env.` family needs the union search;
    - `check(..., limit=5_000)` gives `too_complex`, and `steps` is between 5,000 and 5,000 plus one
      deterministic state's width.
  - `test_the_default_plus_30_names_and_the_dot_env_rewrite_finish_under_the_cap`, forced past the
    fast path by calling `check` directly:
    - the default's marks plus 30 realistic names (`*.p12`, `*.pfx`, `secrets.*`, `*.jks`,
      `*.keystore`, `*.ovpn`, `.npmrc`, `.pypirc`, …);
    - the same with `.env.*` replaced by `.env.?*` and `.env.`.

    Both have no witness, are not `too_complex`, and have `steps < 600_000`; the owner's prototype
    measured about 26k and 340k. **If either fails, stop and ask the lead with the step count.**
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_namecover.py -q`.
- [ ] **Step 3: Implement** the three-phase search in the pinned order, with the two prunings, and
  the witness as the shortest miss.
- [ ] **Step 4: Pass the tests.**
- [ ] **Step 5: Commit.** Message: `V5b-fix2: an exact search for a secret name R1 leaves unmarked`.

### Task 12: Wire D27. Fast path, exact check, R1's folder patterns, messages, SPEC §5

**Files:**
- Modify:
  - `agentfly/recorder/rulefile.py`: § `_minimum_problems` and § `_unmarked`, which becomes
    `_coverage_problem(after: Clause) -> str | None`, still `lru_cache(16)`;
  - `SPEC.md` §5: the two D27 sentences of §6.5 (the rules-limit sentence goes to the report as a
    gap for the lead).
- Test:
  - `tests/test_rules_minimum.py`: witness assertions become family assertions, plus the new cases;
  - `tests/test_rules_cost.py`: keep `test_the_work_of_a_file_that_is_refused_is_not_also_judged_by_the_r1_grid`,
    renamed "…by the R1 check".

**Interfaces:**
- Consumes: Task 11's `namecover.check`, and Task 1's `floating`.
- Produces (in `rulefile`): `COVERING: dict[Family, frozenset[str]]`, `SAFE_EXCEPTIONS:
  frozenset[str]` and `D27_STEPS: int = 600_000`.

  Error strings start `rule R1: `:
  - one for a miss, naming the bullet and the witness;
  - one for "too complex";
  - one for a floating R1 pattern, in §6.4's wording.

- [ ] **Step 1: Write the failing tests** in `tests/test_rules_minimum.py`.
  - `test_the_brief_dodge_files_are_refused_naming_r1`: the three files, through `rules check`.
    Each exits 1, and stderr has `rule R1:` with the family's bullet.
  - `test_files_that_only_add_names_or_respell_load` keeps every existing `ACCEPTED` entry, and adds
    the default plus 30 realistic names (fast path) and `.env*` for `.env` and `.env.*`.
  - `test_the_fast_path_tables_are_proved`: for every family and every spelling in `COVERING`, and
    every subset of `SAFE_EXCEPTIONS`, `namecover.check` finds no witness.
  - `test_the_fast_path_runs_no_search`: monkeypatch `namecover.check` to raise. The default and a
    names-only extension still load.
  - `test_the_sample_grid_agrees_with_the_exact_check`: for every `ACCEPTED` and refused fixture,
    the old grid finds a miss exactly when the exact check does, or the exact check finds a
    degenerate miss (`.env.`, a trailing space) the grid lacks. Assert that list explicitly.
  - `test_r1s_floating_folder_patterns_are_refused`: `.ssh/**`, `a/**/b` and `**/x/**` are refused
    with §6.4's text. `~/.aws/config`, `~/.aws/**` and `/etc/ssl/private/*` load.
  - `test_env_dot_question_star_alone_is_refused_for_env_dot`: the witness is `.env.`.
  - The existing tests that assert `'prod.pem'` (or another named witness) now assert the
    bullet's text.
  - `test_the_grid_is_judged_once_per_clause` (lines 262-265) becomes
    `test_the_check_is_judged_once_per_clause`, on `rulefile._coverage_problem.cache_info().misses
    == 1`.
- [ ] **Step 2: Run them and see them fail.** Run `uv run pytest tests/test_rules_minimum.py -q`.
- [ ] **Step 3: Implement** in `_minimum_problems`:
  - floating refusal;
  - exception shape (unchanged);
  - then the fast path;
  - else `namecover.check(SECRET_FAMILIES, name patterns, exceptions, limit=D27_STEPS)`.
- [ ] **Step 4: Measure the load time.** A scratch script times `load_bytes` of the default and of
  the 30-name rewrite, best of five. Record the numbers for the report.
- [ ] **Step 5: Pass the tests.** Run
  `uv run pytest tests/test_rules_minimum.py tests/test_rulefile.py tests/test_rules_load.py tests/test_rules_cli.py tests/test_rules_trust.py tests/test_rules_cost.py tests/test_rules_shipped.py -q`.
  Expected: all pass.
- [ ] **Step 6: Commit and run the full check.** Message: `V5b-fix2: R1's minimum is proven on every
  SPEC name (D27)`. Then run the full check command; expected green.

## Part 4: install (§7)

### Task 13: Shared trust test; `untrusted`, `unknown`, and the notice

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

### Task 14: `rules check <link to the active file>`, and `init.py`'s two small gaps

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

### Task 15: AGENTS.md, measurements, verification, report

**Files:**
- Modify: `AGENTS.md`. Only the "Testing" section changes:
  - lines for `tests/test_rules_matcher.py`, `tests/test_rules_meter.py`, `tests/test_rules_limit.py`,
    `tests/test_long_words.py` and `tests/test_namecover.py`;
  - edits to the Cost, R1 minimum, Rules file and Install lines, to match the new behaviour.
- Create: `docs/reports/V5b-fix2.md` (format: `docs/reports/README.md`).

- [ ] **Step 1: Update AGENTS.md "Testing".** One short paragraph per new file, in its current style.
- [ ] **Step 2: Run the full check three times under load.** Run the check command 3× while a second
  copy of `uv run pytest -q -n auto --dist loadgroup` loops in another shell. Paste the pass counts.
- [ ] **Step 3: Check the demo replay.** Run
  `uv run pytest tests/test_package.py tests/test_step_fields.py -q`. Expected: the byte-identical
  tests pass, also from the wheel.
- [ ] **Step 4: Gather the measurements** of the spec's §9 from Tasks 6, 7, 8 and 12. Include the
  residuals: command size, R1 never stopped, a full name list at 30-character names.
- [ ] **Step 5: Write the report**, with all of this in it:
  - top block, plus a `## YYYY-MM-DD HH:MM` section;
  - "Needs owner" (at most 300 characters): "Confirm R1's narrowings: floating folder patterns refused
    (Option C, not names only) and degenerate names like `.env.` counted; recommend yes. Detail
    under Details.";
  - every gap and residual;
  - the new module, if the lead kept it;
  - gaps for the lead: the HOOKS.md line for `rules_limit`, and a SPEC §5 sentence that the rules
    limit fails closed for block rules;
  - the tight margin: about 70 ms of budget plus about 100 ms of baseline at 60 deep, against
    0.2 s.
- [ ] **Step 6: Run `/final-verification`** on `main...HEAD`, then commit its result. Then run
  `/code-review high` on `main...HEAD`. Fix a finding only inside the brief's Touches; list the
  others with one line each.
- [ ] **Step 7: Commit the report and stop.** Message: `V5b-fix2: report`. Do not start another
  card.

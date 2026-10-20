# V5b-fix2 design: a sound hook-cost bound, R1's minimum on every name, honest "intact", long words

Card: V5b-fix2 (`git show main:docs/briefs/V5b-fix2.md`, read at main bcb9e9d). Intent:
`docs/superpowers/intents/2026-10-20-V5b-fix2-second-review-intent.md` (approved by the owner
2026-10-20, revised the same day). Branch `ag-v5b-rules-file`. Author: the worker, for the owner.
Status: approved by the owner 2026-10-20 (revision 2, after the builder check and the owner's measurement review).

The brief and the intent are the authority; this document says how. Where it would differ from the
brief, the builder stops and asks. "My call" marks a choice the owner did not make.

## 1. Why

`docs/reports/V5b-fix.md` priced each rules-file pattern with a fixed weight fitted to measured
shapes. The second review showed four holes:
- the weights ignore path depth, so two accepted files cost 0.4 s idle and 1.4 s busy per hook;
- R1's minimum (D27) is judged on 474 sample names, so three crafted lists load and leave a SPEC §5
  secret unmarked;
- `init -g` calls a rules file "intact" on its bytes alone, even when the recorder refuses it;
- one shell word over 255 bytes per part, or 1,024 in all, makes `apply_rules` raise.

This round makes each guarantee hold by construction for every file `rules check` accepts. Where a
guarantee needs a condition (ordinary-length names, no floating patterns), the condition is stated,
tested, and warned about by `rules check`.

## 2. Goals, non-goals, anti-goals

Goals, in the brief's order:
1. **Cost.** A matcher whose cost does not grow with folder depth for most patterns, plus a per-hook
   meter that bounds the rest.
2. **Long words.** No word or path makes the hook raise, and `bash -c` with 300 deep paths is fast
   under the default rules.
3. **D27.** R1's `after` is proven to mark every SPEC §5 secret name, from the patterns' structure.
4. **Install.** `init -g`:
   - never calls an untrusted rules file intact;
   - prints the notice for an edited one;
   - and `rules check <link to the active file>` judges the active file.

Non-goals:
- what the brief lists as not included;
- cost that grows with command size (reported, not fixed);
- a change to the saved session format.

Anti-goals (a failure even if the tests pass):
- **No answer changes.** A hook answer must not change for a file the old code accepted on a command
  that does not reach the meter. The demo replay stays byte-identical, also from the wheel.
- **R0 and R1 stand.** Neither answer may change because the meter ran out.
- **No R1 text on another reason.** A deny for something other than R1 must not carry R1's text.
- **No laundering.** `init -g` must not make an unknown file trusted (no chown or chmod of bytes it
  has not checked).
- **No content in logs.** No request body, command text or file content goes into a log line.

## 3. Constraints

- AGENTS.md rule shape stays `Rule(id, severity, message, check)`, with `check(action, session)`.
- `MAX_WORK` (200) and its weights do not change, so the same files load as before, apart from the
  narrowings in §6.4.
- These files are the lead's and are not edited:
  - D27 and D28 text;
  - DECISIONS, STATE, BOARD;
  - HOOKS.md.

  SPEC §5 gets the sentences listed in §6.5.
- The healthy `/health` answer stays exactly its three keys.
- `sessions.py` is outside the Touches and does not change.
- No new dependency.

## 4. Part 1: cost

### 4.1 A matcher whose cost does not grow with depth

A slash pattern's parts are split at each `**` into blocks of fixed length. An unanchored pattern has
an implicit `**` in front. A match then checks three kinds of block:
- **First block** (anchored patterns only): compared with the path's first segments, at one
  position.
- **Last block** (patterns that do not end in `**`): compared with the path's last segments, at one
  position.
- **Middle blocks** (a run with a `**` on each side): each found left to right at the earliest place
  after the previous one. Greedy leftmost placement is correct for fixed-length blocks between `**`.

A bare `*` part matches any one segment without `fnmatch`.

`rulefile.floating(pattern) -> bool` is true when the pattern has a middle block. Examples of
floating patterns: `.ssh/**` (unanchored), `a/**/b`, `**/x/**`. Not floating: `~/.aws/config`,
`~/.aws/**`, `/etc/ssl/private/*`, unanchored `a/b`, anchored `/a/**/b`. A pattern that is not
floating costs at most its number of parts per path, whatever the depth. The same predicate is used
by R1's refusal (§6.4), the `rules check` lint (§4.3) and the tests.

`Pattern` keeps its fields and gains the blocks, computed once in `compile_pattern`. Two lookups move
out of the per-test path:
- `Pattern.matches` takes the folded home folder from its caller, as an optional parameter
  (existing tests wrap it with two arguments). `os.path.expanduser` is called once per clause
  evaluation, not once per pattern test, which saves about 1.7 µs per slash test;
- the old `_glob` moves to `tests/` as the oracle (§8).

### 4.2 The meter

- **Where it lives.** `rulefile` gains a meter: a `ContextVar` holding this hook's `Meter`, or
  `None`. With `None`, charging does nothing, so pure tests, `doctor` and the D27 check behave as
  today.
- **What it counts.** A `Meter` holds two budgets and the ids of rules left unfinished. A charge
  past either budget raises `WorkLimit`.
  - **Pattern steps.** One name-pattern test costs `1 + n * m // DIV`, one step in total (never one
    for the call and one for `fnmatch`). `n` is the name's length and `m` the pattern's. One part
    compared with one segment costs the same, with the segment's length as `n`. One start position
    tried for a middle block costs 1.
  - **Command steps.** One index look-up or one command entry examined costs 1 (§4.5).
- **`DIV = 256`**, with no free zone (the owner's measurement):
  - the worst real time of a test with `n × m = 2,048` is 4.1 µs, and `1 + 2048 // 256 = 9` steps
    is about 5.1 µs;
  - a test costs 1 step only when `n × m < 256`;
  - an agent can craft its own words, and a slow hook falls to the offline guard, which allows
    everything that is not outbound. So under-charging is worse than a false deny.

  The builder re-measures and keeps 256 unless a test shows a charged step costing much over
  0.6 µs.
- **Charging in bulk** (a meter call costs about 0.57 µs):
  - A clause adds its charges in a local counter and calls the meter once per candidate.
  - For name patterns, the charge for a name of length `n` is the exact per-pattern sum `count +
    Σ (n × m_i // DIV)`. It is memoized per (clause, `n`), so a command's few dozen distinct name
    lengths cost one sum each, and every other candidate costs O(1). A plain upper bound (`count +
    n × Σm // DIV`) would charge ordinary names up to twice and break the bound in §4.4.
  - Slash parts add their actual segment charges to the same local counter as they are compared.
  - A floating pattern's middle-block starts are charged as the walk goes.
- **Distinct candidates only.** `Clause._words_hit` walks the command's distinct candidates (one
  memoized tuple per parsed command), not `all_commands()` as it is. A command that parses only
  partly is then tested, and charged, once per candidate, as its budget assumes. The answers are the
  same (`any` over the same set).
- **Budgets come from the command** (my call). Let `C` be the distinct candidates of the command and
  `W` its words, over `Parsed.all_commands()` with duplicates removed (a command that parses only
  partly no longer counts its words twice):
  - pattern budget: `MAX_WORK × max(C, 900)`;
  - command budget: `2 × MAX_RULES × max(W, 300)`.

  A short command still gets the full 300-word allowance. Cost may grow with command size, as
  cleaning and R1 already do (§9).
- **Where it runs.** `rules.one_hook()` is a context manager. It opens the meter and holds what the
  hook has already worked out:
  - the pass (§4.3);
  - R1's answer for this action (below).

  `cli/rules_test.py` uses it for each inline test step, so `rules test` judges as the recorder
  does.
- **R0 and R1 are counted but never stopped** (my call). R1's `after` and `check` (and
  `RuleSet.secret`) run inside `rulefile.unstoppable()`. Their charges add to the budgets, so the
  hook's total stays bounded, but they never raise. A rule metered later gets only what is left. R0
  uses no `rulefile` patterns.
- **R1 runs once per hook.** At the start of `one_hook`, `secret(action)` is evaluated once,
  unconditionally, and kept in the context. Both `rules.mark` and `store.build_step_record` read it.
  Today `mark` skips it when the chat is already marked (`session.marked or …`), so "reuse mark's
  answer" would lose `file_sensitive` for a marked chat's shell steps. The per-token `is_sensitive`
  calls in `build_step_record` stay (one name each).

### 4.3 Order across the hook, and what happens when the meter runs out

A rule's `then` depends only on its own trigger, so the hook runs in two passes:
1. R1's mark and the block rules' triggers, then R0 and the block checks;
2. the warn and highlight triggers, then the warn and highlight checks.

**How the passes run.**
- `app.apply_rules` calls `store.apply_mark` and `decide` once per pass. The pass is held in the
  hook context, so `sessions.py` does not change.
- In pass 2, `mark` runs only the warn and highlight triggers. `apply_mark` is idempotent, and the
  `marks` results of the two calls are OR-ed.
- Pass 2's triggers always run, so a trigger set by a blocked command is still kept, as today.
- Pass 2's checks run only when pass 1 found no block.
- The winner is unchanged: the first block in file order, else the first warn, else the first
  highlight.

**When the meter runs out in a trigger** (`WorkLimit` inside a non-R1 `after`):
- *A block rule's trigger counts as fired.* A lost trigger is lost for the rest of the chat, while a
  skipped check heals on the next hook. The cost is that a false trigger also lasts the chat: it
  survives a restart, reaches the parent chat and subagents, and holds through the 30-minute
  fallback. For a lockdown rule (an event-only `then`) that covers every action of that event. The
  later deny shows the rule's own message; the log and `/health` explain it.
- *A warn or highlight trigger is skipped and logged.* A comment says the loss lasts the chat.

**When the meter runs out in a check:**
- *An unfinished block check* is remembered, and evaluation goes on. Later metered checks fail at
  their first charge; R0 and R1 still run in full. The brief decides the answer:
  1. if R0 or R1 fired, that rule's answer;
  2. else, if any file block rule was left unfinished, the limit deny, even if another file block
     rule fired;
  3. else the first file block rule that fired.
- *An unfinished warn or highlight check* is skipped and logged.

**The limit deny.** It is a real rule: `LIMIT_RULE = Rule(LIMIT_ID, "block", LIMIT_MESSAGE,
_never_fires)`. Its check takes `(action, session)`; the existing `_never` takes one argument and
would raise.
- `LIMIT_ID = "rules limit"`. The space is outside the file id grammar, so no file rule can take it.
  The id is fine in history, Neo4j and the page (checked by the owner's review).
- It is not in `RuleSet.rules`, so `/api/rules` and the wheel test pinning `R0, R1,
  npm-publish-after-env` do not change. `find_rule(LIMIT_ID)` returns it, so the answer, the step's
  `rule_text` and both messages come from it (plus `BLOCK_TAIL`).
- The message: "AgentFly's rules took too long to check this action, so it is blocked. Simplify the
  rules file's patterns; `agentfly rules check` names the heavy ones." The wording may be polished.
- The step's verdict is `blocked`.

**Lint.** `rules check` prints a `warn:` line for each shape that can reach the meter: every
floating pattern, and every command list in which two entries share a program and first word (§4.5).
The line reads: "rule X: pattern '…' is checked at every folder of a path; on long, deep commands it
may reach the rules limit, which blocks the action if X is a block rule and skips it otherwise;
anchor it if you can". The file still loads.

**Reporting.** After the hook, `app.apply_rules` reads the meter:
- if anything was unfinished, it logs one warning line with the chat id, the unfinished rule ids and
  whether the limit deny went out (no command text), and adds to a process counter;
- `/health` then sends `rules_limit`, one line of at most `MAX_PROBLEM_CHARS`, absent until the
  first hit: "the rules limit was reached on N hooks since the recorder started; last at <UTC ms>,
  rules <ids>".

### 4.4 The bound, and why it holds

**Pattern steps.** When every test has `n × m < 256` (one step each), a non-floating pattern costs at
most its `pattern_work` in steps per candidate:
- a name pattern costs 1;
- a slash pattern without a middle block compares each part once, and `WORK_SLASH + WORK_PART ×
  (parts − 4)` is at least its number of parts.

A clause's fixed `WORK_CLAUSE`, R1's second count, and R1 now running once only add slack. So a file
with no floating pattern uses at most `MAX_WORK × C` pattern steps: it never reaches the pattern
budget, at any depth or command size.

Longer names are charged what they cost. A full-size name list (167 patterns of about 9 characters)
on 300 words of 30-character names is about 300k steps, past the 180k budget. Its block rules then
get the limit deny. Meeting 0.2 s makes that unavoidable, and the report says so.

**Command steps.** With the index (§4.5), a clause costs, per simple command, the sum over its listed
programs of `min(first-word keys of that program, distinct words after it)`, plus one per entry
examined. When each simple command names at most one listed program and a list's entries do not
share a program and first word, that is at most `2 × W` per clause. So the file uses at most
`2 × rules × W` command steps and never reaches the command budget. A command crafted so that each
simple command names many listed programs, each with many first words, can reach it, and then fails
closed.

**Floating patterns, shared-first-word lists, long names and crafted commands** may reach a budget.
They fail closed (§4.3), and `rules check` warns about the file-side shapes. The owner accepted this
on 2026-10-20. Re-pricing would only move the breaking depth and refuse more files.

**Time** (300 words, 60 deep, idle):
- the pattern budget is 180k steps, at about 0.43 µs of `fnmatch` each once the charge overhead is
  removed;
- command steps are dictionary look-ups;
- the baseline is cleaning plus parsing.

The plan trims `clean.py`'s baseline as a planned step: `_split_keeping_seps`, `shlex`, and the
`resolve` calls the long-word guard leaves. This reconciles the intent's "where cheap" with the
design's "only if needed": the step is planned, and stops where it stops paying.

The target is under 0.2 s for the reviewer's two files and a command-list file at their limits. If
the measured worst case stays over 0.2 s after the trim, the builder stops and asks. `MAX_WORK` is
not changed.

### 4.5 Command lists

Today `Clause._command_hit` loops over every entry for every simple command: about 354 ms for an
accepted file of 198 rules × 200 `cat wN` entries on 10 joined `cat` commands, and 5.1 s at 150.
The fix:
- **An index.** At compile time, each clause's command list becomes a map: program → (first extra
  word, or none) → entries. Per simple command, the clause looks up each program the command holds,
  at its first position `at`:
  - an entry with no extra word fires at once;
  - otherwise the clause iterates **the smaller of** that program's first-word keys (each checked
    with `last.get(key, -1) > at`) and the distinct words after `at` (each looked up among the
    keys);
  - only the entries under a key that holds then have their remaining extras checked, with today's
    `_last_positions` test.
- **The same answers.** "Program, then the extra words in any order, after it" is unchanged; an
  entry with no extra word fires on the program alone.
- **Metered.** Look-ups and entries examined charge the command budget, so a pathological list is
  bounded by construction. With distinct (program, first word) pairs, nothing realistic reaches it.

## 5. Part 2: long words

`clean._project_relative` returns a path only when `exists()` holds, and today it raises for a word
over the name limits. So:
- **A word over 1,024 characters** returns `None` before `resolve()`. Measured with that guard: a
  `bash -c` of 300 paths takes 23 ms to clean at 20 deep, and 139 ms at 60 deep, against 445 ms and
  3.1 s today. Matching adds about 9 ms.
- **`resolve()` and `exists()`** are inside `except (OSError, ValueError)`. A lone surrogate from
  JSON gives `ValueError`; a part over 255 bytes gives ENAMETOOLONG.
- **Containment** is a string test in place of `relative_to` (quadratic on 3.12). The rules:
  - a resolved path equal to the root gives `"."`, as `relative_to(...).as_posix()` does today;
  - otherwise the path must start with the root plus `/`, and a root that already ends in `/` (the
    workspace `/`) is used as it is.

`store.relative_file_path` keeps `resolve()`. A 1,338-character Read path is saved relative today,
and still is. The function gets:
- the same `except`;
- the same string containment;
- if `resolve()` fails, the string-only `os.path.normpath` of the absolute path in its place.

The `(root / token).exists()` in `store.build_step_record`:
- skips a token over 1,024 characters;
- and is wrapped in the same `except`.

No saved value changes for a path that worked before. Tests pin:
- a long absolute Read path saved relative;
- the root itself (`"."`);
- the workspace `/`.

## 6. Part 3: D27 by structure

### 6.1 One table for "secret"

`rulefile.SECRET_FAMILIES` holds SPEC §5's name bullets. Each family is a literal start, a literal
end, whether anything may come between, and the endings that exempt it:
- `.env` exactly;
- `.env.` then anything, unless it ends `.example`, `.sample` or `.template`;
- anything ending `.pem`;
- anything ending `.key`;
- `id_rsa` then anything, unless it ends `.pub`;
- `credentials` then anything.

`spec_secret` is rewritten to read this table, and must answer as today on the grid and on random
names. `EXEMPTIONS` is derived from the same table.

### 6.2 The fast path

Most files reach the check with R1's lists spelled the way the default spells them. The fast path
covers that case. Two in-code tables, not `default.toml`, so a later default never refuses an older
file:
- **`COVERING`**: for each family, the literal spellings that cover it alone: `.env` / `.env*` /
  `.*` for `.env`; `.env.*` / `.env*` / `.*` for `.env.`; `*.pem`; `*.key`; `id_rsa*`;
  `credentials*`.
- **`SAFE_EXCEPTIONS`**: `.env*.example`, `.env*.sample`, `.env*.template`, `.env.example`,
  `.env.sample`, `.env.template`, `id_rsa*.pub`, `id_rsa.pub`.

If every family has a covering spelling in `after.path` (case-folded, literal), and every exception
is in `SAFE_EXCEPTIONS`, coverage holds, and no automaton runs. A test proves the two tables with the
exact check (§6.3). So the default, and any file that only adds names to it, loads in microseconds,
as the brief requires.

### 6.3 The exact check (every other file)

**What it searches.** R1 marks a name when the name matches a name pattern in `after.path` and none
in `after.path_except` (names case-folded). Slash patterns only add marks, so the proof ignores
them. A breadth-first search looks for the shortest secret name left unmarked, over the product of:
- the family table, as small automata;
- the set of positions reached in the `path` patterns (an NFA made deterministic on the fly);
- the same for the `path_except` patterns.

A state is a miss when a family accepts and either no `path` pattern accepts or an exception does.

**Pruning** (the builder may add more, if a test shows it exact):
- a state whose family automaton is dead is dropped;
- a state whose `path` set holds a universal position (the rest of that pattern is only `*`) and
  whose exception set is empty and cannot revive is covered for every extension, and is dropped.

**The alphabet.** It is a finite set of representative characters:
- every character any pattern or the table names, with its neighbours ±1;
- one character beyond the highest.

Each must satisfy `c.casefold() == c`; `/` and NUL are excluded. A representative that is not fixed
by case folding is replaced by the nearest one in its gap that is; a gap with no such character holds
no name that can exist.

**Class meaning is never re-implemented.** Patterns are split into tokens by `fnmatch`'s own rules
(a literal, `?`, `*`, `[...]`, an unclosed `[` as a literal), and a class token's membership is
`fnmatch.fnmatchcase(c, token)`.

**The work cap.**
- *The unit:* one NFA state-step, that is, one position of one pattern advanced by one representative
  character. A deterministic state of k positions costs k per character.
- *The cap:* `D27_STEPS = 600_000`. At the owner's measured 0.55–0.67 µs per state-step, a hostile
  `?`/`[…]` pattern is refused in under 0.5 s. The builder re-measures, and lowers the cap if needed
  to keep that gate.
- *Past it,* R1 is refused: "rule R1: its 'after' lists are too complex to check against SPEC section
  5's names; use simpler patterns (D27)". This is the one place the check is not exact, and it fails
  closed.
- *The check that matters:* with the pruning, a realistic rewrite, for example the default with
  `.env.*` replaced by `.env.?*` and `.env.`, plus 30 added names, forced through the automaton,
  finishes under the cap. Without pruning, the owner's prototype needed 7.7M steps for it. If it does
  not finish under the cap, the builder stops and asks.

**Errors.** An error names the family's SPEC bullet and a witness: "rule R1: its 'after' leaves
'.env.' unmarked, but SPEC section 5 counts every name starting with '.env.' as a secret; widen the
lists or narrow the exceptions". Witnesses can be degenerate (`.env.`, `credentials ` with a trailing
space, `.pem`). These are real SPEC secrets, so `.env.?*` alone is refused, a narrowing the report
records.

**What stays.** The exception-shape rule stays. The proof also covers exceptions on its own:
`*.example` is refused either way. `_unmarked`'s sample grid moves to the tests as a second opinion.
The clause-level `lru_cache` stays. Load time for the default (fast path) and for the 30-name rewrite
(automaton) is measured and reported.

### 6.4 What it changes, and R1's folder patterns

**What changes:**
- the three dodge files in the brief are refused, naming R1;
- these still load: the default; a file that only adds names; `.env*` in place of `.env` and
  `.env.*`; `.*`;
- a bare `*` stays refused, as "matches every path";
- tests that assert a particular witness (`'prod.pem'`) assert the family instead.

**R1's folder patterns.** `rules check` refuses a `floating` pattern in R1's `after.path`: "rule R1:
pattern '.ssh/**' costs more the deeper a path is; anchor it ('~/.ssh/**' or '/...') or put it in a
rule of its own". `~/.aws/config` (`ACCEPTED["a name from a folder"]`) still loads.

This narrows D27's "widening is allowed". The report's "Needs owner" asks the owner to confirm it,
against the alternative of names only, together with §6.3's degenerate names. Option C is built
unless the owner says otherwise.

### 6.5 SPEC §5

Three sentences:
- R1's names are checked exactly against the bullets, up to a work limit past which R1 is refused;
- R1 may not hold floating folder patterns;
- the rules limit fails closed for block rules.

## 7. Part 4: install

**The principle**, written in the code comment and the report: `init -g` writes only bytes it has
checked, and never changes the trust of bytes it has not checked.

**The shared trust test.**
- `rulefile.trust_problem(path, uid) -> str | None` is the recorder's trust test alone: the same
  `O_NOFOLLOW` open and `fstat` checks, the same wording, and no read.
- `_trusted_bytes` and `trust_problem` share one private helper, so the recorder, `doctor` and the
  installer cannot drift.
- The recorder's rule does not change. A root:admin 0640 file that the recorder loads today still
  loads.

**Known-good bytes** (`current` or `older`). The installer rewrites them unless the file is exactly
what it would write: a regular file owned by the layout's owner, mode 0644. Rewriting known bytes is
harmless, and the rewrite is a fresh inode (root, 0644).
- `rules_state` gains `untrusted`: the current bytes, but not exactly that.
- `status` counts `untrusted` as bad.
- The message names the reason and asks for a recorder restart, as `older` does.

**An unreadable file.** When an unprivileged `init -g` cannot read the file (`PermissionError`, for
example a 0600 root file), `rules_state` says `unknown`, not `edited`. `status` counts it as bad, so
root takes the decision after the password, with the full state.

**An edited file** is never written, chowned or chmodded:
- trusted: the existing notice, "kept your edited rules file …; this version's default rules were not
  applied";
- untrusted: "kept your edited rules file …, but the recorder will not read it: <reason>;
  <DEFAULT_IN_FORCE>". The reason comes from `trust_problem`, which already says what to do.

**One notice helper.** `installer.rules_notice(layout, wanted) -> str | None` builds the notice. It is
printed in two places:
- by `init._as_user`, after the pinned line "already installed and intact; nothing changed" (no sudo
  needed for a readable file);
- by root's `install()`, in its messages.

**`rules check <link>`.** When the given file is the active file (`is_active_path` follows links),
`cli/rules_check.load` reads `rulefile.ACTIVE_RULES` with `load_active_file`, and its messages name
the active path.

**`init.py`'s two other gaps** are fixed only if a few lines do it; otherwise they are noted in the
report:
- a bad packaged default is caught only after the password;
- a rules-only refresh says "Quit and reopen Cursor".

## 8. Tests

New or changed tests. AGENTS.md "Testing" gets matching lines.

**Matcher oracle.**
- The old `_glob` lives in a test helper. On thousands of seeded random patterns and paths
  (anchored, unanchored, leading, trailing and inner `**`, `*`, `?` and classes), the new matcher
  answers the same.
- A second run compares `Pattern.matches`, old and new, on `~/`, `/`, `..`, `//` and mixed case.

**Counting is real.**
- The reviewer's shape (a block rule of `d*/d*/d*/zN/**` × 5 at `MAX_WORK`, whose tail matches the
  test words) and the 198 × 200 `cat wN` command-list file are added to `test_rules_cost.py`.
- A test counts real steps by patching `fnmatch.fnmatchcase` and counting bare-`*` parts,
  middle-block starts and command look-ups. It checks that the hook stops at the budget and answers
  with the limit deny.
- With the meter disabled, the count exceeds the budget, so the test fails if the bound is removed.
- The "holds by construction" tests that already exist stay, but no longer claim to bound work.

**Non-floating bound.**
- Every non-floating shape at the limit: all existing `test_rules_cost.py` shapes, plus anchored and
  tail-only slash shapes, plus command lists with distinct (program, first word).
- It runs at 300 words, at 20 and 60 deep, and on a command that parses only partly.
- The counted steps are at most `MAX_WORK × C` and `2 × rules × W`, and no rule is left unfinished.

**`DIV`.**
- A test with `n × m < 256` is charged 1; one with `n × m = 2,048` is charged 9.
- A 250-character name against a 200-character pattern is charged in proportion to its measured
  time.
- The memoized name-pattern charge equals the per-pattern sum.
- A command that parses only partly is walked once per distinct candidate.

**Command index, 200 programs.** A command whose simple commands hit 200 listed programs is charged
as §4.4 says, and answers as the old loop does.

**Limit behaviour.**
- R0's and R1's answers are unchanged at the limit: a `.env` read then `curl`, and an R0 path, each
  with a heavy file rule.
- An unfinished file block rule gives the limit deny, with `LIMIT_RULE`'s message in both fields.
- An unfinished warn or highlight is skipped.
- A block trigger counts as fired; a warn trigger does not.
- A heavy highlight cannot starve a block rule.
- `/health` has `rules_limit` only after a hit, and the log line holds no command text.
- `rules test` uses the same meter and passes.
- A marked chat's shell step still gets `file_sensitive`.

**Long words.**
- The words: a quoted word of 300 and 5,000 characters, with and without `/`, and one of 128 emoji
  (512 bytes in one part), in a real existing workspace folder, not `/w`.
- For each: the answer equals the short-word answer, R1 still blocks after a `.env` read, and the
  step reaches history. The same for a long Read `file_path`.
- Assert answers and time, not that the old code raised. APFS and Python 3.14 do not always raise.

**D27 exact.**
- The engine on toy families equals brute force over 5 letters up to length 7.
- Class tokens equal `fnmatch` on `[]]`, `[!]]`, `[a-]`, `[z-a]`, an unclosed `[`, a backslash, and
  random classes.
- The fast-path tables are proved by the automaton.
- The three dodges are refused, and the accepted variants load.
- The grid agrees with the exact check on every accepted and refused fixture.
- A hostile pattern is refused at the cap in under 0.5 s.
- The 30-name rewrite finishes under the cap.

**R1 folder patterns.** These are refused: `.ssh/**`, `a/**/b`, `**/x/**`. These load: `~/.aws/config`,
`~/.aws/**`, `/etc/ssl/private/*`.

**Command-list index.** It gives the same answers as today on the existing entry tests, plus seeded
random commands and lists.

**Install.** With a layout owner different from the file's, as the doctor tests do:
- current bytes with the wrong owner, with mode 664 and with mode 0600 are each rewritten, and the
  message asks for a restart;
- an edited, untrusted file keeps its bytes and mode, `init -g` exits 0 and prints the notice;
- an intact re-run with an edited file prints the pinned line, then the notice;
- an unreadable file is `unknown`, not `edited`;
- `rules check <link to the active file>` gives the recorder's verdict.

## 9. Measurements for the report (not test bounds)

On this Mac, idle, best of three:
- **300-word commands at 60 deep** under:
  - the reviewer's two files;
  - the floating shape at the limit;
  - the command-list file (with 10, 50 and 150 joined commands);
  - each existing shape.
- **`bash -c` with 300 paths** under the default rules, at 20 and 60 deep (expected about 150 ms at
  60).
- **D27 load time**, for the default (fast path) and the 30-name rewrite.
- **Counts:** the step count of each shape, and the measured `DIV`.
- **Residuals:**
  - cost grows with command size, and the budgets scale with it, so a 1,000-word command can still
    pass 0.5 s and fall to the offline guard;
  - R1 is never stopped, so very long names cost R1 what they take;
  - a full-size name list reaches the budget at about 30-character names.

The full AGENTS.md check is green 3× while another copy of the suite runs, and the demo replay is
byte-identical, also from the wheel.

## 10. Left to the builder

- Function and helper names not fixed above.
- How the meter is passed inside `rulefile`.
- Further D27 pruning, if a test shows it exact.
- The limit message's wording, within its meaning.
- Commit boundaries inside each part.

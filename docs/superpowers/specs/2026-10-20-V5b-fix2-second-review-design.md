# V5b-fix2 design: a sound hook-cost bound, R1's minimum on every name, honest "intact", long words

Card: V5b-fix2 (`git show main:docs/briefs/V5b-fix2.md`, read at main 67efc8d). D27 as changed
2026-10-20 (`git show main:docs/DECISIONS.md`). Intent:
`docs/superpowers/intents/2026-10-20-V5b-fix2-second-review-intent.md`. Branch `ag-v5b-rules-file`.
Author: the worker, for the owner.
Status: revision 4 (2026-10-21), awaiting the lead's check. Revision 4 changes one point of
revision 3: command lists are metered (owner). After Task 6's gate found accepted command-list files
at 0.27 to 2 s a hook, the owner decided that command-list entry checks count against the same
per-hook budget as floating patterns (§4.2, §4.5, §4.7), with a `rules check` line for a heavy list
(§4.4); an unfinished highlight is still skipped. The brief's "meter only floating patterns" is
superseded on this point; the brief is the lead's to edit. Revision 3 (2026-10-20) followed the
owner's changes in the brief at 67efc8d: the meter in one pass, with a budget priced from measured
time; an unfinished block rule denies and records no trigger; an unfinished warn on a shell command
asks; D27 is a structural rule with no automaton; R1 and `path_except` refuse floating patterns.
Revision 2 (approved by the owner earlier the same day) is superseded on these points. The final
review's fixes (2026-10-21: a walk stops at the budget, §4.2; "may name", §4.3) change no decision.

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

## 2. Goals, non-goals, anti-goals

Goals, in the brief's order:
1. **Cost.** A matcher whose cost does not grow with folder depth unless the pattern floats, a
   command-list index, and a per-hook meter on floating patterns and command lists (revision 4).
2. **Long words.** No word or path makes the hook raise, and `bash -c` with 300 deep paths is fast
   under the default rules.
3. **D27.** R1's `after` is judged by the shape of its patterns: one covering pattern per SPEC §5
   family, and no floating folder pattern.
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
- `MAX_WORK` (200) and its weights do not change. The same files load as before, apart from the
  narrowings the brief makes (§4.6, §6.3).
- These files are the lead's and are not edited:
  - D27 and D28 text;
  - DECISIONS, STATE, BOARD, learnings;
  - HOOKS.md, SPEC §7 and §8.

  SPEC §5 gets the D27 sentences listed in §6.4.
- The healthy `/health` answer stays exactly its three keys.
- `sessions.py` is outside the Touches and does not change.
- No new dependency, and no new module in `agentfly/`.

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

The order is pinned: the head first, then the tail, then the middle blocks. A path whose tail does
not fit is refused after a few comparisons. With the middle blocks first, today's floating shapes
cost about 390k steps at 60 deep instead of about 4.5k (measured by the owner's review).
`_glob(pattern, segments, blocks=None)` keeps its two-argument form for callers and tests that pass
parts. `Pattern` passes its precomputed blocks as the third argument.

A bare `*` part matches any one segment without `fnmatch`.

`rulefile.floating(pattern) -> bool` is true when the pattern has a middle block. Examples of
floating patterns: `.ssh/**` (unanchored), `a/**/b`, `**/x/**`, `src/**/gen.py`. Not floating:
`~/.aws/config`, `~/.aws/**`, `/etc/ssl/private/*`, unanchored `a/b`, `**/secret.txt`, anchored
`/a/**/b`, and both of the reviewer's shapes (`*/*/*/*/*/*/*/k0.pem`, `*/*/secret0/*.json`: tail
only). A pattern that is not floating costs at most its number of parts per path, whatever the depth.
The same predicate is used by the meter (§4.2), the refusals (§4.6, §6.3), the `rules check` lint
(§4.4) and the tests.

`Pattern` keeps its fields and gains the blocks, computed once in `compile_pattern`. Two lookups move
out of the per-test path:
- `Pattern.matches` takes the folded home folder from its caller, as an optional parameter
  (existing tests wrap it with two arguments). `os.path.expanduser` is called once per clause
  evaluation, not once per pattern test. The segments are not hoisted: each pattern still asks the
  `_folded_segments` memo, which a test counts;
- the old `_glob` moves to `tests/` as the oracle (§8).

`Clause._words_hit` walks the command's distinct candidates (one memoized tuple per parsed command),
not `all_commands()` as it is. A command that parses only partly is then tested once per candidate.
The answers are the same (`any` over the same set). This keeps the unmetered work at most
`MAX_WORK × C` tests (§4.5), where `C` is the number of distinct candidates.

### 4.2 The meter: floating patterns and command lists, one fixed budget

- **What it covers.** A floating pattern's test charges the meter: its head, tail and middle
  comparisons and its middle-block start positions. Command lists charge too (owner, 2026-10-21):
  a bucket of the index (§4.7) is charged `Σ (1 + len(rest))` over its entries before it is walked
  (the weight is worked out when the index is built and kept beside the bucket), and a run of key
  probes is charged `len(probes) // 4` before it is made (a run of fewer than 4 charges nothing,
  so it still answers once the budget is spent). Name patterns, non-floating slash patterns, hosts
  and command classes never charge. R0 uses no `rulefile` patterns, and R1 holds no floating
  pattern (§6.3) and no `command` (D27's check refuses one), so neither ever touches the meter. No
  "unstoppable" mode is needed.
- **Where it lives.** `rulefile` holds a `ContextVar` with this hook's `Meter`, or `None`. With
  `None`, charging does nothing, so pure tests, `rules test`, `doctor` and the D27 check behave as
  today.
- **The price of a step**, from measured time:
  - one part compared with one segment by `fnmatch` costs `1 + n × m // DIV`, with `n` the segment's
    length, `m` the part's, and `DIV = 256` (the owner's measurement: a test with `n × m = 2,048`
    takes at most 4.1 µs, priced 9 steps);
  - a bare `*` part, a literal compare, and one start position tried for a middle block each cost 1.
- **The budget** is one fixed number of steps per hook, `FLOAT_STEPS`, priced from measured time
  (my call on the allowance): the builder measures the slowest kind of step (µs per step, best of
  three, idle) on the floating shapes of §8, and sets `FLOAT_STEPS` so that a whole budget of that
  kind costs at most **20 ms** on this Mac. The start value is 40,000 (about 0.5 µs a step). It does
  not grow with the command.
- **Charging.** A floating pattern's test adds its steps to a local counter and charges the meter
  after each block, so a hook overshoots the budget by at most one block's walk; a walk that has
  spent what the meter had left when it began is charged at once (final audit A1), so that walk is
  itself bounded by the budget and ends at most one start's work past it. A charge that takes
  the budget below 0 raises `WorkLimit`. Once the budget is spent, every later floating test raises
  at its first charge.
- **One pass.** The hook runs as today: `mark`, then `decide`, each over the rules in file order.
  There are no severity passes. A heavy rule early in the file can use up the budget for a later
  floating rule, which is then unfinished and handled as below (fail closed for a block rule). A
  rule without floating patterns is never unfinished, so it is never starved.

### 4.3 What an unfinished rule does

A rule is **unfinished** when `WorkLimit` is raised while its trigger (`after`) or its check runs.
The meter keeps the ids of unfinished rules.

**Triggers** (`mark`):
- an unfinished trigger is never recorded, for any severity. For a block rule, the brief says so:
  the hook is denied (below), so the action that would set the trigger does not run. For a warn or
  highlight rule it is my call, the same rule for all: a warn on a shell command asks (below), and if
  the user lets the command run, that trigger is lost (reported);
- R1's mark is never affected (R1 is never metered);
- a trigger the chat already holds is not evaluated again (today's short-circuit), so it cannot be
  left unfinished. A trigger held only through a parent chat or the 30-minute workspace fallback is
  evaluated again (re-firing keeps it in the child for good), and if that is left unfinished the
  check still runs as for a held trigger (`_outcome`, final review CR2): the rule is not unfinished.

**Checks** (`winning_rule`), with one rule for every severity: within a severity, the first rule in
file order that fired or was left unfinished decides.
- An unfinished rule, whether its trigger or its check ran out, counts at its place in file order.
- **Block:** a fired block rule wins as today, unless an unfinished block rule comes before it; then
  the answer is `LIMIT_RULE` (a deny). The one exception: if R0 or R1 fires, its answer stands,
  whatever was unfinished. R0 comes first; evaluation goes on after an unfinished block rule only to
  see whether R1 fires.
- **Warn** (when no block decided): the first warn rule that fired or was left unfinished decides.
  Unfinished gives `LIMIT_WARN_RULE`, a warn, so the answer is `ask` on a shell command, as for every
  warn (D11). On another event, a warn is a plain allow, and the step shows the limit rule.
- **Highlight:** an unfinished highlight is skipped and logged. A highlight never changes an answer.

**The limit rules.** Two real rules, one id and one message:
- `LIMIT_ID = "rules limit"`. The space is outside the file id grammar, so no file rule can take it.
  The id is fine in history, Neo4j and the page (checked by the owner's review).
- `LIMIT_RULE = Rule(LIMIT_ID, "block", LIMIT_MESSAGE, _never_fires)` and `LIMIT_WARN_RULE`, the
  same with severity `warn`. `_never_fires` takes `(action, session)`; the existing `_never` takes
  one argument and would raise.
- Neither is in `RuleSet.rules`, so `/api/rules` and the wheel test pinning `R0, R1,
  npm-publish-after-env` do not change. `find_rule(LIMIT_ID)` returns `LIMIT_RULE`. Its message is
  the warn rule's too, and `app.hook_answer` picks deny or ask from the verdict, so both answers carry
  the limit message (plus `BLOCK_TAIL` or `SKIP_TAIL`).
- `LIMIT_MESSAGE`: "AgentFly's rules took too long to check this action (the rules limit). Simplify
  the rules file's patterns or command lists; `agentfly rules check` may name the heavy ones." The
  wording may be polished ("may name": a list heavy only with key probes gets no lint line, final
  review M6).

### 4.4 Lint and reporting

**Lint.** `rules check` prints a `warn:` line for each floating pattern in a rule's `path` (R1's and
`path_except`'s are refused, §4.6 and §6.3): "rule X: pattern '…' is checked at every folder of a
path; on long, deep commands it may reach the rules limit, which then blocks the action if X is a
block rule, asks if it is a warn, and skips it if it is a highlight; anchor it if you can". The file
still loads. The packaged default has no floating pattern, so it carries no lint.

For a command list (revision 4), `rules check` prints one `warn:` line per list a rule names whose
heaviest bucket weighs more than 20 (`rulefile.HEAVY_BUCKET`; ten entries of one word left each
weigh 20): "rule X: N entries of list 'l' share the word 'w' and are each checked when a command
holds it; on long commands the rule may reach the rules limit", with N and w those of the heaviest
bucket. So `LIMIT_MESSAGE`'s "`agentfly rules check` may name the heavy ones" holds for lists
too. The packaged default's one list (`publish_tools`) has buckets of one entry, so it carries no lint.

**Reporting.** After the hook, `app.apply_rules` reads the meter:
- if anything was unfinished, it logs one warning line with the chat id, the unfinished rule ids and
  the answer the limit gave (deny, ask, or none), with no command text, and adds to a process
  counter. `lifespan` resets the counter, as it resets `_last_hook_at`;
- `/health` then sends `rules_limit`, one line of at most `MAX_PROBLEM_CHARS`, absent until the
  first hit: "rules limit reached by N hook(s) since the recorder started; last at <UTC ms>, rules
  <ids>".

### 4.5 Why the work is bounded

**Unmetered patterns.** A non-floating pattern costs at most its `pattern_work` in tests per
candidate:
- a name pattern costs 1;
- a slash pattern without a middle block compares each part once, and `WORK_SLASH + WORK_PART ×
  (parts − 4)` is at least its number of parts.

A clause's fixed `WORK_CLAUSE` only adds slack. So a file uses at most `MAX_WORK × C` unmetered
tests per hook, at any depth, by construction. A test's time grows with the name's length; R1 and
name lists are never stopped, so a command of very long names costs what it takes (§9). A full-size
name list (167 names, the default plus 169 units) on 300 words of 30-character names is never
stopped, as the brief requires.

**Floating patterns** add at most `FLOAT_STEPS` plus one block's walk, priced at 20 ms.

**Command lists** are metered (revision 4, owner 2026-10-21). With the index (§4.7), a clause
costs, per distinct simple command, the sum over its listed programs of `min(keys of that program,
distinct words after it)` probes, plus one check per entry under a key that holds. The estimate
"about `rules × (200 + 200)`" holds for one simple command of 300 words, not for many short ones: a
crafted list whose entries share common words checks rules × entries × simple commands entries
(up to about three million at 300 words), and no index avoids that when the command holds every key
and no entry completes. So the entry checks and the probe runs are charged (§4.2), and a hook does at
most `FLOAT_STEPS` steps of list work plus one bucket. What stays unmetered is the fixed look-up per
(clause, simple command, program) and runs of fewer than four probes: at most a few dictionary
operations per clause and simple command (about 15 ms at 198 rules × 150 simple commands), which
grows with command size (out of scope, §2).

**Time** (300 words, 60 deep, idle): cleaning and parsing (the baseline, about 0.1 s today), plus at
most `MAX_WORK × C` short tests (180k at 900 candidates, about 70 ms; less once a file spends units
on floating patterns, each of which weighs at least 28), plus 20 ms of floating budget. That is
close to 0.2 s, so the plan trims `clean.py`'s baseline as a planned step (`_split_keeping_seps`,
`shlex`, and the `resolve` calls the long-word guard leaves), and stops where it stops paying. If the
measured worst case stays over 0.2 s after the trim, the builder stops and asks. `MAX_WORK` is not
changed.

### 4.6 `path_except` refuses floating patterns

`rules check` refuses a `floating` pattern in any rule's `path_except` (brief): "rule X: exception
'…' is checked at every folder of a path; an exception must be a name, anchored ('~/…' or '/…'), or
end at the file name". No packaged default or test fixture holds one (checked: every `path_except`
in the defaults and tests is a name pattern).

### 4.7 Command lists

Today `Clause._command_hit` loops over every entry for every simple command: about 354 ms for an
accepted file of 198 rules × 200 `cat wN` entries on 10 joined `cat` commands, and 5.1 s at 150.
The fix:
- **An index.** Built in `Clause.__post_init__`, so clauses that tests build directly have it too.
  Identical entries are kept once. Each clause's command list becomes a map: program → key → entries,
  where an entry's **key is its rarest extra word** among that program's entries (ties go to the
  first in the entry's order), or none for an entry with no extra word. Keying on the first extra
  word instead puts every entry of `cat w a0` … `cat w a199` under `(cat, w)`, and an accepted file
  of 198 such rules takes 5.5 s on 100 simple commands `cat w x` (measured by the review). Per
  simple command, the clause looks up each program the command holds, at its first position `at`:
  - an entry with no extra word fires at once;
  - otherwise the clause iterates **the smaller of** that program's keys (each checked with
    `last.get(key, -1) > at`) and the distinct words after `at` (each looked up among the keys);
  - only the entries under a key that holds then have their remaining extras checked, with today's
    `_last_positions` test.
- **Each distinct simple command once.** A clause reads each distinct simple command (as a tuple of
  words) once per hook, so a command that repeats one simple command pays once.
- **The same answers.** "Program, then the extra words in any order, after it" is unchanged; an
  entry with no extra word fires on the program alone.
- **Why this is enough.** An entry is checked only when its rarest word is in the simple command. A
  key shared by many entries is a word that each of them holds and that is no rarer than any of
  their other words, so a big bucket needs many entries built from a few common words; the gate
  (Task 6) timed the worst such shapes, at 0.27 to 2 s, so the lists are now metered (§4.2).
- **Each bucket carries its weight** (`rulefile._Bucket`: the weight `Σ (1 + len(rest))` and the
  rests), worked out once when the index is built; `_bucket_hit` charges it before it reads an entry,
  and `_program_hit` charges each run of probes. The index's answers do not change.

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

`rulefile.SECRET_FAMILIES` holds SPEC §5's name bullets. Each `Family` (a frozen dataclass in
`rulefile`) is a literal start, a literal end, whether it is one exact name, the endings that exempt
it, and the bullet's words for messages:
- `.env` exactly;
- `.env.` then anything, unless it ends `.example`, `.sample` or `.template`;
- anything ending `.pem`;
- anything ending `.key`;
- `id_rsa` then anything, unless it ends `.pub`;
- `credentials` then anything.

`spec_secret` is rewritten to read this table and must answer as today. `EXEMPTIONS` is derived from
the same table, with the same value.

### 6.2 The structural rule

R1's `after.path` must hold, for every family, one name pattern (no `/`; only `name_only` patterns
are looked at) that covers the whole family by its shape. After case folding, as the matcher folds:
- **`P`**, a literal with no `*`, `?` or `[`, covers only an exact family, and only when `P` is that
  name (`.env`).
- **`P*Q`**, one `*` and no `?` or `[`, covers a family when `P` is a prefix of the family's literal
  start and `Q` is a suffix of its literal end. For the exact `.env`, `P` and `Q` must also fit
  inside it: `|P| + |Q| ≤ 4`.

Why it is sound: every name of the family starts with its start and ends with its end, and is at
least as long as both together, so it starts with `P`, ends with `Q`, and is long enough for the `*`
to take the rest (possibly nothing).

Examples (all case-folded):
- cover `.env`: `.env`, `.env*`, `.*`, `*env`, `.e*v`; not `.env*.env`, `.env.*`;
- cover `.env.…`: `.env.*`, `.env*`, `.*`, `.en*`; not `.env.?*`, `.env.[!s]*`, `.env`;
- cover `….pem`: `*.pem`, `*pem`, `*m`; not `?*.pem`, `*.pe?`, `prod.pem`;
- cover `id_rsa…`: `id_rsa*`, `id_*`; not `id_rsa`, `id_rsa.*`;
- cover `credentials…`: `credentials*`, `cred*`; not `credentials`, `credentials[!$ ]*`.

A bare `*` would cover every family; it stays refused, as "matches every path".

**Exceptions.** The exception-shape rule stays as it is: an exception starts `.env` and ends
`.example`, `.sample` or `.template`, or starts `id_rsa` and ends `.pub`, and names no folder. Every
name such an exception matches is one SPEC §5 itself exempts, or no family's name at all, so
exceptions cannot unmark a secret, and the structural rule needs only `after.path`.

**What it refuses that covers.** A union of narrower patterns, such as `.env.[!s]*` plus `.env.s`
plus `.env.s[!e]*` and so on, is refused even where it would cover. That is the point: no automaton,
and no samples.

**Messages.** One error per family left without a covering pattern, starting `rule R1: `:
"rule R1: no pattern in its 'after' marks every name SPEC section 5 counts as secret under
'<bullet>'; add one such as '<the default's spelling>' (a single `*` and no `?` or `[`) (D27)".

### 6.3 R1's folder patterns

`rules check` refuses a `floating` pattern in R1's `after.path` (D27 as changed): "rule R1: pattern
'.ssh/**' costs more the deeper a path is, and R1 is never cut short; anchor it ('~/.ssh/**' or
'/...') or put it in a rule of its own (D27)". `~/.ssh/**` and `~/.aws/config` (`ACCEPTED["a name
from a folder"]`) load. Slash patterns in R1 never count as covering a family.

### 6.4 What changes, what stays, SPEC §5

**Refused:** the three dodge files in the brief, and an R1 with `.ssh/**`, each with `rules check`
exit 1 naming R1.

**Loads:** the default; a file that only adds names; `.env*` in place of `.env` and `.env.*`; `.*`;
`*pem`; `~/.ssh/**`. The shipped defaults in `tests/fixtures/shipped_defaults/` load (same lists).

**Code that goes:** `_unmarked` and the sample grid leave `rulefile`. The grid (`_secret_names`,
`SECRET_NAMES`, `_FAMILIES`, `_TAILS`, `_SWEEP`, `_LITERALS`, `_FOLDERS`) moves to a test helper,
`tests/r1_grid.py`, as a second opinion: every file the structural rule accepts leaves no grid name
unmarked. The clause-level `lru_cache` moves to the new check.

**Tests that change wording:** those that assert a grid witness (`'credentials' unmarked`, `and 87
more`, `leaves 'prod.pem' unmarked`) assert the bullet instead. An exception like `prod.pem` is
refused for its shape alone; the structural rule does not look at exceptions.

**SPEC §5**, D27's paragraph only (the brief allows SPEC §5 edits only where D27's wording changes):
- the sentence "Judged on those names, not on how a list is spelled (`.env*` in place of `.env` and
  `.env.*` is fine)" becomes the structural rule of §6.2, in one sentence with its examples;
- one sentence is added: R1 holds no floating folder pattern (`.ssh/**`; an anchored `~/.ssh/**` is
  fine), because R1 is never cut short by the rules limit.

The rules limit, and `path_except` refusing floating patterns, are not D27's wording. They go to the
report as gaps for the lead (SPEC §5's "What a file may cost", and HOOKS.md's `rules_limit` line).

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
- `floating` is true and false on the examples of §4.1.

**The meter.**
- Name patterns and non-floating slash patterns never charge: a meter's budget is unchanged after a
  300-word command under the default, the reviewer's two files, and a 167-name list.
- A floating pattern charges by §4.2's prices (`1 + n × m // 256` for an `fnmatch` compare, 1 for a
  start).
- Past the budget, `WorkLimit` is raised, and every later floating test raises at its first charge.
- With no meter, nothing is charged or raised.

**Counting is real.**
- The floating shape (a block rule of `d*/d*/d*/zN/**` × 5) runs on the 300-word `command(20)`,
  whose words hold `d…` folders and no `zN` folder, so every middle walk runs to the end and none
  matches. (A word holding `z0` would make the rule fire on the first candidate and spend almost
  nothing.) A test counts real steps by patching
  `fnmatch.fnmatchcase` and counting bare-`*` parts and middle-block starts. The hook answers with
  the limit deny, and the count is at most `FLOAT_STEPS` plus one block's walk.
- With the charge disabled, the count exceeds `FLOAT_STEPS`, so the test fails if the bound is
  removed.

**Unmetered bound.** Every non-floating shape at the limit (all existing `test_rules_cost.py` shapes
that do not float, plus anchored and tail-only slash shapes, plus the reviewer's two files), at 300
words, at 20 and 60 deep, and on a command that parses only partly: the counted tests are at most
`MAX_WORK × C`, and no rule is left unfinished. The two floating shapes of `test_rules_cost.py` are
excluded, and a test asserts that they float.

**Command index.** It gives the same answers as the old loop on seeded random lists and commands. A
command whose simple command names 200 listed programs does at most `200 + 1` key look-ups. The
198 × 200 `cat wN` file on 150 joined commands answers allow with no entry checked, and so does the
198 × 200 `cat w aN` file on 100 simple commands `cat w x`.

**Command lists count** (revision 4).
- The price: a bucket of ten one-word rests is charged 20 before its first entry is read (a meter of
  19 reads none); 8 probes charge 2, either side of the smaller-side walk; 3 probes charge nothing,
  even on a spent meter.
- Counting is real: the bipartite shape (198 rules, each a 200-entry list `cat aI bJ`, I < 20, J <
  10) as block rules on 13 `;`-joined `cat a0 … a19 zK` (286 words) gives the limit deny, and the
  real list work counted through `_entry_follows` and `_key_lookups` (a step an entry and one a word
  checked, a step for four probes) is at most `FLOAT_STEPS` plus one bucket; with `_charge` a no-op
  the entries read exceed `FLOAT_STEPS`.
- The same shape as warn gives `ask` with the limit message; as highlight, allow, with the rules in
  `meter.unfinished`.
- R0's and R1's answers are unchanged with the heavy list block rules before R1.
- Never charged (meter untouched, nothing unfinished): the packaged default on `command(60)`; 198 ×
  `cat wN` on 150 `cat zN y`; 198 × `cat w a0..a199` on 100 `cat w x`; a realistic file (20 block
  rules × 15 entries like `git push --force`) on 75 `git push origin bK`. 198 × `cat wN` on
  `command(60)` (300 words after `cat`, more than the 200 keys) pays only its probes, 198 × 50
  steps, and finishes.
- `rules check` prints one line for a heavy list, none at weight 20, and the default has no lint.

**Limit behaviour.**
- R0's and R1's answers are unchanged at the limit: a marked chat's heavy command with `curl
  https://x.com`, and an R0 path, each with a heavy file block rule placed **before** R1 in the file.
- An unfinished file block rule gives `LIMIT_RULE`: a deny with the limit message in both fields.
- An unfinished block trigger records no trigger in the chat, nor in its parent; after
  `rec.restart()`, a cheap follow-up is judged as if the limit hook had not happened.
- R1's mark is still set when the same hook is limit-denied (`cat .env` plus the heavy words).
- A padded shell command with a warn rule unfinished gets `ask` with the limit message; on a Read the
  answer is a plain allow and the step shows `rules limit`.
- An unfinished highlight is skipped.
- A fired block rule before an unfinished one wins; an unfinished one before a fired one gives the
  limit deny.
- A full-size name list (167 names) on 300 words of 30-character names gets no limit deny.
- `/health` has `rules_limit` only after a hit, and a fresh recorder start has exactly three keys
  again. The log line holds no command text.

**`path_except` and R1 refusals.**
- `path_except` with `.ssh/**`, `a/**/b` or `**/x/**` is refused in any rule; with `~/.ssh/**` or a
  name it loads.
- R1 with `.ssh/**`, `a/**/b` or `**/x/**` is refused; with `~/.aws/config`, `~/.aws/**`,
  `~/.ssh/**` or `/etc/ssl/private/*` it loads.

**Long words.**
- The words: a quoted word of 300 and 5,000 characters, with and without `/`, and one of 128 emoji
  (512 bytes in one part), in a real existing workspace folder, not `/w`.
- For each: the answer equals the short-word answer, R1 still blocks after a `.env` read, and the
  step reaches history. The same for a long Read `file_path`.
- Assert answers and time, not that the old code raised. APFS and Python 3.14 do not always raise.

**D27 by structure.**
- `spec_secret` from the table equals today's on the grid and on random names.
- The three dodges are refused naming R1 and the bullet; the brief's loading list loads.
- **Brute force** (the brief's test): a thousand seeded random R1 name lists, each built from one
  covering shape per family with some swapped for near misses, made by random one-character edits
  (insert, delete, replace from `. e n v p m k y i d _ r s a c l * ? [ ! ]`) of the covering shapes,
  so that a slip in `covers` (an `in` for an `endswith`, the wrong family's start) is drawn; and some
  near misses added, with exceptions drawn from the safe ones. For every list the file accepts, every secret name built from a family's start, a
  middle of up to 2 characters from a small alphabet, and the family's end (plus the exempt endings)
  is marked. The test asserts that both accepted and refused lists occur (at least 100 of each).
- The grid (now in `tests/r1_grid.py`) finds nothing unmarked in every accepted fixture.

**Install.** With a layout owner different from the file's, as the doctor tests do:
- current bytes with the wrong owner, with mode 664 and with mode 0600 are each rewritten, and the
  message asks for a restart;
- an edited, untrusted file keeps its bytes and mode; on an intact re-run `init -g` exits 0 and
  prints the notice, and on a repair run (any other work to do) `assert_locked` still fails closed:
  the bytes and mode are untouched and the repair is undone (controller ruling R-n, 2026-10-21);
- an intact re-run with an edited file prints the pinned line, then the notice;
- an unreadable file is `unknown`, not `edited`;
- `rules check <link to the active file>` gives the recorder's verdict.

## 9. Measurements for the report (not test bounds)

On this Mac, idle, best of three:
- **300-word commands at 60 deep** under:
  - the reviewer's two files;
  - the floating shape at the limit (the limit deny);
  - the command-list file (with 10, 50 and 150 joined commands);
  - each existing shape, and the 167-name list on 30-character names.
- **`bash -c` with 300 paths** under the default rules, at 20 and 60 deep (expected about 150 ms at
  60).
- **The meter's price:** µs per step of each step kind, the chosen `FLOAT_STEPS`, and the measured
  `DIV`.
- **D27 load time** for the default (expected microseconds: a few string tests).
- **Residuals:**
  - cost grows with command size; the floating budget does not, so a long floating-heavy command
    reaches the limit sooner;
  - R1 and name lists are never stopped, so very long names cost what they take;
  - the list charge is conservative by design: a step of a long rest takes about 0.09 µs against
    0.35 µs for a one-word rest (the advisor's measurement), so a long rest is charged up to about
    4× its time, and a crafted file with long entries reaches the limit sooner than its time needs;
  - `init -g`'s `untrusted` (not exactly the owner's and 0644) is stricter than the recorder's trust
    rule (which loads root:admin 0640), so `init -g` may rewrite known bytes `doctor` calls fine;
  - an unfinished warn trigger is not recorded, so it is lost if the user lets the command run;
  - D27 refuses some covering unions (by design).

The full AGENTS.md check is green 3× while another copy of the suite runs, and the demo replay is
byte-identical, also from the wheel.

## 10. Left to the builder

- Function and helper names not fixed above.
- How the meter is passed inside `rulefile`.
- The limit message's wording, within its meaning.
- Commit boundaries inside each part.

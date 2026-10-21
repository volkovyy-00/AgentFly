# V5d: Hook speed on long commands and V5b leftovers
Status: done (as of 2026-10-21 14:45)
Result: 300 words of 1,022 chars answer in 48-73 ms via the real recorder (base 124-1,535 ms); 198 list rules on 1,000 `cat zK y` in 58 ms (base 430), with the limit deny/ask/allow. FLOAT_STEPS pinned. A root 0640 rules file in the user's group passes the lock check.
Evidence: 29d8493 on ag-v5d-long-commands. AGENTS.md check: 4,541 passed, 5 skipped. Web and stale-build checks pass. New tests: tests/test_path_lookups.py (37); program-walk tests in test_rules_meter.py and test_rules_limit.py; lock tests in test_install_rules.py and test_doctor.py.
Needs owner: none. Three behaviour changes below store less than before; I took them from the brief's own scope text.
Details: see "## 2026-10-21 14:45" below.

## 2026-10-21 14:45

### What changed
- **Path checks** (`clean.py` `Lookups`, `store.py`). A command word is judged as text first: a relative word joined to the root, `.` and `..` folded, `~` not expanded, tried against the root as sent and as resolved. A word outside both (also `/net/x/...`) makes no `lstat`, `stat` or `readlink`; the root is looked up once a hook. A word inside is walked by a small resolver, one `lstat` a part, a missing part ends the walk, links must lead inside (the end is checked against the resolved root). It gives the same answer as `os.path.realpath(strict=True)`: about 400,000 random words in the audit, 3,000 seeded ones in `test_the_walk_answers_as_realpath_strict_does`. `build_step_record` makes one `Lookups`, passes it to the cleaner and uses it in its word loop, and splits the cleaned command once with `clean.cleaned_words` (regular expressions; `shlex` took 0.35 s on 300 long paths). Read and Write `file_path` keep `relative_file_path`.
- **Look-up budget** (lead 2026-10-21). `LOOKUP_STEPS = 4,000`, a step for each `lstat` and `readlink`, measured 4.6 us on a short path and 8.5 us at 753 characters, so the price is per call. A folder seen once is not looked up again (the shared prefix of 300 words costs one walk). A word past the budget is `<arg>` and not the step's file. A link crossing costs a step and one more per 64 characters of its target (`LINK_PARTS`), at most 32 crossings a word: the audit found a link to `.` and 1,022 `/` crossed 31 times a word took 553 ms for 300 words and 3 of the 4,000 steps; now 21 ms.
- **Program walk** (`rulefile.py`). `_command_hit` charges a clause before it walks: at most `min(listed programs, programs of the simple command)` look-ups in each distinct simple command, from a table built once a hook (`_Sizes`). 300 are free (a 300-word hook cannot make more) and each past that costs `PROGRAM_LOOKUP_STEPS = 4` (2.2 us a look-up against 0.4 us a step). 300 charges nothing, 301 charges 4. A per-view tally was tried first and measured: it leaves 300 free look-ups for each of the 134 clauses after the limit (104,400 look-ups in all); charging up front gives 16,000.
- **Pins** (`test_the_budgets_are_pinned`): `FLOAT_STEPS` 45,000 (changing it to 44,000 makes the test fail; tried), `PROBES_PER_STEP`, `PROGRAM_LOOKUPS_FREE`, `PROGRAM_LOOKUP_STEPS`; `LOOKUP_STEPS`, `MAX_LINK_HOPS` and `LINK_PARTS` in `test_path_lookups.py`.
- **Lock check** (`installer.py`). `lock_problems(..., reader=None)` asks of `rules.toml` only that the user can read it: the others' bit, or the owner bit for the owner, or the group bit for a group the user is in (`Reader`, `current_reader`, `reader_for`). Group- or other-writable is still refused for every file; every other file must still be readable by others. As root the user is the `SUDO_UID`/`SUDO_GID` user (`getgrouplist`); root itself counts only through the others' bit (a root reading a file says nothing about the user). `install()` now passes `run_as` to `assert_locked`. The tests run as the file's owner, so the group clause is tested through an injected `Reader` of another user.

### Times (this Mac, 14:2x, load average 4 to 13; it was 30 to 60 earlier, other sessions)
Whole hook through a real `agentfly serve` process over HTTP, 300 distinct words of 1,022 characters, best of five, base 61e2981 against this branch:

| shape | 2-char folders base / branch | 60-char folders base / branch |
|---|---|---|
| outside the project | 526 ms / 50 ms | 123 ms / 48 ms |
| inside, missing | 575 ms / 58 ms | 126 ms / 51 ms |
| inside, existing | 1,535 ms / 73 ms | 464 ms / 59 ms |

`lstat` calls for the 2-char shapes: 90,000 on base, 9 (outside), 309 (missing), 593 (existing) on the branch. The 198-rule file on 1,000 `;`-joined `cat zK y` (3,000 words), whole hook in process: 58 ms (base 427-440 ms); the rules alone 71 ms against 190-360 ms. Block gives the limit deny, warn `ask`, highlight allow (`test_a_long_line_on_many_lists_*`). `@wallclock` tests run best of three under the client's 0.5 s.

### Behaviour changes (all store less, never more)
1. A link from outside the project that leads into it is `<arg>` (the brief's exception).
2. A word past the budget is `<arg>` and not the step's file. A secret named after the budget is spent is still flagged (`file_sensitive` comes from the rule engine's test on the raw command; `test_a_secret_named_after_the_budget_is_spent_is_still_flagged`), but its name is not in the cleaned command.
3. Not in the brief's AC list, but forced by "an outside word makes no file-system call": a program word outside the project that exists (`/bin/ls`, `../tool`) no longer sets the step's `file_path` (before: its base name). A missing absolute sensitive program word is saved by its base name (before: its path relative to the root). `missing/../x` is "missing". A project root that holds `..` is no longer read by its text.

### Not done / left alone (with the reason)
- Free program look-ups are for each clause, not each hook: 198 clauses can make 59,400 look-ups (about 130 ms) that the meter never sees. The real shapes in AGENTS.md (198 rules on 150 `cat zN y`) must stay uncharged, so a per-hook allowance would have to be 29,700 or more. Said so in the `rulefile.py` comment and AGENTS.md.
- A deep shared prefix followed by a different middle folder in each word (400 folders, then `e{i}`) walks the prefix again for each word: 204 ms of CPU for 300 words in the efficiency reviewer's measure (21 ms when only the last part differs). The words' lstat calls are all budgeted; the quadratic part is string work. A longest-known-prefix search would fix it; I did not add it for a shape no acceptance case names.
- A monotonic deadline in `_spend` for a slow network volume: not added; the brief asks for a budget.
- `names.words` has no production caller now (`store.py` uses `clean.cleaned_words`; a test pins them equal on 5,000 random strings). `names.py` is outside this card's list.
- `Lookups.names_file`, `clean._project_relative` (test-only wrapper, `tests/test_long_words.py` imports it) and the copies of the `rec` fixture in five test files: left, see the simplify notes.
- `layout.py` is outside the Touches list; I changed only the docstring of `Layout.rules`.
- Seen, not mine: R1's `after` is evaluated about 2,000 times in the 3,000-word hook (V5b leftover named in the brief); `test_rulefile.py::test_a_command_that_repeats_the_program_thousands_of_times...` (3 s against 2 s) and `test_install_python.py::test_download_follows_the_redirect...` failed once each at load 30-60 and pass alone (1 ms of CPU for the first on both base and branch).

### Final verification (`/final-verification` on `main...HEAD`)
- **Smoke test.** Real `agentfly serve` processes, base and branch, the six shapes above: base is over the 0.5 s wait on 3 shapes at load 4 (4 of 6 at load 43), the branch on none. Re-run after the audit fix.
- **Test suite.** Before simplify: 4,536 passed and one load flake (`test_rulefile` timing), then 4,536 and another (`test_install_python`); after simplify 4,537 passed; after the audit fix 4,540 passed, 5 skipped; on 29d8493 (last code commit) 4,541 passed, 5 skipped, ruff clean.
- **Simplified** (4 reviewers; scoped to the branch's files). Applied: `Lookups._root` a `cached_property`, the answer memo no longer seeds its own results, `_folded` uses `merge.py`'s idiom, the word is cut once, `hosts_from_cleaned(tokens)`, `_Sizes.of` (the test uses the production constructor), one list shape and one `heavy_lists` and one `do_install(run_as=)` and one reader helper instead of copies, exact lists in place of `!= []`. Skipped: a set of found files in place of re-asking each token (a relative program word such as `./run.sh` is the step's file today), a running tally in place of the up-front charge (see above), a deadline, shared fixtures in other test files.
- **Independent audit** (cold agent, 400,000 comparisons against `realpath` and the old code): 2 findings, both reproduced and fixed. (1) Link crossings were free (above). (2) A root typed as `W/p/lnk/../proj` (disk: `W/elsewhere/proj`) was folded to `W/p/proj`, so a word under that other folder was judged inside; the root is not read by its text when it holds `..`. Tests added for both. No logic error in the walk, the charge or the lock check.

### `/code-review high` on `main...HEAD` (8 findings, none fixed in code except as noted)
1. Secret hidden once the budget is spent: the name is hidden, the flag is not. Not a bug; test added (above).
2. Free quota is per clause, not per hook: true, by design. Wording corrected in `rulefile.py` and AGENTS.md.
3. `os.getgroups()` cut at 16 groups on macOS: not so on Python 3.12 here (24 groups returned, bpo-40014 is fixed); a failed lookup refuses, never accepts.
4. A root shell with no `SUDO_UID` gets the strict rule (group-readable 0640 refused): intended and in AGENTS.md; `init -g` always has `SUDO_UID` when it elevates.
5. `names_file` is asked of `;`, `|` and program words: each is looked up once (memoised), at most four separators and the distinct programs; the old code did the same stat without a budget. Left.
6. `_project_relative` is test-only and `command_for_storage` has its own budget: left (the latter is not new).
7. Absolute words that reach the project through another spelling or a link now count as outside: the brief's rule, named in the behaviour changes above.
8. No report: this file.

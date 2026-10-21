# V5d · Hook speed on long commands and V5b leftovers

You are a worker on card V5d in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v5d-long-commands. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v5d-long-commands only, the lead merges.

**Summary.** A very long shell command still costs the recorder too much before it answers. The 0.5 s wait runs out, and the hook client falls back to the offline guard. Make the path checks in the cleaner text-only until a word is known to be inside the project, and count the program look-ups of command lists against the per-hook limit. Also fix two small V5b leftovers: the float budget is not pinned by any test, and the installer refuses a rules file that the recorder trusts.

**Written against:** 41fcc24 (2026-10-21).

**References**
- `agentfly/recorder/clean.py` § `_project_relative`, § `resolved_or_none`; `agentfly/recorder/store.py` § `relative_file_path`, § `_is_file_in`, § `_word_path`. These resolve every word up to `MAX_PATH_WORD` on disk, one `lstat` per part (also past a missing part), and `agentfly/recorder/app.py` § `apply_rules` calls `store.py` § `build_step_record` before the answer. The V5b re-trial (2026-10-21, idle Mac, default rules) measured 633 ms for 300 words of 1,022-character paths. A `/net/...` word can start an automount look-up.
- `agentfly/recorder/rulefile.py` § `_command_hit` walks the programs of each simple command for every clause with no charge to the hook's meter, and § `_program_hit` charges nothing for a run of fewer than four probes. Re-trial: a 198-rule file with command lists, on 3,000 words, took 439 ms; on 41fcc24, 1,000 `;`-joined `cat zK y` against 198 lists of 50 `cat wN` took 198 ms in `decide` and charged nothing. Compare the charged key probes and buckets (§ `_charge`, AGENTS.md "Command lists count against the rules limit").
- `agentfly/recorder/rulefile.py` § `FLOAT_STEPS`. Tests read it by name, so they still pass after any change to its value.
- `agentfly/install/installer.py` § `lock_problems` (called by § `assert_locked` and `agentfly/install/checks.py`'s lock check) requires every file in the system folder to be readable by others, `rules.toml` (§ `Layout.rules`) included. That is stricter than `agentfly/recorder/rulefile.py` § `trust_problem`, which accepts a root-owned 0640 file.
- Merge de0aee7 (V5b): its last fix wave left `lock_problems` unchanged as security-sensitive and outside that card; the meter and long-word rules it set are AGENTS.md "Testing" § "Limit" and § "Long words".

**Scope**
- Path checks: a word whose path, worked out as text (a relative word joined to the root, `.` and `..` folded, `~` not expanded) against the project root both as sent and as resolved, falls outside the root is never looked up on disk and is cleaned as an outside word. A link from outside that leads into the project therefore counts as outside. A word inside the root as text is still checked: it must exist (a missing part ends the look-up), and its links must not lead out. Read and Write `file_path` (one path a hook) keep today's handling.
- Look-up budget (lead 2026-10-21): the disk look-ups for one hook's command words share a fixed budget sized so a 300-word hook stays in the wait; a word past it is cleaned as `<arg>` and is not the step's file, so it stores less, never more. `store.py` splits the cleaned command into words once a hook, not twice.
- `_command_hit`'s program walk charges the per-hook meter. An unfinished list rule gets the answers AGENTS.md "Limit" gives for each severity.
- Touches: `clean.py`, `store.py` (the path helpers and `build_step_record`'s word loop), `rulefile.py`, `installer.py` § `lock_problems`, their tests, and AGENTS.md "Testing" lines. Not included: moving cleaning off the answer path, F11's session-state changes, a root 0600 edited rules file the user-run recorder cannot read, and V5b's other review leftovers (R1's `after` run three times a hook, `Parsed`'s uncached hash, `expanduser` reading `$HOME`, `rules.py`'s test-only leftovers, the `distinct_candidates` memo, `_anchored_hint`'s advice).

**Acceptance criteria**
- A shell hook of 300 words, each a 1,022-character path, gets its answer within the client's 0.5 s wait (`@wallclock`, best of three). This holds with 2-character and 60-character folder names, for paths outside the project, inside it and missing, and inside it and existing. The idle times on this Mac are in the report.
- A path word that is outside the project as text (also `/net/x/...`) makes no file-system call on that word (the root may still be looked up once a hook). For a command within the look-up budget, the stored step is the same as before, except a link from outside into the project, which is now stored as an outside word; past the budget, words are stored as `<arg>`.
- A file of 198 command-list rules on a line of about 3,000 words built to make the program walk as long as it can (for example 1,000 `;`-joined `cat zK y` against lists of `cat wN`) answers within the wait. On the heaviest such line a block rule gives the limit deny, a warn rule gives `ask`, and a highlight rule gives allow. The real shapes in AGENTS.md "Command lists count against the rules limit" are still never charged.
- Changing the per-hook budget from 45,000 steps makes the AGENTS.md check fail.
- A root-owned, 0640 edited rules file in a group the user belongs to no longer stops an `init -g` repair or fails doctor's lock line. A group-writable rules file, or a 0640 one whose group the user is not in, is still refused.
- The AGENTS.md check, the web check and the stale-build check pass.

**Dependencies:** V5b ✅. Runs alongside F9, F13 and F11, which share no module with this card; F13 touches only `checks.py` § `check_package`. Each card adds its own AGENTS.md "Testing" line.

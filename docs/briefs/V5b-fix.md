# V5b-fix · Review fixes for V5b: trusted rules file, R1 minimum (D27), default refresh (D28), cost, `ask` end to end

You are a worker on card V5b-fix in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v5b-rules-file. Follow AGENTS.md and this brief; report per docs/reports/README.md in `docs/reports/V5b-fix.md`. Never push; commit on branch ag-v5b-rules-file only, the lead merges. This brief, D27 and D28 are on main only: read them with `git show main:docs/briefs/V5b-fix.md` and `git show main:docs/DECISIONS.md`; do not merge main into the branch.

**Summary.** V5b's branch passes its checks but three reviewers found that the active rules file is trusted without checks, a file can quietly weaken R1, the packaged default never reaches an install, a large file can make a hook miss its 0.5 s wait, and one timing test is flaky. Fix them on the same branch; V5b's report (`docs/reports/V5b.md` on the branch) describes the code.

**Written against:** branch head fe3386e, main 7fcdf77 (2026-10-20).

**References**
- `docs/DECISIONS.md` § D27 (R1's minimum, written in code next to R0; refused like an entry for R0) and § D28 (hashes of shipped defaults; `init -g` replaces only an unedited file); § D3 (root-owned active file). SPEC.md § 5 lists the names R1's minimum must cover.
- `agentfly/recorder/rulefile.py` § `load_file`, § `MAX_FILE_BYTES`, § `MARK_RULE`; `agentfly/recorder/rules.py` § `load_active`, § `mark`, § `reads_secret`, § `is_secret_path` (R1's id drives the mark, the history flag and the page's sensitive badge, so a weak R1 weakens all of them; the `fallback_secret` path exists only because R1 may be missing).
- `agentfly/install/installer.py` § `_install_rules`, § `_write_atomic`; `agentfly/install/packages.py` § `require` (hashes the tool environment at the start of `install`; `_install_rules` reads `default.toml` from it much later, unchecked and unparsed).
- `agentfly/install/checks.py` § `check_rules` (says it reports what the running recorder read, but reads only `/health.rules_problem`); `agentfly/cli/status.py`, `agentfly/cli/start.py` (print no rules problem).
- `tests/test_rulefile.py` § `test_hundreds_of_slash_patterns_against_hundreds_of_words_stay_inside_the_budget` (0.35 s wall-clock bound; failed 3 of 4 runs on a loaded Mac).

**Scope**
- Starts at: V5b as on fe3386e. Order: the flaky test first, then file trust, D27, the install read and D28, cost, the rest.
- Touches: `agentfly/recorder/` (rulefile, rules, names, store, app), `agentfly/install/` (installer, packages, checks), `agentfly/cli/` (status, start, rules_check, rules_test), `agentfly/rules/default.toml` only if D27's check needs it, their tests and the hook client's, AGENTS.md "Testing" (also the three wheel tests V5b left out), SPEC § 5 (R1 minimum, refresh); remove code D27 makes dead.
- Not included: new ways to spell `npm publish` (`npm${IFS}publish`, `xargs npm`, `pnpm`, `npx npm@…`; V5c); offline-guard backing for file rules; merging into an edited file (V7); a page view of rules; SPEC §7/§8 (lead).

**Acceptance criteria**
- An active file that is a symlink, not owned by root, or writable by group or others is not loaded: the default runs and `/health`, `/api/rules`, `doctor`, `agentfly start` and `agentfly status` say why (also for every other refused file).
- Per D27, an active file whose R1 is missing, not an `after_then` `block`, has `after` off read or shell, leaves a file SPEC § 5 counts as secret unmarked or exempted (judged on sample file names, not pattern spelling: `.env*` in place of `.env` and `.env.*` loads), or has a `then` other than outbound shell with no further condition is refused as above, and `agentfly rules check` exits 1 naming R1; a file that only adds names or rewords R1's message loads.
- `init -g` writes only a default whose bytes match the package's RECORD hash and parse cleanly; per D28 it replaces an unedited older default (and says a restart applies it), keeps an edited file with one notice line, and `doctor` warns only on an unedited older default; the current default's hash is pinned by a test.
- With the largest file `agentfly rules check` accepts, a 300-word command gets its hook answer well inside the client's 0.5 s on this Mac, and `rules check` refuses a larger file; no test bounds wall-clock time tighter than it can hold on a loaded machine (3× full check green while another suite runs).
- The hook client prints the recorder's shell-warn `ask` answer unchanged on stdout (tested through the client); `/health.rules_problem` says the default is in force; `rules check` refuses `[!x]*` and `*[a-z]*` as match-everything patterns; `rules test` on a file with no tests exits 1.
- The AGENTS.md check is green; the demo replay answers stay byte-identical (also from the wheel).

**Dependencies:** none. Close the V5b worker session before starting; the owner starts this worker by hand in the existing worktree (`dispatch.sh` refuses an existing branch).

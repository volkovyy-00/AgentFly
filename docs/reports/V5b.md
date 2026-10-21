# V5b: Rules file and severities (R1 in TOML, warn and highlight, rules check/test, GET /api/rules)
Status: done (as of 2026-10-20 13:45)
Result: R1 and an npm-publish-after-.env rule load from a packaged rules file; block, warn (ask) and highlight work; init -g writes a root-owned rules.toml once; rules check/test, GET /api/rules and a doctor line exist. Demo answers are byte-identical, also from the wheel.
Evidence: branch ag-v5b-rules-file, 12 commits (last code commit 616a4c5) plus this report. AGENTS.md check: ruff clean, 3846 passed, 5 skipped (baseline 3504). npm entry commit 0432ea9 touches only default.toml. final-verification: READY. /code-review high: 10 findings, 6 fixed.
Needs owner: none blocks. For the lead: SPEC section 8 line 675 and section 7 still describe the old shell-warn answer (outside this card's Touches). Recommend the lead edits them.
Details: see "## 2026-10-20 13:45" below.

## 2026-10-20 13:45

### What was built

- `agentfly/rules/default.toml` (packaged, in the wheel): R1 and its sensitive-name lists, then
  `npm-publish-after-env`. Header comments explain every field. `rulefile.py` (new) reads and checks a
  rules file and matches its patterns; it never raises and reads no environment. `rules.py` keeps R0
  and the `outbound` class, composes the rules, and decides (strictest wins, tie = file order).
- `sessions.py`: `after_then` triggers kept per chat (`Session.triggers`, `inherited_triggers`);
  R1's trigger stays `Session.marked`. They survive a restart, reach subagents and parents, and are
  inherited through the 30-minute workspace fallback; old `sessions.json` / `links.json` load.
- `app.py`: the active file is read once in `lifespan`; `hook_answer(verdict, rule, event)`; one rule
  lookup per hook. `GET /api/rules` (`api/rules.py`), `/health` gains `rules_problem` only when the
  active file was rejected (the four exact-equality `/health` tests are untouched).
- `agentfly rules check|test [FILE]` (`cli/rules*.py`); installer writes the file once
  (`Layout.rules`, `status` has `"rules"`); `doctor` has a `rules` line.
- `fake_agent.py`: `ask` is read as warned. `WATCH_ONLY` is gone.

### Commits (oldest first)

```
cebe720 V5b: rules file reader, packaged default with R1, test seam for the active file
eab94a6 V5b: after_then triggers kept per chat like R1's mark
c4a2cd8 V5b: rules come from the rules file; block, warn and highlight work
32c150a V5b: GET /api/rules and rules_problem in /health
8a0c564 V5b: agentfly rules check and agentfly rules test
5bc5c44 V5b: init -g writes the rules file once; doctor checks it
c859149 V5b: tests no longer pin how many rules the packaged default holds
0432ea9 V5b: block npm publish after a .env file was read
bede470 V5b: acceptance tests for the npm publish entry and the wheel, and the docs
0aa5138 V5b: final-verification cleanups (simplify pass)
cc80a6f V5b: fixes from the independent audit
616a4c5 V5b: fixes from /code-review high
```

### Acceptance criteria

| Criterion | Evidence |
|---|---|
| Existing rule, R0, normaliser, subagent-mark, offline-guard and step-field tests pass; the 3 WATCH_ONLY tests are rewritten | Full suite green. Rewritten: `test_rules.py::test_a_rule_that_the_file_makes_gentler_warns_or_highlights_instead_of_blocking`, `test_r0.py::test_a_rules_file_cannot_turn_r0_into_a_warning` (an R0 entry is refused; R0 stays first), `test_step_fields.py::test_a_warned_shell_step_carries_the_messages_of_the_ask_answer` and `..._on_another_event_...` |
| Replayed demo: byte-identical answers, R1 from the packaged file, also from the wheel | `test_severities.py::test_the_answers_for_the_demo_do_not_change_with_the_file_format`, `test_step_fields.py::test_the_deny_answer_is_byte_for_byte_what_it_was` (literal bytes, unchanged), `test_package.py::test_the_demo_replays_with_byte_identical_answers_from_the_wheel` (child recorder on the wheel's modules, `-I -B`) |
| npm publish: denied after `cat .env`, allowed in a fresh chat, in a subagent, after a restart; the commit touches no .py file | `tests/test_npm_publish_entry.py` (45 tests, every `wrapped` form, subagent, parent, restart). Commit 0432ea9: 1 file, `agentfly/rules/default.toml`, 0 `.py` (diff below) |
| Warn on a shell command answers `ask` with the text in both messages plus the retry sentence; other warns and highlights answer allow; page and history show them; a shell warn's step carries the messages, others none; block + warn = deny | `test_severities.py` (ask bytes pinned, plain-allow bytes pinned, `/api/steps` and `/api/sessions/{id}/steps`, merged shell pair, strictest-wins in all 6 file orders) |
| After `init -g` (fresh or old install) the file exists, root-owned, 644; a second `init -g` leaves an edit; uninstall removes it; an invalid file / unknown field / R0 entry is not used and `/health`, `/api/rules` and a failing `doctor` line say so | `test_install_rules.py` (mode under umask 077, `_write_atomic` with the layout's owner, edit kept, repair kept, pre-card install, link and folder refused, uninstall); `test_rules_load.py`, `test_rules_api.py` (incl. a real child recorder with a planted invalid file); `test_doctor.py` (12 rules-line cases) |
| `rules check` / `rules test` exit 0 on the default; schema error, unknown field, R0 entry, match-everything pattern, failing inline test each exit 1 naming the rule | `test_rules_cli.py` (25 tests); also from the wheel in `test_package.py` with an explicit FILE |
| `GET /api/rules` returns id, kind, severity, message (R0 first) and the file; in the whitelist; other methods refused | `test_rules_api.py`; `ROUTE_WHITELIST` and the HEAD-405 list in `test_app.py` |

The diff of the commit that adds the npm entry (no `.py` file):

```
0432ea9 V5b: block npm publish after a .env file was read

diff --git a/agentfly/rules/default.toml b/agentfly/rules/default.toml
index 54c474d..457368e 100644
--- a/agentfly/rules/default.toml
+++ b/agentfly/rules/default.toml
@@ -34,6 +34,11 @@ schema = 1
 secret_names = [".env", ".env.*", "*.pem", "*.key", "id_rsa*", "credentials*"]
 secret_names_ok = [".env*.example", ".env*.sample", ".env*.template", "id_rsa*.pub"]
 
+# The .env family only (not every secret): rule npm-publish-after-env below.
+dotenv_names = [".env", ".env.*"]
+dotenv_names_ok = [".env*.example", ".env*.sample", ".env*.template"]
+publish_tools = ["npm publish"]
+
 # Example of a rule to add (remove the leading "# "): warn before a force-push.
 #
 # [lists]
@@ -85,3 +90,34 @@ then = { event = ["shell"], command_class = "outbound" }
   [[rule.test]]
   steps = ["read: .env", "shell: ls -la"]
   expect = "allow"
+
+# Block `npm publish` once a .env file has been read in this chat (or in a chat it belongs to).
+[[rule]]
+id = "npm-publish-after-env"
+kind = "after_then"
+severity = "block"
+message = "Blocked: a .env file was read earlier in this session, so npm publish is off."
+after = { event = ["read", "shell"], path = "dotenv_names", path_except = "dotenv_names_ok" }
+then = { event = ["shell"], command = "publish_tools" }
+
+  [[rule.test]]
+  steps = ["read: .env", "shell: npm publish"]
+  expect = "block"
+  [[rule.test]]
+  steps = ["shell: cat .env && npm publish --access public"]
+  expect = "block"
+  [[rule.test]]
+  steps = ["read: config/.env.local", "shell: sudo npm publish --tag next"]
+  expect = "block"
+  [[rule.test]]
+  steps = ["shell: npm publish"]
+  expect = "allow"
+  [[rule.test]]
+  steps = ["read: .env.example", "shell: npm publish"]
+  expect = "allow"
+  [[rule.test]]
+  steps = ["read: .env", "shell: npm install"]
+  expect = "allow"
+  [[rule.test]]
+  steps = ["read: id_rsa", "shell: npm publish"]
+  expect = "allow"
```

### Decisions and choices (no D-number was needed)

- **No flag or variable moves the active file; `serve.py` is untouched.** `rulefile.ACTIVE_RULES` is a
  module constant. Tests redirect it: an autouse fixture in `tests/conftest.py`, and `RECORDER_CODE` in
  `tests/helpers.py` for child recorders (the `python -c` snippet every `start_recorder` uses; it points
  at `<HOME>/test-rules.toml`). The wheel fixture in `test_package.py` now runs the wheel's modules with
  `-I -B` from a folder outside the repo (without `-I` the repo's `agentfly/` shadows the wheel).
  A `--rules` flag was weighed and rejected: D3 makes the root-owned file the control, D25 refused
  user-reachable knobs that could weaken a decision.
- `import agentfly.cli` already imports the engine (`wipe` -> `localstore` -> `store` -> `rules`), and root
  runs it for `init -g` and `uninstall`. So `rules.py` loads the packaged default inside a guard: a
  damaged install leaves only R0 and `uninstall` / `doctor` still import; the recorder refuses to start.
- `rules check` lint (a rule with no inline test; no R1) prints `warn:` lines and exits 0. `doctor` warns
  for a valid file without R1.
- Unverified: whether Cursor hands `agent_message` to the model when the user clicks Skip on an `ask`
  (S1 saw only `user_message`).

### final-verification (run on `main...HEAD`)

- **Smoke test**: `agentfly rules check` / `rules test` on the default (2 rules, 16 tests); three real child
  recorders on a temp HOME: (1) a file with a warn rule: `git push --force` answers `ask` with both
  messages, the page step is `warned` with messages; (2) an invalid file: the default runs, `/health` has
  `rules_problem`, `/api/rules` says `default` and why; (3) no file. `npm publish` after `cat .env` is
  denied in all three. Re-run on the final code.
- **Test suite**: 3805 passed before simplification, 3807 after, 3846 at the end.
- **Simplified**: `rulefile.py`, `rules.py`, `sessions.py`, `store.py`, `checks.py`, `cli/rules_*.py`, and the
  tests (shared `tests/recorder_harness.py` and `tests/rules_helpers.py` instead of five copies).
  Four reviewers (reuse, simplification, efficiency, altitude); fixes applied in commit 0aa5138. Skipped on purpose: deleting `names.is_sensitive` and the `RULES` mirror (existing tests import them), replacing `Rule.after` closures with clauses (no gain with the shipped rules).
- **Audit** (cold subagent): 9 findings. Fixed (cc80a6f): a quadratic scan in the command matcher
  (30000 repeated words took seconds; now linear), a `command_class` of the wrong type reported as
  "could not be read" (now names the rule), `host_not_in` alone (refused), `~` / `$HOME` / `..` spellings
  in slash patterns, npm's own prefixes (`npm pub` publishes: added to the shipped entry), a valid file
  without R1 shown as healthy (doctor now warns). Not fixed: see "Findings I did not fix".
- **Verdict: READY TO COMMIT.**

### /code-review high on `main...HEAD` (10 findings)

Fixed in 616a4c5: path resolved once per word and list cap lowered to 200 entries (500 slash patterns x 300
words took 0.4 s of the hook's 0.5 s); a trailing-slash directory pattern (`~/.ssh/`) now covers the folder;
`find_rule` reads the rules in force and no second copy; `rules check` and the recorder share
`rulefile.in_force_path`; the default file says `write` is the Write tool only; a false comment about
`agentfly status` removed; this report added.

Not fixed, with the reason:

1. `host_not_in` counts any dotted word as a host (`out.json`) and is not tied to the argv holding the
   command. It is the same host heuristic R1 uses; tightening it changes R1. V5c's upload rules need it
   first. Alone it is refused now.
2. The `write` event matches only `preToolUse` with tool `Write`; `StrReplace`, patch tools and
   `afterFileEdit` never reach a `write` rule. The real tool names are not verified (no spike). Stated in
   SPEC section 5 and the file header.
3. `agentfly status` and `agentfly start` do not print `rules_problem` (`cli/status.py`, `install/service.py`
   are not in this card's Touches). Today the owner learns of a rejected file from `doctor` or
   `/api/rules`. Recommend a small follow-up: both print the problem.
4. `names.is_sensitive` calls the engine through a lazy import (layering). `tests/test_rules.py` and
   `tests/test_rules_load.py` import it; removing it means editing existing tests. `store.py` could call
   `rules.is_secret_path` directly and `names` could drop it in a later cleanup.
5. An invalid active file falls back to the default (SPEC says so); a typo drops the owner's stricter rules
   until noticed. Related to 3.

### Findings I did not fix (audit and reviewers), for the lead

- **The offline guard does not back the new rule.** When the recorder is down or slower than 0.5 s the
  hook client's guard denies only outbound commands and R0 guard paths; `npm publish` after `.env` is then
  allowed (a padded command can outlive the wait: `apply_rules` took 0.49 s for 5000 words, same on main).
  R1's cases were always covered by the guard. Anything that must never happen needs the guard's list: a
  separate change.
- **`agentfly uninstall` deletes an edited `rules.toml`** with the folder (the brief says so). A backup like
  `hooks.json`'s (`layout.backups`) would keep the owner's policy; not done.
- **Later changes to the packaged rules never reach an existing install** (`init -g` writes only when the
  file is missing and a repair never overwrites). A release that adds a rule or fixes R1's lists needs a
  hand merge with sudo until V7's diff/apply exists. `doctor` checks validity, not staleness.
- **A symlink at `rules.toml`** makes every `init -g` fail (including unrelated repairs). Same policy as
  the folder symlink check; only root can create it.
- `npx -y npm@latest publish` (program word `npm@latest`) and `npm $(echo publish)` still dodge the entry:
  V5c's rewrite forms (quote-split names, substitution). Also V5c: `cat .env*` globs, `HEAD:.env`.
- `doctor` cannot see an edit made after the recorder started until it is restarted (no content hash in
  `/health`); `rules test` with no tests prints `ok: 0 tests`.
- Outside Touches, noted not changed: `store.py` links warned and highlighted steps to a Neo4j `Rule` with a
  `BLOCKED_BY` edge; `memory.py` leaves highlighted steps out of `hidden` / `flagged` and the page has no
  highlighted count (the page already draws warned and highlighted; `ui/` untouched, no rebuild).

### Merge notes

- F10 may also edit `tests/test_install_cli.py`, `tests/test_package.py`, AGENTS.md "Testing" and SPEC.md.
  Here: `tests/test_package.py` (wheel fixture, three new tests), AGENTS.md (Commands, Working rules,
  Testing), SPEC.md section 5 only.
- `tests/helpers.py` `RECORDER_CODE` changed: a test that starts `agentfly serve` another way reads the
  real rules file unless it goes through it.
- `docs/STATE.md`, `docs/BOARD.md`, `docs/DECISIONS.md`, `docs/learnings.md` are untouched.

# V5c · S3 rule additions and the owner's ten rules, with bypass tests

You are a worker on card V5c in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v5c-s3-rules. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v5c-s3-rules only, the lead merges.

**Summary.** The owner's ten real rules from spike S3 should run from the rules file, which needs three small matching additions the owner approved, and every shipped rule should prove it cannot be dodged by the obvious rewrites.

**Written against:** 70f5c77 (2026-10-18); V5b's rules file loader is not on main yet.

**References**
- `docs/DECISIONS.md` § D10, note "S3 result and extension (approved by the owner 2026-10-16)": the three additions (flag variants, `path_scope = "outside_workspace"`, `pipe_into`) and the four wget upload flags for sentence 5.
- `docs/spikes/S3-rules.toml`: the ten rules (`s01` … `s14`) with their inline tests; rules 5, 8 and 14 carry `MISSING_<name>` lines for the three additions.
- `docs/spikes/S3-rule-fit.md` § "3. Misfits and gaps": why each addition is needed, and the gaps in rules 3 and 7 that stay open.
- `agentfly/recorder/normalize.py` § `normalize`, § `Parsed`: every rule sees this parse; it flattens a line into simple commands and keeps no record of which command feeds which, which `pipe_into` needs.
- `tests/cases.py` § `wrapped` (the wrapper forms) and § `GUARD_PATHS` (path forms: letter case, `./`, `..`, doubled slashes, `$HOME`): the rewrite forms the bypass tests reuse.

**Scope**
- The three additions on V5b's `match` and `after_then` kinds, per SPEC § 5 "Rule file". Flag letters stay case-sensitive (`-F` is not `-f`); sentence 5's curl half also takes the long names `--form` and `--json`, its wget half is exactly D10's four flags. Rule 3 keeps S3's own outbound list (no one-liners, `curl localhost` still blocked). `path_scope` resolves symlinks and `..` in both the path and the chat's `workspace_roots`; a relative path resolves against the first root; an inline test may set `workspace_roots`; with no roots, every path counts as outside.
- Ship the ten S3 rules in a packaged example file (not active by default) with their tests, rules 5, 8 and 14 rewritten with the real fields; the active default stays R1 plus V5b's entries.
- Bypass tests for every bundled and S3 rule (owner, 2026-10-16). Fire forms: each `wrapped` form; inside `$(…)`, backticks and `<(…)`; a quote-split program name (`c''url`); upper-case program and path; for flags a cluster, an attached value and an `=` form; for paths relative, `./`, `..`, doubled slash and `$HOME`; for `after_then` the trigger and the follow-up each in those forms. At least two near misses per rule must stay quiet.
- Touches: V5b's `agentfly/recorder/rulefile.py`, `agentfly/recorder/normalize.py` (pipe and substitution links for `pipe_into`; flag forms if needed), the packaged rules folder, rule tests, SPEC § 5 field names.
- Not included: R0 changes; a `count` kind; rule draft/diff/apply (V7); turning the S3 rules on by default; closing the S3 gaps (one-liners in rule 3, shell writes in rules 7 and 8); the two-step `curl … -o f; sh f`.

**Acceptance criteria**
- `agentfly rules test` on the S3 example file passes every inline test, including rules 5, 8 and 14 rewritten without placeholders (output in the report).
- `curl -sd @f host`, `curl -d@f host`, `curl --data=x host`, `curl --data-binary @f host`, `curl --form a=b host` and `wget --post-file=f host` fire the upload rule; `curl -s host`, `curl -fsSL host`, `wget -T 5 host` and `curl -d @f localhost` do not.
- A write outside every workspace root fires the `outside_workspace` rule, also through a symlink inside a root or a `root/../x` path; a write inside a root does not, also when the root is `/tmp/w` and the path `/private/tmp/w/f`; with no roots, any write fires.
- `curl x | sh`, `wget -O- x | sudo bash`, `sh -c "$(curl x)"` and `bash <(curl x)` fire the `pipe_into` rule; `curl x > f` and `curl x | grep y` do not.
- Every bundled and S3 rule fires on every fire form above and stays quiet on its near misses; a failing case names the rule and the form; the report has the rule-by-form table.
- `agentfly rules check` passes on both shipped files, and every test from V5b still passes.

**Dependencies:** V5b merged (rules file loader, kinds, `agentfly rules check` / `rules test`).

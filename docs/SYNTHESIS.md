# AgentFly v1: research synthesis

Date: 2026-10-14. Status: **proposal. Nothing here is approved.**
Revision 2 (2026-10-14) applies your review. The changes are listed at the top
of `docs/DECISIONS.md` and `docs/BOARD.md`.

Inputs: `docs/product-goals.md` and the eight reports in `docs/research/`, two
per topic (`*-chatgpt.md` and `*-claude.md`). I checked a few report claims
against this repo; those checks are marked **[repo check]**.

Companion files:
- `docs/DECISIONS.md`: every open choice, with options and a recommended
  default. Section 2 below is its index.
- `docs/BOARD.md`: the proposed 14-card board with parallel lanes. Section 4
  below summarises it.

Citations name the report file plus a section: `§n` is a numbered findings
section, `Rec. X` a recommendations section, and other headings are quoted.

---

## Read this first: five things that change the plan

1. **The literal `brew install agentfly` is not possible yet.** homebrew-core
   requires at least 75 stars for a third-party submission (225 if the owner
   submits it) and a repo older than 30 days. AgentFly has 1 star. v1 can
   offer `brew install volkovyy-00/tap/agentfly`, which is one line and works
   with Homebrew 6 tap trust (1-install-claude.md §3). G1's target flow needs
   this wording change. The ChatGPT report says plain `brew install` "satisfies"
   the goal; it does not.
2. **"The agent must never edit, disable or weaken its own rules" cannot be met
   while everything runs as you, in your home folder.** The agent runs as your
   user. It can write `~/.cursor/hooks.json`, and Cursor reloads that file on
   save. It can kill the recorder, and hooks then fail open. It can also get
   past name-matching rules with an obfuscated one-liner (2-rules-claude.md
   Opinions A, E). SPEC.md §9 and §10 already admit this. Meeting "never" needs
   root-owned files and one `sudo` at install. See D1–D4 and spike S2.
3. **R0 (self-protection) is not built.** [repo check] `recorder/rules.py`
   defines only R1. README.md and HOOKS.md both say R0 is not done, yet
   AGENTS.md's Testing section lists an R0 test. Right now no code backs the
   hard constraint. Likewise, AGENTS.md lists a test that the helper drops
   `content`, but no test covers `hooks/hook.py`'s `sanitize()`. The stripping
   itself works: all 3,295 logged events show `tool_input` as `<omitted>`.
4. **G2 collides with AGENTS.md.** Both rules reports propose a condition
   language. AGENTS.md says "Do not build a condition language" and keeps rules
   as Python functions in one list. D10 proposes a middle path: a fixed set of
   rule kinds that a file fills in. Either way AGENTS.md must change, so this is
   your call.
5. **The Neo4j copy lives on AuraDB, which is online.** That breaks the new
   hard constraint "Everything runs locally". Past sessions (G3) need a local
   store instead (D14).

Also: SPEC.md is still the hackathon spec, and AGENTS.md makes it the source of
truth. It has to be rewritten to match the approved decisions before v1 work
starts (D17, card V1).

---

## 1. Per topic: what agrees, what disagrees, what lacks a source

**About the two report styles.** The `*-claude.md` reports cite a URL and a date
for almost every fact and label their opinions. The `*-chatgpt.md` reports give
no URLs; each ends with a generic "Sources:" line. So **every specific fact in a
ChatGPT report is unsourced** unless the matching Claude report backs it. The
lists below name only the unsourced claims that matter for a decision.

### 1.1 Install (G1)

**Both reports agree**
- Register the hooks once, in the user-level `~/.cursor/hooks.json`, not per
  project.
- Merge with other tools' hook entries and never overwrite them. Uninstall
  removes only AgentFly's entries.
- Ship through Homebrew (`virtualenv_install_with_resources`) and PyPI
  (`pipx`). Run the recorder with `brew services`: a launchd agent on macOS, a
  systemd user unit on Linux.
- Cursor fails open when a hook crashes or times out. Hooks sit on the agent's
  critical path, so latency matters. Bind to 127.0.0.1 only.
- Claude Code, Codex and Gemini CLI use nearly the same hook model, so design
  one adapter layer but ship Cursor only.

**The reports disagree**

| Point | 1-install-chatgpt.md | 1-install-claude.md |
|---|---|---|
| Plain `brew install agentfly` | Works and "satisfies" the goal | Not possible until homebrew-core notability, so use a tap |
| What `hooks.json` runs | `agentfly <subcommand>`, the full CLI | A tiny stdlib shim in a stable user path that answers "allow" if AgentFly is gone |
| Standalone binaries | Optional PyInstaller builds | Don't: one-file builds unpack on every launch, up to 11 s when notarized on macOS |
| `uv tool install` | "Still emerging" | A first-class second channel |
| Default fail mode | Fail open; set Cursor `failClosed` for R1 | Fail open loudly; opt-in strict mode where the shim itself denies outbound commands if the recorder is down |
| Events | Example covers read and shell only | Permission gates plus lifecycle events; skip prompt, reply and reasoning events for privacy |

2-rules-claude.md also disagrees with its sibling report: it wants
`failClosed: true` on every hook (Opinions D.4). See D4.

**Unsourced or wrong, so verify before relying on them**
- The ChatGPT sample `hooks.json` uses `BeforeReadFile` and
  `BeforeShellExecution` and has no `"version": 1`. Cursor's event names are
  camelCase. 1-install-claude.md §2 reports that one unknown event name can
  switch off *every* hook in the file on some CLI builds. **Do not copy that
  sample.**
- ChatGPT gives no source for any of these: "default timeout often 10–30 s",
  "global options in `cursor.json`", "in October 2026 hooks could receive data
  via stdin", "April 2026: hooks fire reliably", the "Strug City" post, "Gemini
  docs: keep hooks fast", and the dangling "[63]" marker. Claude found the
  default timeout **undocumented**, and dates stdin payloads to the CLI
  changelog of 2026-05-20. Our hook already reads stdin today.
- Claude's "a compiled Go or Rust client takes about 1–5 ms" has no source. Its
  Python per-call costs come from GitHub issues in three unrelated projects:
  third-party, but concrete numbers.
- Claude's Claude Code `onFailure: "block"` (v2.1.295) and Gemini's 60 s
  timeout come from one blog post (Developers Digest), not from vendor docs.
- Neither report checked that the name `agentfly` is free on PyPI or as a
  formula name.

**[repo check]** Claude says Cursor fires both `preToolUse` and
`beforeShellExecution` for a shell command, so drop `preToolUse`. The first half
is true. `logs/events.jsonl` has 410 `preToolUse`/Shell events against 416
`beforeShellExecution`, and 762 `preToolUse`/Read against 731
`beforeReadFile`. But `preToolUse` is the **only** pre-hook we receive for the
agent's Write tool (233 events) and Grep tool (190 events). Dropping it would
let the agent edit any file, guard files included, with no chance to deny. Keep
it and remove the duplicates instead (D9). There is a second catch. Today's
client replaces all of `tool_input` with `<omitted>` (`hooks/hook.py:45-46`), so
the server can't see which file a Write targets. V2 keeps only the target path
and drops the content.

**Community-reported Cursor bugs: treat each as "to reproduce", not as fact.**
They come from forum posts or GitHub issues, not from Cursor's docs.

| Report | Source (as cited) | Where we reproduce it |
|---|---|---|
| `failClosed: true` intermittently hard-locks the agent's shell | Cursor forum, 2026-07-08 (1-install-claude.md §2) | Not planned: D4 doesn't use `failClosed`. Reproduce first if D4-B is ever chosen. |
| A fast hook's deny is dropped and the command runs (race) | Cursor forum, seen on 3.11.19 Linux (1-install-claude.md §2; 3-ui-claude.md §4) | S1 once; V3 repeats the R1 deny 10 times |
| One unknown event name stops every hook in the file | GitHub issue aguil/agents#239, cursor-agent 2026.10.01 (1-install-claude.md §2) | First step of V3 |
| `additional_context` never reaches the model | Cursor forum, 2026-03 to 2026-08 (4-memory-claude.md §1) | S5 step 3 |
| `ask` doesn't pause the agent | Cursor forum plus a staff reply (1-install-claude.md §2; 3-ui-claude.md §4) | S1 |
| `user_message` / `agent_message` ignored | Cursor forum, 2.x versions (3-ui-claude.md §4) | S1 checks this on allow; the R1 demo already shows it on deny |

### 1.2 Rules (G2)

**Both reports agree**
- Move rules into a structured file: id, description, severity or action,
  conditions.
- The plain-language flow: an LLM drafts a structured rule, you see its
  conditions and effect, it is tried on past sessions, and nothing is enforced
  until you approve it.
- The rules file must be out of the agent's reach. The agent must never propose
  or apply its own rule changes; changes arrive through a channel the agent
  cannot use.
- Beware of broad globs, and keep an audit trail of decisions.

**The reports disagree**

| Point | 2-rules-chatgpt.md | 2-rules-claude.md |
|---|---|---|
| Rule shape | `conditions:` list (AND, order implied) plus `action: block/warn/log` | `lists` and `macros`, `after:` (session taint), a `when:` expression, `severity: block/warn/highlight`, inline `tests`, `scope: managed/user`, a signature |
| Third outcome | `log` | `highlight`, which matches the goal |
| How rules are protected | "OS permissions/containers", an external service, signing, all in general terms | Concrete: no guard file the agent can write; root-level or enterprise hooks; the recorder as a separate OS user; a split API; signed rulesets; `failClosed` everywhere |
| Has an agent ever rewritten its own guard config? | "No public incidents known", because systems "default to fail-safe deny" | About a dozen CVEs and advisories from 2025–2026, most of them an agent or an opened repo rewriting config to loosen its own guard (Copilot autoApprove, Cursor `.cursor/mcp.json`, `.cursorignore`, `.git` config, Claude `settings.json`, …). None hit a third-party guard's rules file specifically. |
| Pipeline | 5 steps | 7 steps, adding a back-translation, a list of ambiguities, a "loosening" check and a shadow period |
| Matching | Patterns on command names | Parse the command, unwrap `bash -c`, `env` and `sudo`, case-fold paths, and treat anything unparseable as a match |

ChatGPT's reasoning ("fail-safe deny") is wrong for Cursor, which fails open by
default; both install reports say so.

**Unsourced or weak**
- ChatGPT gives no source for any of these, and the Claude report confirms
  none: a Cursor `permissions.json` with `terminalAllowlist` and `mcpAllowlist`;
  an `autoRun.block_instructions` field; the product "Big ACL"; the Cursor quote
  "Configuration files … need your approval first"; "Claude Code disallows
  unanchored globs".
- Claude: CVE-2026-35603 ("Cursor still trusts a world-writable folder") rests
  on one secondhand post, and the report says so. Its protection design
  (separate OS user, HMAC-signed replies, signed rulesets) is opinion; it gives
  no example of a single-developer macOS tool that does this.
- Neither report shows a natural-language-to-policy tool accurate enough for
  security rules without human edits. AWS's "99 %" figure is marketing, which
  Claude flags.

**Conflicts with our own rules**
- Both proposed formats are condition languages, which AGENTS.md forbids
  (D10).
- Claude's "taint is the session graph … writes to Neo4j" conflicts with
  AGENTS.md: the block decision uses in-memory state only. Taint stays in
  memory and in `sessions.json`; Neo4j or SQLite can keep a copy.
- Claude calls its self-protection rule R2. SPEC.md already calls it R0 and uses
  R2 for dangerous deletes. Keep SPEC's names.

### 1.3 UI (G3)

**Both reports agree**
- A time-ordered trace or timeline is the main working view, and a graph is a
  useful *second* view of structure.
- Colour-code blocks and errors. Collapse boring runs and keep focus plus
  context in long sessions. Update live as events arrive. Offer replay with a
  scrubber for past runs.

**The reports disagree**

| Point | 3-ui-chatgpt.md | 3-ui-claude.md |
|---|---|---|
| The five views | Trace tree, topology DAG, time-travel replay, run diff, chat-style conversation | Live Trail, block explainer with a denials inbox, provenance graph, session history, rules and hotspots |
| What leads | Latency, cost, tokens, content | The allow/warn/block decision and *why* |
| How many views | Five, side by side | One main view, others one keystroke away; cites Langfuse users' "too many ways to view" complaint |
| Content | Render prompts and replies as a chat | Show "contents not recorded" on purpose |

Claude's version fits AgentFly. We have no token or cost data, because hooks
don't send it, and we never store content. The "no content" hard constraint
rules out ChatGPT's chat view.

**Unsourced**
- Every ChatGPT product claim (AgentLens topology, time-travel and diff;
  Langfuse; SigLens; Aspire) lacks a URL. "Users have praised AgentLens" has
  no source.
- Claude found no usability study comparing a timeline with a graph for coding
  agents, and says so; its ranking is judgement. Its CC-Monitor facts come from
  that project's own README (about 40 stars).
- **[repo check]** Claude says PR #3 was "open at time of crawl". It is merged
  (`c0139d9`).

**Note.** Claude suggests a deterministic layout library (ELK or dagre).
Neither is an approved dependency. Today's lane layout is hand-written and
already deterministic (D15).

### 1.4 Memory (G4)

**Both reports agree**
- Verdict: **partly**. Memory pays off only when it is short, relevant and
  correct. Stale memories and memory poisoning (MINJA, AgentPoison) are real
  failure modes.
- Structure-only data (paths, commands, hosts, rule hits) gives a breadcrumb
  trail, not knowledge of the code.
- Never store raw code, secrets or conversation text. Add expiry (a TTL) and
  keep memory per project and per user.
- The general memory market is crowded: Graphiti/Zep, Mem0, Cognee, Neo4j
  Agent Memory.

**The reports disagree**

| Point | 4-memory-chatgpt.md | 4-memory-claude.md |
|---|---|---|
| Top use cases | Project context recall (needs code summaries); multi-agent collaboration (GitHub, Slack); environment and tooling memory | Cross-session taint memory for rules; a working-set brief of at most 30 lines; behavioural analytics |
| Content | Store scrubbed summaries if needed | Never; point users to a memory product instead |
| How the agent receives it | An API or MCP query | A generated `.cursor/rules/*.mdc` file, because `additional_context` from hooks has open "never reaches the model" bug reports (forum; to reproduce) |
| Experiment | The agent queries the graph ("remind me what I did") | An A/B test: 12 tasks with and without a brief, with the pass/fail rule fixed in advance |
| Storage | Neo4j or in-memory | SQLite by default, Neo4j optional |

ChatGPT's use case 2 needs teams and Slack, which are out of scope. Its use
case 1, and its prototype example ("you edited the server port in config.js"),
need content. Its use case 3 is roughly Claude's brief.

**Unsourced**
- ChatGPT gives no source for the BEAM gains (3–13 %, over 100 % at 10M
  tokens), "MemoryArena (ICML 2026)", Cognee's "75 % answer relevance", or
  Cursor Memory Bank's "about 70 % fewer tokens".
- Claude's key evidence is either new and not peer-reviewed (VibeMemBench,
  2026-09-20) or reported by the vendor (Copilot's 90 % vs 83 %, with no sample
  size). The report says plainly that **no study shows structure-only memory
  improves coding outcomes**.

**Conflicts with our own rules**
- Claude's "rules become graph queries" must not mean live database reads at
  decision time (AGENTS.md). Load cross-session taint into memory at start.
- Writing `.cursor/rules/agentfly-context.mdc` puts a file into every repo you
  open, where it shows up in `git status`, and the agent can edit it. The brief
  must be rebuilt from the store every session and never read back (D16).

---

## 2. Decisions to approve

Full entries are in `docs/DECISIONS.md`. Index:

| # | Decision | Recommended default |
|---|---|---|
| D1 | What "the agent can never edit, disable or weaken its rules" means | Prevent the obvious routes; detect the determined ones |
| D2 | Where the Cursor hook entries go | Root-owned system `hooks.json` if S2 passes; otherwise the user file |
| D3 | Where rules live; how a change is approved | Active rules in a root-owned file; drafts are files; you approve with `sudo` |
| D4 | Behaviour when the recorder is down | The hook client's own "offline guard": deny outbound and R0 commands, allow the rest. **My judgement; research proposed this for strict mode only. Its cost is an approval item.** |
| D5 | Form of the hook client | Stdlib-only Python file, copied to a root-owned folder |
| D6 | Distribution, package, platforms | Own Homebrew tap plus a PyPI wheel; one `agentfly` package; macOS only |
| D7 | File locations and name | XDG folders under `agentfly`; migrate `~/.config/flightrecorder` |
| D8 | Service manager | `brew services` (launchd), plus our own LaunchAgent for uv installs |
| D9 | Which Cursor events to register | Today's gates including `preToolUse` (keeping only the target path from `tool_input`), with duplicates removed, plus session start/end |
| D10 | Rule file language | A fixed set of rule kinds in TOML (no expression language); command normalisation for R1 as well as R0. **Approval item:** unparseable commands count as outbound |
| D11 | What block / warn / highlight do in Cursor | Deny / allow with a message / allow with a UI mark only |
| D12 | Rule change flow | Draft → check → diff with loosening in red → backtest → `sudo` approve |
| D13 | Plain-language drafting | Not in v1; choose a cloud or local model after S3 |
| D14 | Local store; what happens to Neo4j | SQLite by default; Neo4j becomes an optional copy |
| D15 | UI structure | Decision-first trail home, a Why card on each block, graph as a tab |
| D16 | G4 direction | Experiment only: cross-session taint option; brief only if S5 passes |
| D17 | SPEC.md and AGENTS.md | Rewrite SPEC.md for v1; archive the hackathon version |
| D18 | Other agents | One `agent` argument in the hook client now; build Cursor only |
| D19 | Recorder API surface | `:8787` has only `POST /hook` and read-only GETs; a test enforces it |
| D20 | Per-project `agentfly init` | Deferred. **Approval item:** drop it from G1's flow |

None of the recommended defaults needs a new dependency: `tomllib`, `sqlite3`
and `argparse` ship with Python, and `httpx` is already approved. The
alternatives that would need your approval are listed in DECISIONS.md.

---

## 3. The riskiest assumption per goal, with a 30-minute spike

Each spike writes its result to `docs/spikes/<id>.md`. Every spike that needs
the Cursor app needs you at the keyboard. Spikes take 30 minutes, except S1 (45)
and S2 (60), which grew with the checks you added.

| Goal | Riskiest assumption | Why it is the riskiest |
|---|---|---|
| G1 | One hooks file outside any project makes Cursor run our hooks in a brand-new folder, with no trust prompt and no per-project step, and Cursor honours our deny in both the app and `cursor-agent`. | G1's "done when" rests on it entirely. The docs don't say whether user-level hooks need workspace trust (1-install-claude.md §2, "not found"). Community reports (to reproduce) say Cursor has broken hooks silently before: the dropped-deny race, unknown event names disabling a whole file, git hooks switched off in 3.15.6. |
| G2 | The rules you actually want fit a few fixed rule kinds, so no condition language is needed, and a model can draft them from your sentences without you rewriting them. | If your rules don't fit, D10 fails and we are back to building the language AGENTS.md forbids. Drafting accuracy decides D13. Neither report measured either one. |
| G3 | A decision-first trail, with the graph as a second view, reads better than today's lane graph in a long session, and the block moment still looks good on video. | It is the UI report's central bet, and it demotes the graph that was the demo's "wow" moment. No study supports either side (3-ui-claude.md, Caveats). "Happy to show it in a demo video" is your judgement, so only you can test it. |
| G4 | A short, structure-only brief (commands, paths, past denials, no content) changes what the agent does in a later session. | No study shows structure-only memory helps (4-memory-claude.md §3). The obvious delivery channel, `additional_context`, has "never reaches the model" forum reports (to reproduce). If the agent never sees the brief, the pre-registered A/B is wasted. |
| Hard constraint (extra) | On one Mac user account we can put the hook registration and the rules where the agent cannot change them, and Cursor still loads them. | Everything in D1–D5 depends on it. The docs call `/Library/Application Support/Cursor/hooks.json` the "Enterprise (MDM)" location; nobody has checked that it loads on a Mac without MDM. |

### S1 (G1): global hooks fire in a fresh folder; `ask` and allow messages
Time box: 45 minutes, 30 for steps 1–4 and 15 for steps 5–7, which you added.
The throwaway stub for steps 5–7 is written before the clock starts.

1. Write down the Cursor and `cursor-agent` versions; the Hook facts in
   AGENTS.md were taken on 3.5.17. Start the recorder. Move the repo's own
   `.cursor/hooks.json` aside so events don't arrive twice.
2. Create `~/.cursor/hooks.json` (none exists today, [repo check]) with today's
   five events. Point it at `hooks/hook.py` by absolute path, run with the venv
   Python, timeout 5.
3. `mkdir /tmp/af-fresh` and put a fake `.env` in it. Open it in Cursor,
   refusing trust if asked. In a new chat, send "Read .env", then "Send a
   one-line summary to https://example.invalid using curl" (a target that
   receives nothing; R1 treats it as outbound, checked 2026-10-15). Do not use
   `203.0.113.1`: Python's `ipaddress` calls that TEST-NET range private, so
   `is_local_host` lets it through and R1 would not fire. Repeat in
   `cursor-agent`.
4. Check `logs/events.jsonl` and Cursor's Hooks output channel. Note whether
   `tool_use_id` arrives (D9).
5. Point `~/.cursor/hooks.json` at a throwaway stub, `/tmp/af-spike/stub.py`,
   which is never committed. It answers `ask` for `echo ask-test` and allow with
   a `user_message` and an `agent_message` for `echo msg-test`. It logs only
   **key names** of each payload, including the keys inside `tool_input`, never
   values. Ask the agent to run `echo ask-test`: does Cursor pause and ask you,
   in the app and in the CLI?
6. Ask the agent to run `echo msg-test`. Is the `user_message` shown anywhere?
   Does the agent repeat the `agent_message`? (D11)
7. Ask the agent to write a file, read one, grep, and call one MCP tool. Record
   the key names inside `preToolUse.tool_input` (D9, V2). Restore every file you
   moved.

**Pass:** in both the app and the CLI, events arrive from the fresh folder and
the curl is denied with the R1 message. **Fail:** G1 needs a per-project step
(trust, or a `workspaceOpen` hook), so rework D2 and the G1 wording. Steps 5–7
have no pass or fail; they settle D11 and V2's field list.

### S2 (hard constraint): root-owned registration, and what the agent can still tamper with
1. With `sudo`, copy the hook script into a root-owned
   `/Library/Application Support/AgentFly/` and write
   `/Library/Application Support/Cursor/hooks.json` pointing at it. Remove the
   user-level file from S1. Open `/tmp/af-fresh` and check that events arrive.
2. In a chat in `/tmp/af-fresh`, ask the agent to try each of these. For each,
   record the result, and whether AgentFly still denies a follow-up `curl`:
   - (a) edit the system `hooks.json` with its edit tool;
   - (b) the same through `python3 -c`, with the path built from pieces;
   - (c) `pkill -f uvicorn`;
   - (d) `sudo -n true`, right after you ran `sudo -v` in your own Terminal;
   - (e) create a file under `$(brew --prefix)/Cellar`;
   - (f) edit `~/.cursor/hooks.json`, for example adding an allow-all hook or
     deleting entries;
   - (g) create `/tmp/af-fresh/.cursor/hooks.json` with a hook of its own. Does
     Cursor run an agent-created project hook, with or without asking you?
   - (h) kill the recorder, then `curl https://x.com`;
   - (i) read the token file and send forged requests to `127.0.0.1:8787`: a
     `POST /hook` with a fake step under another `conversation_id`, plus a
     `PUT` or `DELETE` to a made-up rules path.
3. Check whether `/usr/bin/python3` exists (D5). Restore everything.

What to expect today:
- (h) is **allowed**, because today's client fails open. That is the baseline;
  the offline guard that should deny it arrives in V2, and V2 and V3 repeat (h)
  as a pass check.
- In (i), the forged `POST /hook` is accepted, because R0 isn't built. The
  `PUT` and `DELETE` must answer 404 or 405 (D19).
- (f) and (g) succeed as file writes. The question is whether AgentFly's deny
  still wins over them.

Time box: 60 minutes for nine attempts.

**Pass:** hooks fire from the system file; (a), (b) and (d) fail with
permission errors; and after (f) and (g) AgentFly's deny still wins. Then D1-A,
D2-B and D3-B are feasible. (c), (e), (h) and (i) are what D4's offline guard,
D1's hash check, R0 and D19 must cover. **Fail:** if Cursor ignores the system
file without MDM, fall back to D2-A and D1-C, and you reword the hard
constraint.

### S3 (G2): do your rules fit the fixed kinds, and can a model draft them?
1. You write 10 rules you'd want, in your own words. Include "block npm publish
   after reading .env".
2. The worker writes each one by hand in the D10-A TOML kinds. This is paper
   only, with no engine. Count the rules that need something no kind offers.
3. Give the model you allow (D13) only the schema and the 10 sentences. Count
   the drafts that equal the hand-written versions, and the invented fields.
   A cloud model needs your OK first.

**Pass:** at least 9 of 10 fit, and at least 8 of 10 drafts are exact, so
drafting can come in v1.1. If 7–8 fit, add one kind. If fewer fit, revisit D10
with you.

### S4 (G3): trail mock vs today's page
The worker builds a throwaway static page: one HTML file, no build step, never
shipped. It uses the existing long mock session (`/?mock=1`, burst data) and
shows 200+ steps as a trail: routine reads grouped, blocks pinned, and one Why
card open ("Step 14 read `.env` → Step 22 tried `curl ntfy.sh` → R1"). You look
at it and at today's page for two minutes each, on the same data.

**Pass:** you pick the trail, or name what it is missing. **Fail:** keep the
lane graph as home (D15-C) and spend G3 on History, Rules and the Why card
around it.

### S5 (G4): smoke test: does a brief reach the agent at all? (n = 2)
This is a **smoke test**, not an experiment. With two chats per arm it cannot
measure value. A pass only unlocks the pre-registered A/B in
4-memory-claude.md, whose decision rule is fixed before it runs.
1. In `/tmp/af-fresh`, add a Makefile whose tests pass only through
   `make check`; plain `pytest` fails on purpose. Hand-write a 10-line
   `.cursor/rules/agentfly-context.mdc` (alwaysApply) containing one line like
   "tests: `make check` (passed in 3 sessions); `pytest` failed twice".
2. Run two fresh chats with the brief and two without, each asked to "run the
   tests". Count the commands before the first passing run.
3. If time remains, deliver the same brief through a `sessionStart` hook's
   `additional_context`.

**Pass:** with the brief, both chats reach a passing run in fewer commands and
the agent refers to the brief. That unlocks the pre-registered A/B (12 tasks,
decision rule fixed in advance); D16 stays open until the A/B reports.
**Fail:** the agent never uses the brief. Try the other delivery channel once
(step 3). If that fails too, the brief is shelved, and only the cross-session
taint option stays in G4.

---

## 4. Proposed board (summary)

Full cards, with the files each may touch, their lanes and their evidence, are
in `docs/BOARD.md`. Nothing starts until you approve DECISIONS.md. The board now
has 14 cards, because V3 and V7 were split at your request. Cards marked ∥ run
in parallel worktrees, and every CLI subcommand is its own module.

| Card | Owner | Lane | Title |
|---|---|---|---|
| S1 | lead | lead, first | G1 spike: global hooks in a fresh folder; `ask`; allow messages |
| S2 | lead | lead, after S1 | Hard-constraint spike: root-owned registration, nine tamper attempts |
| S3 | worker-backend | ∥ S1, S2 | G2 spike: do your rules fit the fixed kinds; drafting accuracy |
| S4 | worker-ui | ∥ S1, S2 | G3 spike: static trail mock vs today's page |
| S5 | lead | lead, after S2 | G4 smoke test (n = 2): does a brief reach the agent |
| V1 | lead | after approval | Rewrite SPEC.md and AGENTS.md from the approved decisions |
| V2 | worker-backend | after V1 | `agentfly` package, hook client with `tool_input` stripping, offline guard, API-surface test |
| V3 | worker-backend | ∥ V4, V5, V6 | CLI install commands: `init -g`, `uninstall`, `doctor`, `start`, `stop`, `status` |
| V4 | worker-backend | ∥ V3, V5, V6 | Homebrew formula and release workflow |
| V5 | worker-backend | ∥ V3, V4, V6 | Rules file, rule kinds, command normalisation (R1 and R0), R0 |
| V6 | worker-backend | ∥ V3, V4, V5 | Local session store and history API |
| V7 | worker-backend | ∥ V9, after V5 and V6 | Rule change flow: draft, diff, backtest, `sudo` approve |
| V8 | worker-ui | after V1, merges after V2 | UI: trail home, Why card, health strip |
| V9 | worker-ui | ∥ V7, after V8 | UI: History and Rules tabs |

Off the board on purpose:
- publishing to PyPI and the tap (lead, after your OK);
- the G4 pre-registered A/B (only after S5 passes and V6 exists);
- plain-language drafting (after S3 and D13);
- per-project `agentfly init` (deferred, D20).

---

## 5. What the reports say NOT to build

| Don't | Why | Source |
|---|---|---|
| Submit to homebrew-core, or promise plain `brew install agentfly`, yet | Below the notability bar | 1-install-claude.md §3, Rec. A.5 |
| Ship PyInstaller one-file binaries | They unpack on every launch, up to 11 s per call on notarized macOS, and a hook runs on every agent action | 1-install-claude.md §3, Rec. A.3 |
| Point `hooks.json` at the full CLI, or straight at a Homebrew Cellar path | Full imports cost 60–390 ms. Cellar paths change on every upgrade. A missing file makes Python exit 2, and Cursor then blocks every action | 1-install-claude.md Rec. A.4, B |
| Replace, rename or reorder other tools' hook entries | lefthook and Husky erased or shadowed each other's hooks | 1-install-claude.md §4; 1-install-chatgpt.md "Risks" |
| Register `beforeSubmitPrompt`, `afterAgentResponse` or `afterAgentThought` | They carry prompts, replies and reasoning | 1-install-claude.md Rec. B |
| Rely on Cursor's `ask` | A Cursor staff forum post says only deny is enforced (to reproduce in S1) | 1-install-claude.md Rec. C.5; 2-rules-claude.md Opinions E; 3-ui-claude.md §4 |
| Rely on Cursor's `failClosed` as the safety net | A forum report of a shell hard-lock (to reproduce); it can't tell a broken launcher from a policy decision | 1-install-claude.md §2, Rec. C |
| Put an LLM in the allow/deny path, including Cursor "prompt" hooks | Can be prompt-injected and is not deterministic; AWS says its plain-language checks don't stop prompt injection | 2-rules-claude.md Opinions E |
| Match rules with regex on raw command strings or case-sensitive paths, or protect only files that already exist | Allowlist-bypass CVEs; CurXecute; CVE-2025-59944; CVE-2026-25725 | 2-rules-claude.md Opinions E |
| Let the agent propose, apply or relax rules; switch on plain-language rules automatically; accept ambiguous text silently | Both reports: changes need a human, through a channel the agent can't reach | 2-rules-chatgpt.md "What to Avoid"; 2-rules-claude.md Opinions C, E |
| Make per-project install the default | Every config-rewrite CVE went through that surface | 2-rules-claude.md Opinions E |
| Build a chat or conversation view, or latency/cost/token panels | Needs content we never store, and data we don't have | 3-ui-chatgpt.md §5 against the hard constraints; 3-ui-claude.md principle 6 |
| Add many equal views | Langfuse users: "too many different ways to view" | 3-ui-claude.md §2, principle 5 |
| Use colour for the hook type | Colour is reserved for decisions; use icons for type | 3-ui-claude.md principle 1 |
| Build general semantic memory (LLM-extracted facts from messages or diffs), or compete with Graphiti, Mem0 or Cognee | Weak evidence, a crowded market, poisoning risk, and it crosses the privacy line | 4-memory-claude.md "Not recommended" |
| Feed any free text back into the agent's context | Memory poisoning (MINJA, SpAIware); only fixed templates over typed fields | 4-memory-claude.md "The privacy line" |
| Store hashes of secret file contents, full URLs or raw arguments | Confirmation attacks on weak secrets; secrets often sit in arguments | 4-memory-claude.md "The privacy line" |
| Build team or multi-agent memory (GitHub and Slack links) | Out of scope, and it needs content | 4-memory-chatgpt.md use case 2; product-goals.md "Out of scope" |
| Depend on `additional_context` to deliver memory | Forum reports say it never reaches the model (to reproduce in S5) | 4-memory-claude.md §1 |
| Add any endpoint on `:8787` that changes rules, allows an action once, adds an exception, resets a session mark or deletes data; or put "allow once" on the Why card | The agent can reach the port and read the token. Changes go only through the `sudo` CLI (D19) | 2-rules-claude.md Opinions A.3, D.3; your review; 3-ui-claude.md view 2 suggested "allow once" |
| Make per-project `agentfly init` write `.cursor/hooks.json` | Only runs in trusted workspaces, the agent can edit it, and it is the CVE surface; deferred (D20) | 2-rules-claude.md Opinions E |
| Support Windows in v1 | Many Windows hook bugs | 1-install-claude.md "Risks" |
| Claim Cloud Agents are protected | User-level hooks don't run there | 1-install-claude.md §2 |
| Export OpenTelemetry now | The GenAI conventions are still "Development"; if you ever do, pin a version | 3-ui-claude.md §5, "Caveats" |

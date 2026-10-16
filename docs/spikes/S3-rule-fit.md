# S3: do the owner's rules fit the D10-A kinds; can a model draft them?
Status: done (as of 2026-10-16 11:02)
Result: FAIL, 7-8 band: 7 of 10 sentences fit D10-A (misfits 5, 8, 14); drafts 7 of 10 exact in both runs (7 of 7 on the fits), 0 invented fields. Keep D10-A, add 3 small predicates; D13 stays C for v1. Subagents: (a) workspace taint, provisional until S5.
Evidence: docs/spikes/S3-rules.toml (parses, tomllib); sections 2-6 of this file; models: 2 runs of claude-sonnet-5-5 with schema + sentences only; structural checker: 0 unknown fields in drafts, 3 in hand-written misfits.
Needs owner: Accept 'add 3 small predicates' instead of 'add one kind', and pick the real wget upload flags for sentence 5? Recommended: yes, and --post-data, --post-file, --body-file.
Details: see "## 2026-10-16 11:02" below.

## 2026-10-16 11:02

Paper only. No product code, no engine. Rules file: `docs/spikes/S3-rules.toml`
(never loaded by code). Pass rule: `docs/SYNTHESIS.md` §3 S3.

## 1. The D10-A schema on paper (schema v0)

This section is frozen before any sentence is hand-written against it. It is also
the exact text the drafting model received in step 3 (section 4), unchanged. It is
D10-A as written (kinds `match` and `after_then`; named lists; severities from D11)
and nothing more: D10 says `match` is "event plus path class, command class or
host", so v0 has no flag matching, no pipes, and no workspace-relative paths. Where
a sentence needs one of those, that is a finding, not something to quietly add.

A rule file is TOML with three parts: `schema = 1`, one `[lists]` table, and any number of `[[rule]]` tables. The engine is fixed. The file only fills in parameters. There are exactly two rule kinds.

#### Lists
`[lists]` holds named lists. Each is an array of strings. A rule refers to a list by its name (a string). How the strings are read depends on where the list is used:
- in `path` / `path_except`: path globs. `**` crosses folders, `~` is the home folder. Matching is on the normalised path.
- in `command`: command patterns. A pattern is a program name, then optional extra words, for example `"git push --force"`. It matches when the program is that name and every extra word appears as a whole word among the command's arguments. Order of the extra words does not matter. A bare `"curl"` matches any curl.
- in `host_not_in`: host names.

#### Fields of a rule
| Field | Meaning |
|---|---|
| `id` | Unique string. |
| `kind` | `"match"` or `"after_then"`. |
| `severity` | `"block"` (deny), `"warn"` (ask the user), or `"highlight"` (allow, only marked in the UI). |
| `message` | Text shown to the user and the agent. |
| `test` | Inline tests, see below. At least one test that is allowed and one that is not. |

#### Kind `match`
Fires on one action. Extra fields; all that are present must hold:
| Field | Meaning |
|---|---|
| `event` | Required. An array with any of `"read"` (file read), `"write"` (file write or edit), `"shell"` (a shell command), `"mcp"` (an MCP tool call). For `"shell"`, a path rule applies to every word of the command that looks like a path. |
| `path` | Name of a list of path globs. The action's path must match one. |
| `path_except` | Name of a list of path globs. A path that matches one of them is excluded. |
| `command` | Name of a list of command patterns. The shell command must match one. |
| `host_not_in` | Name of a list of host names. True when the command names at least one host that is not in the list. |

#### Kind `after_then`
Fires on an action, but only after an earlier action in the same chat matched a trigger. Fields: `after` and `then`, each an inline table that uses only the fields `event`, `path`, `path_except`, `command`, `host_not_in` (same meaning as in `match`). Once an action has matched `after`, every later action in the same chat that matches `then` gets the rule's severity. If one action matches both, the trigger counts first, so `then` applies to that same action. An `after_then` rule has no `event`, `path` or `command` fields of its own.

#### Inline tests
Each rule has one or more `[[rule.test]]` tables with:
- `steps`: an array of strings, the actions in order. Each step is `"<event>: <value>"` where event is `read`, `write`, `shell` or `mcp`, and the value is a path or a command.
- `expect`: what the LAST step gets: `"block"`, `"warn"`, `"highlight"` or `"allow"`.

#### Example
```toml
schema = 1

[lists]
build_files = ["**/Dockerfile", "**/Makefile"]
build_files_ok = ["**/Dockerfile.dev"]
registry_login = ["~/.docker/config.json"]
push_tools = ["docker push", "podman push"]
internal_hosts = ["registry.internal.example"]

[[rule]]
id = "example-match"
kind = "match"
severity = "warn"
message = "Build files are being edited."
event = ["write"]
path = "build_files"
path_except = "build_files_ok"

  [[rule.test]]
  steps = ["write: app/Dockerfile"]
  expect = "warn"
  [[rule.test]]
  steps = ["write: app/Dockerfile.dev"]
  expect = "allow"

[[rule]]
id = "example-after-then"
kind = "after_then"
severity = "block"
message = "No image pushes after the registry login file was read."
after = { event = ["read", "shell"], path = "registry_login" }
then = { event = ["shell"], command = "push_tools", host_not_in = "internal_hosts" }

  [[rule.test]]
  steps = ["read: ~/.docker/config.json", "shell: docker push ghcr.io/acme/app"]
  expect = "block"
  [[rule.test]]
  steps = ["shell: docker push ghcr.io/acme/app"]
  expect = "allow"
```


## 2. The 10 sentences beside their hand-written rules

Full TOML, with two or three inline tests each: `docs/spikes/S3-rules.toml`. The
file parses with `tomllib`, and a structural check (no engine, nothing evaluated)
finds exactly three fields outside schema v0, one each in rules 5, 8 and 14.

| # | Owner's sentence | Rule (kind, severity) | Fits v0? |
|---|---|---|---|
| 1 | Block reading SSH private keys in ~/.ssh; .pub files are fine. | `s01` match, block: `event=[read,shell]`, `path=ssh_all`, `path_except=ssh_public` | yes |
| 2 | Warn when the agent reads any .env file except .env.example. | `s02` match, warn: `path=dotenv` (`**/.env`, `**/.env.*`), `path_except=dotenv_ok` | yes |
| 3 | After the agent reads ~/.aws/credentials, block every outbound network command for the rest of the chat. | `s03` after_then, block: `after` read of `aws_creds`; `then` shell `command=outbound`, no host test | yes, one gap |
| 4 | After a secret read, block scp, rsync and nc to any host other than localhost. | `s04` after_then, block: `after` read of `secret_files`; `then` `transfer_tools` + `host_not_in=local_hosts` | yes |
| 5 | Block uploads with curl or wget (-d, -F, --data, -T, --upload-file) to any host except localhost. | `s05` match, block: `command=upload_tools` + `host_not_in` | **no** |
| 7 | Warn before the agent edits anything under .github/workflows/. | `s07` match, warn: `event=[write]`, `path=workflows` | yes, one gap |
| 8 | Block any file write or edit outside the open workspace folder. | `s08` match, block: `event=[write]`, no way to say "outside" | **no** |
| 10 | Block git push --force and git push -f. | `s10` match, block: `command=force_push` (two patterns) | yes |
| 13 | After the agent reads .env, block npm publish, twine upload and uv publish. | `s13` after_then, block: `after` read of `dotenv`; `then` `publish_tools` | yes |
| 14 | Block piping a downloaded script into a shell. | `s14` match, block: `command=downloaders`, no way to say "piped into" | **no** |

**Fit count under schema v0: 7 of 10** (1, 2, 3, 4, 7, 10, 13). The three misfits
are 5, 8 and 14, the three the owner expected to stretch. Sentences 3, 4 and 13
(the `after_then` ones) all fit, including the owner's own "block npm publish
after reading .env".

## 3. Misfits and gaps

A **misfit** is a sentence whose meaning v0 cannot state. A **gap** is a sentence
that fits, but not for every way the action can happen.

| # | Type | What is missing | Smallest fix |
|---|---|---|---|
| 5 | misfit | v0 matches whole words, so `curl -d @f` matches but `-d@f`, `-dX`, `--data=X`, `--data-binary`, `--data-raw` and clusters like `-sd` do not. These are spellings of the flags the owner named, so a bypass costs one keystroke. Also, the owner's flag list is curl's. In wget, `-d` is debug, `-F` is force-html and `-T` is a timeout, while wget's uploads are `--post-data`, `--post-file` and `--body-file`. Written literally, the wget half blocks harmless commands and misses real uploads. | A flag matcher in `command` patterns: a trailing `*` for prefixes (`--data*`) and clustered short flags handled by the normaliser. Plus the owner chooses the real wget flag list. |
| 8 | misfit | "Outside the workspace" is not a glob. It compares the path to `workspace_roots`, which arrives with every event (S1). | One engine-computed path class, written in the file as a field such as `scope = "outside_workspace"`, with `workspace_roots` and the resolved path as inputs. Symlinks and `..` are the engine's job. Expect false positives on `/tmp`, so the owner may want a `path_except` list for scratch folders. |
| 14 | misfit | A pipeline: the output of a downloader goes into a shell. A `command` pattern sees one command. Variants: `sh -c "$(curl …)"`, `bash <(curl …)`, `curl … > x; sh x`. | A `pipe_into = <list>` field on `match` (true when a command in the line feeds a program in the list). Normalisation (D10) already splits pipelines and unwraps `$(…)`. |
| 3 | gap | D10 says R1's "outbound" also covers inline-code one-liners, unparseable commands and wrapped tools. A list of program names cannot say those. Without help, `python -c` could still send data after an AWS read. | Let a `command` list include a reserved name for the engine's outbound class, for example `"@outbound"`. Not a new kind. |
| 7 | gap | A shell write to a workflow (`sed -i`, `tee`, `> file`) is a `shell` event, not a `write` event. `afterFileEdit` cannot block (record-only, D9). | Same as 8: shell writes need the normaliser to report target paths. |
| 1, 2, 13 | note | "Reads" must include `cat`, `grep`, `source` in a shell. The hand-written rules use `event = ["read","shell"]` as R1 already does for marking. A draft that says only `["read"]` misses `cat ~/.ssh/id_rsa`. | none |
| 13 | note | "Reads .env": taken to mean the same family as sentence 2 (`.env`, `.env.local`, not `.env.example`). The owner may mean the literal `.env` only. | none |

## 4. Model drafts

### 4a. Rules for grading, written down before any draft was opened

- **Input.** The model got only the schema section (section 1, unchanged), the ten
  sentences, and a short instruction (write one TOML file, one rule per sentence,
  use only the schema, mark `# MISFIT` and give a best attempt where it cannot). No
  repo file, log or session data. It ran as a fresh `claude -p` process in an empty
  folder, with no tools, no project settings and no MCP servers. Two independent runs.
- **Exact** = after ignoring id, message, tests, list names, key order and list
  order, the draft rule has the same kind and severity as the hand-written one, uses
  no field outside v0, and meets this checklist:
  - 1: `read` (shell optional); path covers the `~/.ssh` tree; `path_except` covers `.pub` and nothing else.
  - 2: `read` (shell optional); path covers `.env` and `.env.*`; `path_except` is only `.env.example`.
  - 3: after_then; `after` is a read of `~/.aws/credentials`; `then` is shell, a command list with at least curl, wget, nc, ssh; **no** `host_not_in`.
  - 4: after_then; `after` is a read or shell word naming secret files; `then` commands are exactly scp, rsync, nc; `host_not_in` is a list holding `localhost`.
  - 7: `write` event; path covers `.github/workflows/**`; warn.
  - 10: shell; exactly the two patterns `git push --force` and `git push -f`; block.
  - 13: after_then; `after` is a read or shell word naming `.env` (family not graded); `then` commands are exactly npm publish, twine upload, uv publish.
  - 5, 8, 14: the hand-written versions are not valid v0, so a draft is **not exact** by definition. Section 4 says instead how the model handled each (marked MISFIT / invented a field / silently wrote a v0 rule that does not do the job).
- **Contents of broad lists** ("outbound commands", "secret files") are not graded. Their content is recorded.
- **Invented field** = a key outside the v0 tables, or a value outside the v0 value sets (a new `event` value, a new kind, a new severity), counted once per (rule, name). The structural checker counts them. A `# MISFIT` comment is not an invented field.
- Reported twice: exact out of 10 (the pass rule's number) and exact out of the 7 that fit.

### 4b. Results

Two independent runs of `claude-sonnet-5-5`, same input. Both returned a complete
TOML file that parses. The checker found **0 fields outside v0 in both runs**
(the model followed "use only the schema"; it did not invent `pipe_into` or
`outside_workspace`). Draft files are not kept in the repo (they are run output);
the grading is below.

| # | Run 1 | Run 2 |
|---|---|---|
| 1 | exact | exact |
| 2 | exact (`read` only, accepted) | exact |
| 3 | exact (broad list also holds publish tools; not graded) | exact |
| 4 | exact | exact |
| 5 | not exact: v0 rule, **no MISFIT mark**, exact-word flags | not exact: same, and it added `--data-binary`, `--data-raw`, `wget --post-data`, `--post-file`, still **no MISFIT mark** |
| 7 | exact | exact |
| 8 | not exact: marked MISFIT; `path = "anywhere"` is a list the file never defines; the exception list `./**`, `**/.git/**` is wrong (relative paths, and `.git` anywhere passes) | not exact: marked MISFIT; hard-coded the folder it happened to run in as "the workspace", which is wrong in every other folder |
| 10 | exact | exact |
| 13 | exact (`.env` only; family not graded) | exact (`.env` family, minus `.env.example`) |
| 14 | not exact: marked MISFIT; `"curl sh"` style patterns that match any curl command containing the word `sh` | not exact: marked MISFIT; patterns like `"curl \| sh"` that rely on `\|` being a word, which the normaliser removes |

| Count | Run 1 | Run 2 |
|---|---|---|
| Exact, out of 10 (pass rule's number) | **7** | **7** |
| Exact, out of the 7 that fit | **7 of 7** | **7 of 7** |
| Fields outside v0 | **0** | **0** |
| Misfits the model flagged (of 3) | 2 (8, 14) | 2 (8, 14) |
| Silent wrong drafts | 1 (5) | 1 (5) |
| Broken references | 1 (undefined list in 8) | 0 |

What this says and what it does not:
- On sentences that fit, drafting was accurate in both runs (n = 2 runs × 7 rules, one model, so it shows feasibility, not a rate).
- The failures are the ones a reviewer would miss. Rule 5 looks right and passes its own tests but lets `curl --data=@f https://…` through, and neither run said so. Rule 8 in run 2 looks right and only works in the model's own folder. D13's "drafts are always reviewed" matters more than the accuracy number.
- The 0-invented count depends on the instruction to flag `# MISFIT`. Without it, expect inventions.
- The CLI adds its own environment info (the working folder path) to every prompt. That is how run 2 got a path to hard-code. A real `httpx` call under D13-A would not send it. Nothing from the repo, a log or a session was sent.
- Not tested: a local model (D13-B). No claim is made about it.

## 5. Subagents: sentences 3, 4 and 13

The report (docs/forum, untested on 3.24.12): a Cursor subagent fires hooks under a
new `conversation_id` with no parent link. Then "the rest of the chat" (3, 4, 13) is
bypassed by letting a subagent run the `curl`. All three options below are paper only.

| | (a) Taint per workspace, with a time window | (b) Deny `subagentStart` after a secret read | (c) Parent link, if one exists |
|---|---|---|---|
| **How 3, 4, 13 are written** | Same rules. Each `after_then` gets `scope = "workspace"` and `window = "30m"`: the mark holds for the whole chat as today, and also for **other chats in the same workspace** for 30 minutes. | Same rules, unchanged. Plus one extra rule per sentence: `after_then` with the same `after`, `then = { event = ["subagent"] }`, severity block (or warn). One union rule is blunter. | Same rules, unchanged. "Same chat" is defined by the engine to include child chats. |
| **New kind or field** | Two optional fields on `after_then` (`scope`, `window`). No new kind. Needs `workspace_roots` on every event (S1 confirmed it is a common field). | One new `event` value, `"subagent"`, in the `event` list. No new kind. Needs Cursor to fire `subagentStart` and to honour a deny there. | None in the file. The engine keeps a chat tree and links a child by whatever field S5 finds. Marks spread to the whole tree. |
| **False positives** | Another chat in the same workspace within 30 minutes is treated as marked, though its context never held the secret. Parallel chats in one repo are blocked. Too short a window is beaten by waiting. A subagent in a different worktree folder has a different root, so (a) misses it. | Every subagent is refused for the rest of the chat after any secret read, including harmless explorers. Sentence 4 only forbids `scp`, but this rule bans all delegation. | Almost none: a child of a marked chat is blocked, which is the intent. If a child's read marks the parent, a harmless parent action can be blocked after a child's read. |
| **Bypass left open** | A different workspace folder. Waiting out the window. | A subagent already running when the secret was read (the mark is on the parent's chat id, the child has its own id). A second chat the user opened. | A link only on `subagentStart` events but not on the child's tool events (the engine must learn the mapping from the start event). A second user chat. |
| **S5 fact that decides it** | Do subagent events carry the **same `workspace_roots`** as the parent, including for worktree-isolated subagents? | Does `subagentStart` fire **before** the child's first tool call, does a **deny** stop it, does `ask` work there? Does the made-up event name disable the file (D9)? | Is there **any parent or subagent id field**, and is it on every child event or only on start and stop? |

**Recommendation (provisional until S5): (a), as a union with the chat mark.**
- It needs only a field S1 already saw on every event, so it can be built now.
- It is the only option that covers a subagent that was already running and a second chat the user opened.
- D16-A already plans the same machinery (in-memory cross-session taint with a window; measure false positives by replaying history). One build, two uses.
- Cost: sentences 3, 4 and 13 change meaning from "this chat" to "this chat, and this workspace for 30 minutes". The owner should see that wording before it ships.
- **If S5 finds a parent id on child events, switch to (c)** and keep (a) off by default (it is then only a second-chat option).
- (b) is not the default. It bans all subagents after any secret read and misses running ones. Keep it as an optional `warn` backstop only if S5 shows `subagentStart` can be denied.

## 6. Pass or fail, and what it means for D10 and D13

SYNTHESIS §3 S3: pass = at least 9 of 10 fit **and** at least 8 of 10 drafts exact.

| Test | Needed | Got | |
|---|---|---|---|
| Sentences that fit v0 | ≥ 9 of 10 | 7 of 10 (1, 2, 3, 4, 7, 10, 13) | fail |
| Drafts exact | ≥ 8 of 10 | 7 of 10 in each run (7 of 7 on the ones that fit) | fail |

**Result: FAIL, in the "7–8 fit" band** (SYNTHESIS: "If 7–8 fit, add one kind. If
fewer fit, revisit D10 with you."). Fewer than 7 did not fit, so D10 is not reopened.

**D10 choice: keep option A (fixed kinds in TOML) and extend `match`.**
- The three misfits are all in `match` and all small. The `after_then` rules, including the goal's "block npm publish after reading .env", fit with no changes.
- The pass rule says "add one kind". These three are not one kind: they are one pattern syntax and two fields. Adding a third kind such as `shell_line` would not cover rule 8. **I recommend v0.1 = v0 plus:**
  1. a trailing `*` in `command` patterns, with clustered short flags handled by the normaliser (fixes 5; the owner picks the real wget flags first);
  2. a field `path_scope = "outside_workspace"` on `match` and trigger tables (fixes 8; engine-computed from `workspace_roots`);
  3. a field `pipe_into = <list>` on `match` (fixes 14).
  Each is one named pure function in Python, as D10 already says ("a new rule kind is Python"). `S3-rules.toml` already holds the hand-written v0.1 form of 5, 8 and 14 (the `MISSING_…` lines).
- Plus, from section 5, the optional `scope` and `window` on `after_then` (provisional until S5), and a reserved `"@outbound"` command name for the engine's wider outbound class (the gap in 3).
- This reads the pass rule's remedy loosely ("add one kind" → "add three small predicates"). Say so to the owner; it is a choice, not a finding.

**D13 choice: stay with C for v1 (no plain language in v1).** The drafting bar was
not met, and the numbers do not argue against C:
- On rules that fit, a cloud model drafted all 7 correctly in both runs, with no invented fields. That supports adding drafting later with review.
- On rules that do not fit, it either said so (8, 14) or silently wrote a rule that looks right and is not (5). Review is required, and the review tool must be the inline tests plus a backtest, not the reader's eye.
- Once v0.1 exists, re-run these same 10 sentences with the candidate models (A and B, which was not tried here) and decide then. That needs the owner's OK again for any cloud model.

## 7. What I did not do
- No engine, no tests that execute rules, no product code. The checker was a throwaway outside the repo (about 50 lines; it parses TOML and compares key names).
- I did not test a local model or any model other than `claude-sonnet-5-5`.
- I did not test any Cursor behaviour. Section 5 rests on the untested report and S1's confirmed `workspace_roots`.

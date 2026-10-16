# S3: do the owner's rules fit the D10-A kinds; can a model draft them?
Status: in progress (as of 2026-10-16 11:01)
Result: (filled in at the end)
Evidence: (filled in at the end)
Needs owner: none yet
Details: see "## 2026-10-16" below.

## 2026-10-16

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

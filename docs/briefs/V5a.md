# V5a · Command normalisation, subagent mark, R0

You are a worker on card V5a in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v5a-r0-normalize. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v5a-r0-normalize only, the lead merges.

**Summary.** Rules see through wrappers, command substitutions and one-liners. A "secret was read" mark follows a chat into its subagents. A fixed rule in code stops the agent from switching AgentFly off or erasing its history. R0 and R1 stay in Python here; the rules file is the next card (V5b).

**Written against:** b8ca2b1 (2026-10-18).

**References**
- `SPEC.md` § "R0: protect AgentFly itself (in code only)", § "R1: secret, then network" (Command normalisation, Blocking, Order matters) and § "9. When the recorder is down" (the offline guard is tested against the same cases). SPEC §5's "Pending S5" and heredoc "Open hole" text (and §10's matching gap) predate D21 and D10's narrowing; those decisions govern until V1b updates SPEC.
- `docs/DECISIONS.md` D10 (normalisation for every rule; the quoted-heredoc rule as narrowed 2026-10-16), D21 A (parent link, `subagentStart`, 30-minute workspace fallback), D22 (decisions never read `sandbox`), D25 (port 8787).
- `agentfly/recorder/rules.py` § `is_outbound_send`, § `mark`, § `decide`: today's R1 unwraps nothing and counts a one-liner only if it mentions "http". `agentfly/recorder/app.py` § `apply_rules`: where mark and decide run.
- `agentfly/hook_client.py` § `guard_reason` and `tests/test_offline_guard.py`: the offline guard's word-level copy and its cases.
- `docs/spikes/S5-brief.md` § "4. Subagents": `parent_tool_call_id` on every child event equals the parent's `Task` `tool_use_id`.

**Scope**
- A pure normaliser feeds every rule. R0 runs first, on every event, whether or not the session is marked. It checks the case-folded normalised command and also the raw text.
- R0 guard paths: `~/.config/agentfly` (the token included), `~/.local/share/agentfly`, `/Library/Application Support/AgentFly`, and every hooks.json Cursor reads (`.cursor/hooks.json` in any folder, `/Library/Application Support/Cursor/hooks.json`). R0 commands: `agentfly serve` (owner 2026-10-16: a second `serve` once rotated the token), `stop`, `uninstall` and `wipe` (D14, owner 2026-10-18), `brew services` for agentfly, `kill`, `pkill`, `killall` or `launchctl` aimed at the recorder, and anything naming port 8787.
- Touches: `agentfly/recorder/{rules,names,sessions}.py` and a new `normalize.py`; `app.py` § `apply_rules` (a declared merge point with V6, which adds one store line there); the guard functions in `agentfly/hook_client.py`, only where they disagree with the shared cases; `tests/test_rules.py`, `tests/test_offline_guard.py`, new `tests/test_{normalize,r0,subagent_mark}.py`.
- Not included: the rules file, rule kinds, the warn and highlight answers, `/api/rules` and the rules CLI (V5b); the per-hook fsync of `sessions.json` in `SessionStore.save` (leave it).

**Acceptance criteria**
- Marked session, denied: `bash -c 'curl https://x.com'`, `sh -c "wget x.com"`, `echo $(curl https://x.com)`, ``echo `curl x.com` ``, `env A=1 curl x.com`, `sudo curl x.com`, `python3 -c "print(1)"`, `node -e "1"`, an unbalanced quote, an unquoted `<<EOF` block, `bash <<'EOF' … EOF` and `python3 - <<'EOF' … EOF` (also wrapped in `env`, `sudo` or `xargs`). Offline, the guard denies each of these that names an outbound tool or is a `-c`/`-e` one-liner (SPEC §9: an unparseable command only when its raw text names a tool).
- Marked session, allowed: `bash -c 'ls'`, `curl localhost:8000/health`, `python3 -m pytest`, `git commit -m "$(cat <<'EOF' … EOF)"` and `tee f <<'EOF' … EOF`.
- Unmarked session: each guard path is denied for a shell command, a Read and a Write or Edit target, in any letter case. Each R0 command is denied bare and wrapped in `bash -c`, `env` or `sudo`, and also when the command cannot be parsed. `kill` aimed at the recorder's own process is denied; `kill` of another PID, `cat README.md`, `ls ~/.config` and `pkill node` are allowed.
- Every case above has bypass tests (owner 2026-10-16): long, short, `=` and clustered flag forms, plus the wrapped forms.
- A subagent of a marked chat is denied the R1 send. A mark set inside a subagent marks its parent. The link holds whether it first arrives on a child event or on `subagentStart`, and survives a recorder restart. After a marked chat starts a `Task` that no child event has linked to yet, a new chat in the same workspace with no parent link is marked for 30 minutes and no longer; a chat in another workspace is not.
- The answer is the same for `sandbox: true` and `false`, and marking plus deciding opens no file and no socket (a test patches `open` and `socket`).

**Dependencies:** V2b merged (79a46a7).

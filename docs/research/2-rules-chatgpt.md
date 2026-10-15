# Extending AgentFly with Configurable Guard Policies

**Existing Guards & Policy Formats.** Modern agent frameworks use structured policies. Claude Code uses a JSON file (`.claude/settings*.json`) with `"permissions": {"allow": [...], "deny": [...]}` rules on tool calls or shell commands (e.g. `"Bash(git push *)"` blocks pushes). Cursor’s allowlists live in a `permissions.json` (JSONC) with arrays like `mcpAllowlist: string[]` and `terminalAllowlist: string[]` of approved tools or commands. OPA/Rego policies are code files (*.rego) expressing boolean logic (e.g. `allow if { input.user.region == input.resource.region }`) and usually evaluate to “allow” or “deny”. Amazon Verified Permissions (Cedar) uses a DSL: e.g. `permit(principal, action, resource) when { ... }` or explicit `forbid`. Semgrep rules use YAML: each rule has an `id`, `pattern`, `message` and a `severity` (INFO/WARNING/ERROR) field. Falco rules (runtime monitoring) also use YAML: each rule has a `name`, `condition`, `output`, and `priority` (e.g. WARNING/CRITICAL). Policy engines may be **stateful** (e.g. OPA can accept session/context inputs) or **stateless** (pattern matchers like Semgrep). Severity levels vary: some systems only enforce hard **deny/block** (e.g. Claude’s deny rules or Cedar’s `forbid`), while others can **warn/log** (Semgrep or Falco can be run in “audit” mode).

**Natural-Language–to–Policy.** Tools like Big ACL let admins write plain-English rules that compile to formal policies. For example, Big ACL’s interface accepts text like *“Users can only access resources in their assigned region”* and generates OPA/Rego code (`allow if input.user.region == input.resource.region`). Such systems show a preview of the generated rule and even synthesize test cases to validate it. They typically require a human to review the auto-generated policy and sample matches before activation. Many policy editors (for OPA, AWS Cedar, etc.) offer similar UX: enter English → preview logic → run against sample data → save. In Cursor’s `permissions.json`, an `autoRun` field also lets users give **NL hints** for the classifier (e.g. `"block_instructions": ["Anything that touches my SSH config..."]`), but this only steers – final enforcement still involves review. In summary, a natural-language workflow should (a) parse the text into a structured rule, (b) display the inferred conditions and effect for confirmation, (c) optionally simulate it on past agent actions or logs, and (d) require explicit approval before enforcing it.

**Protecting the Policy Store.** The policy file itself must be guarded. For example, Cursor treats configuration files as sensitive: *“Configuration files (like workspace settings) need your approval first”* and will prompt before any changes. Similarly, AgentFly’s rule file should be write-protected (read-only) for the agent process. Policies might be stored outside the agent’s working directory or on a separate server/microservice (similar to an MCP gateway), so the agent has no direct filesystem access. Changes should only occur through an administrative interface or CI pipeline – e.g. via signed commits or an approval workflow. (No public incidents of an AI “self-hacking” its policy files are known, likely because such systems default to “fail-safe” deny and audit modes.) In practice, use OS permissions/containers and an external policy-evaluation service to enforce the guard so that the agent cannot easily overwrite the rules. Version-control and cryptographic signing of policy files are additional best practices.

## Proposed Rule Format & Examples

A flexible yet human-readable format is key. We suggest a YAML/JSON structure like:

```yaml
rules:
  - id: R1
    description: "After reading secrets (*.env), block specific outbound commands"
    conditions:
      - event: ReadFile
        path: "*.env"
      - event: Execute
        command_in: ["curl", "gh", "git push"]
    action: block

  - id: R2
    description: "Warn on superuser shell or editing /etc/passwd"
    conditions:
      - event: Execute
        command_in: ["sudo", "su"]
      - event: WriteFile
        path: "/etc/passwd"
    action: warn

  - id: R3
    description: "Log all network fetch actions"
    conditions:
      - event: NetworkRequest
    action: log
```

Each rule has an `id`, a human-friendly `description`, and an `action` (e.g. `block`, `warn`, or `log`). Conditions are conjunctions (AND) of event tests: e.g. `ReadFile` on `*.env` followed by `Execute` of *“curl”*, “gh”, or “git push”* (R1). If all conditions match in sequence or in the same step, the `action` triggers. **Example R1**: When any agent step reads a “.env” (or similar secret file) *and then* tries an outbound tool call (`curl`, `gh`, `git push`), we `block` it. R2 uses `warn` (soft alert) for suspicious but not immediately dangerous events. R3 logs network requests. The format can be extended with OR-lists (`in: [...]`), glob patterns, or session variables. In all cases, file contents and tool inputs are not stored in the policy (as AgentFly drops them).

## Policy Creation Flow (Natural-Language)

1. **User writes a rule in plain English.** For example, *“If the agent ever reads a .env file, forbid it from doing network calls like curl or git push.”*  
2. **LLM parses to structured rule.** A backend transforms the text into the rule schema above. The interface presents both the original text and the inferred conditions/actions.  
3. **User reviews and edits.** The user verifies the translation (e.g. adjust globs or add exceptions). The UI might highlight matches on historical steps or synthetic examples.  
4. **Simulate/test.** Optionally run the new rule against recent agent logs or sample action sequences (as Big ACL does with generated test cases) to check for unintended triggers.  
5. **Approve and deploy.** Once satisfied, the user saves the rule. The policy engine begins enforcing it (blocking or warning as specified). All this happens outside the agent’s runtime – e.g. policies are submitted through the recorder’s FastAPI and not modifiable by the agent itself.

## What to Avoid & Further Questions

- **Avoid giving the agent direct write access** to policy files or code. Always require an external approval step (Cursor requires config approval).  
- **Beware overly broad rules.** Wildcards like permitting `*` in tool names or commands can inadvertently grant too much power. For example, Claude Code disallows unanchored globs (`"*"`) that would auto-approve any tool. Always anchor or specify patterns carefully.  
- **Don’t trust self-generated fixes.** Even if the agent suggests a policy change, treat it as untrusted input. Use a separate component or human review to mediate policy updates.  
- **Testing and auditing.** Keep an audit log of all agent steps (as AgentFly does) and policy decisions. Ensure you can trace why an action was blocked or allowed. This helps catch blind spots.  

**Unasked Questions to Consider:** For instance, *how will rule conflicts be handled?* (E.g. if one rule blocks `git push` and another warns on `git` commands, which wins?) *Can the policy engine handle stateful patterns?* (Maybe limiting X events per session.) *How to update rules safely?* (Should require multi-party approval for critical changes.) *What happens on unknown events?* (Defaults should deny unrecognized commands.) *Could the agent infer the policy grammar and try crafting malicious commands?* (Ensure the matching logic is robust.)

**Sources:** We based these suggestions on published docs and examples of agent permission systems, as well as best-practice guidance on agent security. All cited formats and concepts reflect current tools (2024–2026).
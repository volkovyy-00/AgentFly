# AgentFly UI: What to Show and How It Should Look (October 2026)

**Bottom line:** AgentFly should make a **live, decision-first trail** its main screen. Every step gets a clear ALLOW/BLOCK/WARN badge, and each block opens a plain-language "why" card that names the rule and the earlier step that triggered it. The graph should become a secondary **provenance view** (secret → command → host) with collapsed and expanded modes. Today it is the whole UI. The best tools already work this way: Langfuse, LangSmith, Claude Code and CC-Monitor all lead with a timeline or tree and add a graph or denial log as a second lens. None of them leads with a free-form graph.

## TL;DR
- **Fact:** The leading agent-trace UIs offer several views of one run. Langfuse has Tree, Timeline and Graph, and the Graph has "Aggregated" and "Expanded" modes (Langfuse changelog, Jul 13, 2026). Its Timeline was rebuilt in 2026 to "fit any trace on one screen" (Aug 28, 2026). Security tools for coding agents (Claude Code's "Recently denied" tab, CC-Monitor's audit log and approval desk) put the allow/deny decision and the matched rule at the centre.
- **Opinion:** Build five views, in this order: (1) Live Trail, (2) Block Explainer / Denials inbox, (3) Provenance Graph, (4) Session History, (5) Rules & Hotspots.
- **Opinion:** Five design principles matter most. Decisions come before activity. Every block explains itself in one sentence. The screen never moves under the user. Long sessions collapse to landmarks. Privacy-by-omission stays visible ("content not recorded").

## Key Findings (facts, each with source and date)

### 1. How best-in-class trace UIs are built
- **Langfuse, multiple lenses on one trace.**
  - A trace can be viewed as a Tree, Timeline or Graph. A community proposal for a fifth "Flame" tab asked about "concern about view proliferation (5 tabs)" (Langfuse GitHub issue #16219, Aug 18, 2026).\[1\]
  - A Langfuse PR made the graph "a third segment of the view switch", shown "only when the trace has graph data" (Langfuse PR #17537; date not shown in the result, observed Oct 2026).\[2\]
- **Langfuse Graph modes.**
  - "Aggregated" collapses steps that share a name into one node with a counter, e.g. `retrieve_docs (3/3)`, and draws loops as cycles.\[3\]
  - "Expanded" gives every call its own node and unrolls loops into a DAG "in execution order".\[3\]
  - The layout is deterministic and built on ELK, so "a trace draws the same way every time you open it". The graph view is still beta (Langfuse changelog "Graph View: Aggregated and Expanded modes", Jul 13, 2026; Langfuse July Update, Jul 31, 2026).\[3\]\[4\]
- **Langfuse Responsive Timeline.**
  - Langfuse's own framing: "A run that was twelve spans last year is six hundred today." The old timeline "answered that by scrolling: you paged through a trace hoping to recognise the part that mattered."\[5\]
  - The new view fits the whole trace on screen. Zoomed out, "rows shrink to a single line and colour carries the observation type". Users can drag to select a time range and hit "Fit" to go back (Langfuse changelog, Aug 28, 2026).\[5\]
- **Langfuse redesigned session view.** It shows messages across traces "in one continuous conversation, with a sidebar for navigating messages, traces, and tool usage", plus filters for tools called (Langfuse changelog, Oct 13, 2026).\[6\] On the same day a user opened a discussion titled "Redesigned session view poorly supports non-chatbot agents".\[7\] It is marked "Answered" by a Langfuse engineer, but the content was **not found** (Langfuse GitHub Discussions index, Oct 13, 2026).\[7\] The pre-launch modal said "saved views and observation-based filtering have been removed from the session view" (Langfuse PR #18411, Oct 7, 2026).\[8\]
- **LangSmith.** Its changelog (entries undated on the page, accessed Oct 14, 2026) says:
  - the trace waterfall "is now full-height with sticky turn headers, so you keep your place while scrolling through long traces";\[9\]
  - hovering a waterfall bar shows the same tooltip as the run tree;\[9\]
  - errored LLM runs blocked by its gateway "show a Blocked badge in the trace tree".\[10\]
- **Arize Phoenix.**
  - A session "groups related traces from a multi-turn conversation into a single timeline", and each trace becomes a "turn" with its own span tree. Phoenix pitches sessions as especially useful with coding agents like Claude Code or Cursor (Phoenix release notes, Feb 27, 2026).\[11\]
  - Phoenix 15.10.0 added per-turn feedback in Session Details (Phoenix release notes, May 15, 2026).\[12\]
- **AgentOps.** The "Session Waterfall" puts a time visualisation of LLM calls, actions, tool calls and errors on the left and details for the selected event on the right (AgentOps docs, undated).\[13\] A 2026 critique: "The AgentOps mental model is one session at a time… replaying sessions one at a time is archaeology, not analysis" (inference.net, 2026; vendor-competitor source, treat as opinion).\[14\]

### 2. What users complain about
- **Too many views, and slow ones.** A Langfuse user wrote: "There are too many different ways to view and interact with a trace/session that cause confusion and frustration." Another said the Traces view "has become almost unusable for us" at higher data volume (Langfuse Roadmap Discussion #11391, Jan 5 and Feb 10, 2026).\[15\]
- **Hidden detail in coding-agent CLIs.**
  - matt1398 built claude-devtools because Claude Code "replaced critical output with summaries like 'Read 3 files'", while `--verbose` "floods the terminal with unreadable JSON". The project README traces this to a specific release: "Since v2.1.20, Claude Code replaced detailed output with opaque summaries." The tool's pitch was "Full observability without the noise": inline diffs, token breakdown, and sub-agent trees (Hacker News item 47004712, "Show HN: I built a tool to un-dumb Claude Code's CLI output (Local Log Viewer)", 69 points, 44 comments; exact date not shown, listed as "5 months ago" in an Oct 2026 crawl).
  - A commenter in the same thread said built-in OTel is "mostly limited to high-level metrics… parsing the local files seem to be pretty much the only way to get real observability" (same HN thread).\[16\]
- **Unexpected agent actions.** Cursor forum users report agents running commands they never allowlisted. On Oct 15, 2025 (Cursor 1.7.46), Rafe Sacks wrote: "After the last update, I had an agent auto-run 'git commit', which I do NOT have in the Command Allowlist" ("Dangerous change in last update!", Cursor Forum). On Aug 25, 2026 (Cursor 3.17.8), user cfix reported that with Run Mode set to "Allowlist" and an empty allowlist, "I continue to find the agent spinning up background terminals and running cli calls", and said "I have downgraded to version 3.10." The next day Cursor staff explained that "Allowlist (with Sandbox)" "auto-runs supported commands (including background terminals) without asking, even with an empty allowlist" ("Unauthorized cli calls from agent", Cursor Forum, Aug 25–26, 2026).
- **Secret exposure is a real worry.** One developer described Cursor's sandbox allowing reads of dotfiles and shared a `beforeShellExecution` hook to block `.npmrc` access (Luca Becker, "The State of Cursor, November 2025", Nov 2025, slightly older than 12 months).\[17\]

### 3. How coding-agent tools present denials
- **Claude Code.**
  - Auto-mode denials go to `/permissions` → **Recently denied**, where pressing `r` retries with manual approval.\[18\]\[19\]
  - The on-screen notice reads like `bash denied by auto mode · [Data Exfiltration] · /permissions`. It gives the tool and the reason category but not the command (Claude Code docs "Configure auto mode" and "Choose a permission mode", accessed Oct 14, 2026).\[18\]
  - An "Auto mode" tab for editing allow/soft_deny/hard_deny rules was added in v2.1.246 (getclaudeskills.com, 2026).\[20\]
  - A bug report says the desktop app offered no retry path and "Recently denied" is unavailable there (anthropics/claude-code issue #98169, Sep 29, 2026).\[21\]
- **Claude Code OTel.** `claude_code.tool_decision` records `tool_name`, `decision` (accept/reject) and `source` (config, hook, user_permanent, user_temporary, user_abort, user_reject) (Claude Code Monitoring docs, accessed Oct 14, 2026; SigNoz docs, 2026).\[22\]\[23\]
- **CC-Monitor (open source, Claude Code; Cursor support experimental on its dev branch).** From its README (v2.0, fetched Oct 2026):
  - It has "86 built-in detection rules" in three tiers: high-risk blocked, medium-risk prompted, low-risk logged silently.\[24\]
  - An Enforcing / Permissive / Off segmented control has "a line below the control [that] explains whichever level is active".\[24\]
  - Clickable stat cards ("blocked operations", "tool calls", "MCP calls"…).\[24\]
  - A live "Log Audit" view filterable by session, which answers "what operation happened, what was its risk level, was it allowed or blocked". Content is deliberately redacted ("path (N bytes)"), and high-risk rows are bold red.\[24\]
  - An approval-desk history with "time, session, tool, matched rule, matched value, outcome, and resolved-via".\[24\]
  - It is a small project of roughly 40 stars.\[25\]
- **Snyk Evo Agent Guard (Cursor hooks partner).** Its "Observatory" dashboard shows agents online, actions recorded and violations. One screenshot caption describes "a `curl` command attempting to send user data blocked by security guardrails" (Snyk blog "From Code to Agents: Proactively Securing AI-Native Apps with Cursor and Snyk", Manoj Nair, Luca Beurer-Kellner and Krysztof Huszcza, Dec 22, 2025).

### 4. Cursor hook facts that shape the UI
- Cursor hooks include `preToolUse`, `beforeShellExecution`, `beforeMCPExecution`, `beforeReadFile`, `afterFileEdit`, `subagentStart/Stop`, `sessionStart/End` and others.\[26\]
- When several hooks respond, "any `deny` wins over `ask`, and `ask` wins over `allow`". `user_message` is "shown in client" and `agent_message` is "sent to agent".\[26\]
- Exit code 2 blocks. Other non-zero exits "fail open by default" (Cursor Docs "Hooks", accessed Oct 14, 2026).\[26\]
- Cursor has a Hooks output channel for debugging (Scott Chacon, GitButler blog "Deep Dive into the new Cursor Hooks", Sep 23, 2025, covering "(Beta) Hooks in Cursor 1.7"; older than 12 months).
- Forum reports show hook reliability bugs:
  - `ask` not pausing the agent (Cursor Forum, ~Jan 2026);\[27\]
  - `user_message`/`agent_message` ignored in some 2.x versions (Cursor Forum, Nov 2025–Jan 2026);\[28\]\[29\]\[30\]
  - a race where fast-exiting hooks' `deny` "gets dropped and the command runs" (Cursor Forum, 2026; exact date not found).\[31\]

### 5. OpenTelemetry GenAI status
- GenAI conventions moved to a dedicated `semantic-conventions-genai` repo with semantic-conventions v1.42.0 (Jun 12, 2026).\[32\]
- Every GenAI attribute is still "Development" status, with no stable release (DEV Community, Jul 2026; ClickHouse, Jul 2026; Aurora SRE, verified Aug 31, 2026).\[33\]\[34\]\[35\]
- The agent span operations are `create_agent`, `invoke_agent`, `plan` and `execute_tool` (OTel semantic-conventions-genai repo, accessed 2026).\[36\]
- The OTel blog says Copilot, Codex and Claude Code (beta) emit GenAI traces (OpenTelemetry blog "Inside the LLM Call", 2026).\[33\]
- Cursor-native OTel export of hook decisions: **not found**.

### 6. Visual patterns for long sessions
- **Aggregate vs. expand.** One node per step name with a counter, vs. one node per call (Langfuse, Jul 13, 2026).\[37\]
- **Fit-to-screen with map-like zoom.** Colour carries type when labels don't fit (Langfuse, Aug 28, 2026).\[5\]
- **Sticky group headers** in long waterfalls (LangSmith changelog, undated).\[9\]
- **Expand/collapse subtrees and sub-flows in React Flow.** Group nodes via `parentId`, which is free. Expand/collapse with dagre is a Pro example (React Flow docs, accessed Oct 2026).\[38\]\[39\]
- **Focus+context research.**
  - Semantic zoom changes encoding, not just scale.\[40\]
  - Time-compression techniques fold uninteresting stretches of discrete-event timelines (arXiv 2507.17320 "EventLines", Jul 2025, slightly older than 12 months; arXiv 2009.03385, 2020, older).\[41\]
- **AgentFly's own repo already moved this way:**
  - a three-lane timeline (steps / files / hosts+rules) with a 20-step window (PR #2, Oct 2, 2026);\[42\]
  - stable rows, a calm "Follow" camera and a 7:1-contrast dark theme (PR #3, Oct 2026, open at time of crawl);\[43\]
  - a 500-step server cap that keeps "the newest 5 blocked/warned steps the cap pushed out" as landmarks (PR #4, Oct 3, 2026).\[44\]

## Recommendations: the 5 views, ranked (opinion, with reference examples)

**1. Live Trail (the home screen).** A vertical, newest-at-bottom list of steps: icon by hook type, short label (command head, file basename, host), a time, and a large decision badge (ALLOW grey, WARN amber, BLOCK red). Runs of routine reads auto-group ("12 file reads ▸"). Blocked/warned steps never group and stay pinned as landmarks. Include a "Follow" toggle and a "N steps hidden" divider.
- *Why first:* it answers "what is it doing right now" without the user learning a graph grammar. It also scales past 20 steps, which the current graph does not.
- *References:* Langfuse Responsive Timeline (Aug 28, 2026); LangSmith full-height waterfall with sticky turn headers (LangSmith changelog, undated); CC-Monitor live Log Audit with bold-red high-risk rows (README, Oct 2026).\[5\]\[9\]\[24\]

**2. Block Explainer + Denials inbox.** Clicking any BLOCK opens a side card with:
- rule ID and name ("R1: no outbound after secret read");
- a one-sentence reason;
- the **causal chain**: "Step 14 read `.env` → Step 22 tried `curl api.example.com`";
- what was sent back to the user and the agent (`user_message` / `agent_message`);
- next actions: allow once, add exception, view rule.

A separate inbox lists all denials across sessions.
- *References:* Claude Code `/permissions` → Recently denied with `r` to retry and `[Data Exfiltration]` reason labels (Claude Code docs, accessed Oct 14, 2026);\[18\]\[19\] CC-Monitor approval history with "matched rule, matched value, outcome, and resolved-via" (README, Oct 2026).\[24\]
- *Gap to beat:* Claude Code's notice omits the command, and its desktop app lacks the tab (issue #98169, Sep 29, 2026).\[18\]\[21\]

**3. Provenance Graph (secondary view, toggle from the Trail).** Keep XYFlow, but refocus it on the **taint story**: File → Step → Command → Host, with Rule nodes attached to the edge they cut. Default to "Aggregated" (one node per file/host with counters) and switch to "Expanded" for as-it-ran order. Use a deterministic layout (ELK/dagre) so the picture never reshuffles. Selecting a node highlights its ancestors and descendants and dims the rest (focus+context).
- *Reference:* Langfuse Graph View Aggregated/Expanded on a deterministic ELK renderer (Jul 13, 2026);\[3\] React Flow sub-flows/expand-collapse (React Flow docs).

**4. Session History.** A table of past sessions: start time, repo/workspace (essential once AgentFly works outside its own repo), duration, step count, blocks/warns, and a "marked by R1" flag. Clicking a row opens that session's Trail in replay mode with a scrubber. Neo4j becomes the backing store here.
- *References:* Phoenix Sessions grouping traces into "a single timeline" (Feb 27, 2026);\[11\] AgentOps session drawer + waterfall (AgentOps docs, undated);\[13\]\[14\] CC-Monitor session dropdown "folder · model · short ID" (README, Oct 2026).\[24\]

**5. Rules & Hotspots.** Two halves:
- **Rules:** each rule with plain-language text, mode (Enforce / Warn / Off), hit counts, and last fired.
- **Hotspots:** the most-touched sensitive files and contacted hosts across sessions, with block counts.

This is where R1 stops being hard-coded.
- *References:* CC-Monitor's Enforcing/Permissive/Off control with an explanation line, plus clickable stat cards (README, Oct 2026);\[24\] Claude Code's `/permissions` Auto mode tab for editing rules (v2.1.246, 2026);\[20\] Snyk Observatory violation dashboard (Snyk blog, Dec 22, 2025).

## Design Principles (opinion)
1. **Decision first, activity second.** The badge (allow/warn/block) is the largest element on every row. Colour is reserved for decisions, and hook type uses icons, not colour.
2. **Every block explains itself in one sentence and one chain.** Show rule, trigger step and blocked step together. Never show a bare "denied".
3. **Never move the user's view.** Use stable rows, a deterministic layout, follow-mode only when the user is at the bottom, and a visible "Follow" button otherwise. This is already started in PR #3.
4. **Collapse the boring, pin the risky.** Aggregate repeated reads/edits. Blocks, warnings and secret reads are never collapsed and survive server caps as landmarks (PR #4 pattern).
5. **One primary view, others one keystroke away.** Avoid the "too many ways to view" trap that Langfuse users reported (Jan 2026).\[15\] Default to Trail and make Graph, History and Rules tabs.
6. **Show the privacy contract.** Label omitted content explicitly ("contents not recorded"). This builds trust and matches CC-Monitor's redaction ("path (N bytes)").\[24\]
7. **Show fail-open risk honestly.** Cursor hooks fail open on errors and have had dropped-deny bugs.\[26\]\[31\] Show a health strip: recorder online/offline, last hook seen, hook errors. AgentFly already has an OFFLINE banner.\[43\]

## Caveats
- **OTel export:** GenAI conventions are still "Development" (as of Jul–Aug 2026).\[45\] If AgentFly exports OTel spans, pin a convention version and expect renames.\[34\]
- **Unverified Langfuse feedback:** user complaints about Langfuse's Oct 13, 2026 session redesign could not be read (**not found**). Only the thread titles and status were verified.\[7\]
- **Small or self-described sources:** CC-Monitor's capabilities come from its own README, not independent review. Snyk's and inference.net's statements are vendor content.
- **Missing dates:** several sources (LangSmith changelog entries, AgentOps docs, some Cursor forum posts, the Hacker News Show HN thread) do not show an exact publication date. They are marked as "undated" or "date not found".
- **No usability studies found:** no published usability studies comparing timeline vs. graph views specifically for coding-agent monitoring were found (**not found**). The ranking above is a judgement based on the product patterns and complaints cited.

## Sources

1. [feat(trace): add a flame graph view to visualize where time goes in a trace · Issue #16219 · langfuse/langfuse](https://github.com/langfuse/langfuse/issues/16219)
2. [feat(web): graph becomes a view on the tree/timeline switch by nmtrang29 · Pull Request #17537 · langfuse/langfuse](https://github.com/langfuse/langfuse/pull/17537)
3. [Graph View: Aggregated and Expanded modes - Langfuse](https://langfuse.com/changelog/2026-07-13-graph-view-modes)
4. [AI Agent Observability, Tracing & Evaluation with Langfuse - Langfuse](https://langfuse.com/blog/2024-07-ai-agent-observability-with-langfuse)
5. [Responsive Timeline - Langfuse](https://langfuse.com/changelog/2026-08-28-responsive-timeline)
6. [Redesigned session view - Langfuse](https://langfuse.com/changelog/2026-10-13-redesigned-session-view)
7. [langfuse · Discussions · GitHub](https://github.com/orgs/langfuse/discussions)
8. [fix(sessions): Add session view introduction modal by bezbac · Pull Request #18411 · langfuse/langfuse](https://github.com/langfuse/langfuse/pull/18411)
9. [LangSmith Cloud changelog - Docs by LangChain](https://docs.langchain.com/langsmith/changelog)
10. [LangSmith Cloud changelog - Docs by LangChain](https://changelog.langchain.com/announcements/waterfall-graphs-to-spot-latency-bottlenecks-in-langsmith)
11. [02.27.2026 Sessions API and CLI Support - Phoenix](https://arize.com/docs/phoenix/release-notes/02-2026/02-27-2026-cli-sessions-and-rest-api)
12. [05.15.2026: Session Trace Feedback and ATIF v1.7 Support - Phoenix](https://arize.com/docs/phoenix/release-notes/05-2026/05-15-2026-session-feedback-and-atif)
13. [Introduction - AgentOps](https://docs.agentops.ai/v2/introduction)
14. [AgentOps: What It Does, Pricing, and Alternatives (2026)](https://inference.net/content/agentops-alternatives/)
15. [Roadmap Discussion Thread (2026) · langfuse · Discussion #11391](https://github.com/orgs/langfuse/discussions/11391)
16. [Show HN: I built a tool to un-dumb Claude Code's CLI output (Local Log Viewer) | Hacker News](https://news.ycombinator.com/item?id=47004712)
17. [The State of Cursor, November 2025: When Sandboxing Leaks Your Secrets](https://luca-becker.me/blog/cursor-sandboxing-leaks-secrets/)
18. [Configure auto mode - Claude Code Docs](https://code.claude.com/docs/en/auto-mode-config)
19. [Choose a permission mode - Claude Code Docs](https://code.claude.com/docs/en/permission-modes)
20. [Claude Code Auto Mode Tab in /permissions (2026)](https://www.getclaudeskills.com/blog/claude-code-auto-mode-permissions-tab)
21. [Desktop app: auto mode classifier keeps blocking user-approved Claude in Chrome actions after leaving auto mode; no manual-approval retry offered · Issue #98169 · anthropics/claude-code · GitHub](https://github.com/anthropics/claude-code/issues/98169)
22. [Claude Code Monitoring & Observability with OpenTelemetry](https://signoz.io/docs/claude-code-monitoring/)
23. [Agent Observability with OpenTelemetry and Trajectory Logging — AgentPatterns.ai](https://agentpatterns.ai/observability/agent-observability-otel/)
24. [CC-Monitor/README.md at master · cn0xroot/CC-Monitor](https://github.com/cn0xroot/CC-Monitor/blob/master/README.md)
25. [GitHub - cn0xroot/CC-Monitor: Claude Code Monitor : Monitor & audit every action Claude Code takes on your computer.](https://github.com/cn0xroot/cc-monitor)
26. [Hooks | Cursor Docs](https://cursor.com/docs/hooks)
27. [Hook ASK output not stopping agent - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/hook-ask-output-not-stopping-agent/149002)
28. [\[REGRESSION\] Hook response fields user\_message / agent\_message still ignored in Windows v2.0.77 - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/regression-hook-response-fields-user-message-agent-message-still-ignored-in-windows-v2-0-77/142589)
29. [\[REGRESSION\] Hook response fields userMessage/agentMessage ignored in v2.0.64 - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/regression-hook-response-fields-usermessage-agentmessage-ignored-in-v2-0-64/141516)
30. [When are you going to fix Hooks? - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/when-are-you-going-to-fix-hooks/148573)
31. [Race condition silently disables hooks that exit quickly - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/race-condition-silently-disables-hooks-that-exit-quickly/165818)
32. [OpenTelemetry GenAI Semantic Conventions: Tracing AI Agents in Production (2026)](https://veraexmachina.com/tech/opentelemetry-genai-agent-observability-production/)
33. [OpenTelemetry's GenAI semantic conventions are NOT stable yet — here's what actually shipped in 2026 - DEV Community](https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke)
34. [OpenTelemetry semantic conventions explained](https://clickhouse.com/resources/engineering/opentelemetry-semantic-conventions)
35. [AI Agent Observability: The OpenTelemetry Standard in 2026](https://www.aurorasre.ai/blog/opentelemetry-ai-agent-observability)
36. [semantic-conventions-genai/docs/gen-ai/gen-ai-agent-spans.md at main · open-telemetry/semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)
37. [Agent Graphs - Langfuse](https://langfuse.com/docs/observability/features/agent-graphs)
38. [Expand and Collapse - React Flow](https://reactflow.dev/examples/layout/expand-collapse)
39. [Sub Flows - React Flow](https://reactflow.dev/learn/layouting/sub-flows)
40. [Responsive Matrix Cells: A Focus+Context Approach for Exploring and Editing Multivariate Graphs](https://arxiv.org/pdf/2009.03385)
41. [EventLines: Time Compression for Discrete Event Timelines](https://arxiv.org/pdf/2507.17320)
42. [AG-28: draw the live graph on /v2/ by volkovyy-00 · Pull Request #2 · volkovyy-00/AgentFly](https://github.com/volkovyy-00/AgentFly/pull/2)
43. [AG-29: calm camera, motion and a dark high-contrast theme on /v2/ by volkovyy-00 · Pull Request #3 · volkovyy-00/AgentFly](https://github.com/volkovyy-00/AgentFly/pull/3)
44. [AG-30: keep long sessions light, with landmarks in reach by volkovyy-00 · Pull Request #4 · volkovyy-00/AgentFly](https://github.com/volkovyy-00/AgentFly/pull/4)
45. [The state of the OpenTelemetry GenAI semantic conventions (July 2026) · John Hodge](https://john-hodge.com/blog/opentelemetry-genai-semantic-conventions/)

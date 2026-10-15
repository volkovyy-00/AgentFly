# AgentFly as a Cross-Session Memory Layer: Feasibility Verdict and Plan

**Verdict: PARTLY.** A structure-only graph of agent actions (files, commands, hosts, rule hits, sequences) is worth building as a small, verifiable, safety-and-workflow memory. It is not worth building as a general semantic "agent memory" that competes with Graphiti/Zep, Mem0, Cognee or Neo4j Agent Memory. The best 2026 evidence shows memory gains for coding agents are small, fragile and often negative unless the memory is short, relevant and verifiable against the codebase. AgentFly's no-content design happens to fit those conditions.

## TL;DR
- **Feasible, but narrowly (opinion grounded in facts below):** cross-session memory for coding agents helps only when it is compact and correctly retrieved. In VibeMemBench (arXiv, 2026-09-20), four existing memory systems failed to beat the no-memory baseline in 11 of 12 pairings. GitHub's citation-verified Copilot Memory reported merge rates of 90% vs 83% (github.blog, 2026-01-15). AgentFly should copy the "verifiable, expiring, compact" pattern rather than the "LLM-extracted knowledge graph" pattern.
- **Ranked use cases (opinion):** (1) cross-session security/taint memory built on R1, which is high value and low effort; (2) a session-start "working-set brief" (the build/test commands that worked, hot files, denied actions) written into a Cursor rules file, which is medium-high value and low-medium effort; (3) behavioral analytics over tool-call sequences (loops, anomalies, n-gram/Markov profiles), which is medium value and medium effort.
- **Privacy line (opinion):** never persist file contents, diffs, prompts, agent messages/thoughts, raw command arguments, full URLs or environment values. Never let free text into the context that is re-injected. Store only typed, deterministic structure (path, binary+subcommand, host, exit status, rule ID, timestamps), keep it local, and expire it.

---

## Key Findings — FACTS (each with source domain + date)

*Note on dates: where a page shows no publication date, "accessed 2026-10-14" is given. Sources older than 12 months are marked [older].*

### 1. Who already builds memory / knowledge graphs for coding agents

| Product | What it stores | How it summarizes | How the agent reads it back | Source |
|---|---|---|---|---|
| **Cursor Memories** | Facts from conversations, "stored per project on an individual level" | Background-generated, user-approved | Injected as rules context | cursor.com/changelog/1-0 (2025-06-04) [older]\[1\] |
| **Cursor Memories (status)** | A Cursor staff member wrote "The Memories feature was removed starting from version 2.1.17", and users were told to export memories into Rules (.mdc) | — | Rules / AGENTS.md now | forum.cursor.com "Memories not showing" (2025-11-24); staff statements later conflicted (2026-01-07: "removed… still works, just without a UI"; 2026-01-10: "hasn't been removed"), per mnemoverse.com (accessed 2026-10-14)\[2\]\[3\] |
| **Cursor hooks context injection** | `sessionStart` can return `additional_context` "to add to conversation" | — | System context at session start | cursor.com/docs/hooks (accessed 2026-10-14)\[4\] |
| **Same, in practice** | Multiple bug reports say `additional_context` from `sessionStart`/`postToolUse` never reaches the model. Cursor staff: "For now, the most dependable way to inject static context is through a .cursor/rules file" | — | — | forum.cursor.com bug threads (2026-03-29 to 2026-08-17; staff reply 2026-04-10)\[5\]\[6\]\[7\] |
| **Claude Code CLAUDE.md + auto memory** | CLAUDE.md is written by the human. Auto memory is Claude's own notes in `~/.claude/projects/<project>/memory/` with a `MEMORY.md` index plus topic files; on by default since v2.1.59 | Claude writes and shortens its own notes; the first 200 lines / 25 KB of MEMORY.md load at start; topic files are read on demand, not by vector search | Prompt injection at startup + file reads | blog.memoryplugin.com (2026); vectorize.io (2026); claudcod.com (2026)\[8\]\[9\]\[10\] |
| **claude-mem (plugin)** | Tool-use observations captured by five hooks (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd) in local SQLite + Chroma | An LLM compresses raw tool output into structured observations and session summaries | Injects 50 observations at SessionStart by default, plus MCP search tools | datacamp.com (2026); docs.claude-mem.ai (accessed 2026-10-14); augmentcode.com reports 46.1K GitHub stars (2026)\[11\]\[12\]\[13\] |
| **GitHub Copilot Memory** | Small "memories" stored with **citations** (file:line) | Created by the agent via a tool call | Retrieved, then "verifies the citations in real-time… before using it"; unused memories expire after 28 days, and validation resets the timer | github.blog (2026-01-15); kenmuse.com (2026-05-14)\[14\]\[15\]\[16\]\[17\] |
| **MCP reference server-memory** | Entities (name, type, observations) + directed relations, in a local `memory.jsonl` (`MEMORY_FILE_PATH`) | None; the agent writes atomic observations itself | MCP tools (`create_entities`, `read_graph`, `search_nodes`…) + a `memory://knowledge-graph` resource; the README suggests a system prompt telling the agent to retrieve memory at chat start | github.com/modelcontextprotocol/servers (accessed 2026-10-14)\[18\]\[19\] |
| **Graphiti / Zep** | Episodes, entities and fact edges with **bi-temporal** timestamps (created_at, valid_at, invalid_at, expired_at) | An LLM extracts entities/edges per episode; contradictions **invalidate** edges rather than delete them | Hybrid semantic + BM25 + graph search via SDK/MCP | help.getzep.com (accessed 2026-10-14); Zep paper arXiv 2501.13956 (2025-01) [older]\[20\]\[21\]\[22\] |
| **Neo4j Agent Memory** | Three memory types in one graph: short-term (messages), long-term (POLE+O entity graph), reasoning (traces, steps, tool calls) | Extraction + embeddings | MCP server, 16 tools on the self-hosted Bolt backend; server instructions tell the agent to call `memory_get_context` at conversation start | neo4j.com/labs/agent-memory (accessed 2026-10-14); pypi.org neo4j-agent-memory (released 2026-09-14); github.com/aaif/project-proposals #52 (2026-10)\[23\]\[24\]\[25\]\[26\] |
| **Cognee** | Knowledge graph from text and code (code becomes "a graph of symbols and dependencies") | `remember / recall / forget / improve`; "memify" enriches the graph and derives coding-rule nodes | MCP server for Cursor, Claude Code, Cline | github.com/topoteretes/cognee (accessed 2026-10-14); cognee.ai (2026)\[27\]\[28\]\[29\] |
| **codebase-memory-mcp** | Tree-sitter code graph (functions, classes, call chains, routes) in SQLite | Deterministic parsing, no LLM | 14 MCP tools; its preprint reports 83% answer quality with 10× fewer tokens and 2.1× fewer tool calls than file-by-file exploration across 31 repos | deusdata.github.io (accessed 2026-10-14); arXiv 2603.27277 (2026-03), per aibuilderclub.com\[30\]\[31\]\[32\] |
| **Mem0** | Extracted facts (vector), optional graph variant | LLM extraction + update | SDK / MCP | Mem0 paper arXiv 2504.19413 (2025-04) [older] |

**Adjacent competitors (guardrails/observability on the same hook surface):**
- Cursor's own hooks page lists partner integrations for MCP governance (MintMCP, Oasis, Runlayer), code security (Corridor, Semgrep), dependency security (Endor Labs), agent security (Snyk Evo Agent Guard) and secrets (1Password) (cursor.com/docs/hooks, accessed 2026-10-14).\[4\]
- Invariant Guardrails offers a rule language over agent traces that already expresses R1-style flows, e.g. `(call: ToolCall) -> (call2: ToolCall)`, as well as loop detection ("Too many retries") (github.com/invariantlabs-ai/invariant, accessed 2026-10-14). Snyk announced it had acquired Invariant Labs on June 24, 2025 [older]; the press release says Invariant "has built Guardrails, a transparent security layer at the LLM and agent level" (labs.snyk.io, "Published June 24, 2025"; globenewswire.com, 2025-06-24).

### 2. Evidence that cross-session memory improves coding agents, and its failure modes

**Positive or mixed evidence:**
- **GitHub Copilot A/B (vendor, self-reported):** "90% with memories vs. 83% without" PR merge rate for the coding agent; code review positive feedback 77% vs 75%; "p-value <0.00001". No sample sizes are given (github.blog, 2026-01-15).\[14\]
- **SWE-ContextBench (arXiv 2602.08316 v3, 2026-05-06):** with Claude Sonnet 4.5 on 99 related tasks, the no-context baseline resolved 26.26%. **Oracle-selected summaries** reached 34.34%. **Autonomously retrieved summaries fell to 22.22%**, below the baseline. Full trajectories added little (oracle 27.27%, free 26.26%), and free retrieval cost $0.98/task vs $0.79 baseline. Summaries averaged 217 tokens vs 25,634 for full trajectories. The authors' summary: "unfiltered or incorrectly selected context provides limited or negative benefits."\[33\]
- **VibeMemBench (arXiv 2609.23570 v1, 2026-09-20, not peer-reviewed):**
  - Injecting known-good experience raised resolution by 1.1–4.5 pp on four of five solvers and lowered steps on all five. However, "all five bootstrap intervals cross zero."\[34\]\[35\]
  - When existing memory systems (Mem0, SimpleMem, MemoryOS, A-MEM) had to build and retrieve memory themselves, "eleven of twelve solver and system pairings fail to exceed the matched memory-off baseline." Net effect: a loss of 127 resolved seeds. Mem0 with glm-5 scored −5.5 pp, with a CI entirely below zero.\[35\]
  - 69.3% of failures were "form degradation": the fix pattern was buried in long transcripts. Injected records averaged 65 lines.\[35\]
- **Code-structure graphs:** codebase-memory-mcp reports 10× fewer tokens and 2.1× fewer tool calls on structural questions (arXiv 2603.27277, 2026-03, via aibuilderclub.com).

**Failure modes:**
- **Stale or wrong memories / updates:** on MemoryAgentBench FactConsolidation single-hop, Mem0 scored 18.0 and Zep/Graphiti 7.0. The same paper found explicit bi-temporal versioned edges underperform prose history at answer time (72/81 vs 79/81) "because rendering superseded edges returns stale values" (arXiv 2607.21962, 2026-07).\[36\]
- **Benchmark unreliability:** Zep claimed 84% on LoCoMo, then corrected this to 75.14%. Mem0's re-run scored Zep at 58.44% (getzep.com blog and github.com/getzep/zep-papers issue #5, 2025-05) [older].\[37\]\[38\]\[39\] A 2026 paper cites Mem0 GitHub issues reporting failures to reproduce LoCoMo scores (arXiv 2604.10981, 2026-04).\[40\]
- **Context bloat / context rot:** Chroma tested 18 models and found performance degrades as input length grows, even on simple tasks, with distractors making it worse (trychroma.com/research/context-rot, 2025-07) [older].\[41\]\[42\]\[43\] A 2026 follow-up found monitor recall in Opus 4.6, GPT 5.4 and Gemini 3.1 Pro degrades as transcript length increases (arXiv 2605.12366, 2026-05).\[44\]
- **Prompt injection via memory:**
  - MINJA poisons agent memory through queries alone, with no write access needed (arXiv 2503.03704; NeurIPS 38).\[45\]\[46\]\[47\]
  - AgentPoison assumes direct write access to memory (summarized in arXiv 2608.01759, 2026-08).\[45\]
  - A systematic study found "the same memory design choices that improve agent performance… also expand the memory poisoning attack surface" and that existing prompt-injection defenses give incomplete coverage (arXiv 2606.04329, 2026-06).\[48\]
  - SpAIware planted a persistent exfiltration instruction in ChatGPT memory via indirect prompt injection; it was patched in ChatGPT macOS 1.2024.247 (2024-09) [older; via akto.io and secret-chat.ai, 2026].\[49\]\[50\]\[51\]
  - The OWASP GenAI Security Project's "OWASP Top 10 for Agentic Applications 2026" (genai.owasp.org, published 2025-12-09) [older] lists "ASI06 – Memory & Context Poisoning", noting that "Memory poisoning reshaped behaviour long after the initial interaction". A 2026-05-13 OWASP post by ASI06 entry lead Idan Habler (Cisco) maps Cisco's "MemoryTrap" Claude Code attack, which reached "persistent memory" and "the global hooks configuration", to ASI06.

### 3. What structure alone can reveal

- **Sequences carry signal without content:**
  - "Your Agent Has a Genome" applies n-gram mining, Markov transition matrices and correlation to 347 production ReAct traces to profile behavior and govern it at runtime (arXiv 2606.15579, 2026-06).\[52\]
  - TraceCompiler mines noisy tool-call traces into deterministic workflows, with a median removable fraction of 51.4% (arXiv 2608.02680, 2026-08-03).\[53\]\[54\]
  - TraceAegis detects anomalies from tool-call ordering and behavioral constraints (arXiv 2510.11203, 2025-10).\[55\]
  - The COMPASS methodology ("a COMprehensive Process AnalySiS"; five phases from planning and trajectory extraction to conformance-checking feedback) applies classic process mining to LLM agent trajectories (ceur-ws.org Vol-3996, CAiSE 2025 workshops, published 2025-08-21) [older].
- **Coding-agent workload shape:** TraceLab (University of Washington; arXiv 2606.30560, 2026-06-29) collected traces from 43 developers over about eight months of Claude Code and Codex use, "roughly 4,300 coding-agent sessions, containing about 350,000 LLM steps and 430,000 tool calls". Per request, "the agent will, on average, carry out 8.8 LLM calls and invoke tools 10.8 times", and tool calls "are dominated by the shell" (syfi.cs.washington.edu, 2026-06-25).
- **What the hook payloads expose:**
  - `beforeShellExecution` sends the full command string and cwd.\[56\]
  - `afterFileEdit` sends `file_path` and `edits` (`old_string`/`new_string`), meaning **raw code content** (ntorres.dev, 2026; cursor.com/docs/hooks).\[56\]
  - `afterShellExecution` exists, so command outcomes can be recorded (cursor.com/docs/hooks, accessed 2026-10-14).\[4\]
- **Quantified evidence that structure-only memory alone improves coding outcomes: not found.** Every positive result above injects *content* (summaries, citations to code, code graphs).

### 4. Graph patterns in use

- **Session → summary nodes:** Graphiti keeps EpisodicNodes (raw input), EntityNodes, CommunityNodes (cluster summaries) and fact edges (codepointer.dev, 2026).\[22\] Neo4j Agent Memory chains Conversation → Message and Message → ReasoningTrace → ReasoningStep → ToolCall (neo4j.com/labs/agent-memory, accessed 2026-10-14).\[23\] claude-mem compresses each session into a summary plus typed observations (datacamp.com, 2026).\[11\]
- **Linking to code entities:** Copilot memories cite `file:line` locations (github.blog, 2026-01-15).\[14\] Cognee and codebase-memory-mcp build symbol/call graphs (cognee.ai; deusdata.github.io, 2026).\[28\]\[57\]
- **Time decay / validity:** Graphiti uses bi-temporal invalidate-not-delete (help.getzep.com).\[21\]\[58\] Copilot uses a 28-day TTL refreshed on successful validation (github.blog, 2026-01-15).\[15\]\[16\]\[17\] Note the counter-finding that showing superseded edges can hurt answers (arXiv 2607.21962, 2026-07).\[36\]

### 5. Cursor hooks facts relevant to productizing AgentFly

- **Events:** sessionStart/End, preToolUse/postToolUse/postToolUseFailure, subagentStart/Stop, before/afterShellExecution, before/afterMCPExecution, beforeReadFile/afterFileEdit, beforeSubmitPrompt, preCompact, stop, afterAgentResponse/afterAgentThought, Tab hooks, and workspaceOpen (cursor.com/docs/hooks, accessed 2026-10-14).\[4\]
- **Config:** loaded from Enterprise → Team → Project → User. User hooks in `~/.cursor/hooks.json` "apply globally", which directly fixes "only works inside its own cloned repo". User-level hooks are **not** available in cloud agents (cursor.com/docs/hooks).\[4\]
- **Failure semantics:** exit code 2 blocks. For permission hooks, invalid JSON blocks the action. "Other exit codes – Hook failed, action proceeds (fail-open by default)" (cursor.com/docs/hooks).\[4\] This matters for a security product: if the recorder is down, a crashing hook script fails open.
- **Response merging:** "any deny wins over ask, and ask wins over allow, regardless of source" (cursor.com/docs/hooks).\[4\]

---

## Details — OPINIONS and analysis

### Why "partly" and not "yes"
- **The general-memory market is crowded and the evidence is weak.** Five well-funded or open-source projects already ship knowledge-graph memory with MCP. The two coding-specific benchmarks from 2026 both show that autonomous memory systems often *hurt* (22.22% vs 26.26% baseline in SWE-ContextBench; 11/12 non-improving pairings in VibeMemBench).\[33\]\[35\] AgentFly would enter last, with less data (no content), to compete on a weak value proposition.
- **AgentFly's real asset is different.** It sits on the *pre-execution* control path with allow/deny authority, and it records ground-truth actions rather than LLM-extracted "facts". That makes its memory (a) deterministic, (b) inherently grounded in file paths and hosts that can be re-verified, the way Copilot validates citations, and (c) usable for *enforcement*, not just recall. No memory vendor listed above does (c), while guardrail vendors (Invariant/Snyk, Cursor hook partners) mostly do not keep cross-session graphs. That gap is the product.
- **Structure-only is a feature for the memory problem.** The VibeMemBench failure analysis (69.3% "form degradation" from long transcripts) and context-rot findings both argue for tiny, typed, deterministic injections.\[35\] A 30-line, template-generated brief is the opposite of a 65-line LLM-written transcript record.

### The three use cases, ranked by value vs effort

| Rank | Use case | What it does | Value | Effort | Why |
|---|---|---|---|---|---|
| 1 | **Cross-session taint & policy memory** | Generalize R1 into a stateful graph: "this workspace's agent has read `.env`/`*.pem` in the last N hours", hosts first contacted per repo, rule-hit history, repeated denials. Rules become graph queries (e.g., deny `git push` to a *new* host if any secret-class file was read this session or the previous one; flag first-ever contact with a host). | High | Low | Uses data AgentFly already collects; no LLM; enforceable; differentiates from memory vendors; matches the flow rules Invariant expresses, but adds persistence. |
| 2 | **Session-start working-set brief** | From the last K sessions, generate a ≤30-line `.cursor/rules/agentfly-context.mdc`: build/test commands that exited 0, commands that repeatedly failed, most co-edited files, recently denied actions and why. Each line cites a path or command and expires (TTL) unless re-observed. | Medium-high | Low-medium | Mirrors Copilot's verified, expiring, citation-backed design. Use a rules file rather than `additional_context` because of the documented injection bugs. The gain is unproven, hence the experiment. |
| 3 | **Behavioral analytics / anomaly detection** | Per-repo n-gram/Markov profiles of action sequences; detect loops (same failing command ×N), unusual sequences (read secret → network), drift between models; team dashboard. | Medium | Medium | Research supports the signal (Genome, TraceAegis, TraceCompiler). The buyer is a team lead or security team, not an individual developer, so it needs multi-user aggregation. |

**Not recommended:** content-level semantic memory (LLM-extracted facts from messages/diffs). It is high effort, crowded, raises poisoning risk and crosses the privacy line. If users want it, integrate with Graphiti/Cognee/Neo4j Agent Memory via MCP rather than rebuild it.

### Productization prerequisites (opinion)
1. Install as **user-level hooks** (`~/.cursor/hooks.json`) with a per-workspace session key from `workspace_roots`/`conversation_id`, to escape the single-repo limit.
2. Handle **fail-open**: decide explicitly between fail-closed (exit 2 when the recorder is unreachable, for security mode) and fail-open (memory-only mode).
3. Replace the hard-coded R1 with declarative rules evaluated over the graph. Persist sessions locally by default (SQLite is enough); keep Neo4j optional.
4. Add `afterShellExecution` and `sessionEnd` capture to get exit status and session boundaries. Without outcomes, a "working set" cannot tell good commands from bad ones.

### Minimal weekend experiment (opinion)
**Question:** does a structure-only, template-generated brief reduce wasted agent actions on repeat work in the same repo?

1. **Saturday morning:** add `afterShellExecution` (exit code only) and `sessionEnd` to the recorder. Write a generator that turns the last 10 sessions into ≤30 lines: top 5 successful test/build commands (binary + subcommand + flags, args redacted); top 5 commands with ≥2 failures; top 10 files by edit count with their co-edit partners; the last 5 rule denials. Every line carries a "last seen" date and is dropped after 14 days unless re-observed.
2. **Saturday afternoon:** pick one real repo and write 12 small, realistic tasks (bug fix, add test, refactor). Run each task twice in fresh Cursor chats, alternating order: **A** = no brief, **B** = brief in `.cursor/rules/agentfly-context.mdc`. Use the same model, and reset git between runs.
3. **Sunday:** compute metrics from AgentFly's own graph: actions to first passing test run; number of failed shell commands; number of distinct files read before the first edit; total steps; task success (tests pass). Also hand-check each brief for stale or wrong lines.
4. **Decision rule (pre-registered):** ship use case #2 if B shows a ≥15% median reduction in failed commands or steps-to-first-green with no drop in success. Shelve it if the effect is under 5% or any stale line misled the agent. With n=12 pairs this is directional only; VibeMemBench needed 111 targets and still could not separate 1–4.5 pp gains from zero.\[35\]
5. **In parallel (2 hours):** replay the recorded graph against a "taint persists across sessions" version of R1 and count how many past actions would have been denied or flagged. This sizes use case #1's false-positive rate before shipping it.

### The privacy line AgentFly should not cross (opinion)
- **Never persist:**
  - file contents or diffs (drop `afterFileEdit.edits` inside the hook script, before the POST);
  - prompts (`beforeSubmitPrompt`), agent responses or thoughts;
  - MCP tool inputs/outputs;
  - environment variable values;
  - full URLs or query strings (keep the host only);
  - raw command arguments (keep binary, subcommand and flag names; hash or redact literals, since tokens and passwords often appear in argv).
- **Secret files:** record only that a path matching a secret class was read (e.g., `secret:dotenv`), never a value, and never a content hash that could enable confirmation attacks on low-entropy secrets.
- **Re-injection rule:** only deterministic templates over typed fields may flow back into agent context. No free text from the agent, from file contents or from command output may ever be re-injected. This is the structural defense against MINJA/SpAIware-class memory poisoning, which exploits memory that stores attacker-influenced text.
- **Locality and lifetime:** local-only storage by default (127.0.0.1, user-owned file), explicit opt-in for any team sync, a default TTL on all nodes (14–28 days, cf. Copilot's 28 days), and a one-command wipe.
- **The line itself:** the moment a feature needs message text or code content to work, it belongs in an integration with a dedicated memory product and under the user's explicit consent, not in AgentFly's core.

## Caveats
- Several key numbers are vendor-reported (GitHub Copilot A/B with no sample sizes; Cognee, Zep and Mem0 claims), and the memory-benchmark field has documented reproducibility disputes.
- VibeMemBench is under a month old and not peer-reviewed. SWE-ContextBench's settings comparison uses one model and 99 tasks with no significance tests.
- Cursor's Memories status is contradictory in staff forum statements.\[3\] Cursor's `additional_context` injection has open bug reports across 2026, so behavior may change with any release.\[7\]
- No study was found that measures coding-agent gains from *structure-only* (no-content) memory; use case #2 is a hypothesis to test, not an established result.
- Some sources (Chroma context rot, Zep paper, Mem0 paper, SpAIware, LoCoMo dispute) are older than 12 months and are used only because no newer primary replacement was found.

## Sources

1. [Bugbot, Background Agent access to everyone, and one-click MCP install · Cursor](https://cursor.com/changelog/1-0)
2. [Memories not showing - Help - Cursor - Community Forum](https://forum.cursor.com/t/memories-not-showing/143820)
3. [Cursor Memory Bank: What Actually Loads](https://mnemoverse.com/docs/library/cursor-memory-bank-what-loads)
4. [Hooks](https://cursor.com/docs/hooks)
5. [sessionStart hook additional\_context is never injected into agent's initial system context - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/sessionstart-hook-additional-context-is-never-injected-into-agents-initial-system-context/158452)
6. [Native postToolUse hooks accept and log additional\_context successfully, but the injected context is not surfaced to the model - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/native-posttooluse-hooks-accept-and-log-additional-context-successfully-but-the-injected-context-is-not-surfaced-to-the-model/155689)
7. [Cursor app hooks bugs of additional\_context - #6 by Colin - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/cursor-app-hooks-bugs-of-additional-context/163990/6)
8. [Claude Code Memory Explained: CLAUDE.md and Auto Memory (2026)](https://blog.memoryplugin.com/claude-code-memory/)
9. [Claude Code Memory: Complete Guide to Persistence](https://vectorize.io/articles/claude-code-memory)
10. [Claude Code Auto Memory: Where It Lives, How It Works](https://claudcod.com/blog/claude-code-auto-memory/)
11. [Claude-Mem Guide: Persistent Memory for Claude Code](https://www.datacamp.com/tutorial/claude-mem-guide)
12. [claude-mem hits 46.1K stars as persistent memory plugin for Claude Code](https://www.augmentcode.com/learn/claude-mem-46k-stars-persistent-memory-claude-code)
13. [How to Use Claude-mem for Memory Persistence in Claude Code](https://apidog.com/blog/how-to-use-claude-mem/)
14. [Building an agentic memory system for GitHub Copilot - The GitHub Blog](https://github.blog/ai-and-ml/github-copilot/building-an-agentic-memory-system-for-github-copilot/)
15. [Memory Architecture of GitHub Copilot](https://x.com/mem0ai/article/2064383137338233179)
16. [Understanding Agentic Memory in GitHub Copilot - Ken Muse](https://www.kenmuse.com/blog/understanding-agentic-memory-in-github-copilot/)
17. [GitHub Copilot bekommt Gedächtnis: Wie das Agentic Memory...](https://workshops.de/en/blog/2026-03-31-github-copilot-bekommt-gedaechtnis-wie-das-agenti)
18. [servers/src/memory at main · modelcontextprotocol/servers · GitHub](https://github.com/modelcontextprotocol/servers/tree/main/src/memory)
19. [Memory MCP servers for Claude Code, Codex, Cursor](https://www.pathrule.io/writing/memory-mcp-servers-for-ai-coding-agents)
20. [Stop Using RAG for Agent Memory - Zep](https://blog.getzep.com/stop-using-rag-for-agent-memory/)
21. [Overview](https://help.getzep.com/graphiti/getting-started/overview)
22. [Agent Memory Systems and Knowledge Graphs: Letta, Mem0, Graphiti, and Cognee](https://codepointer.dev/p/agent-memory-systems-and-knowledge)
23. [Neo4j Agent Memory - Neo4j Agent Memory](https://neo4j.com/labs/agent-memory/)
24. [\[Sandbox Project Proposal\] Neo4j Agent Memory · Issue #52 · aaif/project-proposals](https://github.com/aaif/project-proposals/issues/52)
25. [Self-hosted Python MCP reference - Neo4j Agent Memory](https://neo4j.com/labs/agent-memory/reference/mcp-tools/)
26. [Neo4j Agent Memory (Python SDK)](https://pypi.org/project/neo4j-agent-memory/)
27. [Memory Tooling for AI Coding Agents 2026](https://www.cognee.ai/memory-tooling-ai-coding-agents)
28. [GitHub - topoteretes/cognee: Cognee is the open-source AI memory platform for agents. Give your AI agents persistent long-term memory with small models for free · GitHub](https://github.com/topoteretes/cognee)
29. [memify coding agent example](https://glama.ai/mcp/servers/@topoteretes/cognee/blob/d99a7fffdd523edb80cbd10aceb57af96c9114be/examples/python/memify_coding_agent_example.py)
30. [Stop Making Your AI Coding Agent Grep Your Whole Repo — Try codebase-memory-mcp - DEV Community](https://dev.to/arshtechpro/stop-making-your-ai-coding-agent-grep-your-whole-repo-try-codebase-memory-mcp-4g8l)
31. [Codebase Memory MCP: Give Your Coding Agent a Map (2026)](https://www.aibuilderclub.com/blog/codebase-memory-mcp-guide)
32. [Codebase-Memory paper — Tree-Sitter-Based Knowledge Graphs for LLM Code Exploration via MCP](https://memorypapers.org/papers/codebase-memory-tree-sitter-based-knowledge-graphs-for-llm-code-exploration-via-mcp)
33. <https://arxiv.org/pdf/2602.08316v3>
34. [VibeMemBench: Evaluating Memory Systems for Coding Agents on Real Repository Coding Tasks](https://arxiv.org/abs/2609.23570v1)
35. [VibeMemBench: Evaluating Memory Systems for Coding Agentson Real Repository Coding Tasks](https://arxiv.org/html/2609.23570v1)
36. [Ground Truth First: A Longitudinal Evaluation Instrument for Agent Memory, and the Tenure Crossover in Memory-Architecture Rankings](https://arxiv.org/pdf/2607.21962)
37. [Agent Memory Frameworks Showdown: cognee vs Mem0 vs Zep vs Letta](https://theaiengineer.substack.com/p/cognee-vs-zep-vs-mem0-vs-letta)
38. [Is Mem0 Really SOTA in Agent Memory?](https://www.getzep.com/blog/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)
39. [Revisiting Zep’s 84% LoCoMo Claim: Corrected Evaluation & 58.44% Accuracy · Issue #5 · getzep/zep-papers](https://github.com/getzep/zep-papers/issues/5)
40. [ATANT v1.1: Positioning Continuity Evaluation Against Memory, Long-Context, and Agentic-Memory Benchmarks](https://arxiv.org/pdf/2604.10981)
41. [Context Rot: Why Bigger Context Windows Make AI Models Less Reliable](https://geniustechlab.com/posts/2026-06-27-context-rot-long-context-ai-degradation)
42. [P6: Context Rot](https://hamel.dev/notes/llm/rag/p6-context_rot.html)
43. [Tokalator: A Context Engineering Toolkit for Artificial Intelligence Coding Assistants](https://arxiv.org/pdf/2604.08290)
44. [Classifier Context Rot: Monitor Performance Degrades with Context Length](https://arxiv.org/pdf/2605.12366)
45. [Benign Alone, Harmful Together: Exploiting Experience Composition in Self-Evolving LLM Agents](https://arxiv.org/pdf/2608.01759)
46. [Memory Injection Attacks on LLM Agents via Query-Only Interaction](https://www.alphaxiv.org/abs/2503.03704)
47. [Transferable End-to-End Optimization for Indirect Long-Term Memory Poisoning in LLM Agents](https://arxiv.org/pdf/2609.00523)
48. [From Untrusted Input to Trusted Memory: A Systematic Study of Memory Poisoning Attacks in LLM Agents](https://arxiv.org/pdf/2606.04329)
49. [Memory Poisoning in AI Agents: Attacks & Detection 2026](https://www.akto.io/blog/memory-poisoning-ai-agents)
50. [ChatGPT’s AI Memory Spyware Threatening macOS Again - Inside Telecom](https://insidetelecom.com/chatgpts-ai-memory-spyware-threatening-macos-again/)
51. [AI Memory Is a Privacy Time Bomb: What ChatGPT Keeps](https://secret-chat.ai/blog/ai-memory-privacy-time-bomb/)
52. [Your Agent Has a Genome Sequence-Level Behavioral Analysis and Runtime Governance of LLM-Powered Autonomous Agents](https://arxiv.org/html/2606.15579v1)
53. [1Introduction](https://arxiv.org/html/2608.02680)
54. [Skill-Guided Mining and Compilation of LLM Agent Traces ...](https://arxiv.org/pdf/2608.02680)
55. [TraceAegis: Securing LLM-Based Agents via Hierarchical and](https://arxiv.org/pdf/2510.11203)
56. [Cursor hooks.json: JSON Schema, Events & Payloads — Nicolás Torres](https://ntorres.dev/blog/cursor-hooks-json-guide)
57. [codebase-memory-mcp — Code Intelligence Knowledge Graph for AI Coding Agents](https://deusdata.github.io/codebase-memory-mcp/)
58. [Bi-Temporal Fact Invalidation Memory](https://hhuang-brex.github.io/H-AI-/nodes/concepts/bitemporal-fact-invalidation-memory.html)

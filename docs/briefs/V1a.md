You are a worker on card V1a in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v1a-spec. Follow AGENTS.md and this brief; report per docs/reports/README.md.

Card: docs/BOARD.md "V1a". Source: docs/DECISIONS.md (only entries whose Status says approved; D13 and D16 are proposed and stay "pending"), docs/product-goals.md, and today's SPEC.md. Read docs/SYNTHESIS.md only where a decision cites it and you need detail. Commit on branch ag-v1a-spec; do not merge.

This card is docs only. It deliberately makes SPEC.md describe v1 while the code is still the hackathon version, so ignore AGENTS.md's "if code and SPEC disagree, stop": that is the text you are rewriting. List the gaps instead.

Suggested SPEC.md outline (keep the plain-language style and §4's number):
0. Status: v1 target; code moves card by card; hackathon version in docs/archive/SPEC-hackathon.md.
1. The idea (pitch + honest limit).  2. Goals and hard constraints (from product-goals; D1 wording).
3. How it works: hook client (D5, D18), system hooks.json (D2), recorder service (D8), rules (D3, D10), local store (D14), page (D15).
4. What is stored and how commands are cleaned (D14 + today's §4 cleaning rules, workspace path added).
5. Rules: severities (D11), rule file kinds (D10; fields "Pending S3"), R0 in code, R1 definition with normalisation (D10), mark scope per chat ("Pending S5: subagents"), change flow (D3, D12), drafting (D13 pending).
6. The screen (D15 + S4 requests).  7. Install, run, uninstall (D6, D7, D8, D20; name agentfly-recorder, known `agentfly` command clash).
8. Hooks and the hook client (D9 list "revisit after S5", stripping, dedup by tool_use_id, deny answer).
9. When the recorder is down (D4).  10. Protecting AgentFly itself (D1, D3 with "Pending S5: sudo grace period", known gaps).
11. Recorder API (D19).  12. Not in v1 / pending (D13, D16, D20, other agents, Linux/Windows, publishing).  13. Glossary.
Appendix or report: decision → section table.

Then AGENTS.md per the card's "Done when", product-goals G1 flow (drop "or agentfly init for one project", D20), and SPEC references in HOOKS.md/README.md (point stage-setup references at the archive). Run the AGENTS.md check command, write docs/reports/V1a.md, stop.

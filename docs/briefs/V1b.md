# V1b · SPEC catch-up: write in what S3, S5 and the 2026-10-16 to 10-18 answers decided

You are a worker on card V1b in /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v1b-spec. Follow AGENTS.md and this brief; report per docs/reports/README.md. Never push; commit on branch ag-v1b-spec only, the lead merges.

**Summary.** SPEC.md still says "pending" about things the spikes and the owner have since decided. Make it describe the approved v1 target again, so the next workers read one current document. Docs only, no code.

**Written against:** 459487c (2026-10-18).

**References**
- `docs/DECISIONS.md`: the source of truth. Use only entries whose Status says approved, including any dated owner note on the status line (D14's 2026-10-18 note, for example). D16 is still proposed.
- `docs/spikes/S3-rule-fit.md` and `docs/spikes/S5-brief.md`: the facts the "Pending S3" and "Pending S5" markers wait for. S5 found that `sudo -n` fails in the agent's shell after the owner ran `sudo` elsewhere (exit 1), so D3 stands.
- `SPEC.md` § "0. Status": explains the Pending markers this card removes. Keep SPEC's plain-language style and its section numbers.
- `AGENTS.md` § "Testing" and § "Hook client rules": the lists that must agree with SPEC and with the tests that exist.

**Scope**
- Write in, at the right section: D13 = C (no plain-language drafting in v1); D10's S3 additions and the narrowed quoted-heredoc rule, replacing §5's "Open hole" and the §10 gap; D9 with D21 A (`subagentStart` record-only; in §5, the mark follows `parent_tool_call_id` both ways, with the 30-minute workspace fallback, and nothing depends on `subagentStop`) and D23 (only accepted events; `doctor` reads the Hooks log); D22 (the sandbox is not a control); D24 (`~/.claude/settings.json` is a hook source); D25 (always port 8787, no port file); D3 stands after S5's sudo re-run (§10); D5's 2026-10-16 reword (a missing client file is a loud failure and `doctor` turns red, replacing §9's "Flagged to the owner"); D14's 2026-10-18 note (Neo4j only with `neo4j = true` in `~/.config/agentfly/config.toml`; `wipe` keeps marks).
- R0 and the offline guard (owner answers of 2026-10-16 and 2026-10-18, not in DECISIONS; the guard items are already in AGENTS.md § "Hook client rules"): R0 also denies `agentfly serve` and `agentfly wipe`; a 401 or 403 from the recorder gets the offline guard; every inline `python -c` / `node -e` is denied offline; the hook client waits 0.5 s and its p95 target is re-measured on the bundled Python in V3a.
- Where DECISIONS and SPEC disagree, DECISIONS wins. Where no approved decision settles a point, leave SPEC's text and list the point in the report. Do not invent.
- Touches: `SPEC.md`, and `AGENTS.md` only where it contradicts SPEC or names a test that does not exist.
- Not included: README.md and HOOKS.md (they describe today's code; V3a owns README's install section), `docs/DECISIONS.md`, `docs/BOARD.md` and `docs/STATE.md` (the lead's), and D16 (stays pending).

**Acceptance criteria**
- No "Pending S3" or "Pending S5" remains in SPEC.md. D16's open question reads "Pending D16", and §0 explains that marker.
- The report has a table: each approved decision (D1–D15, D17–D25) → the SPEC section(s) that state it. A decision with no SPEC home is listed with the reason.
- A reader of SPEC alone can answer each of these: which events are registered; what happens to a subagent of a marked chat; which port the hook client uses; what R0 denies (including `serve` and `wipe`); what the client does on 401/403; when Neo4j receives steps; what `wipe` deletes. (Report: one line per question with the SPEC section.)
- Every test AGENTS.md "Testing" names exists in `tests/`. The AGENTS.md check command passes.
- Every change traces to an approved decision, an owner answer named in Scope, or a spike fact; the report lists anything left unsettled.

**Dependencies:** none (S3 ✅, S5 ✅; D16 stays open).

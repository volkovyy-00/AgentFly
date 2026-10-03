# Intent: Sunset the old page, one page at `/`
Ticket: AG-31 | Author: Yevhenii Volkovych | Date: 2026-10-03 | Status: approved (2026-10-03)

## Problem
See AG-31. The recorder serves two pages: the old `/` (vis-network from a CDN, last 10
steps) and `/v2/`. The docs describe both. Size: Architectural (the mount sits beside
`POST /hook`, a page is deleted, SPEC and AGENTS.md change, and a manual gate decides).

## Proposed outcome
`/` serves the `ui/dist` build, `/v2/` only redirects, `web/` is gone, and every doc
describes one page. Scope, gate and "after the gate" steps: see AG-31.

## Success criteria
1. A gate comment on AG-31 ticks every item in the ticket plus one AG-30 item, with the
   date and Cursor version. It exists before anything is deleted (manual). The AG-30 item:
   after more than 20 steps the summary box shows its counts; the marking step stays
   reachable by panning with its `SECRET` chip; SECRET SEEN survives a reload. Checked at
   `/v2/?mock=1&len=500`. It covers the page; the 600-step pytest covers the server.
2. `GET /` serves the new page. `/v2/` and `/v2/?mock=1&len=500` answer 307 to `/` and
   `/?mock=1&len=500`. `web/` no longer exists.
3. `POST /hook` is unaffected. The existing tests that post to `/hook` run against the
   real app with the committed `ui/dist` present, and they must pass. A `/` mount
   registered before `POST /hook` is expected to fail them with a 405. The plan proves
   that by trying it, and adds a test if none fails.
4. Wrong Host gives 403 on `/` and its assets. `Cache-Control: no-cache` is sent on `/`
   and its assets. A missing `ui/dist` logs a warning and the app still imports.
5. `grep` finds no `vis-network`, `unpkg` or `web/index.html` outside `node_modules`,
   `.git` and `docs/superpowers/`. The plan holds the literal command.
6. AGENTS.md and SPEC.md have no CDN sentence. The dependency list matches
   `ui/package.json`. Docs say `/` is the page, `/v2/` only redirects, and the mock is
   `/?mock=1`.
7. The Check command, the web check and the stale-build check pass.
8. The README GIF and the backup video show the new page (manual).

## Affected users and systems
`recorder/app.py`, `tests/test_app.py`, `ui/vite.config.ts` (`base`), `ui/index.html`,
`ui/dist`, `web/`, AGENTS.md, SPEC.md § 6 and § 10, README.md, HOOKS.md, `ui/README.md`,
the GIF and the backup video. The rehearsal uses `DEMO_PROMPTS.txt`, which is not edited.
`demo_flows/` already says `/` and becomes correct after the swap.

## Constraints
AGENTS.md checks. No new dependencies. Nothing is deleted until the gate comment exists.
The hook route, the block decision and R1 must not change behaviour.

## Decisions
- Swap only. Any "keep" would be its own ticket landing before the gate. There are none.
- Dropped, and named in the gate comment: dimmed host plus ✕, tainted-chain colouring,
  continuous glow, BLOCKED banner, legend, header counters and session id.
- Already settled: dark only (AG-29), step number in the tooltip (AG-29), secret
  indicator (AG-30), zoom off (AG-29), CSS ellipsis (AG-28).
- The legend drop rests on the demo being narrated aloud (grey and blue are told apart by
  lane). It is a decision, not a test.
- Criterion 5 excludes `docs/superpowers/`: finished plans are records, and this ticket's
  own paperwork must name the old files.
- 307, not 308, so a failed gate rolls back cleanly. The page title becomes "AgentFly".
- Jira edits to AG-31 are one change, approved 2026-10-03: add the AG-30 gate item,
  narrow the search criterion to exclude `docs/superpowers/` (naming the folder), and
  update the stale line "AG-30 is not required".
- SPEC and AGENTS.md edits authorised (2026-10-03), and nothing else in either file:
  SPEC § 6 (the "Two pages from the local server" bullet, the "main view can still
  change later" sentence, the `/v2/?mock=1` line, and "new" in "The new page is a
  timeline" and "The new page draws the 20 most recent steps"); SPEC § 10 (`GET /v2/`
  in the token-free list); AGENTS.md (the dependency paragraph, the "Live graph"
  paragraph, and the `/v2/` lines in Testing, rewritten to describe `/`). If the design
  stage finds another passage, it asks again.

## Out of scope
New features, tests on the title, rewriting history docs, Neo4j, changing `/api/steps`
(only README's "last 10 steps" line).

## Risks
Mount order against `POST /hook` (a 405 would make the helper fail open and R1 stop
blocking). The `/v2` coupling beyond `base`. The file:// mock goes away. A missing
`ui/dist` leaves `/` with no page.

## Open questions
- (spec) How to mount so `/hook` is untouched; what `/` returns when `ui/dist` is missing;
  the Cache-Control path check; where the redirect lives.
- (spec) What `/v2` (no slash), `/v2/index.html` and `/v2/assets/*` do after the swap.
  Recommendation: the first two redirect to `/`, and `/v2/assets/*` is a plain 404,
  since nothing links to it.
- (done) Criterion 3 amended 2026-10-03 (approved by the author): the sentences from "A `/`
  mount registered before `POST /hook`" to the end replace with "The mount has no catch-all
  (an explicit `GET /` plus `/assets`), so route order cannot shadow `/hook`. Tests pin
  `GET /hook` 405, `GET /index.html` 404 and `GET /nope` 404." The outcome is unchanged:
  the existing `/hook` tests pass against the real app with `ui/dist` present.

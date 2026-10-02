# AgentFly UI (v2)

Vite + React + TypeScript live-graph page, served by the recorder at `/v2/`.

Requires **Node `^22.12.0 || >=24`** (see `engines` in `package.json`).
`.nvmrc` pins Node 22 for reproducible `ui/dist` builds.

`@xyflow/react` is pinned exactly (`12.12.0`, no caret) on purpose: layout
pre-measures edge handles against that version's default 6 px handle size
(`HANDLE` in `src/graph/layout.ts`, mirrored on the DOM handles in
`nodes.tsx`). Bump only with a deliberate check that edge ends still match.

`vite` `base` is `/v2/` so asset URLs stay correct under the recorder mount
(and for future client routes under `/v2/...`). Dev server: open
`http://127.0.0.1:5173/v2/`.

```bash
npm --prefix ui ci
npm --prefix ui run check
npm --prefix ui run build
npm --prefix ui run dev   # proxies /api to http://127.0.0.1:8787
```

Commit `dist/` after build.

## What the page draws

A timeline: steps in a left column (oldest at the top), files in the middle
lane, hosts and rules in the right lane. At most 20 steps are drawn, from the
steps the page has seen (the API returns the last 10 per poll). The camera
follows the newest step, one slide per poll. The viewer can pan up and down;
a Follow button returns. Zoom is locked: at most 1, and panes narrower than
the content scale down (floor 0.5). `/v2/?mock=1` replays a sample session without calling the
server; "New session" restarts it.

Layout and camera are pure functions in `src/graph/` (`layout.ts`,
`camera.ts`); positions come from a step's stable row, never from its `order`
or its place in the list. Text is at least 16 px at full width; the one exception is React
Flow's own attribution link, kept on purpose. Tests use a jsdom setup that
measures nodes like a browser (`src/test-setup.ts`); it cannot check layout,
so after a UI change also open `/v2/?mock=1` and a real `fake_agent.py` run in
a browser.

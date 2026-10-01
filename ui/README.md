# AgentFly UI (v2)

Vite + React + TypeScript live-graph page, served by the recorder at `/v2/`.

Requires **Node `^22.12.0 || >=24`** (see `engines` in `package.json`).
`.nvmrc` pins Node 22 for reproducible `ui/dist` builds.

`vite` `base` is `/v2/` so asset URLs stay correct under the recorder mount
(and for future client routes under `/v2/...`). Dev server: open
`http://127.0.0.1:5173/v2/`.

```bash
npm --prefix ui ci
npm --prefix ui run check
npm --prefix ui run build
npm --prefix ui run dev   # proxies /api to http://127.0.0.1:8787
```

Commit `dist/` after build. Graph drawing is not implemented yet — this scaffold only shows "AgentFly v2".

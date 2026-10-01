# AgentFly UI (v2)

Vite + React + TypeScript live-graph page, served by the recorder at `/v2/`.

Requires **Node >= 20.19** (see `engines` in `package.json` and `.nvmrc`,
which pins Node 22 for reproducible `ui/dist` builds).

```bash
npm --prefix ui ci
npm --prefix ui run check
npm --prefix ui run build
npm --prefix ui run dev   # proxies /api to http://127.0.0.1:8787
```

Commit `dist/` after build. Graph drawing is not implemented yet — this scaffold only shows "AgentFly v2".

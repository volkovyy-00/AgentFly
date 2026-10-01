# AgentFly UI (v2)

Vite + React + TypeScript live-graph page, served by the recorder at `/v2/`.

```bash
npm --prefix ui ci
npm --prefix ui run check
npm --prefix ui run build
npm --prefix ui run dev   # proxies /api to http://127.0.0.1:8787
```

Commit `dist/` after build. Graph drawing is not implemented yet — this scaffold only shows "AgentFly v2".

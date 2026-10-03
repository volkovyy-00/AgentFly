# AG-31: sunset the old page, one page at `/` (design)

Intent: [2026-10-03-AG-31-sunset-old-page-intent.md](../intents/2026-10-03-AG-31-sunset-old-page-intent.md)
(approved, criterion 3 amended 2026-10-03). Size: Architectural. Date: 2026-10-03.

This spec resolves the two `(spec)` open questions. Everything the intent decided is
unchanged and not repeated here.

## Decisions made here

1. **No catch-all mount.** `mount_ui(app, dist)` registers an explicit `GET /`
   (`FileResponse(dist/index.html)`, `text/html; charset=utf-8`) and
   `Mount("/assets", StaticFiles(dist/assets))`. Tried in a scratch app on this repo's
   Starlette: `Mount("/")` before `/hook` gives `POST /hook` 405; after `/hook` it works
   but `GET /hook` becomes 404 and `/index.html` becomes a second URL for the page. The
   explicit form keeps `GET /hook` 405 and cannot shadow `/hook` whatever the order.
2. **Missing `ui/dist`.** If `dist/index.html` is not a file or `dist/assets` is not a
   directory, `mount_ui` logs one warning that names `npm --prefix ui run build` and
   registers nothing. `/` is then a plain 404. No special page: `ui/dist` is committed and
   the stale-build check guards it.
3. **Cache-Control.** The host gate sets `no-cache` when `path == "/"` or
   `path.startswith("/assets/")`, replacing `startswith("/v2")`. `/hook`, `/health`,
   `/api/steps` and the redirects keep their headers. The comment above it stops saying `/v2`.
4. **Redirects live in `app.py`.** One small handler, registered by
   `mount_v2_redirects(app)` on `GET /v2`, `GET /v2/` and `GET /v2/index.html`, whether or
   not `dist` exists. It answers 307 to `/` plus the original query string
   (`/v2/?mock=1&len=500` goes to `/?mock=1&len=500`), `Location` relative, never built
   from the Host header, `include_in_schema=False`.
5. **`/v2/assets/*` and every other `/v2/...` path are a plain 404.** Nothing links to
   them. A test pins it.

## Changes

| File | Change |
|---|---|
| `recorder/app.py` | Delete `_WEB_INDEX` and the old `@app.get("/")`. `mount_ui_v2` becomes `mount_ui` (decisions 1, 2). Add `mount_v2_redirects` (4). Update the host gate (3). |
| `ui/vite.config.ts` | Delete `base: '/v2/'` (default `/`). |
| `ui/index.html` | `<title>AgentFly</title>`. |
| `ui/dist/` | Rebuilt and committed. The build references `/assets/index.js` and `/assets/index.css`. |
| `web/` | `git rm -r web` (includes `.gitkeep`). |
| `tests/test_app.py` | See Tests. |
| AGENTS.md | The dependency paragraph (drop the CDN sentence; `@xyflow/react` and `motion` are in `ui/package.json`, so "Add ... when the graph is drawn" becomes a plain statement), the "Live graph" paragraph, the `/v2/` lines in Testing rewritten to describe `/`, including "`/` returns 404 without `ui/dist`". Nothing else in the file. |
| SPEC.md | § 6: the "Two pages" bullet, the "main view can still change later" sentence, the `/v2/?mock=1` line (becomes `/?mock=1`), "new" in "The new page is a timeline" and "The new page draws the 20 most recent steps". § 10: `GET /v2/` leaves the token-free list. Nothing else. |
| README.md | Step 4 (one page at `/`, mock is `/?mock=1`, drop "last 10 steps"), the `web/index.html` and `ui/` rows of the file table. |
| HOOKS.md | Line 54 layout (drop `web/`), the "Live graph" section (226-236), the UI-only rehearsal line (269). |
| `ui/README.md` | Title and intro, the `base` paragraph (dev server is `http://127.0.0.1:5173/`), the `/v2/?mock=1` mentions. |

Left alone: the localStorage key `agentfly_v2_ignore_session` (renaming drops a stored
ignore for no gain), `DEMO_PROMPTS.txt`, `demo_flows/`, `/api/steps`, HOOKS.md's
"last 10 cleaned steps" (that is the API's default and stays true).

## Tests (`tests/test_app.py`)

Existing `/hook` tests are untouched and must pass with `ui/dist` present.

- Wrong Host gives 403 on `/health`, `/` and `/assets/index.js`.
- `GET /`: 200, `text/html`, `Cache-Control: no-cache`, contains `id="root"`, contains
  `/assets/`, contains no `/v2/`, contains no `vis-network`. (The `/v2/` check makes a
  reverted `base` fail a test, not only the stale-build check.)
- The script named in `/`'s HTML loads from `/assets/` with 200 and `no-cache`.
- The three `/v2` paths answer 307 with the right `Location`, plus the query-preserving
  case. These tests use `follow_redirects=False` (the client follows by default).
- Pins for the design: `GET /hook` is 405, `GET /index.html` is 404, `GET /nope` is 404,
  `GET /v2/assets/index.js` is 404.
- `mount_ui` on a bare app: a missing or incomplete `dist` logs the warning and adds no
  `/` route; a complete one serves `/`.
- Delete `test_index_serves_graph_page`. Page tests keep the `requires_ui_dist` skip.

## Order of work

Each step needs the one before it. The plan's first step asks for the gate comment link
and stops if there is none.

1. **Jira (one change, approved in the intent).** Add the AG-30 gate item, narrow the
   search criterion to exclude `docs/superpowers/`, fix the stale "AG-30 is not required".
2. **Gate comment (manual, the author).** Every ticket item plus the AG-30 item, checked at
   `/v2/?mock=1&len=500` on the unchanged build, with date and Cursor version, naming the
   dropped features. Nothing is edited before it exists.
3. **Commit 1, the swap, with its tests.** `web/` is still on disk.
4. **Smoke check (manual, before `web/` goes).** `/` renders; `/?mock=1&len=500` renders;
   one real `fake_agent.py` run draws and blocks; `/v2/?mock=1` lands on `/?mock=1`. This
   covers the rebuild with `base: '/'` that the gate never saw.
5. **Commit 2, `git rm -r web`.**
6. **Commit 3, the docs** (table above).
7. **Greps, each must print nothing** (tracked files only):
   - `git grep -nIE 'vis-network|unpkg|web/index\.html' -- . ':(exclude)docs/superpowers'`
   - `git grep -nI 'web/' -- . ':(exclude)docs/superpowers' ':(exclude)ui/dist'`

   And one with an expected list: `git grep -nI '/v2' -- . ':(exclude)docs/superpowers' ':(exclude)ui/dist'`
   may list only the three redirect routes in `app.py`, the redirect and pin tests, and
   the doc lines that explain the redirect.
8. **Checks.** Check command, web check, stale-build check.

Three commits so a failed smoke check can revert the swap alone.

## After merge (follow-up, not a merge blocker)

Re-record `docs/media/same-command.gif` and the backup video on the new page (criterion 8).
The PR text lists both as open and says that `/v2/` bookmarks redirect to `/` on purpose.
AG-31 is not marked Done until criterion 8 is ticked. Until the GIF is re-recorded the
README hero shows the old page.

## Risks left

- A catch-all added later passes the `/hook` tests; the pin tests (`GET /hook` 405,
  `GET /index.html` 404, `GET /nope` 404) are what catch it.
- The file:// mock goes away. `/?mock=1` needs the recorder or `npm --prefix ui run dev`.
- A missing `ui/dist` leaves `/` as a 404 with only a log line.

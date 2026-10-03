# AG-31 Sunset the Old Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/` serves the `ui/dist` build, `/v2/` only redirects to it, `web/` is gone, and every doc describes one page.

**Architecture:** `recorder/app.py` drops the vis-network page and the `/v2` mount. A new `mount_ui(app, dist)` registers an explicit `GET /` plus `Mount("/assets")` (no catch-all, so `POST /hook` cannot be shadowed whatever the order), and `mount_v2_redirects(app)` registers three `GET` routes that answer 307 to `/` with the query string kept. The host gate sets `Cache-Control: no-cache` on `/` and `/assets/...`. Vite's `base` goes back to `/`, `ui/dist` is rebuilt, `web/` is deleted, docs are rewritten.

**Tech Stack:** Python 3.12 (FastAPI, Starlette, pytest, ruff), Vite 8 + React (Node 22). No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-03-AG-31-sunset-old-page-design.md` (read it first; it holds every decision and its reason). Intent: `docs/superpowers/intents/2026-10-03-AG-31-sunset-old-page-intent.md` (criterion 3 amended by its last `(done)` line). Ticket: AG-31 in Jira.

**Branch:** `ag-31-sunset-old-page` (already created; do all work on it, never on `main`). Baseline when this plan was written: `uv run pytest -q` gave 141 passed; `npm --prefix ui run build` leaves `ui/dist` unchanged on Node 22.

## Global Constraints

- Check before reporting any task done: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`; web: `npm --prefix ui ci && npm --prefix ui run check`; stale build: `npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)"` (run after the commit that rebuilt `ui/dist`).
- Python 3.12, type hints on every function signature, `pathlib`, small functions, ruff `line-length = 100`, rules `E,F,I,B,UP`.
- No new dependency (Python or npm).
- `POST /hook`, the block decision and R1 must not change behaviour. `hooks/`, `recorder/rules.py`, `recorder/memory.py`, `/api/steps` are not edited.
- The redirect is 307 (not 308), `Location` is relative (`/` plus the query string), never built from the Host header.
- Wrong Host gives 403 on `/`, `/assets/...` and `/v2...`. `Cache-Control: no-cache` is sent on `/` and `/assets/...` only. A missing or incomplete `ui/dist` logs a warning and the app still imports.
- The page title is "AgentFly".
- Doc edits stay inside the passages the spec lists. In SPEC.md and AGENTS.md nothing else may change. The one sentence saying `/v2/` redirects to `/` goes in AGENTS.md's Testing lines only. The "`/` is a plain 404 without `ui/dist`" note goes in HOOKS.md only.
- `tests/` must not contain the strings `vis-network`, `unpkg` or `web/index.html` (criterion 5's grep covers `tests/`).
- Nothing is deleted until the gate comment on AG-31 exists (Task 0). `web/` is deleted only after the smoke check passes (Task 2).
- Commit message ends with the trailer line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Three code commits so a failed smoke check can revert the swap alone: Task 1 (swap + tests), Task 3 (`web/` delete), Task 4 (docs).

## Review Focus

Inputs a person is most likely to hit that the spec's tests do not already name. Each has a test in the task shown in brackets.

1. A bookmark with an odd query on the old address (`/v2/?`, `/v2?mock=1`, a percent-encoded value like `q=a%26b`): the redirect must keep the query verbatim, and an empty query must not leave a dangling `?`. [Task 1]
2. A lookalike path (`/v2/foo`, `/v2x`) must be a 404, not a redirect. [Task 1]
3. A `..` path under `/assets/` must not read files outside `ui/dist/assets`, and `/assets/index.html` must be a 404 (it pins the mount root: a mount rooted at `dist` instead of `dist/assets` would serve it). [Task 1]
4. A `dist` that has `index.html` but no `assets/` (or the reverse) must be treated as missing, with the warning, not mounted half-way. [Task 1]
5. Wrong Host on the old address must give 403, not a 307 that reveals `/`. [Task 1]

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `recorder/app.py` | Serve the page and assets, redirect `/v2`, cache header on UI paths | 1 |
| `tests/test_app.py` | Pin the above and the design (`GET /hook` 405, no catch-all) | 1 |
| `ui/vite.config.ts`, `ui/index.html`, `ui/dist/` | `base` back to `/`, title, rebuilt build | 1 |
| `web/` | Deleted | 3 |
| `AGENTS.md`, `SPEC.md`, `README.md`, `HOOKS.md`, `ui/README.md` | One-page wording | 4 |

---

### Task 0: Preflight (no code; stops without the gate link)

**Files:** none.

- [ ] **Step 1: Confirm the branch and a clean tree**

Run: `git branch --show-current && git status --short && git log --oneline -4`
Expected: `ag-31-sunset-old-page`, no status lines, the top commits are the AG-31 spec commits.

- [ ] **Step 2: Ask the author for the two manual items and STOP until both are confirmed**

Ask in chat and wait for the author's reply. Do not look in Jira yourself: a link counts as confirmed only when the author pastes it in the conversation. Ask: "Is the Jira edit to AG-31 done (AG-30 gate item added, search criterion narrowed to exclude `docs/superpowers/`, the 'AG-30 is not required' line fixed)? Please paste the link to the gate comment on AG-31." The gate comment ticks every ticket item plus the AG-30 item, with date and Cursor version, checked at `/v2/?mock=1&len=500` on the unchanged build.
If there is no gate link, stop here and report that. Do not edit, delete or build anything.

- [ ] **Step 3: Run the baseline check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: all pass (141 passed).

---

### Task 1: The swap, with its tests (commit 1; `web/` stays on disk)

**Files:**
- Modify: `ui/vite.config.ts`, `ui/index.html`, `ui/dist/` (rebuilt), `recorder/app.py`, `tests/test_app.py`

**Interfaces:**
- Produces (all in `recorder/app.py`):
  - `is_ui_path(path: str) -> bool`: true for `"/"` and any path starting `"/assets/"`.
  - `mount_ui(application: FastAPI, dist: Path) -> None`: registers `GET /` and `Mount("/assets")`, or logs a warning and registers nothing when `dist/index.html` is not a file or `dist/assets` is not a directory.
  - `v2_redirect(request: Request) -> RedirectResponse`.
  - `mount_v2_redirects(application: FastAPI) -> None`: `GET /v2`, `/v2/`, `/v2/index.html`.
- Removes: `_WEB_INDEX`, the `index` route, `mount_ui_v2`.

- [ ] **Step 1: Point Vite back at `/` and rename the page, then rebuild**

In `ui/vite.config.ts` delete the line `  base: '/v2/',`. In `ui/index.html` change `<title>AgentFly v2</title>` to `<title>AgentFly</title>`.

Run: `node --version && npm --prefix ui ci && npm --prefix ui run build`
Expected: Node 22.x (matches `ui/.nvmrc`); build succeeds.

- [ ] **Step 2: Verify the rebuilt build**

Run: `git diff --stat ui/dist && cat ui/dist/index.html`
Expected: only `ui/dist/index.html` changed (the built JS and CSS are byte-identical). The file contains `src="/assets/index.js"` and `href="/assets/index.css"`, the title `AgentFly`, no `/v2/`, and no `://`. If `index.js` or `index.css` changed too, stop and report: the build is not reproducible and the stale-build check will fail.

- [ ] **Step 3: Write the failing tests**

In `tests/test_app.py`, change the parametrize line of `test_forbidden_host` from `["/health", "/v2/"]` to:

```python
@pytest.mark.parametrize("path", ["/health", "/", "/assets/index.js", "/v2", "/v2/"])
```

Then delete everything from `def test_index_serves_graph_page` through the end of `test_mount_ui_v2_when_dist_exists` (these tests: `test_index_serves_graph_page`, `test_v2_serves_new_page`, `test_v2_serves_asset`, `test_mount_ui_v2_skips_missing_dist`, `test_mount_ui_v2_when_dist_exists`) and put this in their place (keep `_post_shell` and everything after it):

```python
@requires_ui_dist
def test_root_serves_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert response.headers.get("cache-control") == "no-cache"
    text = response.text
    assert 'id="root"' in text
    assert "/assets/" in text
    assert "/v2/" not in text
    assert "://" not in text


@requires_ui_dist
def test_root_asset_loads(client: TestClient) -> None:
    page = client.get("/")
    match = re.search(r'src="[^"]*assets/([^"]+\.js)"', page.text)
    assert match is not None
    response = client.get(f"/assets/{match.group(1)}")
    assert response.status_code == 200
    assert len(response.content) > 0
    assert response.headers.get("cache-control") == "no-cache"


@pytest.mark.parametrize(
    ("path", "location"),
    [
        ("/v2", "/"),
        ("/v2/", "/"),
        ("/v2/index.html", "/"),
        ("/v2/?mock=1&len=500", "/?mock=1&len=500"),
        ("/v2?mock=1", "/?mock=1"),
        ("/v2/?", "/"),
        ("/v2/?q=a%26b", "/?q=a%26b"),
    ],
)
def test_v2_redirects_to_root(client: TestClient, path: str, location: str) -> None:
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == location


def test_v2_redirects_exist_without_dist() -> None:
    bare = FastAPI()
    app_module.mount_v2_redirects(bare)
    with TestClient(bare, base_url="http://127.0.0.1:8787") as local:
        response = local.get("/v2/?mock=1", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/?mock=1"


def test_get_hook_is_405(client: TestClient) -> None:
    # A catch-all mount registered after /hook would turn this into a 404.
    assert client.get("/hook").status_code == 405


def test_no_cache_header_only_on_ui_paths(client: TestClient) -> None:
    assert "cache-control" not in client.get("/health").headers
    assert "cache-control" not in client.get("/hook").headers


@requires_ui_dist
@pytest.mark.parametrize("path", ["/index.html", "/nope", "/v2/assets/index.js", "/v2/foo", "/v2x"])
def test_unserved_paths_are_404(client: TestClient, path: str) -> None:
    assert client.get(path, follow_redirects=False).status_code == 404


@requires_ui_dist
def test_assets_do_not_escape_their_directory(client: TestClient) -> None:
    assert client.get("/assets/%2e%2e/index.html").status_code == 404
    # index.html lives in dist/, not dist/assets/: a mount rooted at dist would serve it.
    assert client.get("/assets/index.html").status_code == 404


@pytest.mark.parametrize("case", ["missing", "empty", "no_assets", "no_index"])
def test_mount_ui_skips_incomplete_dist(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    dist = tmp_path / "dist"
    if case != "missing":
        dist.mkdir()
    if case == "no_assets":
        (dist / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    if case == "no_index":
        (dist / "assets").mkdir()
    bare = FastAPI()
    with caplog.at_level(logging.WARNING, logger="flightrecorder"):
        app_module.mount_ui(bare, dist)
    assert not any(getattr(r, "path", None) in {"/", "/assets"} for r in bare.routes)
    assert any("ui/dist" in message for message in caplog.messages)


def test_mount_ui_serves_complete_dist(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (dist / "assets" / "index.js").write_text("x", encoding="utf-8")
    bare = FastAPI()
    app_module.mount_ui(bare, dist)
    with TestClient(bare, base_url="http://127.0.0.1:8787") as local:
        assert local.get("/").status_code == 200
        assert local.get("/assets/index.js").status_code == 200
        assert local.get("/index.html").status_code == 404
```

- [ ] **Step 4: Run the tests to see them fail**

Run: `uv run pytest tests/test_app.py -q`
Expected: FAIL. At least `test_root_serves_page`, `test_root_asset_loads`, `test_v2_redirects_to_root[...]`, `test_v2_redirects_exist_without_dist`, `test_unserved_paths_are_404[/v2/assets/index.js]` and the `test_mount_ui_*` tests fail (the old page still serves `/`, `mount_ui` does not exist yet). `test_get_hook_is_405` and the other 404 cases pass already; that is expected, they pin the design.

- [ ] **Step 5: Change `recorder/app.py`**

(a) Delete the line:

```python
_WEB_INDEX: Path = Path(__file__).resolve().parent.parent / "web" / "index.html"
```

(b) Change the import to:

```python
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
```

(c) After `content_type_is_json` and before `get_store`, add:

```python
def is_ui_path(path: str) -> bool:
    """True for the page and its assets; the API and redirects are not UI paths."""
    return path == "/" or path.startswith("/assets/")
```

(d) In `host_gate`, replace

```python
    # Fixed Vite asset names need a revalidate hint; fold into the existing gate
    # so /hook is not wrapped by a second middleware and we avoid subclassing
    # StaticFiles (undocumented Starlette hook).
    if request.url.path.startswith("/v2"):
        response.headers["Cache-Control"] = "no-cache"
```

with

```python
    # Fixed Vite asset names (assets/index.js) need a revalidate hint; fold into the
    # existing gate so /hook is not wrapped by a second middleware and we avoid
    # subclassing StaticFiles (undocumented Starlette hook).
    if is_ui_path(request.url.path):
        response.headers["Cache-Control"] = "no-cache"
```

(e) Delete the old route:

```python
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_WEB_INDEX, media_type="text/html; charset=utf-8")
```

(f) Replace `mount_ui_v2` and its call (`mount_ui_v2(app, _UI_DIST)`) with:

```python
def mount_ui(application: FastAPI, dist: Path) -> None:
    """Serve the Vite build at / and /assets; never fail boot if it is missing.

    No catch-all mount: an explicit GET / plus /assets cannot shadow POST /hook,
    whatever the registration order.
    """
    index: Path = dist / "index.html"
    assets: Path = dist / "assets"
    if not (index.is_file() and assets.is_dir()):
        logger.warning(
            "ui/dist incomplete or missing; / has no page. Build it: "
            "npm --prefix ui run build (%s)",
            dist,
        )
        return

    async def page() -> FileResponse:
        return FileResponse(index, media_type="text/html; charset=utf-8")

    application.add_api_route("/", page, methods=["GET"], include_in_schema=False)
    application.mount("/assets", StaticFiles(directory=assets), name="ui_assets")


def v2_redirect(request: Request) -> RedirectResponse:
    """Old address: 307 to /, query string kept. Relative, so Host never matters."""
    query: str = request.url.query
    return RedirectResponse("/" + (f"?{query}" if query else ""), status_code=307)


def mount_v2_redirects(application: FastAPI) -> None:
    for path in ("/v2", "/v2/", "/v2/index.html"):
        application.add_api_route(path, v2_redirect, methods=["GET"], include_in_schema=False)


mount_ui(app, _UI_DIST)
mount_v2_redirects(app)
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run pytest tests/test_app.py -q`
Expected: PASS. If `test_v2_redirects_to_root[/v2/?-/]` or the `a%26b` case fails because the test client rewrote the query, report the actual `Location` and fix the expectation to what the real server answers (check with `curl` in Task 2), do not change `v2_redirect` to chase the client.

- [ ] **Step 7: Run every check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q && npm --prefix ui run check`
Expected: all pass. If `ruff format --check` fails, run `uv run ruff format .` and re-run. All the existing `/hook` tests are in this run and must pass unchanged.

- [ ] **Step 8: Commit, then run the stale-build check**

```bash
git add recorder/app.py tests/test_app.py ui/vite.config.ts ui/index.html ui/dist
git commit -m "AG-31: serve the new page at /, redirect /v2/

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)" && echo STALE-OK
```
Expected: `STALE-OK`.

---

### Task 2: Smoke check on the new build (manual; blocks Task 3)

**Files:** none. Run by the author (it needs a browser), with the executor doing the `curl` parts if a recorder is running.

The gate saw the old build at `/v2/`. This check covers the new `index.html`, and proves the browser is not showing the old cached page (the old `/` had no `Cache-Control`).

- [ ] **Step 1: Restart the recorder on the new code**

In a separate terminal (not Cursor's): stop any running recorder, then
`uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`

- [ ] **Step 2: Prove the server serves the new page and the redirect**

Run:
```bash
curl -s http://127.0.0.1:8787/ | grep -c '/assets/index.js'
curl -s -D - -o /dev/null http://127.0.0.1:8787/ | grep -i '^cache-control'
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' 'http://127.0.0.1:8787/v2/?mock=1'
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8787/hook
```
Expected: `1`; `cache-control: no-cache`; `307 http://127.0.0.1:8787/?mock=1`; `401` (the hook route is alive and wants its token).

- [ ] **Step 3: Replay a session and look at it**

Run: `uv run python fake_agent.py` then `curl -s 'http://127.0.0.1:8787/api/steps?limit=20' | grep -c R1`
Expected: the replay finishes with its expectations met; the grep prints a number of 1 or more (a blocked step names R1).

In the browser, **hard reload** (Cmd-Shift-R), then check:
1. `http://127.0.0.1:8787/` shows the new dark timeline (no legend, no vis-network header) and, after the replay, the `.env` step and the blocked R1 step.
2. `http://127.0.0.1:8787/?mock=1&len=500` renders the long session.
3. `http://127.0.0.1:8787/v2/?mock=1` lands on `/?mock=1`.

- [ ] **Step 4: Decide**

The executor asks in chat for the result and waits for the author's reply; it does not infer a pass. If all pass, the author says "smoke passed" and work continues. If anything fails: run `git revert --no-edit <Task 1 commit>` (the later commits do not exist yet), report what failed, and stop. Record the result for the PR text.

---

### Task 3: Delete `web/` (commit 2)

**Files:**
- Delete: `web/index.html`, `web/.gitkeep`

- [ ] **Step 1: Confirm Task 2 passed and nothing references the folder in code**

First ask the author in chat to paste the Task 2 smoke result, and stop without it. Then run: `git grep -n 'web/' -- recorder tests hooks fake_agent.py install.sh pyproject.toml`
Expected: no output.

- [ ] **Step 2: Remove it**

Run: `git rm -r web && ls web 2>&1 | head -1`
Expected: `ls: web: No such file or directory`.

- [ ] **Step 3: Run the Python check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "AG-31: delete the old vis-network page

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Docs, greps, final checks (commit 3)

**Files:**
- Modify: `AGENTS.md`, `SPEC.md`, `README.md`, `HOOKS.md`, `ui/README.md`

Use the Edit tool with the exact old text below. Do not touch any other passage in AGENTS.md or SPEC.md.

- [ ] **Step 1: AGENTS.md (three passages)**

Dependency paragraph. Replace

```
`@types/react-dom`. Add `@xyflow/react` and motion when the graph is drawn.
The old page at `/` still loads vis-network from a CDN; the new page at
`/v2/` is the Vite build.
```
with
```
`@types/react-dom`, `@xyflow/react` and `motion` (the last two are pinned in
`ui/package.json`). The page at `/` is the Vite build in `ui/dist`.
```

Live graph paragraph. Replace
```
- Live graph: `GET /`, `GET /v2/` (and its assets), and `GET /api/steps` are
  Host-only (no token). The page never talks to Neo4j; it reads process
```
with
```
- Live graph: `GET /` (and its assets under `/assets/`) and `GET /api/steps` are
  Host-only (no token). The page never talks to Neo4j; it reads process
```

Testing lines. Replace
```
  `?all=1` returns more than the default last 10; `GET /` serves the HTML;
  `GET /v2/` serves the React page; `/v2/` assets load; wrong Host on `/v2/`
  → 403; `/v2` file responses send `Cache-Control: no-cache`; missing `ui/dist`
  logs a warning and does not prevent the app from importing.
```
with
```
  `?all=1` returns more than the default last 10; `GET /` serves the React
  page and its `/assets/` load; wrong Host on `/` (and `/v2`) → 403; `/` and its assets send
  `Cache-Control: no-cache`; `/v2/` (also `/v2`, `/v2/index.html`) answers 307 to
  `/` with the query kept; missing `ui/dist` logs a warning and does not
  prevent the app from importing.
```

- [ ] **Step 2: SPEC.md (§ 6 and § 10)**

§ 6, first two bullets. Replace
```
- Two pages from the local server: the current demo page at `/` (vis-network
  from a CDN, steps in a row), and the new React page at `/v2/` (Vite build
  committed under `ui/dist`). The new page draws the lane graph. Which address
  the demo treats as its main view can still change later.
- The new page is a timeline. Steps run down the left, oldest at the top,
```
with
```
- One page from the local server, at `/`: the React page (Vite build committed
  under `ui/dist`), which draws the lane graph.
- The page is a timeline. Steps run down the left, oldest at the top,
```

§ 6, third bullet. Replace `- The new page draws the 20 most recent steps of the *current session*, as the` with `- The page draws the 20 most recent steps of the *current session*, as the`.

§ 6, mock line. Replace
```
  (it does not delete data). Open `/v2/?mock=1` to replay a sample session
  with no server.
```
with
```
  (it does not delete data). Open `/?mock=1` to replay a sample session
  without an agent running.
```

§ 10. Replace
```
`localhost:8787` or `127.0.0.1:8787`. The web pages themselves (`GET /`,
  `GET /v2/` and its assets, and `GET /api/steps`) need no token, because a
```
with
```
`localhost:8787` or `127.0.0.1:8787`. The web pages themselves (`GET /` and its
  assets under `/assets/`, and `GET /api/steps`) need no token, because a
```

- [ ] **Step 3: README.md**

Step 4 paragraph. Replace the block from `**4. Watch the live graph.**` to `(`&len=500&burst=10` replays a long one).` with:

```
**4. Watch the live graph.** With the recorder running, open
<http://127.0.0.1:8787/>. The page (`ui/`, Vite + React) polls `GET /api/steps`
about once a second from the server's memory, so it works without Neo4j. It is
a timeline with steps on the left, files in the middle and hosts and rules on
the right, drawing the 20 most recent steps. In a long session a summary box
above them counts the earlier steps, with up to 5 flagged ones (the step that
made R1 mark the session, and the newest blocks and warnings) one pan upward.
The page needs no token; only `POST /hook` does. To preview it with sample
data and no agent, open <http://127.0.0.1:8787/?mock=1> (`&len=500&burst=10`
replays a long session). The old `/v2/` address redirects to `/`.
```

File table. Delete the row ``| `web/index.html` | Current live graph page (vis-network from a CDN) at `/` |`` and replace the `ui/` row with
```
| `ui/` | Live graph app (Vite + React); committed build at `ui/dist`, served at `/` |
```

- [ ] **Step 4: HOOKS.md**

Line 54. Replace ``Project layout (uv skeleton): `hooks/`, `recorder/`, `web/`, `ui/`, `tests/`,`` with ``Project layout (uv skeleton): `hooks/`, `recorder/`, `ui/`, `tests/`,``.

Live graph section. Replace from `## Live graph (`web/index.html`, `ui/`, + memory API)` through ``  `/v2/assets/...`).`` with:

```
## Live graph (`ui/` + memory API)

- Page: the [`ui/`](ui/) build at `/` (Vite + React; a timeline of the 20 most
  recent steps with, above them, a summary box and up to 5 flagged older steps;
  `/?mock=1` replays a sample session without an agent).
  Server memory: [`recorder/memory.py`](recorder/memory.py) (Part B).
- `GET /` serves the committed `ui/dist` build (Host check only; no token); its
  assets are under `/assets/`. Both send `Cache-Control: no-cache`. If `ui/dist`
  is missing the server logs a warning and `/` is a plain 404: run
  `npm --prefix ui run build`.
- `/v2/` (also `/v2` and `/v2/index.html`) answers 307 to `/`, query string
  kept; any other `/v2/...` path is a 404.
```

Rehearsal line. Replace ``- UI-only rehearsal without the API: `web/index.html?mock=1` (file:// OK).`` with ``- UI-only rehearsal without an agent: `/?mock=1` (needs the recorder or `npm --prefix ui run dev`).``

- [ ] **Step 5: ui/README.md**

Replace `# AgentFly UI (v2)` with `# AgentFly UI`. Replace ``Vite + React + TypeScript live-graph page, served by the recorder at `/v2/`.`` with ``Vite + React + TypeScript live-graph page, served by the recorder at `/`.`` Replace

```
`vite` `base` is `/v2/` so asset URLs stay correct under the recorder mount
(and for future client routes under `/v2/...`). Dev server: open
`http://127.0.0.1:5173/v2/`.
```
with
```
`vite` `base` is the default `/`, so the build references `/assets/index.js`
and `/assets/index.css`, which the recorder serves. Dev server: open
`http://127.0.0.1:5173/`. The old `/v2/` address redirects to `/`.
```
Replace both remaining ``/v2/?mock=1`` with ``/?mock=1`` (one near "replays a sample session without calling the server", one in the last paragraph "also open ... and a real `fake_agent.py` run").

- [ ] **Step 6: The criterion 5 and `web/` greps (each must print nothing)**

Run:
```bash
git grep -nIE 'vis-network|unpkg|web/index\.html' -- . ':(exclude)docs/superpowers'
git grep -nI 'web/' -- . ':(exclude)docs/superpowers' ':(exclude)ui/dist'
```
Expected: no output from either (exit code 1 each). If a line prints, fix that passage (if it is in SPEC.md or AGENTS.md and outside the authorised list, stop and ask the author).

- [ ] **Step 7: The `/v2` grep (expected list)**

Run: `git grep -nI '/v2' -- . ':(exclude)docs/superpowers' ':(exclude)ui/dist'`
Expected: lines only in `recorder/app.py` (the path tuple in `mount_v2_redirects`), `tests/test_app.py` (the redirect, 403 and 404 tests, and the negative check `assert "/v2/" not in text`), and short redirect mentions in `AGENTS.md` (one line), `README.md` (one), `HOOKS.md` (two lines) and `ui/README.md` (one). `ui/vite.config.ts`, `SPEC.md` and `ui/src/` print nothing. Read every line: each must be code or a statement that `/v2/` redirects.

- [ ] **Step 8: Final checks**

Run:
```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
npm --prefix ui ci && npm --prefix ui run check
npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)" && echo STALE-OK
```
Expected: all pass; `STALE-OK`.

- [ ] **Step 9: Commit**

```bash
git add AGENTS.md SPEC.md README.md HOOKS.md ui/README.md
git commit -m "AG-31: docs describe one page at /

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 10: Give the author the PR text, then STOP (do not open the PR)**

Print this for the author to paste:

```
AG-31: one page at `/`; `/v2/` redirects.

- `/` serves the `ui/dist` build; `/v2`, `/v2/`, `/v2/index.html` answer 307 to `/` (query kept). Old `/v2/` bookmarks redirect to `/` on purpose.
- `web/` (the vis-network page) is deleted. No new dependency. `POST /hook` is unchanged.
- Three commits so each can be reverted alone: the swap + tests, the `web/` delete, the docs.
- Smoke check done on the new build before the delete: <paste Task 2 result and date>.
- Reviewing locally? Hard-reload `/` (Cmd-Shift-R): the old `/` had no Cache-Control, so a browser may still show the old page.
- Open after merge: re-record `docs/media/same-command.gif` and the backup video on the new page (criterion 8). Until then the README hero GIF shows the old page. AG-31 is not Done until criterion 8 is ticked.
```

Report: what is committed, the three commit hashes, and that the GIF and video are the only open item.

---

## Self-Review (done when writing)

- **Spec coverage:** decisions 1-5 → Task 1 step 5 and tests; changes table → Tasks 1, 3, 4; tests list → Task 1 step 3 (403 incl. `/v2`, page test with `"://"`, asset test, redirects with `follow_redirects=False`, redirects without dist, `GET /hook` 405, 404 pins marked `requires_ui_dist`, traversal, incomplete-dist cases, complete-dist test creating `assets/`, old tests deleted); order of work → Tasks 0-4 (Jira + gate in Task 0, smoke in Task 2 before the delete); the three greps → Task 4 steps 6-7; checks → Task 4 step 8; after-merge follow-up and PR text → Task 4 step 10.
- **Placeholder scan:** none. The only angle-bracket value is the Task 2 result pasted into the PR text, which does not exist until Task 2 runs.
- **Type consistency:** `is_ui_path`, `mount_ui`, `v2_redirect`, `mount_v2_redirects` are used under the same names in tests and `app.py`.
- **Review Focus:** items 1-5 map to `test_v2_redirects_to_root` (empty and encoded query), `test_unserved_paths_are_404` (`/v2/foo`, `/v2x`), `test_assets_do_not_escape_their_directory` (both assertions), `test_mount_ui_skips_incomplete_dist` (`no_assets`, `no_index`), `test_forbidden_host` (`/v2`, `/v2/`); the cache header staying off non-UI paths is `test_no_cache_header_only_on_ui_paths`.

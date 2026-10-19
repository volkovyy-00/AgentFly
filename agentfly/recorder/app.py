"""AgentFly local server: receive hook events and answer allow/deny."""

from __future__ import annotations

import json
import logging
import secrets
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agentfly.recorder.api import sessions as sessions_api
from agentfly.recorder.localstore import DB_NAME, local_store
from agentfly.recorder.memory import memory_steps, parse_limit
from agentfly.recorder.merge import step_merger
from agentfly.recorder.paths import config_dir, data_dir, migrate_legacy, private_dir
from agentfly.recorder.rules import Session, decide, deny_messages
from agentfly.recorder.sessions import SessionStore
from agentfly.recorder.store import StepRecord, build_step_record, graph_store, neo4j_opt_in

logger = logging.getLogger("agentfly")

TOKEN_HEADER: str = "X-Recorder-Token"


def find_ui_dist() -> Path:
    """The page inside the wheel, else the repo build (a checkout or an editable install)."""
    package: Path = Path(__file__).resolve().parent.parent
    for candidate in (package / "ui_dist", package.parent / "ui" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return package.parent / "ui" / "dist"


_UI_DIST: Path = find_ui_dist()
_token: str = ""
_store: SessionStore | None = None


def write_token(directory: Path) -> str:
    """Create config dir and write a fresh token file (mode 600). Return token."""
    private_dir(directory)
    token: str = secrets.token_urlsafe(32)
    path: Path = directory / "token"
    path.write_text(token, encoding="utf-8")
    path.chmod(0o600)
    return token


def host_allowed(request: Request) -> bool:
    """Host must be a localhost name on the port this server is bound to (any `--port`)."""
    server: Any = request.scope.get("server")
    if not server:
        return False
    port: int = server[1]
    host: str = request.headers.get("host", "")
    return host in {f"localhost:{port}", f"127.0.0.1:{port}"}


def content_type_is_json(request: Request) -> bool:
    raw: str = request.headers.get("content-type", "")
    media: str = raw.split(";", 1)[0].strip().lower()
    return media == "application/json"


def is_ui_path(path: str) -> bool:
    """True for the page and its assets; the API and redirects are not UI paths."""
    return path == "/" or path.startswith("/assets/")


def get_store() -> SessionStore:
    if _store is None:
        raise RuntimeError("session store not initialized")
    return _store


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _token, _store
    migrate_legacy()
    _token = write_token(config_dir())
    _store = SessionStore(data_dir() / "sessions.json")
    memory_steps.clear()
    local_store.start(data_dir() / DB_NAME)
    if neo4j_opt_in():  # D14: neo4j.env alone does not turn Neo4j on
        graph_store.start()
    logger.info("recorder listening; token written under %s", config_dir())
    yield
    graph_store.stop()
    local_store.stop()


# D19: no generated docs or schema; every served route is listed in tests/test_app.py.
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def host_gate(request: Request, call_next: Any) -> Response:
    if not host_allowed(request):
        return JSONResponse({"detail": "forbidden host"}, status_code=403)
    response = await call_next(request)
    # Fixed Vite asset names (assets/index.js) need a revalidate hint; fold into the
    # existing gate so /hook is not wrapped by a second middleware and we avoid
    # subclassing StaticFiles (undocumented Starlette hook).
    if is_ui_path(request.url.path):
        response.headers["Cache-Control"] = "no-cache"
    return response  # type: ignore[no-any-return]


def offline_guard_count() -> int:
    """Calls the hook client's offline guard answered (one byte each in the count file).

    Advisory: the file sits in the user's data folder. It is never deleted here.
    """
    try:
        info = (data_dir() / "logs" / "offline-count").lstat()
    except OSError:
        return 0
    return info.st_size if stat.S_ISREG(info.st_mode) else 0


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "offline_guard_count": offline_guard_count()}


@app.get("/api/steps")
async def api_steps(request: Request) -> JSONResponse:
    try:
        limit: int | None = parse_limit(request.query_params.get("limit"))
    except ValueError:
        return JSONResponse({"detail": "bad limit"}, status_code=400)
    all_flag: str = str(request.query_params.get("all", "") or "")
    all_steps: bool = all_flag in {"1", "true", "yes"}
    return JSONResponse(memory_steps.snapshot(all_steps=all_steps, limit=limit))


def mount_ui(application: FastAPI, dist: Path) -> None:
    """Serve the Vite build at / and /assets; never fail boot if it is missing.

    No catch-all mount: an explicit GET / plus /assets cannot shadow POST /hook,
    whatever the registration order.
    """
    index: Path = dist / "index.html"
    assets: Path = dist / "assets"
    if not (index.is_file() and assets.is_dir()):
        logger.warning(
            "ui/dist incomplete or missing; / has no page. Build it "
            "(npm --prefix ui run build), then restart the server (%s)",
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


sessions_api.add_routes(app)
mount_ui(app, _UI_DIST)
mount_v2_redirects(app)


def apply_rules(payload: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Mark, decide, memory + Neo4j enqueue, persist session. Returns (permission, verdict)."""
    store: SessionStore = get_store()
    stored: Session = store.observe(payload)  # links to a parent chat (D21 A), then the session
    stored, session, marks = store.apply_mark(payload, stored)  # also marks parent chats
    verdict, rule_id = decide(payload, session)
    order: int = session.next_step
    record: StepRecord = build_step_record(
        payload,
        session,
        verdict,
        rule_id,
        order=order,
    )
    # V2c: the second hook of one action updates its step (same order) instead of adding one.
    saved, previous = step_merger.join(session.id, payload, record)
    store.put(replace(stored, next_step=order + 1 if previous is None else stored.next_step))
    if previous is not None:
        memory_steps.replace_from_record(previous, saved, marks=marks)
    else:
        memory_steps.append_from_record(saved, marks=marks)
    graph_store.enqueue(saved)
    local_store.enqueue(saved)

    permission: dict[str, str]
    if verdict == "blocked" and rule_id is not None:
        user_msg, agent_msg = deny_messages(rule_id)
        permission = {
            "permission": "deny",
            "user_message": user_msg,
            "agent_message": agent_msg,
        }
    else:
        permission = {"permission": "allow"}
    return permission, verdict


@app.post("/hook")
async def hook(request: Request) -> Response:
    provided: str | None = request.headers.get(TOKEN_HEADER)
    if provided is None or provided != _token:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)

    if not content_type_is_json(request):
        return JSONResponse({"detail": "unsupported media type"}, status_code=415)

    raw: bytes = await request.body()
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"detail": "malformed json"}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"detail": "malformed json"}, status_code=400)

    if local_store.record_session_event(payload):  # history row only: not a step, no order number
        get_store().observe(payload)  # but still V5a's parent link (subagentStart) and marks
        return JSONResponse({"permission": "allow"})

    permission, verdict = apply_rules(payload)
    event: str = str(payload.get("hook_event_name", ""))
    logger.info("hook event=%s decision=%s", event or "?", verdict)
    return JSONResponse(permission)

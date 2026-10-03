"""AgentFly local server: receive hook events and answer allow/deny."""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from recorder.memory import memory_steps, parse_limit
from recorder.rules import Session, decide, deny_messages, mark
from recorder.sessions import SessionStore
from recorder.store import StepRecord, build_step_record, graph_store

logger = logging.getLogger("flightrecorder")

ALLOWED_HOSTS: frozenset[str] = frozenset({"localhost:8787", "127.0.0.1:8787"})
TOKEN_HEADER: str = "X-Recorder-Token"
_UI_DIST: Path = Path(__file__).resolve().parent.parent / "ui" / "dist"

# Overridable for tests (pytest sets a temp dir before lifespan runs).
config_dir: Path = Path.home() / ".config" / "flightrecorder"
_token: str = ""
_store: SessionStore | None = None


def write_token(directory: Path) -> str:
    """Create config dir and write a fresh token file (mode 600). Return token."""
    directory.mkdir(parents=True, exist_ok=True)
    token: str = secrets.token_urlsafe(32)
    path: Path = directory / "token"
    path.write_text(token, encoding="utf-8")
    path.chmod(0o600)
    return token


def host_allowed(request: Request) -> bool:
    host: str = request.headers.get("host", "")
    return host in ALLOWED_HOSTS


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
    _token = write_token(config_dir)
    _store = SessionStore(config_dir / "sessions.json")
    memory_steps.clear()
    graph_store.start()
    logger.info("recorder listening; token written under %s", config_dir)
    yield
    graph_store.stop()


app = FastAPI(lifespan=lifespan)


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


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


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


mount_ui(app, _UI_DIST)
mount_v2_redirects(app)


def apply_rules(payload: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Mark, decide, memory + Neo4j enqueue, persist session. Returns (permission, verdict)."""
    store: SessionStore = get_store()
    session_id: str = str(payload.get("conversation_id", "") or "unknown")
    session: Session = store.get_or_create(session_id)

    was_marked: bool = session.marked
    session = mark(payload, session)
    marks: bool = session.marked and not was_marked
    verdict, rule_id = decide(payload, session)
    order: int = session.next_step
    record: StepRecord = build_step_record(
        payload,
        session,
        verdict,
        rule_id,
        order=order,
    )
    session = replace(session, next_step=session.next_step + 1)
    store.put(session)
    memory_steps.append_from_record(record, marks=marks)
    graph_store.enqueue(record)

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

    permission, verdict = apply_rules(payload)
    event: str = str(payload.get("hook_event_name", ""))
    logger.info("hook event=%s decision=%s", event or "?", verdict)
    return JSONResponse(permission)

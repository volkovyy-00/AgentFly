"""AgentFly local server: receive hook events and answer allow/deny."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import stat
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agentfly.recorder import rulefile
from agentfly.recorder import rules as rules_module
from agentfly.recorder import sessions as sessions_module
from agentfly.recorder.api import rules as rules_api
from agentfly.recorder.api import sessions as sessions_api
from agentfly.recorder.localstore import DB_NAME, local_store, next_orders
from agentfly.recorder.memory import memory_steps, parse_limit
from agentfly.recorder.merge import step_merger
from agentfly.recorder.paths import config_dir, data_dir, migrate_legacy, private_dir
from agentfly.recorder.rules import (
    LIMIT_ID,
    Rule,
    Session,
    ask_messages,
    block_messages,
    decide,
    find_rule,
    one_hook,
)
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
_last_hook_at: str | None = None  # V8b: UTC, set by each /hook request that passed the token check
# V5b-fix2 §4.4: hooks that left a rule unfinished since the recorder started, and the last one's
# time (UTC) and rule ids. `/health` says so only once there is a hit.
_limit_hits: int = 0
_limit_last: tuple[str, tuple[str, ...]] | None = None


def utc_now() -> str:
    """UTC, in milliseconds: the page parses it with `new Date(...)`, which fixes 3 digits."""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


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


async def sweep_old_notes(store: SessionStore) -> None:
    """D29: drop idle notes every hour (the first sweep ran at start)."""
    while True:
        await asyncio.sleep(sessions_module.SWEEP_EVERY_SECONDS)
        try:
            store.sweep()
        except Exception as exc:  # noqa: BLE001
            logger.warning("session notes: sweep failed (%s)", type(exc).__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _token, _store, _last_hook_at
    migrate_legacy()
    _token = write_token(config_dir())
    store = _store = SessionStore(data_dir() / "sessions.json")
    # F11: a recorder that was killed may not have saved its step counters; history has the truth.
    store.raise_counters(next_orders(data_dir() / DB_NAME))
    store.sweep()
    _last_hook_at = None
    reset_rules_limit()
    memory_steps.clear()
    ruleset = rules_module.load_active()  # once: a rules file is read at start only (D3)
    if ruleset.broken:
        raise RuntimeError(ruleset.problem)  # a damaged install: hooks fall to the offline guard
    rules_module.activate(ruleset)
    if ruleset.problem:
        logger.warning("rules: %s", ruleset.problem)  # the line already says what runs instead
    local_store.start(data_dir() / DB_NAME)
    if neo4j_opt_in():  # D14: neo4j.env alone does not turn Neo4j on
        graph_store.start()
    store.start()
    sweeper = asyncio.create_task(sweep_old_notes(store))
    logger.info("recorder listening; token written under %s", config_dir())
    try:
        yield
    finally:
        sweeper.cancel()
        await asyncio.gather(sweeper, return_exceptions=True)
        store.close()  # first: the notes matter most, and the stops below can take seconds
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
    answer: dict[str, Any] = {
        "ok": True,
        "offline_guard_count": offline_guard_count(),
        "last_hook_at": _last_hook_at,
    }
    problem: str | None = rules_module.current().problem
    if problem:  # only when the active rules file was rejected; `doctor` reads it from here
        answer["rules_problem"] = problem[: rulefile.MAX_PROBLEM_CHARS]
    limit: str | None = rules_limit_line()
    if limit:  # only after a hook left a rule unfinished (the rules limit)
        answer["rules_limit"] = limit
    return answer


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
rules_api.add_routes(app)
mount_ui(app, _UI_DIST)
mount_v2_redirects(app)


def flag_marked(store: SessionStore, chat: Session) -> None:
    """Tell the history which chats the rules count as marked now: this chat and its parents (V6b).

    Every event offers the whole chain, so a parent that a subagent marked (it may have no event
    of its own afterwards) is flagged too, and a flag that was dropped is sent again. It runs after
    the decision and never raises: a history problem must not turn into a hook error.
    """
    try:
        local_store.mark_sessions(c.id for c in store.chain(chat) if store.effective_marked(c))
    except Exception as exc:  # noqa: BLE001
        logger.warning("local store: marked chats not queued (%s)", type(exc).__name__)


def reset_rules_limit() -> None:
    """The hit count starts again with the recorder (and with each test: `tests/conftest.py`)."""
    global _limit_hits, _limit_last
    _limit_hits = 0
    _limit_last = None


def report_rules_limit(chat: str, rule_ids: Sequence[str], answer: str) -> None:
    """One hook left rules unfinished: log it and count it (V5b-fix2 §4.4).

    `answer` is what the limit made of the hook: `deny`, `ask` or `none`. The line holds the chat
    and the rule ids, never the command or any request text; of the chat id at most 80
    characters, so a broken one cannot bloat the line.
    """
    global _limit_hits, _limit_last
    _limit_hits += 1
    _limit_last = (utc_now(), tuple(rule_ids))
    logger.warning(
        "rules limit: chat %r, unfinished %s, answer %s", chat[:80], ", ".join(rule_ids), answer
    )


def fit_ids(ids: Sequence[str], room: int) -> str:
    """The ids in at most `room` characters; when they do not all fit, how many were left out."""
    text: str = ", ".join(ids)
    count: int = len(ids)
    while len(text) > room and count > 1:
        count -= 1
        text = f"{', '.join(ids[:count])} and {len(ids) - count} more"
    return text


def rules_limit_line() -> str | None:
    """What `/health` says as `rules_limit`: None until the first hit, then one short line."""
    if _limit_last is None:
        return None
    at, ids = _limit_last
    head: str = (
        f"rules limit reached by {_limit_hits} hook(s) since the recorder started; "
        f"last at {at}, rules "
    )
    return head + fit_ids(ids, rulefile.MAX_PROBLEM_CHARS - len(head))


def hook_answer(verdict: str, rule: Rule | None, event: str) -> dict[str, str]:
    """What Cursor is told (D11): deny for a block, `ask` for a warn on a shell command, else allow.

    A warn on any other event and every highlight are plain allows: the page carries the mark.
    """
    if verdict == "blocked":
        user_msg, agent_msg = block_messages(rule)
        return {"permission": "deny", "user_message": user_msg, "agent_message": agent_msg}
    if verdict == "warned" and event == "beforeShellExecution" and rule is not None:
        user_msg, agent_msg = ask_messages(rule)
        return {"permission": "ask", "user_message": user_msg, "agent_message": agent_msg}
    return {"permission": "allow"}


def apply_rules(payload: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Mark, decide, memory + Neo4j enqueue, persist session. Returns (permission, verdict)."""
    store: SessionStore = get_store()
    stored: Session = store.observe(payload)  # links to a parent chat (D21 A), then the session
    # The floating patterns and command lists of this hook share one budget (V5b-fix2). Nothing in
    # this block awaits or starts a task: the meter is a context variable and must stay with this
    # hook.
    with one_hook() as meter:
        stored, session, marks = store.apply_mark(payload, stored)  # also marks parent chats
        verdict, rule_id = decide(payload, session)
    rule: Rule | None = find_rule(rule_id)  # the one lookup: the answer and the step both use it
    event: str = str(payload.get("hook_event_name", ""))
    permission: dict[str, str] = hook_answer(verdict, rule, event)
    if meter.unfinished:
        limited: bool = rule_id == LIMIT_ID and permission["permission"] != "allow"
        report_rules_limit(
            session.id, meter.unfinished, permission["permission"] if limited else "none"
        )
    order: int = session.next_step
    record: StepRecord = build_step_record(
        payload,
        session,
        verdict,
        rule_id,
        order=order,
        marks=marks,
        rule_text=rule.message if rule is not None else None,
        # V8b: the very strings the answer sends (none for an allow, a highlight, or a warn that
        # is not on a shell command). They are on each half, so the merge keeps those of the half
        # whose verdict the step shows.
        user_message=permission.get("user_message"),
        agent_message=permission.get("agent_message"),
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
    flag_marked(store, stored)  # after the step is queued: the chat's row exists by then
    return permission, verdict


@app.post("/hook")
async def hook(request: Request) -> Response:
    global _last_hook_at
    provided: str | None = request.headers.get(TOKEN_HEADER)
    if provided is None or provided != _token:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)

    _last_hook_at = utc_now()

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
        store = get_store()
        flag_marked(store, store.observe(payload))  # V5a's parent link (subagentStart) and marks
        return JSONResponse({"permission": "allow"})

    permission, verdict = apply_rules(payload)
    event: str = str(payload.get("hook_event_name", ""))
    logger.info("hook event=%s decision=%s", event or "?", verdict)
    return JSONResponse(permission)

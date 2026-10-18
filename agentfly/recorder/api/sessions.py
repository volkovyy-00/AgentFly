"""Past sessions from the local store: two GET routes, no token, Host-gated like /api/steps."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentfly.recorder.localstore import StoreUnavailable, local_store


# Plain `def`: Starlette runs these in a worker thread, so SQLite never blocks the event loop.
def api_sessions() -> JSONResponse:
    return JSONResponse({"sessions": local_store.list_sessions()})


def api_session_steps(id: str) -> JSONResponse:
    found = local_store.session_steps(id)
    if found is None:
        return JSONResponse({"detail": "unknown session"}, status_code=404)
    steps, truncated = found
    return JSONResponse({"session": id, "steps": steps, "truncated": truncated})


def history_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": "history unavailable"}, status_code=503)


def add_routes(application: FastAPI) -> None:
    """Plain `add_api_route`, like the page: the whitelist test sees every route as an APIRoute."""
    application.add_api_route("/api/sessions", api_sessions, methods=["GET"])
    application.add_api_route("/api/sessions/{id}/steps", api_session_steps, methods=["GET"])
    application.add_exception_handler(StoreUnavailable, history_unavailable)

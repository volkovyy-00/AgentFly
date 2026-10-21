"""The rules in force: one read-only GET route, no token, Host-gated like /api/steps (SPEC 11)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agentfly.recorder import rules


# Plain `def`, like the history routes: Starlette runs it in a worker thread.
def api_rules() -> JSONResponse:
    ruleset = rules.current()
    return JSONResponse(
        {
            "file": ruleset.path,
            "source": ruleset.source,
            "problem": ruleset.problem,
            "rules": [
                {"id": r.id, "kind": r.kind, "severity": r.severity, "message": r.message}
                for r in ruleset.rules
            ],
        }
    )


def add_routes(application: FastAPI) -> None:
    """Plain `add_api_route`, like the page: the whitelist test sees every route as an APIRoute."""
    application.add_api_route("/api/rules", api_rules, methods=["GET"])

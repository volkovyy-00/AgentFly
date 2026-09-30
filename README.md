# Flight Recorder

Cursor hooks send every agent action to a local server that decides allow/block,
saves a cleaned copy to Neo4j, and draws the session as a live graph.

See `SPEC.md` (source of truth) and `AGENTS.md` (working rules). Real Neo4j
credentials live in `~/.config/flightrecorder/.env`, never in this repo.

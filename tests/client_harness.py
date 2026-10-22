"""Run a copy of the hook client for a test.

Usage: `python -I -S client_harness.py FOLDER PORT BUDGET [args]`.

The client has no setting for its port (D25), so a test sets it here, from the outside.
`-I` keeps the script's own folder off sys.path, so FOLDER is added by hand.
"""

import sys

folder, port, budget, *args = sys.argv[1:]
sys.path.insert(0, folder)
# The client's folder is put on sys.path above, at run time: pyright cannot see it.
import hook_client  # noqa: E402  # pyright: ignore[reportMissingImports]

hook_client._PORT = int(port)
if budget:
    hook_client._BUDGET_S = float(budget)
sys.exit(hook_client.main(args))

"""What tests/launchctl_stub.py and tests/brew_stub.py share: a JSON state file and one `main`.

The stubs run as `python <script> <state file> <arguments>` once per call of the code under test, so
they import as little as possible.
"""

import json
import sys
from collections.abc import Callable


def serve(run: Callable[[dict, list[str]], tuple[int, str, str]], argv: list[str]) -> int:
    """Load the state, record the call, let `run` answer it, save the state, print the answer."""
    with open(argv[0], encoding="utf-8") as handle:
        state = json.load(handle)
    state["calls"].append(argv[1:])
    code, out, err = run(state, argv[1:])
    with open(argv[0], "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code

"""`python -m agentfly.cli`: how `init -g` and `uninstall` re-run themselves under sudo."""

import sys

from agentfly.cli import main

sys.exit(main())

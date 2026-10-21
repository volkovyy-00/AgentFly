"""Where the system install lives. The CLI uses only `SYSTEM`; nothing moves it (D25)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

INTERPRETER_REL = Path("bin") / "python3.12"  # inside the bundled Python folder


@dataclass(frozen=True)
class Layout:
    system_root: Path  # the root-owned AgentFly folder
    cursor_dir: Path  # the folder of Cursor's system-wide hooks.json
    cursor_app: Path  # Cursor.app, read for its version
    owner: tuple[int, int] | None  # (uid, gid) given to everything we write, when running as root

    @property
    def python_dir(self) -> Path:
        return self.system_root / "python"

    @property
    def interpreter(self) -> Path:
        return self.python_dir / INTERPRETER_REL

    @property
    def client(self) -> Path:
        return self.system_root / "hook_client.py"

    @property
    def rules(self) -> Path:
        """The active rules file (D3): root's, readable by all, written by `init -g` once."""
        return self.system_root / "rules.toml"

    @property
    def record(self) -> Path:
        return self.system_root / "hashes.json"

    @property
    def backups(self) -> Path:
        """Next to hooks.json, outside the system folder, so a backup outlives uninstall."""
        return self.cursor_dir / "agentfly-backups"

    @property
    def hooks_file(self) -> Path:
        return self.cursor_dir / "hooks.json"


SYSTEM = Layout(
    system_root=Path("/Library/Application Support/AgentFly"),
    cursor_dir=Path("/Library/Application Support/Cursor"),
    cursor_app=Path("/Applications/Cursor.app"),
    owner=(0, 0),
)

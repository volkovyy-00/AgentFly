"""The bundled Python (D5): a pinned python-build-standalone build, checked, unpacked, locked.

Chosen: CPython 3.12.15 `install_only_stripped` from release 20261013. It is relocatable, matches
the project's Python 3.12, is about 25 MB, and its URL and SHA-256 are pinned here, so a checksum
failure is real verification and not trust in a sum fetched next to the file. An update is a new
pin in a new AgentFly release; the next `init -g` sees the recorded pin differs and reinstalls.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from agentfly.install import InstallError
from agentfly.install.layout import INTERPRETER_REL

_RELEASE: str = "20261013"
_VERSION: str = "3.12.15"
_BASE: str = f"https://github.com/astral-sh/python-build-standalone/releases/download/{_RELEASE}/"


@dataclass(frozen=True)
class PythonBuild:
    name: str  # the archive's file name
    url: str
    sha256: str


def _build(arch: str, sha256: str) -> PythonBuild:
    name = f"cpython-{_VERSION}+{_RELEASE}-{arch}-apple-darwin-install_only_stripped.tar.gz"
    return PythonBuild(name=name, url=_BASE + name.replace("+", "%2B"), sha256=sha256)


BUILDS: dict[str, PythonBuild] = {
    "x86_64": _build("x86_64", "d09998f85752b646873a8a6bc7eea442a0d251b1c8d2413aa8ea06ef131c3335"),
    "aarch64": _build(
        "aarch64", "9866e11cf2ae9caa1e671383786f248859a52dd8bfb702fb4c0dc2c65f1d36de"
    ),
}


def has_apple_silicon() -> bool:
    """The hardware, not the running Python: `platform.machine()` says x86_64 under Rosetta."""
    try:
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "hw.optional.arm64"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "1"


def select_build(apple_silicon: bool | None = None) -> PythonBuild:
    if apple_silicon is None:
        apple_silicon = has_apple_silicon()
    return BUILDS["aarch64" if apple_silicon else "x86_64"]


# ---------------------------------------------------------------- hashing


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    """One SHA-256 over every path, kind, executable bit and content (links by target)."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            line = f"L {relative} {os.readlink(path)}\n"
        elif path.is_dir():
            line = f"D {relative}\n"
        else:
            executable = "x" if path.stat().st_mode & 0o111 else "-"
            line = f"F {relative} {executable} {file_sha256(path)}\n"
        digest.update(line.encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


# ---------------------------------------------------------------- download


def check_archive(path: Path, build: PythonBuild) -> None:
    try:
        actual = file_sha256(path)
    except OSError as exc:
        raise InstallError(
            f"cannot read {build.name} ({exc.strerror}); nothing was written"
        ) from exc
    if actual != build.sha256:
        raise InstallError(
            f"checksum mismatch for {build.name}: expected {build.sha256}, got {actual}; "
            "nothing was written"
        )


def download(build: PythonBuild, target: Path) -> None:
    """Fetch the archive to `target` (created atomically) and check it. Redirects are followed."""
    import httpx  # only a download needs it; every other command skips the import

    target.parent.mkdir(parents=True, exist_ok=True)
    partial: Path = target.with_name(target.name + f".part{os.getpid()}")
    try:
        with httpx.stream("GET", build.url, follow_redirects=True, timeout=60.0) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(1 << 20):
                    handle.write(chunk)
        check_archive(partial, build)
        os.replace(partial, target)
    except httpx.HTTPError as exc:
        raise InstallError(
            f"cannot download {build.name} ({type(exc).__name__}: {exc}); nothing was written"
        ) from exc
    except OSError as exc:
        raise InstallError(
            f"cannot save {build.name} ({exc.strerror}); nothing was written"
        ) from exc
    finally:
        partial.unlink(missing_ok=True)


# ---------------------------------------------------------------- unpack and lock


def _check_member(member: tarfile.TarInfo) -> None:
    parts = Path(member.name).parts
    if ".." in parts or not parts or parts[0] != "python":
        raise InstallError(f"unsafe path in the Python archive: {member.name!r}")
    if member.isdir() or member.isreg():
        return
    if member.issym():
        base = Path(member.name).parent
        resolved = os.path.normpath(base / member.linkname)
        if member.linkname.startswith("/") or not (resolved + "/").startswith("python/"):
            raise InstallError(f"unsafe link in the Python archive: {member.name!r}")
        return
    raise InstallError(f"unexpected entry type in the Python archive: {member.name!r}")


def extract(archive: Path, destination: Path) -> Path:
    """Unpack into `destination`/python with Python's `data` filter plus our own member check."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                _check_member(member)
            tar.extractall(destination, members=members, filter="data")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise InstallError(f"cannot unpack the Python archive ({type(exc).__name__})") from exc
    return destination / "python"


def lock_tree(root: Path, owner: tuple[int, int] | None) -> None:
    """Explicit modes (never the umask): directories 755, files 644, executables 755.

    `owner` is applied only when running as root; the system folder is `root:admin`, so new
    files would otherwise be group-writable by every admin.
    """
    new_owner = owner if os.geteuid() == 0 else None
    for path in [root, *root.rglob("*")]:
        if not path.is_symlink():
            mode = path.stat().st_mode
            os.chmod(path, 0o755 if stat.S_ISDIR(mode) or mode & 0o111 else 0o644)
        if new_owner is not None:
            os.lchown(path, *new_owner)  # off links lchown is chown


def compile_stdlib(python_dir: Path) -> None:
    """Byte-compile the standard library once, as root: the user cannot write the tree later.

    Without this every hook run recompiles re/json/enum from source (measured: client 70/106 ms
    median/p95 without it, 43/55 ms with it).
    """
    interpreter = python_dir / INTERPRETER_REL
    result = subprocess.run(
        [str(interpreter), "-I", "-m", "compileall", "-q", "-j", "0", str(python_dir / "lib")],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        raise InstallError(
            f"cannot byte-compile the bundled Python: {result.stderr.strip()[-200:]}"
        )

"""A stand-in sandbox backed by a temporary folder, so tool tests run without Docker.

It maps /workspace/repo to the folder, runs `python` and `grep` for real on the host, and refuses any
other command, so a test fails if a tool starts running something unexpected (or something that writes).
"""

import subprocess
import sys
from pathlib import Path

from bugbite.sandbox import CommandResult
from bugbite.sandbox.setup import REPO_DIR


class LocalSandbox:
    def __init__(self, root: Path):
        self.root = root
        self.commands: list[list[str]] = []
        self.reads: list[str] = []

    # helpers for building a repo
    def write(self, rel: str, text: str | bytes = "") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode())

    def snapshot(self) -> dict[str, bytes]:
        return {str(p.relative_to(self.root)): p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file() and not p.is_symlink()}

    def _to_host(self, text: str) -> str:
        return text.replace(REPO_DIR, str(self.root))

    def _to_sandbox(self, text: str) -> str:
        return text.replace(str(self.root.resolve()), REPO_DIR).replace(str(self.root), REPO_DIR)

    def run(self, command, *, timeout=None, **_):
        assert isinstance(command, list), "tools must pass an argument list, never a shell string"
        assert all(isinstance(part, str) for part in command)
        self.commands.append(list(command))
        assert command[0] in ("python", "grep"), f"unexpected command: {command[0]}"
        argv = [sys.executable if command[0] == "python" else command[0]] + [self._to_host(p) for p in command[1:]]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return CommandResult(done.returncode, self._to_sandbox(done.stdout), self._to_sandbox(done.stderr), False, 0.0, False)

    def read_file(self, path: str, max_bytes: int = 1 << 20):
        self.reads.append(path)
        host = Path(self._to_host(path))
        if not host.exists():
            return None
        assert host.stat().st_size <= max_bytes
        return host.read_bytes()

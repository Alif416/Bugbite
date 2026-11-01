"""One round trip into the sandbox that resolves a path (following symlinks) and says what it is.

The check happens inside the container because only there can symlinks be resolved. The script
refuses anything that resolves outside the repository or into .git, whatever the host-side check said.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from bugbite.sandbox.setup import REPO_DIR

LIST_LIMIT = 5000
TIMEOUT_S = 30

_SCRIPT = """
import json, os, stat, sys
root = os.path.realpath(sys.argv[1]); rel = sys.argv[2]; mode = sys.argv[3]; limit = int(sys.argv[4])
def out(**kw):
    print(json.dumps(kw))
target = os.path.realpath(os.path.join(root, rel)) if rel else root
if target != root and not target.startswith(root + os.sep):
    out(kind="outside")
else:
    r = os.path.relpath(target, root)
    r = "" if r == "." else r
    if ".git" in r.split(os.sep):
        out(kind="git")
    elif not os.path.exists(target):
        out(kind="missing", rel=r)
    elif os.path.isdir(target):
        if mode == "list":
            names = []
            with os.scandir(target) as it:
                for e in it:
                    if e.name == ".git" and r == "":
                        continue
                    kind = "l" if e.is_symlink() else ("d" if e.is_dir(follow_symlinks=False) else "f")
                    names.append([e.name, kind])
                    if len(names) > limit:
                        break
            out(kind="dir", rel=r, entries=names)
        else:
            out(kind="dir", rel=r)
    elif os.path.isfile(target):
        out(kind="file", rel=r, size=os.path.getsize(target), mode=stat.S_IMODE(os.stat(target).st_mode))
    else:
        out(kind="other", rel=r)
"""


@dataclass(frozen=True)
class Resolved:
    kind: str  # file, dir, missing, outside, git, other
    rel: str = ""
    size: int = 0
    mode: int = 0o644
    entries: tuple[tuple[str, str], ...] = ()

    @property
    def absolute(self) -> str:
        return f"{REPO_DIR}/{self.rel}" if self.rel else REPO_DIR


def resolve(sandbox: Any, relative: str, mode: str = "stat") -> Resolved:
    """Ask the sandbox what `relative` (already cleaned) is. `mode='list'` also lists a directory."""
    result = sandbox.run(["python", "-c", _SCRIPT, REPO_DIR, relative, mode, str(LIST_LIMIT)], timeout=TIMEOUT_S)
    if result.timed_out:
        raise TimeoutError("the sandbox took too long to look at that path")
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
        return Resolved(
            kind=str(data["kind"]),
            rel=str(data.get("rel", "")),
            size=int(data.get("size", 0)),
            mode=int(data.get("mode", 0o644)),
            entries=tuple((str(n), str(k)) for n, k in data.get("entries", ())),
        )
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError("the sandbox could not resolve that path") from None


PROBLEMS = {
    "missing": "No such file or directory: {path}",
    "outside": "{path} resolves to a location outside the repository (a symlink?), which is not available.",
    "git": "The .git directory is not available.",
    "other": "{path} is not a regular file or directory.",
}

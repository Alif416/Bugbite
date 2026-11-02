"""The scanner inside the real sandbox container: no network, no credentials, nothing run from the repo."""

import json

import pytest

from bugbite.config import SandboxConfig
from bugbite.retrieval import build_index
from bugbite.sandbox import Sandbox, list_sandbox_containers

pytestmark = pytest.mark.docker

CONFIG = SandboxConfig(max_lifetime_s=300, setup_timeout_s=120, workspace_mb=256)

_BUILD = r'''
import os
root = "/workspace/repo"
os.makedirs(root + "/pkg", exist_ok=True)
os.makedirs(root + "/.git", exist_ok=True)
open(root + "/pkg/app.py", "w").write('"""App."""\nclass App:\n    async def run(self, x: int) -> int:\n        """Run it."""\n\ndef main(): ...\n')
open(root + "/pkg/evil.py", "w").write("open('/workspace/MARKER', 'w').write('ran')\ndef trap(): ...\n")
open(root + "/pkg/bad.py", "w").write("def (:\n")
open(root + "/.git/hooks.py", "w").write("def hidden(): ...\n")
os.symlink("/etc", root + "/etclink")
os.symlink("/etc/passwd", root + "/passwd.py")
open(root + "/data.bin", "wb").write(b"\x00\x01")
'''


def test_the_index_is_built_inside_the_container():
    before = set(list_sandbox_containers())
    with Sandbox(CONFIG) as sb:
        assert sb.run(["python", "-c", _BUILD]).exit_code == 0
        assert sb.has_network is False
        env = sb.run(["python", "-c", "import os, json; print(json.dumps(sorted(os.environ)))"])
        names = set(json.loads(env.stdout)) - {"GPG_KEY"}  # GPG_KEY is the Python image's public signing key id, not a secret
        assert not any(w in name for name in names for w in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        idx = build_index(sb)
        assert [f.path for f in idx.files] == ["data.bin", "pkg/app.py", "pkg/bad.py", "pkg/evil.py"]
        assert [s.qualname for s in idx.symbols] == ["App", "App.run", "main", "trap"]
        assert idx.get("App.run").is_async and idx.get("App.run").signature == "(self, x: int) -> int" and idx.get("App.run").doc == "Run it."
        assert "SyntaxError" in idx.file("pkg/bad.py").parse_error and idx.file("data.bin").language == "binary"
        assert sb.read_file("/workspace/MARKER") is None  # parsing did not run the repo's code
        assert idx.complete
    assert set(list_sandbox_containers()) <= before

"""Rules about how the code is put together, checked on the source itself."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "bugbite"
CONCRETE_CLASSES = {"ClaudeAdapter", "OpenAICompatibleAdapter"}
CONCRETE_MODULES = {"bugbite.adapter.claude", "bugbite.adapter.openai_compatible"}


def find_violations(root: Path, adapter_dir: str = "adapter") -> list[str]:
    """Every use of a concrete adapter outside the adapter package. Only `create_adapter` may build them,
    because it is what puts the privacy guard around them (AD-081)."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.relative_to(root).parts[0] == adapter_dir:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        where = path.name
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in CONCRETE_MODULES or any(a.name in CONCRETE_CLASSES for a in node.names):
                    found.append(f"{where}:{node.lineno} imports a concrete adapter")
                elif node.level and (module.split(".")[-1] in {"claude", "openai_compatible"} or any(a.name in {"claude", "openai_compatible"} for a in node.names)):
                    found.append(f"{where}:{node.lineno} imports a concrete adapter module")
            elif isinstance(node, ast.Import):
                if any(a.name in CONCRETE_MODULES for a in node.names):
                    found.append(f"{where}:{node.lineno} imports a concrete adapter module")
            elif isinstance(node, ast.Name) and node.id in CONCRETE_CLASSES:
                found.append(f"{where}:{node.lineno} names {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in CONCRETE_CLASSES:
                found.append(f"{where}:{node.lineno} names {node.attr}")
    return found


def test_no_code_outside_the_adapter_package_builds_a_concrete_adapter():
    assert find_violations(SRC) == []


def test_the_checker_would_catch_each_way_of_bypassing_create_adapter(tmp_path):
    (tmp_path / "adapter").mkdir()
    (tmp_path / "adapter" / "fine.py").write_text("from bugbite.adapter.claude import ClaudeAdapter\n")  # allowed: inside the package
    bad = {
        "a.py": "from bugbite.adapter import ClaudeAdapter\n",
        "b.py": "from bugbite.adapter.claude import ClaudeAdapter\n",
        "c.py": "import bugbite.adapter.openai_compatible\n",
        "d.py": "from bugbite.adapter.openai_compatible import OpenAICompatibleAdapter as O\n",
        "e.py": "import bugbite.adapter as a\nx = a.ClaudeAdapter(None)\n",
        "f.py": "from bugbite.adapter import *\nx = OpenAICompatibleAdapter\n",
        "g.py": "from .adapter.claude import thing\n",
        "h.py": "from . import claude\n",
    }
    for name, source in bad.items():
        (tmp_path / name).write_text(source)
    (tmp_path / "ok.py").write_text("from bugbite.adapter import create_adapter, ModelAdapter\n")
    caught = {line.split(":")[0] for line in find_violations(tmp_path)}
    assert caught == set(bad), caught


def test_the_adapter_package_name_is_what_the_checker_exempts():
    assert (SRC / "adapter").is_dir() and (SRC / "adapter" / "registry.py").is_file()

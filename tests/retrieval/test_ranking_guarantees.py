"""Ranking this repository for realistic issues, and the guarantees: no model, no network, no environment, exact JSON."""

import ast
import json
import re
from pathlib import Path

import pytest
from idx_helpers import index_of
from rank_helpers import fixture_index
from tool_helpers import LocalSandbox

from bugbite.retrieval import Ranking, RetrievalError, build_index, rank_files

SRC = Path(__file__).resolve().parents[2] / "src" / "bugbite"
RETRIEVAL = SRC / "retrieval"

REAL_ISSUES = {
    "a replay divergence": (
        'Replaying a recording fails.\n\nTraceback (most recent call last):\n  File "/app/src/bugbite/replayer/provider.py", line 40, in generate\n'
        '    raise ReplayDivergence(kind, call)\nbugbite.replayer.errors.ReplayDivergence: request mismatch', "replayer/provider.py"),
    "a cost cap": ("The cost cap is not enforced: the total in `CostLedger` goes over the limit and the agent keeps going", "adapter/ledger.py"),
    "the text action parser": ("The text action parser rejects a model reply when the json has a trailing comma", "adapter/text_action.py"),
    "the symbol scanner": ("The symbol index scanner skips async functions inside classes when it parses python files", "retrieval/scanner.py"),
}


@pytest.fixture(scope="module")
def repo_index():
    return build_index(LocalSandbox(SRC))


@pytest.mark.parametrize("name", REAL_ISSUES)
def test_the_known_file_is_in_the_top_three_for_a_real_looking_issue(repo_index, name):
    issue, expected = REAL_ISSUES[name]
    ranking = rank_files(issue, repo_index)
    top = [c.path for c in ranking.candidates[:3]]
    assert expected in top, [(c.path, c.score) for c in ranking.candidates[:5]]
    assert len(ranking.candidates) <= 10


def test_a_traceback_in_this_repository_puts_the_failing_file_first_with_its_function(repo_index):
    ranking = rank_files(REAL_ISSUES["a replay divergence"][0], repo_index)
    top = ranking.candidates[0]
    assert top.path == "replayer/provider.py" and top.symbols and top.symbols[0].qualname == "ReplayProvider.generate"


# -- guarantees -----------------------------------------------------------------------------------------------------
NEW_MODULES = ["ranker.py", "signals.py", "words.py", "ranking_types.py"]


@pytest.mark.parametrize("module", NEW_MODULES)
def test_the_ranking_code_uses_no_model_network_process_or_environment(module):
    source = (RETRIEVAL / module).read_text()
    tree = ast.parse(source)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 0}
    assert not imported & {"os", "socket", "subprocess", "httpx", "requests", "anthropic", "docker", "urllib", "sys", "random", "time", "datetime"}
    assert not re.search(r"environ|getenv|open\(|\.read_text|\.write_text", source)
    assert "bugbite.adapter" not in source and "bugbite.sandbox" not in source


def test_only_the_agent_issue_parser_is_imported_from_the_agent_package():
    for module in NEW_MODULES:
        for line in (RETRIEVAL / module).read_text().splitlines():
            if "bugbite.agent" in line and line.startswith(("from", "import")):
                assert "bugbite.agent.issue_parse" in line, line


def test_the_json_round_trip_is_exact(tmp_path):
    ranking = rank_files("`TTLCache.expire_entries` fails in make_key", fixture_index(tmp_path))
    assert ranking.candidates and Ranking.from_json(json.loads(json.dumps(ranking.to_json()))) == ranking


@pytest.mark.parametrize("change", [
    lambda d: d.pop("notes"), lambda d: d.update(extra=1), lambda d: d.update(considered="3"), lambda d: d["candidates"][0].pop("score"),
    lambda d: d["candidates"][0]["reasons"][0].update(kind="magic"), lambda d: d["candidates"][0]["reasons"][0].update(points="5"),
    lambda d: d["candidates"][0]["symbols"].append({"name": 1}),
])
def test_a_damaged_ranking_is_refused(tmp_path, change):
    data = rank_files("`TTLCache.expire_entries` fails in make_key", fixture_index(tmp_path)).to_json()
    change(data)
    with pytest.raises(RetrievalError):
        Ranking.from_json(data)


def test_the_input_index_is_not_changed_and_the_inputs_are_checked(tmp_path):
    idx = fixture_index(tmp_path)
    before = idx.to_json()
    rank_files("make_key", idx)
    assert idx.to_json() == before
    with pytest.raises(TypeError):
        rank_files(None, idx)  # type: ignore[arg-type]


def test_an_empty_index_gives_no_candidates_and_a_note():
    from bugbite.retrieval import RepoIndex

    ranking = rank_files("make_key breaks", RepoIndex((), ()))
    assert ranking.candidates == () and ranking.considered == 0 and ranking.notes

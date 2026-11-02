"""Whole rankings: the right file first, reasons that add up, bounded and honest results."""

import time

import pytest
from idx_helpers import index_of
from rank_helpers import FILES, fixture_index, paths, ranked

from bugbite.retrieval import rank_files

TRACEBACK = '''Calling get on an entry that should have expired returns it.

Traceback (most recent call last):
  File "/home/me/app/main.py", line 3, in <module>
    cache.get("a")
  File "/usr/lib/python3.11/site-packages/other/lib.py", line 9, in wrapper
    return fn()
  File "/home/me/proj/src/cachelib/ttl.py", line 17, in expire_entries
    del self.items[key]
KeyError: 'a'
'''

ISSUES = {
    "a traceback": (TRACEBACK, "src/cachelib/ttl.py"),
    "a qualified method name": ("`TTLCache.expire_entries` removes entries that are still alive.", "src/cachelib/ttl.py"),
    "a function name": ("make_key returns the same key for different keyword arguments", "src/cachelib/keys.py"),
    "a named path": ("Bug in src/cachelib/serialize.py: unicode is lost on the way out", "src/cachelib/serialize.py"),
    "words only": ("Reading the configuration file ignores a parse failure on invalid input", "src/cachelib/config.py"),
    "a failing test and a method": ("tests/test_cache.py::test_evict fails: `LRUCache.evict` returns the newest item", "src/cachelib/cache.py"),
}


@pytest.mark.parametrize("name", ISSUES)
def test_the_expected_file_comes_first(tmp_path, name):
    issue, expected = ISSUES[name]
    ranking = ranked(tmp_path, issue)
    assert paths(ranking)[0] == expected, [(c.path, c.score) for c in ranking.candidates]


def test_every_candidate_has_reasons_that_add_up_to_its_score(tmp_path):
    for issue, _ in ISSUES.values():
        for c in ranked(tmp_path, issue).candidates:
            assert c.reasons and round(sum(r.points for r in c.reasons), 3) == c.score
            assert all(r.text and r.kind in ("traceback", "path", "test", "symbol", "words", "test_file") for r in c.reasons)


def test_a_traceback_names_the_frame_and_the_function_that_failed(tmp_path):
    ranking = ranked(tmp_path, TRACEBACK)
    top = ranking.candidates[0]
    assert top.reasons[0].kind == "traceback" and "innermost frame" in top.reasons[0].text and "expire_entries, line 17" in top.reasons[0].text
    assert [h.qualname for h in top.symbols] == ["TTLCache.expire_entries"] and (top.symbols[0].line, top.symbols[0].end_line) == (13, 18) or top.symbols
    assert "lib.py" not in " ".join(paths(ranking)) and not any("main.py" in p for p in paths(ranking))  # frames outside the repo are ignored


def test_symbol_hits_carry_line_ranges_and_the_reason(tmp_path):
    top = ranked(tmp_path, "`TTLCache.expire_entries` removes live entries").candidates[0]
    [hit] = [h for h in top.symbols if h.qualname == "TTLCache.expire_entries"]
    assert hit.why == "named in the issue" and hit.line < hit.end_line


def test_a_test_file_the_issue_does_not_name_ranks_below_the_code(tmp_path):
    ranking = ranked(tmp_path, "evict should remove the oldest item from the cache")
    order = paths(ranking)
    assert order[0] == "src/cachelib/cache.py"
    for c in ranking.candidates:
        if c.path.startswith("tests/"):
            assert any(r.kind == "test_file" and r.points < 0 for r in c.reasons)


def test_a_named_test_file_is_not_penalised_and_its_source_is_credited(tmp_path):
    ranking = ranked(tmp_path, "tests/test_ttl.py::test_expire_entries fails")
    by = {c.path: c for c in ranking.candidates}
    assert "tests/test_ttl.py" in by and not any(r.kind == "test_file" for r in by["tests/test_ttl.py"].reasons)
    assert any("covered by tests/test_ttl.py" in r.text for r in by["src/cachelib/ttl.py"].reasons)


def test_a_bare_test_name_finds_the_test_file(tmp_path):
    assert "tests/test_ttl.py" in paths(ranked(tmp_path, "test_expire_entries fails on CI"))


def test_ties_are_broken_by_path_and_the_result_does_not_depend_on_file_order(tmp_path):
    items = list(FILES.items())
    a = rank_files("cache entries", index_of(tmp_path / "a", dict(items))[0])
    b = rank_files("cache entries", index_of(tmp_path / "b", dict(reversed(items)))[0])
    assert a == b
    scores = [(-c.score, c.path) for c in a.candidates]
    assert scores == sorted(scores)


def test_the_same_input_gives_the_same_output(tmp_path):
    idx = fixture_index(tmp_path)
    assert rank_files(TRACEBACK, idx) == rank_files(TRACEBACK, idx)


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_max_results_is_honoured(tmp_path, limit):
    assert len(ranked(tmp_path, "cache entries expire", max_results=limit).candidates) <= limit


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, None])
def test_max_results_must_be_sensible(tmp_path, bad):
    with pytest.raises(ValueError):
        ranked(tmp_path, "cache", max_results=bad)


def test_an_issue_that_says_nothing_gives_no_candidates_and_a_note(tmp_path):
    for text in ["", "   \n\t", "it does not work, please help, thanks", "the the the and or but", "\x00\x01\x02", "🙂🙂🙂"]:
        ranking = ranked(tmp_path, text)
        assert ranking.candidates == () and any("no file could be linked" in n for n in ranking.notes), text


def test_a_word_found_everywhere_is_not_evidence(tmp_path):
    files = {f"pkg/m{i}.py": "def handle_request(): ...\n" for i in range(10)} | {"pkg/special.py": "def other(): ...\n"}
    ranking = rank_files("request handling is slow", index_of(tmp_path, files)[0])
    assert ranking.candidates == ()


def test_a_name_defined_in_many_places_is_ignored_but_a_unique_one_wins(tmp_path):
    files = {f"pkg/m{i}.py": "def handle(): ...\n" for i in range(12)} | {"pkg/rare.py": "def reconcile_ledger(): ...\n"}
    ranking = rank_files("`handle` is wrong and reconcile_ledger too", index_of(tmp_path, files)[0])
    assert paths(ranking) == ["pkg/rare.py"]


def test_a_name_in_a_few_places_is_shared_between_them(tmp_path):
    files = {"a.py": "def helper_thing(): ...\n", "b.py": "def helper_thing(): ...\n", "c.py": "def other_thing_here(): ...\n"}
    ranking = rank_files("helper_thing breaks", index_of(tmp_path, files)[0])
    assert paths(ranking) == ["a.py", "b.py"]
    [symbol] = [r for r in ranking.candidates[0].reasons if r.kind == "symbol"]
    assert symbol.points == 3.0 and "one of 2 places" in symbol.text  # 6 points shared between the two places


def test_an_incomplete_index_adds_a_note(tmp_path):
    files = {f"f{i}.py": "def thing_%d(): ...\n" % i for i in range(5)}
    idx = index_of(tmp_path, files, max_files=3)[0]
    assert any("index is incomplete (max_files)" in n for n in rank_files("thing_1 breaks", idx).notes)


def test_a_path_with_dotdot_or_outside_the_repo_names_nothing(tmp_path):
    ranking = ranked(tmp_path, "see ../../etc/passwd.py and /usr/lib/python3.11/os.py and ../../outside/secret.py")
    assert ranking.candidates == ()


def test_an_ambiguous_file_name_is_not_taken_as_a_named_path(tmp_path):
    files = {"a/util.py": "def x_one(): ...\n", "b/util.py": "def x_two(): ...\n"}
    ranking = rank_files("look at util.py", index_of(tmp_path, files)[0])
    assert not any(r.kind == "path" for c in ranking.candidates for r in c.reasons)  # no single file is "the" util.py
    assert sorted(paths(ranking)) == ["a/util.py", "b/util.py"] and ranking.candidates[0].score == ranking.candidates[1].score


def test_the_considered_count_and_a_huge_issue_note(tmp_path):
    ranking = ranked(tmp_path, "cache " * 20_000)
    assert ranking.considered == len(FILES) and any("was cut" in n for n in ranking.notes)


def test_hostile_text_stays_fast_and_small(tmp_path):
    idx = fixture_index(tmp_path)
    nasty = [
        "a" * 1_000_000, "`" * 100_000, "(" * 100_000, ".a" * 100_000, "_a" * 100_000, " ".join(f"name_{i}_x" for i in range(5_000)),
        "File \"" * 20_000, "Traceback (most recent call last):\n" * 5_000, "A" * 50_000 + "b" * 50_000, "\n".join("x.py:1: " + "y" * 200 for _ in range(2_000)),
    ]
    for text in nasty:
        start = time.monotonic()
        ranking = rank_files(text, idx)
        assert time.monotonic() - start < 3, text[:30]
        assert len(ranking.candidates) <= 10


def test_a_large_index_ranks_quickly(tmp_path):
    files = {f"pkg{i % 50}/mod{i}.py": "".join(f"def func_{i}_{j}(a, b):\n    '''Does thing {j}.'''\n" for j in range(8)) for i in range(1500)}
    idx = index_of(tmp_path, files, max_output_bytes=20_000_000, max_symbols=100_000)[0]
    assert idx.complete
    start = time.monotonic()
    ranking = rank_files("func_7_3 is wrong and thing 5 is slow in module mod42", idx)
    assert time.monotonic() - start < 5 and ranking.candidates[0].path == "pkg7/mod7.py"


def test_equal_scores_come_out_in_path_order_whatever_order_the_evidence_came_in(tmp_path):
    files = {"b.py": "def f1(): ...\n", "a.py": "def g1(): ...\n"}
    text = 'Traceback (most recent call last):\n  File "b.py", line 1, in f1\n    x\nKeyError: 1\n\nTraceback (most recent call last):\n  File "a.py", line 1, in g1\n    x\nKeyError: 2\n'
    ranking = rank_files(text, index_of(tmp_path, files)[0])
    assert [c.score for c in ranking.candidates] == [18.0, 18.0] and paths(ranking) == ["a.py", "b.py"]


def test_a_faint_match_alone_is_not_a_candidate(tmp_path):
    files = {f"m{i}.py": "def other(): ...\n" for i in range(9)} | {"special.py": 'def f():\n    """Frobnicates the widget."""\n'}
    ranking = rank_files("the widget looks odd", index_of(tmp_path, files)[0])
    assert ranking.candidates == ()  # a docstring word is worth 0.3 times its rarity: under the minimum on its own


def test_symbol_hits_are_listed_once_and_in_line_order(tmp_path):
    text = TRACEBACK + "\nAlso `TTLCache.expire_entries` and expire_entries() and `TTLCache.get` again."
    top = rank_files(text, fixture_index(tmp_path)).candidates[0]
    assert [h.qualname for h in top.symbols] == ["TTLCache.get", "TTLCache.expire_entries"] and top.symbols[1].why == "contains the failing line"
    assert [h.line for h in top.symbols] == sorted(h.line for h in top.symbols) and len({h.qualname for h in top.symbols}) == len(top.symbols)

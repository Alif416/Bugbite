"""Each signal alone, and the word and identifier helpers under it."""

import pytest
from rank_helpers import fixture_index

from bugbite.agent.issue_parse import find_path_mentions, find_test_mentions, parse_tracebacks
from bugbite.retrieval import signals
from bugbite.retrieval.words import MAX_IDENTIFIERS, MAX_WORDS, identifiers, issue_words, split_words, stem


# -- words ----------------------------------------------------------------------------------------------------------
def test_words_split_snake_camel_and_plain_text():
    assert split_words("parseConfig_value HTTPServer") == [stem(w) for w in ["parse", "config", "value", "http", "server"]]
    assert split_words("a b to x1 12") == []  # shorter than three letters, or digits


def test_the_stemmer_joins_simple_forms():
    assert len({stem(w) for w in ["parse", "parses", "parsed", "parsing"]}) == 1
    assert len({stem(w) for w in ["cache", "caches", "cached"]}) == 1
    assert stem("class") == "class" and stem("status") == "status" and stem("is") == "is"


def test_issue_words_drop_stop_words_and_keep_the_written_form():
    words = issue_words("The cache does not work when parsing the Config, it fails with an error")
    assert list(words.values()) == ["cache", "parsing", "config"]
    assert words[stem("parsing")] == "parsing"


def test_issue_words_are_distinct_and_capped():
    assert list(issue_words("cache cache Cache CACHE")) == [stem("cache")]
    many = " ".join(f"word{chr(97 + i % 26)}{chr(97 + i // 26)}x" for i in range(500))
    assert len(issue_words(" ".join(f"{a}{b}{c}word" for a in "abcdefghij" for b in "abcdefghij" for c in "abc"))) == MAX_WORDS
    assert many


@pytest.mark.parametrize("text, expected", [
    ("call `Cache.get` now", ["Cache.get"]),
    ("`make_key(a, b)` is wrong", ["make_key"]),
    ("LRUCache evicts", ["LRUCache"]),
    ("HTTPServer and getItem and JSONDecodeError", ["HTTPServer", "getItem", "JSONDecodeError"]),
    ("the expire_entries step", ["expire_entries"]),
    ("run parse_config() first", ["parse_config"]),
    ("see cachelib.ttl.TTLCache for it", ["TTLCache", "cachelib.ttl.TTLCache"]),
    ("```\nresult = build_index(sandbox)\n```", ["build_index"]),
    ("in file util.py and README.md and example.com", []),
    ("version 1.2.3 and e.g. this", []),
    ("_a self cls __init__ Config HTTP API Python", []),
    ("plain words only, nothing code like", []),
    ("`a`, `ab`, `abc`", []),
])
def test_identifiers(text, expected):
    assert identifiers(text) == expected


def test_identifiers_are_distinct_in_order_and_capped():
    assert identifiers("make_key and make_key and `make_key` then other_name") == ["make_key", "other_name"]
    assert len(identifiers(" ".join(f"name_{i}_x" for i in range(1000)))) == MAX_IDENTIFIERS


# -- signals --------------------------------------------------------------------------------------------------------
@pytest.fixture
def idx(tmp_path):
    return fixture_index(tmp_path)


def tb(text):
    return parse_tracebacks(text)


def test_traceback_innermost_frame_counts_most_and_outer_frames_less(idx):
    text = ('Traceback (most recent call last):\n  File "/x/src/cachelib/cache.py", line 10, in get\n    a\n'
            '  File "/x/src/cachelib/keys.py", line 2, in make_key\n    b\n  File "/x/src/cachelib/ttl.py", line 11, in expire_entries\n    c\nKeyError: 1\n')
    found = signals.traceback_signal(tb(text), idx)
    points = {p: r[0].points for p, r in found.items()}
    assert points == {"src/cachelib/ttl.py": 10.0, "src/cachelib/keys.py": 8.0, "src/cachelib/cache.py": 6.0}
    assert "innermost" in found["src/cachelib/ttl.py"][0].text and "frame 1 of 3" in found["src/cachelib/cache.py"][0].text


def test_traceback_points_never_go_below_the_floor(idx, tmp_path):
    files = {f"m{i}.py": "def f(): ...\n" for i in range(8)}
    from idx_helpers import index_of

    big = index_of(tmp_path / "x", files)[0]
    text = "Traceback (most recent call last):\n" + "".join(f'  File "m{i}.py", line 1, in f\n    x\n' for i in range(8)) + "ValueError: v\n"
    points = sorted(r[0].points for r in signals.traceback_signal(tb(text), big).values())
    assert points[0] == 3.0 and points[-1] == 10.0  # literal numbers on purpose: a change to the weights should be a visible decision


def test_traceback_frames_outside_the_repo_are_ignored(idx):
    text = 'Traceback (most recent call last):\n  File "/usr/lib/python3.11/json/decoder.py", line 3, in decode\n    x\n  File "/x/site-packages/y/z.py", line 1, in f\n    y\nValueError: v\n'
    assert signals.traceback_signal(tb(text), idx) == {}


def test_a_file_in_two_tracebacks_keeps_its_best_score(idx):
    one = 'Traceback (most recent call last):\n  File "src/cachelib/keys.py", line 2, in f\n    x\nValueError: a\n'
    two = 'Traceback (most recent call last):\n  File "src/cachelib/keys.py", line 2, in f\n    x\n  File "src/cachelib/ttl.py", line 1, in g\n    y\nValueError: b\n'
    assert signals.traceback_signal(tb(one + "\n" + two), idx)["src/cachelib/keys.py"][0].points == 10.0


def test_named_paths(idx):
    found = signals.path_signal(find_path_mentions("look at src/cachelib/ttl.py and ttl.py and nothing/missing.py"), idx)
    assert list(found) == ["src/cachelib/ttl.py"] and found["src/cachelib/ttl.py"][0].points == signals.PATH_NAMED
    assert signals.path_signal(["conftest.py"], idx)["tests/conftest.py"][0].points == signals.PATH_NAMED * signals.TEST_FILE_FACTOR


def test_named_tests_credit_the_test_file_and_its_source(idx):
    found = signals.test_signal(find_test_mentions("tests/test_cache.py::test_evict fails"), idx)
    assert found["tests/test_cache.py"][0].points == signals.TEST_FILE_NAMED
    assert found["src/cachelib/cache.py"][0].points == signals.TEST_SOURCE_PAIR and "covered by tests/test_cache.py" in found["src/cachelib/cache.py"][0].text


def test_a_bare_test_name_is_found_in_the_index(idx):
    assert list(signals.test_signal(find_test_mentions("test_expire_entries is flaky"), idx)) == ["tests/test_ttl.py", "src/cachelib/ttl.py"]
    assert signals.test_signal(find_test_mentions("test_unknown_name is flaky"), idx) == {}


def test_symbols_by_plain_and_qualified_name(idx):
    reasons, hits = signals.symbol_signal(["make_key", "TTLCache.expire_entries", "nothing_here"], idx)
    assert set(reasons) == {"src/cachelib/keys.py", "src/cachelib/ttl.py"}
    assert reasons["src/cachelib/keys.py"][0].points == signals.SYMBOL_UNIQUE and reasons["src/cachelib/ttl.py"][0].points == signals.SYMBOL_QUALIFIED
    assert [s.qualname for s in hits["src/cachelib/ttl.py"]] == ["TTLCache.expire_entries"]


def test_a_dotted_name_matches_its_longest_known_suffix(idx):
    reasons, _ = signals.symbol_signal(["cachelib.cache.LRUCache.evict"], idx)
    assert "src/cachelib/cache.py" in reasons and "LRUCache.evict" in reasons["src/cachelib/cache.py"][0].text


def test_a_name_that_is_defined_twice_is_split_between_the_places(idx):
    reasons, _ = signals.symbol_signal(["evict"], idx)  # Cache.evict and LRUCache.evict, both in cache.py
    assert [r.points for r in reasons["src/cachelib/cache.py"]] == [3.0, 3.0]


def test_symbol_points_per_file_are_capped(tmp_path):
    from idx_helpers import index_of

    idx = index_of(tmp_path, {"a.py": "".join(f"def name_{i}(): ...\n" for i in range(10))})[0]
    reasons, _ = signals.symbol_signal([f"name_{i}" for i in range(10)], idx)
    assert sum(r.points for r in reasons["a.py"]) == signals.SYMBOL_CAP_PER_FILE


def test_words_use_rarity_and_where_they_were_found(idx):
    found = signals.word_signal(issue_words("serialize the expire entries"), idx)
    assert found["src/cachelib/serialize.py"][0].points > 0 and "serialize" in found["src/cachelib/serialize.py"][0].text
    assert found["src/cachelib/ttl.py"][0].points > 0
    assert signals.word_signal({}, idx) == {}


def test_word_points_are_capped_and_only_the_strongest_matches_count(tmp_path):
    from idx_helpers import index_of

    files = {"alpha_beta_gamma_delta.py": "def x(): ...\n"} | {f"other{i}.py": "def y(): ...\n" for i in range(40)}
    idx = index_of(tmp_path, files)[0]
    found = signals.word_signal(issue_words("alpha beta gamma delta"), idx)
    assert found["alpha_beta_gamma_delta.py"][0].points == signals.WORD_CAP_PER_FILE
    one = signals.word_signal(issue_words("alpha"), idx)["alpha_beta_gamma_delta.py"][0].points
    two = signals.word_signal(issue_words("alpha beta"), idx)["alpha_beta_gamma_delta.py"][0].points
    assert 0 < one < signals.WORD_CAP_PER_FILE and two == signals.WORD_CAP_PER_FILE


def test_a_one_word_module_name_in_the_issue_is_credited(idx):
    found = signals.module_name_signal(issue_words("the serialize module breaks and keys too"), idx)
    assert set(found) == {"src/cachelib/serialize.py", "src/cachelib/keys.py"} and found["src/cachelib/keys.py"][0].points == signals.MODULE_NAME_MENTIONED
    assert "'serialize'" in found["src/cachelib/serialize.py"][0].text


def test_a_module_name_shared_by_many_files_is_ignored(tmp_path):
    from idx_helpers import index_of

    files = {f"p{i}/utils.py": "def f(): ...\n" for i in range(5)} | {"a/special.py": "def g(): ...\n"}
    found = signals.module_name_signal(issue_words("utils and special"), index_of(tmp_path, files)[0])
    assert list(found) == ["a/special.py"]


def test_test_path_detection():
    for path in ["tests/a.py", "src/tests/x/y.py", "test_a.py", "a_test.py", "conftest.py", "pkg/test/x.py"]:
        assert signals.is_test_path(path), path
    for path in ["src/a.py", "contest.py", "pkg/testing_utils.py", "latest.py", "attest/x.py"]:
        assert not signals.is_test_path(path), path or True


def test_a_file_s_word_points_use_its_three_strongest_words_only(tmp_path):
    import math

    from idx_helpers import index_of

    names = "alpha beta gamma delta epsilon zeta".split()
    files = {"a.py": "".join(f"def {n}(): ...\n" for n in names)} | {f"o{i}.py": "def q(): ...\n" for i in range(4)}
    found = signals.word_signal(issue_words(" ".join(names)), index_of(tmp_path, files)[0])
    assert found["a.py"][0].points == round(3 * 0.6 * math.log(1 + 5 / 1), 3)
    assert found["a.py"][0].text.endswith("alpha, beta, delta, epsilon and 2 more") or "and 2 more" in found["a.py"][0].text


def test_a_name_in_a_test_file_counts_half(idx):
    reasons, _ = signals.symbol_signal(["test_evict"], idx)
    assert reasons["tests/test_cache.py"][0].points == 3.0  # 6 for a name defined once, halved because it is a test


def test_a_name_defined_in_more_than_eight_places_is_ignored(tmp_path):
    from idx_helpers import index_of

    nine = index_of(tmp_path / "9", {f"m{i}.py": "def shared_name(): ...\n" for i in range(9)})[0]
    eight = index_of(tmp_path / "8", {f"m{i}.py": "def shared_name(): ...\n" for i in range(8)})[0]
    assert signals.symbol_signal(["shared_name"], nine) == ({}, {}) and len(signals.symbol_signal(["shared_name"], eight)[0]) == 8


def test_a_word_in_more_than_forty_percent_of_files_is_ignored_but_forty_percent_counts(tmp_path):
    from idx_helpers import index_of

    def repo(count):
        return index_of(tmp_path / str(count), {f"m{i}.py": "def common_word_here(): ...\n" if i < count else "def zz(): ...\n" for i in range(10)})[0]

    assert signals.word_signal(issue_words("common"), repo(5)) == {}
    assert len(signals.word_signal(issue_words("common"), repo(4))) == 4

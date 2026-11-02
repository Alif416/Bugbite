from sem_helpers import build

from bugbite.retrieval import render_semantic


def test_the_expected_chunk_comes_first_for_plain_words(tmp_path):
    with build(tmp_path)[0] as s:
        first = s.search("where do we run again after a timeout error").hits[0]
        assert (first.path, first.qualname, first.kind) == ("src/retry.py", "retry_after_timeout", "function")
        assert s.search("parse yaml settings from a configuration file").hits[0].path == "src/config.py"
        assert s.search("remove the oldest item").hits[0].qualname == "Cache.evict"


def test_hits_carry_line_ranges_and_bounded_scores(tmp_path):
    with build(tmp_path)[0] as s:
        for hit in s.search("retry delay growing exponentially").hits:
            assert 1 <= hit.line <= hit.end_line and 0 < hit.score <= 1


def test_files_without_symbols_are_searchable_by_their_head(tmp_path):
    with build(tmp_path)[0] as s:
        assert any(h.kind == "file" and h.path == "notes.txt" for h in s.search("plain notes").hits)

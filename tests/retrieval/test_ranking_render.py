"""The text view of a ranking stays small and is never cut in the middle of a line."""

import pytest
from rank_helpers import fixture_index

from bugbite.retrieval import Candidate, Ranking, Reason, rank_files, render_ranking


@pytest.fixture
def ranking(tmp_path):
    return rank_files("`TTLCache.expire_entries` and make_key and the cache config parse entries", fixture_index(tmp_path))


def test_the_view_shows_reasons_and_symbols(ranking):
    out = render_ranking(ranking)
    assert out.startswith("1. src/cachelib/") and "score" in out and "symbols: " in out and "named in the issue as" in out


def test_it_never_exceeds_max_chars_and_cuts_only_whole_lines(ranking):
    full = render_ranking(ranking, max_chars=100_000).splitlines()
    for limit in (100, 150, 300, 600, 1000, 2000):
        out = render_ranking(ranking, max_chars=limit)
        assert len(out) <= limit
        for line in out.splitlines():
            assert line in full or line.startswith("... and ") or line.startswith("note: "), line


def test_it_says_how_many_candidates_were_left_out(ranking):
    out = render_ranking(ranking, max_chars=400)
    shown = sum(1 for line in out.splitlines() if line[:1].isdigit() and ". " in line[:4])
    left = int(out.splitlines()[-1].split()[2]) if "... and " in out else 0
    assert shown + left == len(ranking.candidates) and left > 0


def test_notes_are_shown(tmp_path):
    out = render_ranking(rank_files("nothing at all", fixture_index(tmp_path)))
    assert out.startswith("note: no file could be linked")


def test_a_penalty_reason_is_shown_but_other_zero_or_negative_ones_are_not():
    c = Candidate("tests/x.py", 2.0, (Reason("symbol", "defines f", 4.0), Reason("test_file", "a test file the issue does not name", -2.0)))
    out = render_ranking(Ranking((c,), 1))
    assert "defines f" in out and "a test file the issue does not name" in out


def test_long_lines_are_cut():
    c = Candidate("a.py", 5.0, (Reason("symbol", "x" * 1000, 5.0),))
    assert all(len(line) <= 200 for line in render_ranking(Ranking((c,), 1)).splitlines())


@pytest.mark.parametrize("bad", [0, 99, -1, 2.5, True, None])
def test_the_limit_must_be_sensible(ranking, bad):
    with pytest.raises(ValueError):
        render_ranking(ranking, max_chars=bad)


def test_an_empty_ranking_renders_as_nothing():
    assert render_ranking(Ranking((), 0)) == ""

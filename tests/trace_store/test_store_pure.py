"""Parts of the trace store that need no database."""

import ast
import dataclasses
from pathlib import Path

import pytest

from bugbite.trace_store import MIGRATIONS, JobStart, TraceStore, TraceStoreError, clean_json, clean_text
from bugbite.trace_store import store as store_module
from bugbite.trace_store.store import MAX_TEXT_CHARS

SRC = Path(store_module.__file__).parent


# -- text safety -----------------------------------------------------------------------------------------------------------


def test_nul_characters_become_visible_text():
    assert clean_text("a\x00b\x00") == "a\\x00b\\x00" and "\x00" not in clean_text("\x00" * 5)


def test_long_text_is_cut_with_a_marker():
    text = clean_text("x" * (MAX_TEXT_CHARS + 25))
    assert text.startswith("x" * MAX_TEXT_CHARS) and text.endswith("[... 25 more characters not stored ...]")
    assert clean_text("x" * MAX_TEXT_CHARS) == "x" * MAX_TEXT_CHARS


def test_lone_surrogates_and_other_odd_text_are_made_storable():
    out = clean_text("ok \ud800 bad")
    out.encode("utf-8")  # must not raise
    assert out.startswith("ok ") and clean_text("emoji 🙂 עברית") == "emoji 🙂 עברית"
    assert clean_text(5) == "5"  # type: ignore[arg-type]


def test_json_is_cleaned_in_keys_and_values_recursively():
    cleaned = clean_json({"a\x00": ["b\x00", {"c": "d\x00"}, 1, 2.5, True, None], "n": 3})
    assert cleaned == {"a\\x00": ["b\\x00", {"c": "d\\x00"}, 1, 2.5, True, None], "n": 3}
    assert clean_json(object).startswith("<class")  # anything else is stored as text


# -- construction and safety -----------------------------------------------------------------------------------------------------


def test_the_connection_string_never_appears_in_the_repr_or_in_errors():
    store = TraceStore("postgresql://user:SECRET-PASSWORD@127.0.0.1:1/db")
    assert "SECRET" not in repr(store) and "SECRET" not in str(store)
    with pytest.raises(TraceStoreError) as info:  # nothing listens on port 1
        store.create_schema()
    assert "SECRET" not in str(info.value) and "could not connect" in str(info.value) and info.value.__cause__ is None
    assert "SECRET" not in repr(vars(store).get("_conn"))


@pytest.mark.parametrize("bad", ["", "   ", None, 5])
def test_a_dsn_is_required(bad):
    with pytest.raises(ValueError):
        TraceStore(bad)  # type: ignore[arg-type]


def test_a_sensitivity_must_be_known():
    for ok in ("public", "sandbox", "private"):
        JobStart("u", "o/r", "m", ok)
    for bad in ("PRIVATE", "secret", "", None):
        with pytest.raises(ValueError, match="sensitivity"):
            JobStart("u", "o/r", "m", bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 2.5, None])
def test_list_limits_are_checked_before_any_connection(limit):
    with pytest.raises(ValueError, match="limit"):
        TraceStore("postgresql://u:p@127.0.0.1:1/db").list_jobs(limit=limit)


def test_the_migration_list_is_ordered_and_has_no_gaps():
    versions = [v for v, _ in MIGRATIONS]
    assert versions == list(range(1, len(versions) + 1)) and len(versions) >= 1
    sql = MIGRATIONS[0][1]
    for table in ("jobs", "steps", "model_calls", "tool_calls"):
        assert f"CREATE TABLE {table}" in sql
    assert sql.count("ON DELETE CASCADE") == 3 and "numeric(" not in sql and "numeric CHECK" in sql and "jsonb" in sql and "timestamptz" in sql


def test_sql_is_never_built_from_text():
    """Every execute() call in the store takes fixed SQL; the only interpolation allowed is the column-list constant."""
    tree = ast.parse((SRC / "store.py").read_text())
    migrations = ast.parse((SRC / "migrations.py").read_text())
    checked = 0
    for module in (tree, migrations):
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                first = node.args[0]
                checked += 1
                if isinstance(first, ast.Constant):
                    continue
                if isinstance(first, ast.Name):
                    continue  # a module constant such as the migration text
                assert isinstance(first, ast.JoinedStr), ast.dump(first)
                names = [v.value.id for v in first.values if isinstance(v, ast.FormattedValue)]
                assert set(names) <= {"_JOB_COLUMNS"}, names
    assert checked >= 15


def test_values_that_reach_sql_are_parameters():
    text = (SRC / "store.py").read_text()
    for forbidden in (".format(", "% (", "%s'", ' + "SELECT', "+ sql", "sql +"):
        assert forbidden not in text, forbidden


def test_no_environment_access_in_the_trace_store():
    for path in SRC.glob("*.py"):
        text = path.read_text()
        assert "os.environ" not in text and "getenv" not in text, path.name


def test_the_dataclasses_are_frozen():
    for cls in (JobStart,):
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen

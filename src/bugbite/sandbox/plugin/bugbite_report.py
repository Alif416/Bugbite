"""Bugbite pytest plugin: records exact test outcomes as JSON lines.

Loaded with `-p bugbite_report`. It appends one JSON object per line to the file
named by the BUGBITE_REPORT_FILE environment variable, so partial results
survive a timeout or crash. Standard library only, and plain syntax, so that it
loads on old and new pytest versions.

Records:
  {"t": "collected", "count": N}               (+ "ids": [...] if BUGBITE_LIST_IDS=1)
  {"t": "test", "id": ..., "outcome": ..., "duration": seconds, "message": ...}
  {"t": "collect_error", "id": ..., "message": ...}
  {"t": "session", "exitstatus": int}
Every record also has "worker": the xdist worker name, or null.
"""

import json
import os

_MAX_MESSAGE = 500
_RANK = {"passed": 0, "skipped": 1, "xfailed": 1, "xpassed": 1, "failed": 3, "error": 3}
_state = {}


def _write(record):
    path = os.environ.get("BUGBITE_REPORT_FILE")
    if not path:
        return
    record["worker"] = os.environ.get("PYTEST_XDIST_WORKER")
    try:
        with open(path, "a") as handle:
            handle.write(json.dumps(record) + "\n")
    except (OSError, TypeError, ValueError):
        pass  # a missing report is detected by the reader


def _clip(text):
    return " ".join(str(text).split())[:_MAX_MESSAGE]


def _test_message(report):
    wasxfail = getattr(report, "wasxfail", None)
    if wasxfail:
        return _clip(wasxfail)
    longrepr = getattr(report, "longrepr", None)
    if longrepr is None:
        return ""
    crash = getattr(longrepr, "reprcrash", None)
    if crash is not None and getattr(crash, "message", None):
        return _clip(crash.message)
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return _clip(longrepr[2])  # (path, lineno, skip reason)
    return _clip(longrepr)


def _collect_message(report):
    text = str(getattr(report, "longrepr", "") or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    first, last = lines[0], lines[-1]
    message = first if first == last else first[:200] + " | " + last[:250]
    return _clip(message)


def pytest_collection_finish(session):
    record = {"t": "collected", "count": len(session.items)}
    if os.environ.get("BUGBITE_LIST_IDS") == "1":
        record["ids"] = [item.nodeid for item in session.items]
    _write(record)


def pytest_collectreport(report):
    if report.failed:
        _write({"t": "collect_error", "id": report.nodeid, "message": _collect_message(report)})


def pytest_runtest_logreport(report):
    entry = _state.setdefault(report.nodeid, {"outcome": None, "duration": 0.0, "message": ""})
    entry["duration"] += getattr(report, "duration", 0.0) or 0.0
    when = report.when
    wasxfail = hasattr(report, "wasxfail")

    outcome = None
    if report.failed:
        outcome = "failed" if when == "call" else "error"
    elif report.skipped:
        outcome = "xfailed" if wasxfail else "skipped"
    elif when == "call":
        outcome = "xpassed" if wasxfail else "passed"

    if outcome is not None:
        current = entry["outcome"]
        if current is None or _RANK[outcome] > _RANK[current]:
            entry["outcome"] = outcome
            entry["message"] = _test_message(report)

    if when == "teardown":
        entry = _state.pop(report.nodeid)
        _write(
            {
                "t": "test",
                "id": report.nodeid,
                "outcome": entry["outcome"] or "error",
                "duration": round(entry["duration"], 4),
                "message": entry["message"] if entry["outcome"] else "no result was recorded for this test",
            }
        )


def pytest_sessionfinish(session, exitstatus):
    _write({"t": "session", "exitstatus": int(exitstatus)})

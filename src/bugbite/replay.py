"""Command line: `python -m bugbite.replay <recording folder> [--allow-partial] [--json]`.

Exit codes: 0 the replay is identical, 1 it differs or had to stop, 2 the recording cannot be replayed.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from bugbite.recorder import RecordingError
from bugbite.replayer import ReplayError, ReplayResult, replay

IDENTICAL, DIFFERS, CANNOT = 0, 1, 2


def _summary(result: ReplayResult) -> str:
    lines = []
    if result.identical:
        status = result.agent.status if result.agent else "?"
        lines.append(f"IDENTICAL: the replay matches the recording ({len(result.events)} events, run ended as {status}).")
    elif result.divergence is not None:
        d = result.divergence
        lines.append(f"DIVERGED at {d.kind} (call {d.call}): {d.message}")
    else:
        lines.append(f"DIFFERENT: {len(result.differences)} difference(s) between the replay and the recording:")
        lines.extend(f"  - {d}" for d in result.differences)
    lines.extend(f"note: {n}" for n in result.notes)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bugbite.replay", description="Replay a recording offline and compare it with what was recorded.")
    parser.add_argument("recording", help="the recording folder (it holds manifest.json and events.jsonl)")
    parser.add_argument("--allow-partial", action="store_true", help="replay an incomplete recording as far as it goes")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    try:
        result = replay(args.recording, allow_partial=args.allow_partial)
    except (RecordingError, ReplayError) as exc:
        print(f"cannot replay: {exc}", file=sys.stderr)
        return CANNOT
    if args.json:
        d = result.divergence
        print(json.dumps({
            "identical": result.identical, "status": result.agent.status if result.agent else None,
            "divergence": None if d is None else {"kind": d.kind, "call": d.call, "message": d.message, "fields": list(d.fields), "path": d.path},
            "differences": list(result.differences), "notes": list(result.notes), "events": len(result.events),
        }, indent=2))
    else:
        print(_summary(result))
    return IDENTICAL if result.identical else DIFFERS


if __name__ == "__main__":
    raise SystemExit(main())

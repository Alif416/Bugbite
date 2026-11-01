"""Make sure crashed or killed jobs leave no sandboxes behind.

Three layers work together:

1. Docker removes a sandbox (and its workspace volume) itself when it exits.
2. `sweep_orphans()` removes sandboxes whose owner process is gone, or that
   outlived their lifetime, and leftover workspace volumes.
3. Live sandboxes are closed on normal exit (`atexit`) and, if an entry point
   asks for it, on SIGTERM and SIGINT (`install_signal_cleanup`).

Only objects carrying the Bugbite label are ever touched.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import signal
import socket
import subprocess
import threading
import time
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

import docker
from docker.errors import APIError, NotFound

log = logging.getLogger(__name__)

LABEL = "bugbite.sandbox"
JOB_LABEL = "bugbite.job"
HOST_LABEL = "bugbite.owner_host"
PID_LABEL = "bugbite.owner_pid"
STARTED_LABEL = "bugbite.owner_started"
CREATED_LABEL = "bugbite.created"
LIFETIME_LABEL = "bugbite.max_lifetime"

DEFAULT_LIFETIME_S = 1800
DEFAULT_GRACE_S = 60


def brief(exc: BaseException) -> str:
    """Short, single-line description of a Docker/SDK error."""
    if isinstance(exc, APIError) and exc.explanation:
        text = str(exc.explanation)
    else:
        text = str(exc) or type(exc).__name__
    text = " ".join(text.split())
    return text if len(text) <= 300 else text[:297] + "..."


# -- owners -------------------------------------------------------------------


@dataclass(frozen=True)
class Owner:
    """The process that created a sandbox. `started` guards against process-id reuse."""

    host: str
    pid: int
    started: str


def _process_start_token(pid: int) -> str:
    """When the process started, as `ps` prints it ("" if it cannot be read)."""
    try:
        done = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return " ".join(done.stdout.split()) if done.returncode == 0 else ""


_owner_cache: dict[int, Owner] = {}


def current_owner() -> Owner:
    pid = os.getpid()
    if pid not in _owner_cache:
        _owner_cache[pid] = Owner(host=socket.gethostname(), pid=pid, started=_process_start_token(pid))
    return _owner_cache[pid]


def owner_alive(owner: Owner) -> bool | None:
    """True/False if we can tell whether the owner process is still running; None if unknown."""
    if owner.host != socket.gethostname():
        return None
    if owner.pid <= 0:
        return False
    try:
        os.kill(owner.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # the process exists but belongs to someone else
    except OSError:
        return None
    if owner.started:
        token = _process_start_token(owner.pid)
        if token and token != owner.started:
            return False  # the process id now belongs to a different process
    return True


# -- labels ---------------------------------------------------------------------


def make_labels(job_id: str, owner: Owner, created: float, max_lifetime: int) -> dict[str, str]:
    return {
        LABEL: "1",
        JOB_LABEL: job_id,
        HOST_LABEL: owner.host,
        PID_LABEL: str(owner.pid),
        STARTED_LABEL: owner.started,
        CREATED_LABEL: str(int(created)),
        LIFETIME_LABEL: str(int(max_lifetime)),
    }


@dataclass(frozen=True)
class ParsedLabels:
    owner: Owner | None
    created: float | None
    max_lifetime: int | None


def parse_labels(labels: Mapping[str, str] | None) -> ParsedLabels:
    """Read ownership labels. Missing or malformed values become None; this never raises."""
    labels = labels or {}
    owner = None
    host, pid = labels.get(HOST_LABEL), labels.get(PID_LABEL)
    if host and pid and re.fullmatch(r"\d+", pid):
        owner = Owner(host=host, pid=int(pid), started=labels.get(STARTED_LABEL, ""))
    created = labels.get(CREATED_LABEL, "")
    lifetime = labels.get(LIFETIME_LABEL, "")
    return ParsedLabels(
        owner=owner,
        created=float(created) if re.fullmatch(r"\d+", created) else None,
        max_lifetime=int(lifetime) if re.fullmatch(r"\d+", lifetime) and int(lifetime) > 0 else None,
    )


# -- the orphan decision (pure) -----------------------------------------------------


def is_orphan(
    labels: Mapping[str, str] | None,
    docker_created: float,
    now: float,
    *,
    grace_s: float = DEFAULT_GRACE_S,
    alive: Callable[[Owner], bool | None] = owner_alive,
) -> tuple[bool, str]:
    """Decide whether a sandbox container is an orphan, and say why.

    A sandbox whose owner is alive and within its lifetime is never an orphan.
    """
    parsed = parse_labels(labels)
    created = parsed.created if parsed.created is not None else docker_created
    lifetime = parsed.max_lifetime or DEFAULT_LIFETIME_S
    age = max(0.0, now - created)  # clock skew can make the age negative

    if parsed.owner is not None and alive(parsed.owner) is False:
        return True, "its owner process is gone"
    if age > lifetime + grace_s:
        return True, f"it is older than its lifetime ({lifetime}s) plus {grace_s:g}s grace"
    if parsed.owner is None:
        return False, "no owner recorded, but it is still within its lifetime"
    return False, "its owner is alive or unknown and it is within its lifetime"


def _parse_docker_time(text: Any) -> float | None:
    """Docker timestamps look like 2026-11-01T07:47:00.123456789Z."""
    if not isinstance(text, str):
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?", text)
    if not match:
        return None
    fraction = (match.group(2) or "0")[:6].ljust(6, "0")
    moment = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(
        microsecond=int(fraction), tzinfo=timezone.utc
    )
    return moment.timestamp()


# -- the sweeper -------------------------------------------------------------------


@dataclass(frozen=True)
class SweepReport:
    containers_removed: tuple[str, ...]
    volumes_removed: tuple[str, ...]
    kept: tuple[tuple[str, str], ...]  # (name, reason)
    errors: tuple[str, ...]


def sweep_orphans(
    client: docker.DockerClient | None = None,
    *,
    grace_s: float = DEFAULT_GRACE_S,
    now: float | None = None,
) -> SweepReport:
    """Remove orphaned sandbox containers, then leftover workspace volumes."""
    owns_client = client is None
    if client is None:
        from bugbite.sandbox.container import _connect  # imported late: container imports this module

        client = _connect(60)
    moment = time.time() if now is None else now
    removed_containers: list[str] = []
    removed_volumes: list[str] = []
    kept: list[tuple[str, str]] = []
    errors: list[str] = []
    try:
        for container in client.containers.list(all=True, filters={"label": f"{LABEL}=1"}):
            name = container.name
            created = _parse_docker_time(container.attrs.get("Created")) or moment
            orphan, reason = is_orphan(container.labels, created, moment, grace_s=grace_s)
            if not orphan:
                kept.append((name, reason))
                continue
            try:
                container.remove(force=True, v=True)
                removed_containers.append(name)
            except NotFound:
                pass  # already gone (for example removed by Docker on exit)
            except Exception as exc:
                errors.append(f"container {name}: {brief(exc)}")

        for volume in client.volumes.list(filters={"label": f"{LABEL}=1"}):
            name = volume.name
            created = _parse_docker_time(volume.attrs.get("CreatedAt")) or moment
            if moment - created <= grace_s:
                kept.append((name, "volume is younger than the grace period"))
                continue
            try:
                volume.remove()
                removed_volumes.append(name)
            except NotFound:
                pass
            except APIError as exc:
                if exc.status_code == 409:
                    kept.append((name, "volume is still in use"))
                else:
                    errors.append(f"volume {name}: {brief(exc)}")
            except Exception as exc:
                errors.append(f"volume {name}: {brief(exc)}")
    finally:
        if owns_client:
            client.close()
    return SweepReport(tuple(removed_containers), tuple(removed_volumes), tuple(kept), tuple(errors))


# -- exit hooks ---------------------------------------------------------------------

_live: "weakref.WeakSet[Any]" = weakref.WeakSet()
_live_lock = threading.Lock()


def register_sandbox(sandbox: Any) -> None:
    with _live_lock:
        _live.add(sandbox)


def unregister_sandbox(sandbox: Any) -> None:
    with _live_lock:
        _live.discard(sandbox)


def live_sandboxes() -> list[Any]:
    with _live_lock:
        return list(_live)


def close_all_sandboxes() -> None:
    """Close every live sandbox, ignoring individual failures."""
    for sandbox in live_sandboxes():
        try:
            sandbox.close()
        except Exception as exc:  # keep going: one failure must not leave the rest running
            log.warning("could not close a sandbox during cleanup: %s", brief(exc))


atexit.register(close_all_sandboxes)


def _signal_handler(previous: Any) -> Callable[[int, Any], None]:
    def handler(signum: int, frame: Any) -> None:
        close_all_sandboxes()
        if callable(previous):
            previous(signum, frame)  # for SIGINT this raises KeyboardInterrupt as usual
        else:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)  # end the process the normal way for this signal

    return handler


def install_signal_cleanup(signals: Sequence[int] | None = None) -> Callable[[], None]:
    """Close all live sandboxes on SIGTERM and SIGINT, then let the previous behaviour run.

    Call this from an entry point (CLI, API), not from library code: it changes
    process-wide signal handling and must run in the main thread. Signals that
    are currently ignored are left alone. Returns a function that removes the handlers.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("install_signal_cleanup must be called from the main thread")
    chosen = tuple(signals) if signals is not None else (signal.SIGTERM, signal.SIGINT)
    previous: dict[int, Any] = {}
    for signum in chosen:
        old = signal.getsignal(signum)
        if old == signal.SIG_IGN:
            continue
        previous[signum] = old
        signal.signal(signum, _signal_handler(old))

    def uninstall() -> None:
        for signum, old in previous.items():
            signal.signal(signum, old if old is not None else signal.SIG_DFL)

    return uninstall

"""Orphan rules, labels, owners, registry, and signal handling. No Docker needed."""

import os
import signal
import socket
import subprocess
import sys
import threading

import pytest

from bugbite.sandbox import cleanup
from bugbite.sandbox.cleanup import (
    CREATED_LABEL,
    DEFAULT_LIFETIME_S,
    HOST_LABEL,
    LABEL,
    LIFETIME_LABEL,
    PID_LABEL,
    STARTED_LABEL,
    Owner,
    close_all_sandboxes,
    current_owner,
    install_signal_cleanup,
    is_orphan,
    live_sandboxes,
    make_labels,
    owner_alive,
    parse_labels,
    register_sandbox,
    unregister_sandbox,
)

HOST = socket.gethostname()
NOW = 1_800_000_000.0
LIFETIME = 1800
GRACE = 60


def labels_for(owner, age=0.0, lifetime=LIFETIME, now=NOW):
    return make_labels("job", owner, now - age, lifetime)


ALIVE = lambda owner: True  # noqa: E731
DEAD = lambda owner: False  # noqa: E731
UNKNOWN = lambda owner: None  # noqa: E731
MINE = Owner(HOST, 4242, "token")


# -- the orphan rule -------------------------------------------------------------------


def test_live_owner_within_lifetime_is_kept():
    orphan, reason = is_orphan(labels_for(MINE, age=10), NOW - 10, NOW, alive=ALIVE)
    assert orphan is False and "alive" in reason


def test_live_owner_is_kept_even_with_zero_grace_while_within_lifetime():
    assert is_orphan(labels_for(MINE, age=LIFETIME - 1), NOW, NOW, grace_s=0, alive=ALIVE)[0] is False


def test_live_owner_that_outlived_lifetime_plus_grace_is_an_orphan():
    orphan, reason = is_orphan(labels_for(MINE, age=LIFETIME + GRACE + 1), NOW, NOW, grace_s=GRACE, alive=ALIVE)
    assert orphan is True and "lifetime" in reason


def test_grace_boundary_exactly_equal_is_kept_and_one_over_is_orphan():
    assert is_orphan(labels_for(MINE, age=LIFETIME + GRACE), NOW, NOW, grace_s=GRACE, alive=ALIVE)[0] is False
    assert is_orphan(labels_for(MINE, age=LIFETIME + GRACE + 1), NOW, NOW, grace_s=GRACE, alive=ALIVE)[0] is True


def test_dead_owner_is_an_orphan_even_when_young():
    orphan, reason = is_orphan(labels_for(MINE, age=1), NOW, NOW, alive=DEAD)
    assert orphan is True and "gone" in reason


def test_unknown_owner_other_host_young_is_kept_and_old_is_orphan():
    other = Owner("another-machine", 1, "")
    assert is_orphan(labels_for(other, age=30), NOW, NOW, alive=UNKNOWN)[0] is False
    assert is_orphan(labels_for(other, age=LIFETIME + GRACE + 5), NOW, NOW, alive=UNKNOWN)[0] is True


def test_per_container_lifetime_is_used_not_the_default():
    # a sandbox with a 5 s lifetime is an orphan at age 100 (> 5 + 60 grace)...
    short = labels_for(MINE, age=100, lifetime=5)
    assert is_orphan(short, NOW, NOW, grace_s=GRACE, alive=ALIVE)[0] is True
    # ...but at age 30 (< 5 + 60) it is still kept
    young = labels_for(MINE, age=30, lifetime=5)
    assert is_orphan(young, NOW, NOW, grace_s=GRACE, alive=ALIVE)[0] is False
    # with the default 1800 s lifetime, age 100 would be fine
    default = labels_for(MINE, age=100, lifetime=DEFAULT_LIFETIME_S)
    assert is_orphan(default, NOW, NOW, grace_s=GRACE, alive=ALIVE)[0] is False


def test_legacy_container_without_labels_is_judged_by_docker_creation_time():
    plain = {LABEL: "1"}
    assert is_orphan(plain, NOW - 10, NOW)[0] is False
    assert is_orphan(plain, NOW - (DEFAULT_LIFETIME_S + GRACE + 1), NOW)[0] is True
    assert is_orphan(None, NOW - 10, NOW)[0] is False


def test_unreadable_labels_fall_back_instead_of_raising():
    junk = {LABEL: "1", PID_LABEL: "abc", HOST_LABEL: HOST, CREATED_LABEL: "yesterday", LIFETIME_LABEL: "-5"}
    assert is_orphan(junk, NOW - 10, NOW)[0] is False
    assert is_orphan(junk, NOW - 10_000, NOW)[0] is True


def test_negative_age_from_clock_skew_is_treated_as_zero():
    future = labels_for(MINE, age=-500)  # created "in the future"
    assert is_orphan(future, NOW, NOW, alive=ALIVE)[0] is False


# -- labels ---------------------------------------------------------------------------------


def test_labels_round_trip():
    owner = Owner("host-a", 77, "Sun Nov  1 10:00:00 2026")
    parsed = parse_labels(make_labels("job-1", owner, 1234.9, 600))
    assert parsed.owner == owner
    assert parsed.created == 1234.0
    assert parsed.max_lifetime == 600


@pytest.mark.parametrize("bad", [{}, None, {PID_LABEL: "x"}, {HOST_LABEL: HOST}, {PID_LABEL: "-3", HOST_LABEL: HOST}])
def test_parse_labels_never_raises(bad):
    parsed = parse_labels(bad)
    assert parsed.owner is None and parsed.created is None and parsed.max_lifetime is None


def test_every_object_carries_the_bugbite_label():
    labels = make_labels("", MINE, NOW, 10)
    assert labels[LABEL] == "1"
    assert set(labels) >= {HOST_LABEL, PID_LABEL, STARTED_LABEL, CREATED_LABEL, LIFETIME_LABEL}


# -- owners -----------------------------------------------------------------------------------


def test_current_owner_describes_this_process():
    owner = current_owner()
    assert owner.pid == os.getpid() and owner.host == HOST
    assert current_owner() is owner  # cached
    assert owner_alive(owner) is True


def test_a_finished_process_is_not_alive():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert owner_alive(Owner(HOST, child.pid, "")) is False


def test_a_reused_process_id_with_another_start_token_is_not_alive():
    mine = current_owner()
    if not mine.started:
        pytest.skip("`ps` is not available to read process start times")
    assert owner_alive(Owner(HOST, mine.pid, "Mon Jan  1 00:00:00 2001")) is False
    assert owner_alive(mine) is True


def test_other_host_is_unknown_and_bad_pids_are_not_alive():
    assert owner_alive(Owner("some-other-host", os.getpid(), "")) is None
    assert owner_alive(Owner(HOST, 0, "")) is False
    assert owner_alive(Owner(HOST, -5, "")) is False


def test_pid_that_exists_without_a_token_counts_as_alive():
    assert owner_alive(Owner(HOST, os.getpid(), "")) is True


# -- docker timestamps ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1970-01-01T00:00:10Z", 10.0),
        ("1970-01-01T00:00:10.5Z", 10.5),
        ("1970-01-01T00:00:10.123456789Z", 10.123456),
        ("1970-01-01T00:00:10+00:00", 10.0),
    ],
)
def test_docker_time_parsing(text, expected):
    assert cleanup._parse_docker_time(text) == pytest.approx(expected)


@pytest.mark.parametrize("bad", [None, "", "yesterday", 5])
def test_docker_time_parsing_rejects_junk(bad):
    assert cleanup._parse_docker_time(bad) is None


# -- registry and exit hooks ---------------------------------------------------------------------


class FakeSandbox:
    def __init__(self, fail=False):
        self.closed = False
        self.fail = fail

    def close(self):
        self.closed = True
        if self.fail:
            raise RuntimeError("cannot close")


def test_registry_add_and_remove():
    sb = FakeSandbox()
    register_sandbox(sb)
    assert sb in live_sandboxes()
    unregister_sandbox(sb)
    assert sb not in live_sandboxes()
    unregister_sandbox(sb)  # removing twice is fine


def test_registry_holds_weak_references():
    import gc

    sb = FakeSandbox()
    register_sandbox(sb)
    del sb
    gc.collect()
    assert all(not isinstance(s, FakeSandbox) for s in live_sandboxes())


def test_close_all_closes_every_sandbox_even_if_one_fails():
    bad, good = FakeSandbox(fail=True), FakeSandbox()
    register_sandbox(bad)
    register_sandbox(good)
    try:
        close_all_sandboxes()
        assert bad.closed and good.closed
    finally:
        unregister_sandbox(bad)
        unregister_sandbox(good)


CHILD = """
import os, signal, sys
from bugbite.sandbox import cleanup

class Fake:
    def close(self):
        print("closed", flush=True)

fake = Fake()
cleanup.register_sandbox(fake)
mode = sys.argv[1]
if mode == "signal":
    cleanup.install_signal_cleanup()
    os.kill(os.getpid(), signal.SIGTERM)
    print("still running", flush=True)
elif mode == "sigint":
    cleanup.install_signal_cleanup()
    try:
        os.kill(os.getpid(), signal.SIGINT)
    except KeyboardInterrupt:
        print("keyboard interrupt", flush=True)
elif mode == "ignored":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    cleanup.install_signal_cleanup()
    os.kill(os.getpid(), signal.SIGTERM)
    print("survived ignored signal", flush=True)
"""


def run_child(mode):
    return subprocess.run([sys.executable, "-c", CHILD, mode], capture_output=True, text=True, timeout=60)


def test_atexit_closes_live_sandboxes_on_normal_exit():
    done = run_child("exit")
    assert done.returncode == 0
    assert done.stdout.split() == ["closed"]


def test_sigterm_closes_sandboxes_then_ends_the_process_by_the_signal():
    done = run_child("signal")
    assert done.returncode == -signal.SIGTERM
    assert "closed" in done.stdout and "still running" not in done.stdout


def test_sigint_closes_sandboxes_and_still_raises_keyboard_interrupt():
    done = run_child("sigint")
    assert "keyboard interrupt" in done.stdout
    assert "closed" in done.stdout


def test_ignored_signals_are_left_alone():
    done = run_child("ignored")
    assert done.returncode == 0
    assert "survived ignored signal" in done.stdout
    assert "closed" in done.stdout  # still closed, by atexit at normal exit


def test_handler_runs_cleanup_then_the_previous_handler_and_uninstall_restores_it():
    calls = []
    sb = FakeSandbox()
    register_sandbox(sb)
    original = signal.signal(signal.SIGUSR2, lambda signum, frame: calls.append("previous"))
    try:
        uninstall = install_signal_cleanup([signal.SIGUSR2])
        os.kill(os.getpid(), signal.SIGUSR2)
        assert sb.closed is True and calls == ["previous"]
        uninstall()
        sb.closed = False
        os.kill(os.getpid(), signal.SIGUSR2)
        assert sb.closed is False and calls == ["previous", "previous"]  # our handler is gone
    finally:
        unregister_sandbox(sb)
        signal.signal(signal.SIGUSR2, original)


def test_install_signal_cleanup_refuses_to_run_off_the_main_thread():
    errors = []

    def attempt():
        try:
            install_signal_cleanup([signal.SIGUSR2])
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=attempt)
    thread.start()
    thread.join()
    assert errors and "main thread" in errors[0]


def test_nothing_is_installed_on_import():
    out = subprocess.run(
        [sys.executable, "-c", "import signal, bugbite.sandbox; print(signal.getsignal(signal.SIGTERM) == signal.SIG_DFL, signal.getsignal(signal.SIGINT) == signal.default_int_handler)"],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert out.stdout.split() == ["True", "True"]

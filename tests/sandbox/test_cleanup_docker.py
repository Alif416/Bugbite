"""Cleanup against real Docker: processes are killed mid-job and the leftovers swept."""

import json
import logging
import signal
import socket
import subprocess
import sys
import time

import docker
import pytest
from docker.errors import NotFound

from bugbite.config import SandboxConfig
from bugbite.errors import SANDBOX_CLOSED, START_FAILED, SandboxError
from bugbite.sandbox import Owner, Sandbox, list_sandbox_containers, sweep_orphans
from bugbite.sandbox import container as container_module
from bugbite.sandbox.cleanup import LABEL

pytestmark = pytest.mark.docker

HOST = socket.gethostname()
FAST = SandboxConfig(max_lifetime_s=300)

CHILD_TEMPLATE = """
import json, os, signal, sys, time
from bugbite.sandbox import Sandbox, install_signal_cleanup
{prelude}
sb = Sandbox(job_id="cleanup-test").start()
info = sb.inspect()
print(json.dumps({{"name": sb.container_name, "volume": info["Mounts"][0]["Name"]}}), flush=True)
{action}
"""

ACTIONS = {
    "kill9": "os.kill(os.getpid(), signal.SIGKILL)",
    "exit": "sys.exit(0)",
    "wait": "time.sleep(300)",
    "stdin": "sys.stdin.readline()",
}


def start_child(action, prelude=""):
    script = CHILD_TEMPLATE.format(prelude=prelude, action=ACTIONS[action])
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    line = proc.stdout.readline()
    if not line:
        proc.wait(timeout=30)
        pytest.fail(f"child did not start a sandbox: {proc.stderr.read()}")
    return proc, json.loads(line)


@pytest.fixture
def client():
    c = docker.from_env()
    yield c
    c.close()


@pytest.fixture
def children():
    procs = []
    yield procs
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=30)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream:
                stream.close()


def container_exists(client, name):
    try:
        client.containers.get(name)
        return True
    except NotFound:
        return False


def volume_exists(client, name):
    try:
        client.volumes.get(name)
        return True
    except NotFound:
        return False


def wait_until(predicate, timeout=40, step=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


@pytest.fixture(autouse=True)
def _tidy(client):
    """Whatever happens, leave no labelled objects behind."""
    yield
    for c in client.containers.list(all=True, filters={"label": f"{LABEL}=1"}):
        c.remove(force=True, v=True)
    for v in client.volumes.list(filters={"label": f"{LABEL}=1"}):
        try:
            v.remove(force=True)
        except Exception:
            pass


# -- crashed and killed owners ---------------------------------------------------------------


def test_killed_owner_leaves_a_container_that_the_sweeper_removes(client, children):
    proc, info = start_child("kill9")
    children.append(proc)
    proc.wait(timeout=30)
    assert proc.returncode == -signal.SIGKILL
    # The crash really did leave the sandbox behind (this is the problem being solved).
    assert container_exists(client, info["name"]) and volume_exists(client, info["volume"])

    report = sweep_orphans(client)

    assert info["name"] in report.containers_removed
    assert not container_exists(client, info["name"])
    assert not volume_exists(client, info["volume"])
    assert report.errors == ()


def test_normal_exit_without_closing_cleans_up_through_atexit(client, children):
    proc, info = start_child("exit")
    children.append(proc)
    assert proc.wait(timeout=60) == 0
    assert not container_exists(client, info["name"])
    assert not volume_exists(client, info["volume"])


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_signal_cleanup_removes_the_sandbox_when_the_process_is_signalled(client, children, sig):
    proc, info = start_child("wait", prelude="install_signal_cleanup()")
    children.append(proc)
    assert container_exists(client, info["name"])
    proc.send_signal(sig)
    proc.wait(timeout=60)
    if sig == signal.SIGTERM:
        assert proc.returncode == -signal.SIGTERM
    else:
        assert "KeyboardInterrupt" in proc.stderr.read() or proc.returncode in (-signal.SIGINT, 1, 130)
    assert not container_exists(client, info["name"])
    assert not volume_exists(client, info["volume"])


def test_without_signal_cleanup_a_sigterm_leaves_the_sandbox_for_the_sweeper(client, children):
    # Shows why entry points should call install_signal_cleanup(): the default SIGTERM does not run atexit.
    proc, info = start_child("wait")
    children.append(proc)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=60)
    assert container_exists(client, info["name"])
    assert info["name"] in sweep_orphans(client).containers_removed
    assert not container_exists(client, info["name"])


# -- expiry by Docker itself ---------------------------------------------------------------------


def test_expired_sandbox_disappears_by_itself_and_reports_it(client):
    sb = Sandbox(SandboxConfig(max_lifetime_s=5), job_id="expiry").start()
    name, volume = sb.container_name, sb.inspect()["Mounts"][0]["Name"]
    assert sb.run("echo alive").stdout == "alive\n"
    assert wait_until(lambda: not container_exists(client, name)), "Docker did not remove the expired sandbox"
    assert wait_until(lambda: not volume_exists(client, volume)), "the workspace volume was left behind"
    with pytest.raises(SandboxError) as info:
        sb.run("echo again")
    assert info.value.code == SANDBOX_CLOSED
    assert "maximum lifetime" in info.value.message
    sb.close()
    sb.close()  # safe even though Docker already removed it


def test_other_calls_on_an_expired_sandbox_also_say_so(client):
    sb = Sandbox(SandboxConfig(max_lifetime_s=5)).start()
    name = sb.container_name
    assert wait_until(lambda: not container_exists(client, name))
    with pytest.raises(SandboxError) as info:
        sb.write_file("/workspace/x.txt", "x")
    assert info.value.code == SANDBOX_CLOSED


# -- live owners are never touched --------------------------------------------------------------------


def test_sweeper_never_removes_a_sandbox_owned_by_this_live_process(client):
    with Sandbox(FAST) as sb:
        report = sweep_orphans(client, grace_s=0)
        assert sb.container_name not in report.containers_removed
        assert container_exists(client, sb.container_name)
        assert sb.run("echo fine").stdout == "fine\n"
        assert any(name == sb.container_name for name, _ in report.kept)


def test_sweeper_never_removes_a_sandbox_owned_by_another_live_process(client, children):
    proc, info = start_child("stdin")
    children.append(proc)
    report = sweep_orphans(client, grace_s=0)
    assert info["name"] not in report.containers_removed
    assert container_exists(client, info["name"]) and volume_exists(client, info["volume"])
    proc.stdin.write("done\n")
    proc.stdin.flush()
    assert proc.wait(timeout=60) == 0
    assert not container_exists(client, info["name"])  # closed by the child's own atexit


# -- the sweeper runs when a sandbox starts --------------------------------------------------------------


def dead_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_starting_a_sandbox_removes_orphans_of_dead_owners(client):
    ghost = Sandbox(FAST, owner=Owner(HOST, dead_pid(), "")).start()
    ghost_name = ghost.container_name
    assert container_exists(client, ghost_name)
    with Sandbox(FAST) as fresh:
        assert wait_until(lambda: not container_exists(client, ghost_name), timeout=10)
        assert container_exists(client, fresh.container_name)


def test_a_failing_sweeper_never_blocks_a_start(monkeypatch, caplog):
    def boom(client):
        raise RuntimeError("sweeper exploded")

    monkeypatch.setattr(container_module, "sweep_orphans", boom)
    with caplog.at_level(logging.WARNING, logger="bugbite.sandbox.container"):
        with Sandbox(FAST) as sb:
            assert sb.run("echo started").stdout == "started\n"
    assert any("orphan sweep failed" in r.getMessage() and "sweeper exploded" in r.getMessage() for r in caplog.records)


def test_owner_on_another_host_is_kept_when_young_and_removed_when_old(client):
    foreign = Sandbox(FAST, owner=Owner("a-different-machine", 1, "")).start()
    name = foreign.container_name

    young = sweep_orphans(client)
    assert name not in young.containers_removed and container_exists(client, name)

    old = sweep_orphans(client, now=time.time() + 3600)  # one hour later: past lifetime + grace
    assert name in old.containers_removed
    assert not container_exists(client, name)


# -- volumes ------------------------------------------------------------------------------------------------


def test_old_unreferenced_labelled_volume_is_removed(client):
    stray = client.volumes.create(labels={LABEL: "1"})
    report = sweep_orphans(client, now=time.time() + 120)
    assert stray.name in report.volumes_removed
    assert not volume_exists(client, stray.name)


def test_young_labelled_volume_is_kept(client):
    stray = client.volumes.create(labels={LABEL: "1"})
    report = sweep_orphans(client)
    assert volume_exists(client, stray.name)
    assert (stray.name, "volume is younger than the grace period") in report.kept


def test_volume_in_use_by_a_running_sandbox_is_kept(client):
    with Sandbox(FAST) as sb:
        volume = sb.inspect()["Mounts"][0]["Name"]
        report = sweep_orphans(client, now=time.time() + 120)
        assert volume_exists(client, volume)
        assert (volume, "volume is still in use") in report.kept
        assert sb.run("echo ok").stdout == "ok\n"


def test_unlabelled_volumes_are_never_touched(client):
    other = client.volumes.create()  # not ours: no Bugbite label
    try:
        sweep_orphans(client, now=time.time() + 10_000)
        assert volume_exists(client, other.name)
    finally:
        other.remove(force=True)


def test_unlabelled_containers_are_never_touched(client):
    other = client.containers.run("hello-world:latest", detach=True)
    try:
        sweep_orphans(client, now=time.time() + 10_000)
        assert container_exists(client, other.name)
    finally:
        other.remove(force=True)


# -- start failures and lifecycle -----------------------------------------------------------------------------


def test_immediate_exit_image_still_gives_start_failed_and_leaves_nothing(client):
    with pytest.raises(SandboxError) as info:
        Sandbox(SandboxConfig(image="hello-world:latest")).start()
    assert info.value.code == START_FAILED
    assert "exited right after starting" in info.value.message
    assert wait_until(lambda: list_sandbox_containers(client) == [], timeout=10)


def test_containers_are_created_with_auto_remove_and_full_labels(client):
    with Sandbox(FAST, job_id="labels") as sb:
        info = sb.inspect()
        assert info["HostConfig"]["AutoRemove"] is True
        labels = info["Config"]["Labels"]
        assert labels[LABEL] == "1" and labels["bugbite.job"] == "labels"
        assert labels["bugbite.owner_host"] == HOST
        assert int(labels["bugbite.max_lifetime"]) == 300
        volume = client.volumes.get(info["Mounts"][0]["Name"])
        assert volume.attrs["Labels"][LABEL] == "1"


def test_close_removes_container_and_volume_immediately(client):
    sb = Sandbox(FAST).start()
    name, volume = sb.container_name, sb.inspect()["Mounts"][0]["Name"]
    sb.close()
    assert not container_exists(client, name) and not volume_exists(client, volume)


def test_nothing_labelled_is_left_at_the_end(client):
    assert list_sandbox_containers(client) == []
    assert client.volumes.list(filters={"label": f"{LABEL}=1"}) == []

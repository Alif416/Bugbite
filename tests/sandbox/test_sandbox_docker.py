"""Sandbox tests against a real Docker daemon. Skipped when Docker is unreachable."""

import pytest

from bugbite.config import SandboxConfig
from bugbite.errors import (
    BACKSTOP_TIMEOUT,
    DOCKER_UNAVAILABLE,
    IMAGE_UNAVAILABLE,
    SANDBOX_CLOSED,
    START_FAILED,
    SandboxError,
)
from bugbite.sandbox import Sandbox, container as container_module, list_sandbox_containers

SMALL = SandboxConfig(memory_mb=256, pids_limit=32, workspace_mb=64, max_output_bytes=1000, max_lifetime_s=300)

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def shared():
    with Sandbox(job_id="tests-shared") as sb:
        yield sb


@pytest.fixture
def make_sandbox():
    made = []

    def factory(config=SMALL, **kwargs):
        sb = Sandbox(config, job_id="tests", **kwargs)
        made.append(sb)
        return sb.start()

    yield factory
    for sb in made:
        sb.close()


def _interfaces(sb):
    """Interfaces seen by the container. /proc/net/dev follows the container's own network
    namespace (unlike /sys/class/net). Inert placeholder tunnels like gre0 always appear;
    only eth0 means a real network."""
    out = sb.run("sed -n '3,$p' /proc/net/dev | cut -d: -f1").stdout  # names only: short output
    return sorted(name.strip() for name in out.splitlines())


def _routes(sb):
    lines = sb.run("cat /proc/net/route").stdout.splitlines()[1:]
    return [line for line in lines if line.strip()]


# -- running commands ---------------------------------------------------


def test_echo(shared):
    r = shared.run("echo hello")
    assert (r.exit_code, r.stdout, r.stderr) == (0, "hello\n", "")
    assert r.timed_out is False and r.truncated is False
    assert r.duration_s >= 0


def test_failure_and_stderr(shared):
    r = shared.run("echo oops >&2; exit 3")
    assert r.exit_code == 3
    assert r.stderr == "oops\n"
    assert r.stdout == ""


def test_command_not_found_is_a_result_not_an_exception(shared):
    r = shared.run("definitely_not_a_command")
    assert r.exit_code == 127
    assert "not found" in r.stderr
    r = shared.run(["definitely_not_a_command"])
    assert r.exit_code == 127


def test_list_form_runs_without_a_shell(shared):
    r = shared.run(["echo", "$HOME;", "&&", "id"])
    assert r.stdout == "$HOME; && id\n"


def test_working_directory_and_persistence(make_sandbox):
    sb = make_sandbox()
    assert sb.run("pwd").stdout == "/workspace\n"
    assert sb.run("echo data > note.txt").exit_code == 0
    assert sb.run("cat /workspace/note.txt").stdout == "data\n"


def test_workspace_allows_executing_files(make_sandbox):
    sb = make_sandbox()
    r = sb.run("printf '#!/bin/sh\\necho ran\\n' > run.sh && chmod +x run.sh && ./run.sh")
    assert (r.exit_code, r.stdout) == (0, "ran\n")


def test_invalid_utf8_is_replaced(shared):
    r = shared.run("printf '\\377\\376ok'")
    assert r.exit_code == 0 and r.stdout.endswith("ok")


def test_bad_arguments(shared):
    with pytest.raises(ValueError):
        shared.run("echo hi", timeout=0)
    with pytest.raises(ValueError):
        shared.run([])


# -- timeouts and output caps -------------------------------------------


def test_timeout_then_sandbox_still_works(make_sandbox):
    sb = make_sandbox()
    r = sb.run("sleep 30", timeout=2)
    assert r.timed_out is True
    assert r.exit_code in (124, 137)
    assert r.duration_s < 10
    assert sb.run("echo alive").stdout == "alive\n"


def test_timeout_kills_child_processes(make_sandbox):
    sb = make_sandbox()
    assert sb.run("sleep 777 & sleep 777", timeout=2).timed_out is True
    scan = (
        "import glob\n"
        "hits = [p for p in glob.glob('/proc/[0-9]*/cmdline') "
        "if open(p, 'rb').read().split(b'\\0')[:2] == [b'sleep', b'777']]\n"
        "print(len(hits))\n"
    )
    assert sb.run(["python", "-c", scan]).stdout.strip() == "0"


def test_command_timeout_default_comes_from_config(make_sandbox):
    sb = make_sandbox(SandboxConfig(command_timeout_s=2, max_lifetime_s=300))
    assert sb.run("sleep 30").timed_out is True


def test_output_over_cap_is_truncated(make_sandbox):
    sb = make_sandbox()
    r = sb.run("python -c \"print('x' * 5000)\"")
    assert r.exit_code == 0
    assert len(r.stdout) == 1000
    assert r.truncated is True


def test_stderr_over_cap_is_truncated(make_sandbox):
    sb = make_sandbox()
    r = sb.run("python -c \"import sys; sys.stderr.write('e' * 5000)\"")
    assert len(r.stderr) == 1000 and r.truncated is True


def test_output_at_cap_is_not_truncated(make_sandbox):
    sb = make_sandbox()
    r = sb.run("python -c \"import sys; sys.stdout.write('y' * 1000)\"")
    assert len(r.stdout) == 1000
    assert r.truncated is False


def test_endless_output_is_bounded_by_timeout_and_cap(make_sandbox):
    sb = make_sandbox()
    r = sb.run("yes", timeout=2)
    assert r.timed_out is True
    assert len(r.stdout) == 1000 and r.truncated is True


def test_backstop_kills_sandbox_when_command_will_not_return(make_sandbox, monkeypatch):
    # Simulate a stuck exec by removing the grace period so the backstop fires first.
    sb = make_sandbox()
    monkeypatch.setattr(container_module, "BACKSTOP_GRACE_S", -100)
    name = sb.container_name
    with pytest.raises(SandboxError) as info:
        sb.run("sleep 30", timeout=3)
    assert info.value.code == BACKSTOP_TIMEOUT
    assert name not in list_sandbox_containers()
    with pytest.raises(SandboxError) as info:
        sb.run("echo again")
    assert info.value.code == SANDBOX_CLOSED


# -- isolation ----------------------------------------------------------


def test_runs_as_unprivileged_user(shared):
    assert shared.run("id -u").stdout.strip() == "1000"
    assert shared.run("id -g").stdout.strip() == "1000"


def test_no_new_privileges_and_no_capabilities(shared):
    status = shared.run("cat /proc/self/status").stdout
    assert "NoNewPrivs:\t1" in status
    assert "CapEff:\t0000000000000000" in status
    assert "CapBnd:\t0000000000000000" in status


def test_host_environment_is_not_visible(monkeypatch, make_sandbox):
    monkeypatch.setenv("BUGBITE_TEST_HOST_SECRET", "topsecret-value")
    monkeypatch.setenv("GITHUB_TOKEN", "topsecret-token")
    sb = make_sandbox()
    env = sb.run("env").stdout
    assert "topsecret" not in env
    assert "BUGBITE_TEST_HOST_SECRET" not in env
    assert "GITHUB_TOKEN" not in env


def test_no_docker_socket_and_no_host_mounts(make_sandbox):
    sb = make_sandbox()
    assert sb.run("test -e /var/run/docker.sock").exit_code != 0
    info = sb.inspect()
    assert [m for m in info["Mounts"] if m["Type"] != "tmpfs"] == []
    assert info["HostConfig"]["Binds"] in (None, [])
    assert "/workspace" in info["HostConfig"]["Tmpfs"]


def test_no_network_by_default(make_sandbox):
    sb = make_sandbox()
    assert sb.inspect()["HostConfig"]["NetworkMode"] == "none"
    assert "eth0" not in _interfaces(sb)
    assert _routes(sb) == []
    probe = "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)"
    assert sb.run(["python", "-c", probe]).exit_code != 0


def test_network_can_be_enabled_per_container(make_sandbox):
    sb = make_sandbox(network=True)
    assert sb.inspect()["HostConfig"]["NetworkMode"] == "bridge"
    assert "eth0" in _interfaces(sb)
    assert _routes(sb) != []


# -- resource limits ----------------------------------------------------


def test_limits_are_applied_to_the_container(make_sandbox):
    cfg = SandboxConfig(cpus=0.5, memory_mb=256, pids_limit=32, workspace_mb=64, max_lifetime_s=300)
    info = make_sandbox(cfg).inspect()
    host = info["HostConfig"]
    assert host["NanoCpus"] == 500_000_000
    assert host["Memory"] == 256 * 1024 * 1024
    assert host["MemorySwap"] == host["Memory"]
    assert host["PidsLimit"] == 32
    assert host["CapDrop"] == ["ALL"]
    assert any("no-new-privileges" in opt for opt in host["SecurityOpt"])
    assert info["Config"]["User"] == "1000:1000"
    assert info["Config"]["Labels"]["bugbite.sandbox"] == "1"
    assert info["Config"]["Labels"]["bugbite.job"] == "tests"
    assert info["Config"]["Cmd"] == ["sleep", "300"]


def test_memory_hog_is_killed(make_sandbox):
    sb = make_sandbox()
    r = sb.run(["python", "-c", "b = b'x' * (900 * 1024 * 1024); print('survived')"])
    assert r.exit_code != 0
    assert "survived" not in r.stdout
    assert sb.run("echo still-here").stdout == "still-here\n"


def test_fork_loop_is_stopped_by_pids_limit(make_sandbox):
    sb = make_sandbox()
    script = (
        "import os, time\n"
        "n = 0\n"
        "for _ in range(500):\n"
        "    try:\n"
        "        pid = os.fork()\n"
        "    except OSError:\n"
        "        break\n"
        "    if pid == 0:\n"
        "        time.sleep(3)\n"
        "        os._exit(0)\n"
        "    n += 1\n"
        "print(n)\n"
    )
    r = sb.run(["python", "-c", script], timeout=20)
    assert r.exit_code == 0
    assert 0 < int(r.stdout.strip()) < 32


def test_workspace_size_is_limited(make_sandbox):
    sb = make_sandbox()
    r = sb.run("dd if=/dev/zero of=big bs=1M count=200")
    assert r.exit_code != 0
    assert "No space left" in r.stderr


# -- cleanup and lifecycle ----------------------------------------------


def test_close_removes_container_and_is_idempotent():
    sb = Sandbox(SMALL, job_id="tests").start()
    name = sb.container_name
    assert name in list_sandbox_containers()
    sb.close()
    sb.close()
    assert name not in list_sandbox_containers()


def test_exception_inside_with_still_cleans_up():
    names = []
    with pytest.raises(RuntimeError):
        with Sandbox(SMALL, job_id="tests") as sb:
            names.append(sb.container_name)
            raise RuntimeError("job crashed")
    assert names[0] not in list_sandbox_containers()


def test_run_before_start_and_after_close_raise():
    sb = Sandbox(SMALL)
    with pytest.raises(SandboxError) as info:
        sb.run("echo no")
    assert info.value.code == SANDBOX_CLOSED
    sb.start()
    sb.close()
    with pytest.raises(SandboxError) as info:
        sb.run("echo no")
    assert info.value.code == SANDBOX_CLOSED


def test_cannot_restart_a_closed_sandbox():
    sb = Sandbox(SMALL).start()
    sb.close()
    with pytest.raises(SandboxError) as info:
        sb.start()
    assert info.value.code == SANDBOX_CLOSED


def test_unavailable_image_raises_and_leaves_nothing():
    before = list_sandbox_containers()
    with pytest.raises(SandboxError) as info:
        Sandbox(SandboxConfig(image="bugbite-test.invalid/nope/missing:0")).start()
    assert info.value.code == IMAGE_UNAVAILABLE
    assert list_sandbox_containers() == before


def test_rejected_settings_raise_start_failed_and_leave_nothing():
    before = list_sandbox_containers()
    with pytest.raises(SandboxError) as info:
        Sandbox(SandboxConfig(cpus=1000)).start()
    assert info.value.code == START_FAILED
    assert list_sandbox_containers() == before


def test_failed_start_after_create_removes_the_container():
    # hello-world has no `sleep`, so the container is created but cannot start.
    before = list_sandbox_containers()
    with pytest.raises(SandboxError) as info:
        Sandbox(SandboxConfig(image="hello-world:latest")).start()
    assert info.value.code == START_FAILED
    assert list_sandbox_containers() == before


def test_no_labelled_containers_are_left_by_this_module(shared):
    # The shared sandbox is the only one allowed to exist while the module runs.
    assert list_sandbox_containers() == [shared.container_name]

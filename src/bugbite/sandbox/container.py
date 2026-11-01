"""Docker sandbox: a locked-down container where untrusted code runs.

One container per job; commands run inside it with `exec`. Defaults: no
network, non-root, no capabilities, no host mounts, no host environment,
memory/CPU/process limits, and a disk-backed /workspace volume with a soft
size cap (see `check_workspace`).
"""

from __future__ import annotations

import io
import logging
import re
import tarfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import docker
from docker.errors import NotFound
from docker.types import Mount

from bugbite.config import SandboxConfig
from bugbite.errors import (
    BACKSTOP_TIMEOUT,
    DOCKER_UNAVAILABLE,
    EXEC_FAILED,
    SANDBOX_CLOSED,
    START_FAILED,
    WORKSPACE_FULL,
    SandboxError,
)
from bugbite.sandbox.cleanup import (
    LABEL,
    Owner,
    brief as _brief,
    current_owner,
    make_labels,
    register_sandbox,
    sweep_orphans,
    unregister_sandbox,
)
from bugbite.sandbox.image import ensure_image

log = logging.getLogger(__name__)

WORKDIR = "/workspace"
USER = "1000:1000"
BACKSTOP_GRACE_S = 15
_KILL_AFTER_S = 2
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MAX_READ_BYTES = 64 * 1024 * 1024


def _is_container_gone(exc: BaseException) -> bool:
    """Docker says "No such container" when a sandbox expired or was removed."""
    return isinstance(exc, NotFound) and "no such container" in str(exc).lower()


_GONE_MESSAGE = "The sandbox no longer exists: it reached its maximum lifetime or was removed."


def _check_workspace_path(path: str) -> str:
    if not isinstance(path, str) or not path.startswith(WORKDIR + "/") or ".." in path.split("/"):
        raise ValueError(f"path must be absolute and under {WORKDIR}: {path!r}")
    if "\x00" in path or "\n" in path:
        raise ValueError("path contains illegal characters")
    return path


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float
    truncated: bool


def _connect(timeout: float) -> docker.DockerClient:
    try:
        client = docker.from_env(timeout=timeout)
        client.ping()
    except Exception:  # SDK, requests, and OS errors all mean "cannot reach Docker"
        raise SandboxError(
            DOCKER_UNAVAILABLE,
            "Cannot reach Docker. Start Docker Desktop (or the Docker daemon) and try again.",
        ) from None
    return client


def list_sandbox_containers(client: docker.DockerClient | None = None) -> list[str]:
    """Names of all Bugbite sandbox containers (running or not)."""
    own = client is None
    client = client or _connect(30)
    try:
        return sorted(c.name for c in client.containers.list(all=True, filters={"label": f"{LABEL}=1"}))
    finally:
        if own:
            client.close()


class _Capture:
    """Accumulates a byte stream up to a cap, then discards the rest."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.data = bytearray()
        self.truncated = False

    def add(self, chunk: bytes) -> None:
        room = self.cap - len(self.data)
        if room > 0:
            self.data += chunk[:room]
        if len(chunk) > room:
            self.truncated = True

    def text(self) -> str:
        return bytes(self.data).decode("utf-8", errors="replace")


class Sandbox:
    def __init__(
        self,
        config: SandboxConfig | None = None,
        *,
        network: bool = False,
        job_id: str | None = None,
        owner: Owner | None = None,
    ) -> None:
        self.config = config or SandboxConfig()
        self.network = network
        self.job_id = job_id or ""
        self.owner = owner or current_owner()  # tests may pass another owner to simulate a crashed process
        self._client: docker.DockerClient | None = None
        self._container: Any = None
        self._closed = False

    # -- lifecycle -------------------------------------------------------

    @property
    def container_name(self) -> str | None:
        return self._container.name if self._container is not None else None

    def start(self) -> "Sandbox":
        if self._closed or self._container is not None:
            raise SandboxError(SANDBOX_CLOSED, "This sandbox was already started; create a new one.")
        cfg = self.config
        client = _connect(timeout=cfg.max_lifetime_s + 60)
        self._client = client
        try:
            self._sweep_first(client)
            ensure_image(client, cfg.image)
            mem = f"{cfg.memory_mb}m"
            labels = make_labels(self.job_id, self.owner, time.time(), cfg.max_lifetime_s)
            container = client.containers.create(
                cfg.image,
                command=["sleep", str(cfg.max_lifetime_s)],
                labels=labels,
                auto_remove=True,  # Docker deletes the container and its volume when it exits
                network_mode="bridge" if self.network else "none",
                nano_cpus=int(cfg.cpus * 1_000_000_000),
                mem_limit=mem,
                memswap_limit=mem,
                pids_limit=cfg.pids_limit,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                user=USER,
                working_dir=WORKDIR,
                mounts=[Mount(target=WORKDIR, source=None, type="volume", labels=labels)],  # anonymous, labelled
                init=True,
                environment={},
            )
        except SandboxError:
            self._release_client()
            raise
        except Exception as exc:
            self._release_client()
            raise SandboxError(START_FAILED, f"Could not create the sandbox container: {_brief(exc)}") from None
        self._container = container
        register_sandbox(self)
        try:
            container.start()
        except Exception as exc:
            self.close()
            raise SandboxError(START_FAILED, f"Could not start the sandbox container: {_brief(exc)}") from None
        try:
            self._check_ready()
        except BaseException:
            self.close()
            raise
        return self

    @staticmethod
    def _sweep_first(client: docker.DockerClient) -> None:
        """Remove orphans from crashed jobs before starting. Never blocks the start."""
        try:
            report = sweep_orphans(client)
        except Exception as exc:
            log.warning("orphan sweep failed (continuing): %s", _brief(exc))
            return
        if report.containers_removed or report.volumes_removed:
            log.info(
                "removed %d orphaned sandbox container(s) and %d volume(s)",
                len(report.containers_removed),
                len(report.volumes_removed),
            )
        for error in report.errors:
            log.warning("orphan sweep problem: %s", error)

    def _check_ready(self) -> None:
        """Confirm the container stayed up and `sh` and `timeout` work inside it.

        A container whose keep-alive command cannot run still "starts" and then
        exits at once; catch that here instead of failing on the first command.
        """
        container = self._container
        time.sleep(0.1)  # let a doomed container exit before we look
        gone = False
        try:
            container.reload()
            running = container.status == "running"
        except NotFound:
            running, gone = False, True  # Docker already removed it (auto_remove)
        except Exception as exc:
            raise SandboxError(START_FAILED, f"Could not check the sandbox container: {_brief(exc)}") from None
        if not running:
            detail = " Docker removed it at once, so its output is not available." if gone else ""
            if not gone:
                try:
                    tail = container.logs(tail=5).decode("utf-8", errors="replace")
                except Exception:
                    tail = ""
                detail = f" Output: {' '.join(tail.split())[:200]}" if tail.strip() else ""
            raise SandboxError(
                START_FAILED,
                f"The sandbox container exited right after starting; the image {self.config.image} "
                f"may be missing required tools (sleep, sh, timeout).{detail}",
            )
        try:
            probe = self.run("true", timeout=10)
        except SandboxError as exc:
            raise SandboxError(START_FAILED, f"The sandbox container is not usable: {exc.message}") from None
        if probe.exit_code != 0:
            raise SandboxError(
                START_FAILED,
                f"The image {self.config.image} cannot run commands (sh or timeout is missing or broken).",
            )

    def _release_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def close(self) -> None:
        """Remove the container. Safe to call more than once."""
        container, self._container = self._container, None
        self._closed = True
        unregister_sandbox(self)
        if container is not None:
            try:
                container.remove(force=True, v=True)
            except NotFound:
                pass
            except Exception as exc:
                log.warning("could not remove sandbox container %s: %s", container.name, _brief(exc))
        self._release_client()

    def write_file(self, path: str, content: str | bytes) -> None:
        """Write a file (owned by the sandbox user) under /workspace. The directory must exist."""
        _check_workspace_path(path)
        if self._container is None:
            raise SandboxError(SANDBOX_CLOSED, "The sandbox is not running.")
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        directory, _, name = path.rpartition("/")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o644
            info.uid = info.gid = 1000
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
        try:
            ok = self._container.put_archive(directory, buffer.getvalue())
        except Exception as exc:
            if _is_container_gone(exc):
                self.close()
                raise SandboxError(SANDBOX_CLOSED, _GONE_MESSAGE) from None
            raise SandboxError(EXEC_FAILED, f"Could not write {path}: {_brief(exc)}") from None
        if not ok:
            raise SandboxError(EXEC_FAILED, f"Could not write {path}.")

    def read_file(self, path: str, max_bytes: int = MAX_READ_BYTES) -> bytes | None:
        """Read a file under /workspace. Returns None if it does not exist."""
        _check_workspace_path(path)
        if self._container is None:
            raise SandboxError(SANDBOX_CLOSED, "The sandbox is not running.")
        try:
            stream, stat = self._container.get_archive(path)
        except NotFound as exc:
            if _is_container_gone(exc):
                self.close()
                raise SandboxError(SANDBOX_CLOSED, _GONE_MESSAGE) from None
            return None
        except Exception as exc:
            raise SandboxError(EXEC_FAILED, f"Could not read {path}: {_brief(exc)}") from None
        if int(stat.get("size", 0)) > max_bytes:
            raise SandboxError(EXEC_FAILED, f"{path} is larger than {max_bytes} bytes.")
        try:
            with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
                member = tar.next()
                handle = tar.extractfile(member) if member is not None else None
                return handle.read() if handle is not None else None
        except (tarfile.TarError, OSError) as exc:
            raise SandboxError(EXEC_FAILED, f"Could not read {path}: {_brief(exc)}") from None

    def inspect(self) -> dict[str, Any]:
        """Docker's description of the running container (for tests and diagnostics)."""
        if self._container is None or self._client is None:
            raise SandboxError(SANDBOX_CLOSED, "The sandbox is not running.")
        try:
            return self._client.api.inspect_container(self._container.id)
        except NotFound:
            self.close()
            raise SandboxError(SANDBOX_CLOSED, _GONE_MESSAGE) from None

    @property
    def has_network(self) -> bool:
        """True if Docker reports the container attached to any real network."""
        networks = self.inspect()["NetworkSettings"]["Networks"] or {}
        return any(name != "none" for name in networks)

    def disconnect_network(self) -> None:
        """Detach the container from every network. Safe to call more than once."""
        info = self.inspect()
        networks = info["NetworkSettings"]["Networks"] or {}
        assert self._client is not None and self._container is not None
        for name in list(networks):
            if name == "none":
                continue
            try:
                self._client.api.disconnect_container_from_network(self._container.id, name, force=True)
            except Exception as exc:
                raise SandboxError(EXEC_FAILED, f"Could not disconnect the sandbox from network {name}: {_brief(exc)}") from None
        if self.has_network:
            raise SandboxError(EXEC_FAILED, "The sandbox is still attached to a network after disconnecting.")

    def workspace_usage_mb(self) -> int:
        """Disk used under /workspace, in MB (rounded up)."""
        result = self.run(["du", "-sm", WORKDIR], timeout=120)
        try:
            return int(result.stdout.split()[0])
        except (IndexError, ValueError):
            raise SandboxError(EXEC_FAILED, "Could not measure the workspace size.") from None

    def check_workspace(self) -> int:
        """Return usage in MB, or raise `workspace_full` if it exceeds `workspace_mb`.

        Docker Desktop cannot enforce a hard disk quota on a volume, so this is a
        soft cap that callers check after steps that write a lot.
        """
        used = self.workspace_usage_mb()
        if used > self.config.workspace_mb:
            raise SandboxError(
                WORKSPACE_FULL,
                f"The workspace uses {used} MB, over the {self.config.workspace_mb} MB limit.",
            )
        return used

    def __enter__(self) -> "Sandbox":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- running commands ------------------------------------------------

    def run(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None = None,
        workdir: str = WORKDIR,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run a command in the container.

        A string runs through `sh -c`; a list runs directly with no shell.
        `workdir` is the directory inside the container to run in. `env` adds
        environment variables for this command only; names and values must come
        from Bugbite code, never from the repo, the issue, or the model.
        """
        if self._container is None or self._client is None:
            raise SandboxError(SANDBOX_CLOSED, "The sandbox is not running (start it, or use it in a 'with' block).")
        limit = float(self.config.command_timeout_s if timeout is None else timeout)
        if limit <= 0:
            raise ValueError("timeout must be greater than zero")
        argv = ["sh", "-c", command] if isinstance(command, str) else list(command)
        if not argv:
            raise ValueError("command must not be empty")
        wrapped = ["timeout", f"--kill-after={_KILL_AFTER_S}", f"{limit:g}", *argv]
        environment = None
        if env:
            for name in env:
                if not _ENV_NAME.fullmatch(name):
                    raise ValueError(f"invalid environment variable name: {name!r}")
            environment = [f"{name}={value}" for name, value in env.items()]

        api = self._client.api
        try:
            exec_id = api.exec_create(
                self._container.id, wrapped, stdout=True, stderr=True, workdir=workdir, user=USER,
                environment=environment,
            )["Id"]
            stream = api.exec_start(exec_id, stream=True, demux=True)
        except Exception as exc:
            if _is_container_gone(exc):
                self.close()
                raise SandboxError(SANDBOX_CLOSED, _GONE_MESSAGE) from None
            raise SandboxError(EXEC_FAILED, f"Could not run the command in the sandbox: {_brief(exc)}") from None

        out = _Capture(self.config.max_output_bytes)
        err = _Capture(self.config.max_output_bytes)
        failure: list[BaseException] = []

        def drain() -> None:
            try:
                for out_chunk, err_chunk in stream:
                    if out_chunk:
                        out.add(out_chunk)
                    if err_chunk:
                        err.add(err_chunk)
            except BaseException as exc:  # reported to the caller thread below
                failure.append(exc)

        started = time.monotonic()
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        reader.join(limit + _KILL_AFTER_S + BACKSTOP_GRACE_S)
        duration = time.monotonic() - started

        if reader.is_alive():
            self.close()  # kills the container; the stream ends and the reader exits
            raise SandboxError(
                BACKSTOP_TIMEOUT,
                f"The command did not stop within {limit:g}s plus a grace period; the sandbox was killed.",
            )
        if failure:
            raise SandboxError(EXEC_FAILED, f"Lost the connection to the command: {_brief(failure[0])}") from None
        try:
            exit_code = api.exec_inspect(exec_id).get("ExitCode")
        except Exception as exc:
            raise SandboxError(EXEC_FAILED, f"Could not read the command's exit code: {_brief(exc)}") from None
        if exit_code is None:
            raise SandboxError(EXEC_FAILED, "Docker did not report an exit code for the command.")

        timed_out = exit_code == 124 or (exit_code == 137 and duration >= limit)
        return CommandResult(
            exit_code=exit_code,
            stdout=out.text(),
            stderr=err.text(),
            timed_out=timed_out,
            duration_s=duration,
            truncated=out.truncated or err.truncated,
        )

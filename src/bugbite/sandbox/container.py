"""Docker sandbox: a locked-down container where untrusted code runs.

One container per job; commands run inside it with `exec`. Defaults: no
network, non-root, no capabilities, no host mounts, no host environment,
memory/CPU/process limits, and a size-limited memory-backed /workspace.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Sequence

import docker
from docker.errors import APIError, ImageNotFound, NotFound

from bugbite.config import SandboxConfig
from bugbite.errors import (
    BACKSTOP_TIMEOUT,
    DOCKER_UNAVAILABLE,
    EXEC_FAILED,
    IMAGE_UNAVAILABLE,
    SANDBOX_CLOSED,
    START_FAILED,
    SandboxError,
)

log = logging.getLogger(__name__)

LABEL = "bugbite.sandbox"
JOB_LABEL = "bugbite.job"
WORKDIR = "/workspace"
USER = "1000:1000"
BACKSTOP_GRACE_S = 15
_KILL_AFTER_S = 2


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
    ) -> None:
        self.config = config or SandboxConfig()
        self.network = network
        self.job_id = job_id or ""
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
            self._ensure_image(client)
            mem = f"{cfg.memory_mb}m"
            container = client.containers.create(
                cfg.image,
                command=["sleep", str(cfg.max_lifetime_s)],
                labels={LABEL: "1", JOB_LABEL: self.job_id},
                network_mode="bridge" if self.network else "none",
                nano_cpus=int(cfg.cpus * 1_000_000_000),
                mem_limit=mem,
                memswap_limit=mem,
                pids_limit=cfg.pids_limit,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                user=USER,
                working_dir=WORKDIR,
                tmpfs={WORKDIR: f"rw,exec,nosuid,nodev,size={cfg.workspace_mb}m,uid=1000,gid=1000,mode=0755"},
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

    def _check_ready(self) -> None:
        """Confirm the container stayed up and `sh` and `timeout` work inside it.

        A container whose keep-alive command cannot run still "starts" and then
        exits at once; catch that here instead of failing on the first command.
        """
        container = self._container
        time.sleep(0.1)  # let a doomed container exit before we look
        try:
            container.reload()
            running = container.status == "running"
        except Exception as exc:
            raise SandboxError(START_FAILED, f"Could not check the sandbox container: {_brief(exc)}") from None
        if not running:
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

    def _ensure_image(self, client: docker.DockerClient) -> None:
        image = self.config.image
        try:
            client.images.get(image)
            return
        except ImageNotFound:
            pass
        except Exception as exc:
            raise SandboxError(IMAGE_UNAVAILABLE, f"Could not check for image {image}: {_brief(exc)}") from None
        log.info("pulling sandbox image %s", image)
        try:
            client.images.pull(image)
        except Exception as exc:
            raise SandboxError(
                IMAGE_UNAVAILABLE,
                f"Image {image} is not available locally and could not be pulled: {_brief(exc)}",
            ) from None

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
        if container is not None:
            try:
                container.remove(force=True, v=True)
            except NotFound:
                pass
            except Exception as exc:
                log.warning("could not remove sandbox container %s: %s", container.name, _brief(exc))
        self._release_client()

    def inspect(self) -> dict[str, Any]:
        """Docker's description of the running container (for tests and diagnostics)."""
        if self._container is None or self._client is None:
            raise SandboxError(SANDBOX_CLOSED, "The sandbox is not running.")
        return self._client.api.inspect_container(self._container.id)

    def __enter__(self) -> "Sandbox":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- running commands ------------------------------------------------

    def run(self, command: str | Sequence[str], *, timeout: float | None = None) -> CommandResult:
        """Run a command in the container.

        A string runs through `sh -c`; a list runs directly with no shell.
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

        api = self._client.api
        try:
            exec_id = api.exec_create(
                self._container.id, wrapped, stdout=True, stderr=True, workdir=WORKDIR, user=USER
            )["Id"]
            stream = api.exec_start(exec_id, stream=True, demux=True)
        except Exception as exc:
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


def _brief(exc: BaseException) -> str:
    """Short, single-line description of a Docker/SDK error (never includes env or secrets)."""
    if isinstance(exc, APIError) and exc.explanation:
        text = str(exc.explanation)
    else:
        text = str(exc) or type(exc).__name__
    text = " ".join(text.split())
    return text if len(text) <= 300 else text[:297] + "..."

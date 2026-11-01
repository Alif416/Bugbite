"""Sandbox image: build Bugbite's own image on first use, pull anything else."""

from __future__ import annotations

import logging
from pathlib import Path

import docker
from docker.errors import ImageNotFound

from bugbite.errors import IMAGE_UNAVAILABLE, SandboxError

log = logging.getLogger(__name__)

# Bump the suffix whenever docker/sandbox.Dockerfile changes.
SANDBOX_IMAGE = "bugbite-sandbox:py3.11-1"
DOCKERFILE_DIR = Path(__file__).resolve().parents[3] / "docker"
DOCKERFILE_NAME = "sandbox.Dockerfile"


def _brief(exc: BaseException) -> str:
    text = " ".join((str(exc) or type(exc).__name__).split())
    return text if len(text) <= 300 else text[:297] + "..."


def ensure_image(client: docker.DockerClient, image: str) -> None:
    """Make sure `image` exists locally.

    Bugbite's own image is built from the Dockerfile; any other image is pulled.
    """
    try:
        client.images.get(image)
        return
    except ImageNotFound:
        pass
    except Exception as exc:
        raise SandboxError(IMAGE_UNAVAILABLE, f"Could not check for image {image}: {_brief(exc)}") from None

    if image == SANDBOX_IMAGE:
        _build(client, image)
    else:
        _pull(client, image)


def _build(client: docker.DockerClient, image: str) -> None:
    if not (DOCKERFILE_DIR / DOCKERFILE_NAME).is_file():
        raise SandboxError(IMAGE_UNAVAILABLE, f"Cannot build {image}: {DOCKERFILE_DIR / DOCKERFILE_NAME} is missing.")
    log.info("building sandbox image %s (first use; this can take a few minutes)", image)
    try:
        client.images.build(path=str(DOCKERFILE_DIR), dockerfile=DOCKERFILE_NAME, tag=image, rm=True, pull=True)
    except Exception as exc:
        raise SandboxError(IMAGE_UNAVAILABLE, f"Could not build image {image}: {_brief(exc)}") from None


def _pull(client: docker.DockerClient, image: str) -> None:
    log.info("pulling sandbox image %s", image)
    try:
        client.images.pull(image)
    except Exception as exc:
        raise SandboxError(
            IMAGE_UNAVAILABLE,
            f"Image {image} is not available locally and could not be pulled: {_brief(exc)}",
        ) from None

# Bugbite sandbox image. Tagged bugbite-sandbox:py3.11-1 (bump the suffix when this file changes).
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# /workspace becomes an anonymous volume at run time; the volume inherits this
# ownership, so the unprivileged sandbox user (1000:1000) can write to it.
RUN mkdir -p /workspace/.home /workspace/.cache \
    && chown -R 1000:1000 /workspace

ENV HOME=/workspace/.home \
    PIP_CACHE_DIR=/workspace/.cache/pip \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GIT_TERMINAL_PROMPT=0

WORKDIR /workspace

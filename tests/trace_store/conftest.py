"""A throwaway PostgreSQL 17 for the tests that need a real database (AD-116).

It is a container started here, on a random local port with a random password, labelled `bugbite` so the usual
leftover checks see it, and removed at the end even if the tests fail. No other database on this machine is used.
"""

import atexit
import secrets
import time
from dataclasses import dataclass

import pytest

IMAGE = "postgres:17"


@dataclass(frozen=True)
class PgServer:
    host: str
    port: int
    password: str
    container_name: str

    def dsn(self, database: str = "postgres") -> str:
        return f"postgresql://postgres:{self.password}@{self.host}:{self.port}/{database}"


def _remove(container) -> None:
    try:
        container.remove(force=True, v=True)
    except Exception:
        pass


@pytest.fixture(scope="session")
def pg_server():
    import docker
    import psycopg

    client = docker.from_env()
    password = secrets.token_hex(16)
    name = f"bugbite-trace-test-{secrets.token_hex(4)}"
    container = client.containers.run(
        IMAGE, detach=True, name=name, environment={"POSTGRES_PASSWORD": password},
        ports={"5432/tcp": ("127.0.0.1", None)}, tmpfs={"/var/lib/postgresql/data": ""},
        labels={"bugbite": "trace-store-test"}, command=["postgres", "-c", "fsync=off", "-c", "max_connections=60"],
    )
    atexit.register(_remove, container)
    try:
        port = None
        deadline = time.monotonic() + 90
        good = 0
        while time.monotonic() < deadline:
            container.reload()
            bindings = (container.ports or {}).get("5432/tcp")
            if bindings:
                port = int(bindings[0]["HostPort"])
                try:
                    with psycopg.connect(f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres", connect_timeout=2) as conn:
                        conn.execute("SELECT 1")
                    good += 1
                    if good >= 2:  # the image restarts the server once after initialising; wait until it stays up
                        break
                    time.sleep(1.5)
                    continue
                except psycopg.Error:
                    good = 0
            time.sleep(0.5)
        else:
            raise RuntimeError("the test PostgreSQL did not become ready in time")
        yield PgServer("127.0.0.1", port, password, name)
    finally:
        _remove(container)
        client.close()


@pytest.fixture
def pg_dsn(pg_server):
    """A fresh, empty database on the throwaway server for one test."""
    import psycopg

    name = f"t_{secrets.token_hex(6)}"
    with psycopg.connect(pg_server.dsn(), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    yield pg_server.dsn(name)
    with psycopg.connect(pg_server.dsn(), autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def store(pg_dsn):
    from bugbite.trace_store import TraceStore

    with TraceStore(pg_dsn) as s:
        s.create_schema()
        yield s

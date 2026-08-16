"""Fixtures for tests that need a live Samba AD DC.

Point them at your own test domain:

    TEST_DC_HOST=192.168.1.10
    TEST_ADMIN_USER=Administrator
    TEST_ADMIN_PASSWORD=…
    TEST_INSECURE=1          # self-signed certificate

    SAMCON_TARGET=test       # the suite lives in the image, not in a mount

    docker compose up -d --build
    docker compose exec samcon python -m pytest tests/integration -q

Everything goes through the HTTP API rather than the internal modules: that is
what an administrator actually exercises, and it covers the session, CSRF and
error-translation layers at the same time.

WARNING: these tests create and delete objects. Each run works inside its own
throwaway OU named ``samcon-test-<random>`` and removes it afterwards, but the
domain still has to be one you are willing to write to.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

# The server to sign in against. TEST_DC_HOST is what .env uses; the rest are
# fallbacks so the tests also run against a container configured the old way.
TEST_SERVER = (
    os.environ.get("TEST_SERVER")
    or os.environ.get("TEST_DC_HOST")
    or os.environ.get("SAMCON_DC_HOSTS", "").split(",")[0]
).strip()
TEST_REALM = os.environ.get("TEST_REALM") or os.environ.get("SAMCON_REALM", "")
TEST_ADMIN = os.environ.get("TEST_ADMIN_USER", "Administrator")
TEST_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
TEST_INSECURE = os.environ.get("TEST_INSECURE", "0").lower() in ("1", "true", "yes")


def _samba_available() -> bool:
    try:
        import samba  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture(scope="session")
def reachable_server() -> str:
    """The configured server, verified to answer on an LDAP port.

    An address that nothing answers on is a misconfigured environment, not a
    failing code path — so this skips, but names the address so the cause is
    obvious rather than showing up as four unrelated assertion errors.
    """
    if not _samba_available():
        pytest.skip("python3-samba is missing — run inside the container")
    if not TEST_SERVER:
        pytest.skip("TEST_DC_HOST is not set — no domain to test against")

    from samcon.ad.discovery import LDAP_PORT, LDAPS_PORT, check_port, normalise_host

    host = normalise_host(TEST_SERVER)
    if not check_port(host, LDAP_PORT) and not check_port(host, LDAPS_PORT):
        pytest.skip(
            f"TEST_DC_HOST={host} answers on neither port {LDAP_PORT} nor {LDAPS_PORT} "
            "— check the address in .env"
        )
    return host


@pytest.fixture(scope="session")
def running_app(reachable_server: str):
    """The application, started once for the whole test session.

    ``TestClient`` as a context manager runs the lifespan — including the
    shutdown, which clears the session store. Every client that did that would
    sign out every other client, so the lifespan is owned here and the clients
    below are plain ones that only send requests.
    """
    from fastapi.testclient import TestClient

    from samcon.main import app

    with TestClient(app):
        yield app


@pytest.fixture(scope="session")
def api(running_app, reachable_server: str):
    """An authenticated API client, signed in for the whole session."""
    if not TEST_PASSWORD:
        pytest.skip("TEST_ADMIN_PASSWORD is not set — cannot sign in")

    from fastapi.testclient import TestClient

    client = TestClient(running_app)
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": TEST_ADMIN,
            "password": TEST_PASSWORD,
            # With a server given, the realm is discovered from its rootDSE —
            # the same path the sign-in form takes.
            "server": reachable_server,
            "realm": TEST_REALM or None,
            "insecure": TEST_INSECURE,
        },
    )
    if response.status_code != 200:
        pytest.skip(f"cannot sign in to the test domain: {response.text}")

    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    yield client
    client.post("/api/v1/auth/logout")


@pytest.fixture
def anonymous(running_app):
    """A client that has not signed in.

    Its own cookie jar, so it stays anonymous, but the same running
    application — a second lifespan would end the session of every other
    client.
    """
    from fastapi.testclient import TestClient

    return TestClient(running_app)


@pytest.fixture(scope="session")
def domain(api) -> dict[str, Any]:
    return api.get("/api/v1/auth/session").json()["domain"]


@pytest.fixture(scope="session")
def base_dn(domain: dict[str, Any]) -> str:
    return domain["base_dn"]


@pytest.fixture
def test_ou(api, base_dn: str):
    """A throwaway OU, removed afterwards even if the test failed."""
    name = f"samcon-test-{uuid.uuid4().hex[:8]}"
    response = api.post(
        "/api/v1/ous",
        json={
            "parent_dn": base_dn,
            "name": name,
            "description": "SAMCON integration test — safe to delete",
            # Protection would only get in the way of the cleanup below.
            "protect_from_deletion": False,
        },
    )
    assert response.status_code == 200, response.text
    dn = response.json()["dn"]

    yield dn

    api.delete(f"/api/v1/ous?dn={dn}&recursive=true")


def unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"

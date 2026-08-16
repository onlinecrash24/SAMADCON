"""API behaviour that does not need a domain controller.

Covers the error envelope, authentication gating and CSRF — the parts a
misconfigured deployment would otherwise expose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from samcon.ad.target import ConnectionTarget
from samcon.auth.kerberos import Principal
from samcon.auth.session import get_store, reset_auth_state
from samcon.main import app

TARGET = ConnectionTarget(realm="SAMCON.TEST", hosts=("dc1.samcon.test",))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    reset_auth_state()


def test_health_needs_no_authentication(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_info_reports_the_realm(client: TestClient):
    payload = client.get("/api/v1/info").json()
    assert payload["realm"] == "SAMCON.TEST"
    assert "sessions" in payload


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/directory/roots",
        "/api/v1/auth/session",
        "/api/v1/users?dn=CN=x,DC=test",
        "/api/v1/groups?dn=CN=x,DC=test",
        "/api/v1/computers?dn=CN=x,DC=test",
        "/api/v1/ous?dn=CN=x,DC=test",
    ],
)
def test_protected_endpoints_require_a_session(client: TestClient, path: str):
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] in ("not_authenticated", "session_expired")


def test_error_envelope_shape(client: TestClient):
    error = client.get("/api/v1/directory/roots").json()["error"]
    assert set(error) >= {"code", "message"}
    assert isinstance(error["message"], str)


def test_validation_errors_use_the_same_envelope(client: TestClient):
    # Missing password.
    response = client.post("/api/v1/auth/login", json={"username": "admin"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert any(field["field"] == "password" for field in error["context"]["fields"])


def test_unknown_fields_are_rejected(client: TestClient):
    """A typo in a field name must fail loudly, not be ignored."""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "x", "typo": True},
    )
    assert response.status_code == 422


def test_security_headers_are_present(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def _open_session(tmp_path) -> tuple[str, str]:
    """Register a session directly, bypassing Kerberos."""
    store = get_store()
    ccache = tmp_path / "ccache"
    ccache.write_text("not-a-real-ticket")
    session_id = store.new_id()
    session = store.create(
        session_id=session_id,
        principal=Principal("admin", "SAMCON.TEST"),
        target=TARGET,
        ccache=ccache,
        ticket_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    return session_id, session.csrf_token


def test_write_without_csrf_token_is_refused(client: TestClient, tmp_path):
    session_id, _ = _open_session(tmp_path)
    client.cookies.set("samcon_session", session_id)

    response = client.post(
        "/api/v1/users",
        json={"parent_dn": "OU=Users,DC=samcon,DC=test", "sam_account_name": "test"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_write_with_a_wrong_csrf_token_is_refused(client: TestClient, tmp_path):
    session_id, _ = _open_session(tmp_path)
    client.cookies.set("samcon_session", session_id)

    response = client.post(
        "/api/v1/users",
        json={"parent_dn": "OU=Users,DC=samcon,DC=test", "sam_account_name": "test"},
        headers={"X-CSRF-Token": "wrong"},
    )
    assert response.status_code == 403


def test_expired_session_is_rejected(client: TestClient, tmp_path):
    store = get_store()
    ccache = tmp_path / "ccache-expired"
    ccache.write_text("t")
    session_id = store.new_id()
    store.create(
        session_id=session_id,
        principal=Principal("admin", "SAMCON.TEST"),
        target=TARGET,
        ccache=ccache,
        ticket_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    client.cookies.set("samcon_session", session_id)

    response = client.get("/api/v1/directory/roots")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"


def test_logout_clears_the_cookie(client: TestClient, tmp_path):
    session_id, _ = _open_session(tmp_path)
    client.cookies.set("samcon_session", session_id)

    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json()["status"] == "signed_out"
    assert get_store().count() == 0


def test_logout_without_a_session_is_harmless(client: TestClient):
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_openapi_document_builds(client: TestClient):
    """A broken type annotation in a router would surface here."""
    schema = client.get("/api/openapi.json").json()
    assert schema["info"]["title"].startswith("SAMCON")
    assert "/api/v1/users" in schema["paths"]

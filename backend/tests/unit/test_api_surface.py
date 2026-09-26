"""API behaviour that does not need a domain controller.

Covers the error envelope, authentication gating and CSRF — the parts a
misconfigured deployment would otherwise expose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from samadcon.ad.target import ConnectionTarget
from samadcon.auth.kerberos import Principal
from samadcon.auth.session import get_store, reset_auth_state
from samadcon.main import app

TARGET = ConnectionTarget(realm="SAMADCON.TEST", hosts=("dc1.samadcon.test",))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    reset_auth_state()


def test_health_needs_no_authentication(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def parameters_of(path: str) -> dict[str, dict]:
    """The query parameters a route declares, by name.

    Read off the application rather than fetched: the schema endpoint is not
    served, which is a deliberate choice for something that manages a domain
    and not one to work around in a test.
    """
    schema = app.openapi()
    return {
        parameter["name"]: parameter
        for parameter in schema["paths"][path]["get"].get("parameters", [])
    }


def test_the_search_can_be_told_to_leave_advanced_objects_out():
    """The switch in the console hid objects from the tree and the list and not
    from the search: build_filter could express it, search_objects took it, and
    the route in between had it wired shut. Nothing here can catch that except
    the declaration itself."""
    advanced = parameters_of("/api/v1/directory/search").get("advanced")

    assert advanced is not None, "the search route declares no advanced parameter"
    assert advanced["schema"]["default"] is True


def test_every_dn_parameter_refuses_control_characters():
    """The password reset once put a query-parameter DN into LDIF, and a line
    break in it became further records. DnQuery refuses control characters;
    this holds every route to using it — five DNS routes had their own type
    and went round it until this test was written."""
    missing = []
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []):
                name = parameter["name"]
                if parameter.get("in") != "query" or not (name == "dn" or name.endswith("_dn")):
                    continue
                schema = parameter["schema"]
                patterns = [schema.get("pattern")] + [
                    option.get("pattern") for option in schema.get("anyOf", [])
                ]
                if not any(patterns):
                    missing.append(f"{method.upper()} {path} ?{name}")
    assert missing == []


def test_the_template_import_says_what_to_do_with_templates_already_there():
    """Refusing the lot was the only behaviour, which made a second import of
    Microsoft's package impossible without replacing everything. The store can
    skip now; this holds the route to passing that through."""
    declared = app.openapi()["paths"]["/api/v1/admx/store"]["post"]["parameters"]
    existing = next(item for item in declared if item["name"] == "existing")
    pattern = existing["schema"].get("pattern") or existing["schema"]["anyOf"][0]["pattern"]
    for mode in ("refuse", "skip", "replace"):
        assert mode in pattern


def test_the_template_import_takes_a_choice_of_languages():
    """22 languages in Microsoft's package, 97 MB; two of them are 12."""
    declared = app.openapi()["paths"]["/api/v1/admx/store"]["post"]["parameters"]
    assert "languages" in {item["name"] for item in declared}


def test_browsing_leaves_them_out_by_default_and_searching_does_not():
    """The asymmetry is deliberate. A list of a place may leave things out; an
    answer to "where is X" that omits an object reports it does not exist."""
    for path in ("/api/v1/directory/tree", "/api/v1/directory/children"):
        assert parameters_of(path)["advanced"]["schema"]["default"] is False

    assert parameters_of("/api/v1/directory/search")["advanced"]["schema"]["default"] is True


def test_info_reports_the_realm(client: TestClient):
    payload = client.get("/api/v1/info").json()
    assert payload["realm"] == "SAMADCON.TEST"
    assert set(payload) == {"version", "realm", "ldap_insecure", "ldap_transports"}


def test_info_withholds_internal_topology_before_sign_in(client: TestClient):
    """/info is reachable without a session, so it must not hand an anonymous
    caller the internal DC addresses or a live count of signed-in
    administrators. Both used to be here and the front end read neither."""
    payload = client.get("/api/v1/info").json()
    for leaked in ("dc_hosts", "sessions", "workgroup", "dc_discovery"):
        assert leaked not in payload


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
        principal=Principal("admin", "SAMADCON.TEST"),
        target=TARGET,
        ccache=ccache,
        ticket_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    return session_id, session.csrf_token


def test_write_without_csrf_token_is_refused(client: TestClient, tmp_path):
    session_id, _ = _open_session(tmp_path)
    client.cookies.set("samadcon_session", session_id)

    response = client.post(
        "/api/v1/users",
        json={"parent_dn": "OU=Users,DC=samadcon,DC=test", "sam_account_name": "test"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_write_with_a_wrong_csrf_token_is_refused(client: TestClient, tmp_path):
    session_id, _ = _open_session(tmp_path)
    client.cookies.set("samadcon_session", session_id)

    response = client.post(
        "/api/v1/users",
        json={"parent_dn": "OU=Users,DC=samadcon,DC=test", "sam_account_name": "test"},
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
        principal=Principal("admin", "SAMADCON.TEST"),
        target=TARGET,
        ccache=ccache,
        ticket_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    client.cookies.set("samadcon_session", session_id)

    response = client.get("/api/v1/directory/roots")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"


def test_logout_clears_the_cookie(client: TestClient, tmp_path):
    session_id, _ = _open_session(tmp_path)
    client.cookies.set("samadcon_session", session_id)

    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json()["status"] == "signed_out"
    assert get_store().count() == 0


def test_logout_without_a_session_is_harmless(client: TestClient):
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_openapi_document_builds(client: TestClient):
    """A broken type annotation in a router would surface here."""
    schema = client.get("/api/openapi.json").json()
    assert schema["info"]["title"].startswith("SAMADCON")
    assert "/api/v1/users" in schema["paths"]


def test_login_with_a_typed_server_is_rate_limited(client: TestClient, monkeypatch):
    """A typed-in address makes login resolve a target, which opens outbound
    connections before anyone is authenticated — the same reach /servers/probe
    limits. Login must share that limit or it is a second, unthrottled way to
    use the container as a port scanner. The resolve is stubbed to fail so the
    test never touches the network; the point is that the limiter trips first."""
    from samadcon.ad import targets
    from samadcon.core.errors import InvalidRequest
    from samadcon.core.ratelimit import probe_limiter

    probe_limiter.reset()

    def refuse(*args, **kwargs):
        raise InvalidRequest("no", code="nope")

    monkeypatch.setattr(targets, "resolve_target", refuse)

    body = {"username": "x", "password": "y", "server": "10.0.0.1"}
    codes = [client.post("/api/v1/auth/login", json=body).status_code for _ in range(21)]

    assert codes[:20] == [400] * 20
    assert codes[20] == 429
    # The bucket holds exactly the events it let through, not the one it turned
    # away — the limit is a ceiling, not an off-by-one.
    assert len(probe_limiter._events["testclient"]) == 20
    probe_limiter.reset()


def test_login_without_a_server_is_not_probe_limited(client: TestClient, monkeypatch):
    """The default and configured profiles name operator-chosen hosts, not
    caller-chosen ones, so they are not throttled by the probe limiter. They
    still fail here — resolve is stubbed — but never with a 429."""
    from samadcon.ad import targets
    from samadcon.core.errors import InvalidRequest
    from samadcon.core.ratelimit import probe_limiter

    probe_limiter.reset()
    monkeypatch.setattr(
        targets, "resolve_target", lambda *a, **k: (_ for _ in ()).throw(InvalidRequest("no", code="nope"))
    )

    body = {"username": "x", "password": "y"}
    codes = {client.post("/api/v1/auth/login", json=body).status_code for _ in range(21)}

    assert codes == {400}
    probe_limiter.reset()


def test_a_bitlocker_password_is_only_read_by_a_verified_post(client: TestClient, tmp_path):
    """The listing is a GET; handing out the recovery password is not. As a
    write it needs the CSRF token, which a cross-site page cannot send."""
    session_id, _ = _open_session(tmp_path)
    client.cookies.set("samadcon_session", session_id)
    target = "/api/v1/computers/bitlocker/reveal?dn=CN=PC01,DC=samadcon,DC=test&key_id=1A2B3C4D"

    assert client.get(target).status_code == 405
    refused = client.post(target)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "csrf_failed"


def test_the_bitlocker_search_refuses_a_filter_in_the_key_id(client: TestClient, tmp_path):
    session_id, _ = _open_session(tmp_path)
    client.cookies.set("samadcon_session", session_id)
    response = client.get("/api/v1/computers/bitlocker/find?key_id=1A2B)(name=*")
    assert response.status_code == 422

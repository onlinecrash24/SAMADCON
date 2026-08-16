"""Server discovery against a live domain controller.

These verify the path that makes entering a bare IP address work: the probe
learns the realm, and the sign-in that follows uses it.

The ``reachable_server`` fixture gates all of them, so a wrong or unset
TEST_DC_HOST skips with one clear message instead of producing a handful of
assertion errors that all mean "misconfigured".
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.conftest import TEST_ADMIN, TEST_INSECURE, TEST_PASSWORD

pytestmark = pytest.mark.integration

# The unauthenticated client comes from conftest: it shares the running
# application with the signed-in one, which a locally started client would
# shut down again on its way out.


def probe(client, host: str) -> dict[str, Any]:
    """Probe *host*, failing with the server's own message if it did not work."""
    response = client.post(
        "/api/v1/servers/probe", json={"host": host, "insecure": TEST_INSECURE}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_probe_identifies_the_domain(anonymous, reachable_server: str):
    result = probe(anonymous, reachable_server)

    assert result["realm"], "no realm was derived"
    assert result["realm"] == result["realm"].upper()
    assert result["base_dn"].upper().startswith("DC=")
    assert result["is_domain_controller"] is True
    # Kerberos needs the DC's own name; without it a sign-in cannot work.
    assert result["dc_hostname"]


def test_probe_reports_whether_the_certificate_validates(anonymous, reachable_server: str):
    result = probe(anonymous, reachable_server)

    if not result["ldaps_reachable"]:
        pytest.skip("the DC does not answer on port 636")
    # Either it validates or it does not — but the answer must be definite, so
    # the sign-in form can decide whether to offer the opt-out.
    assert result["ldaps_certificate_trusted"] in (True, False)
    assert result["requires_insecure"] == (result["ldaps_certificate_trusted"] is False)


def test_probe_reports_whether_the_dc_name_resolves(anonymous, reachable_server: str):
    """A name that does not resolve here breaks Kerberos, so it must be told."""
    result = probe(anonymous, reachable_server)
    assert result["dc_hostname_resolves"] in (True, False)


def test_probe_accepts_a_url_shaped_address(anonymous, reachable_server: str):
    """Administrators paste what they have; it should still work."""
    result = probe(anonymous, f"ldaps://{reachable_server}:636/")
    assert result["host"] == reachable_server


def test_probe_of_an_unreachable_address_is_explicit(anonymous):
    # 192.0.2.0/24 is TEST-NET-1 and never routed.
    response = anonymous.post("/api/v1/servers/probe", json={"host": "192.0.2.55"})
    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "server_unreachable"
    assert "389" in error["hint"]


def test_sign_in_by_address_without_naming_the_realm(anonymous, reachable_server: str):
    """The realm comes from the probe — this is the IP-only flow end to end."""
    if not TEST_PASSWORD:
        pytest.skip("TEST_ADMIN_PASSWORD is not set")

    response = anonymous.post(
        "/api/v1/auth/login",
        json={
            "username": TEST_ADMIN,
            "password": TEST_PASSWORD,
            "server": reachable_server,
            "insecure": TEST_INSECURE,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["target"]["realm"]
    assert payload["domain"]["base_dn"].upper().startswith("DC=")
    # The realm was discovered, not supplied.
    assert payload["realm"] == payload["target"]["realm"]

    anonymous.headers["X-CSRF-Token"] = payload["csrf_token"]
    anonymous.post("/api/v1/auth/logout")


def test_the_anonymous_client_does_not_end_the_signed_in_session(api, anonymous):
    """Two clients, one application.

    A client that runs the application's lifespan itself shuts it down again on
    the way out, and that clears every session — including the one the
    signed-in client is holding. From the outside it looked like every test in
    the alphabetically following file had lost its rights.
    """
    assert anonymous.get("/api/v1/auth/session").status_code == 401
    assert api.get("/api/v1/auth/session").status_code == 200


def test_sign_in_with_a_wrong_password_reports_credentials(anonymous, reachable_server: str):
    """Not "realm unknown" or "server unreachable" — the actual reason."""
    response = anonymous.post(
        "/api/v1/auth/login",
        json={
            "username": TEST_ADMIN,
            "password": "definitely-not-the-password-8kQ2",
            "server": reachable_server,
            "insecure": TEST_INSECURE,
        },
    )
    assert response.status_code in (401, 429), response.text
    assert response.json()["error"]["code"] in (
        "invalid_credentials",
        "login_throttled",
        "user_not_found",
    )

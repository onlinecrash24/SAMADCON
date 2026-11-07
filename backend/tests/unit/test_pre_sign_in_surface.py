"""What answers before anyone has signed in, and two writes without CSRF.

Reported by Rowie against 0.6.28:

- ``/api/docs`` and ``/api/openapi.json`` were served to anyone, with no
  way to turn them off. They are now off unless SAMADCON_API_DOCS is set.
- ``GET /api/v1/servers`` named every profile's domain controllers, by host
  name or address. The sign-in form needs the label and the realm.
- ``POST /admx/refresh`` and ``POST /users/certificates/inspect`` took no
  CSRF token. Both harmless, SameSite=Strict covers them, but every other
  POST asks for one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from samadcon.ad import targets
from samadcon.ad.target import ConnectionTarget
from samadcon.auth.kerberos import Principal
from samadcon.auth.session import get_store, reset_auth_state
from samadcon.config import ServerProfile, Settings, get_settings
from samadcon.main import app

TARGET = ConnectionTarget(realm="SAMADCON.TEST", hosts=("dc1.samadcon.test",))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    reset_auth_state()


@pytest.fixture
def setting(monkeypatch):
    def apply(**env: str) -> None:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    monkeypatch.delenv("SAMADCON_API_DOCS", raising=False)
    get_settings.cache_clear()
    yield apply
    get_settings.cache_clear()


# --- API documentation ----------------------------------------------------


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
def test_the_api_documentation_is_off_by_default(client, setting, path):
    response = client.get(path)
    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
def test_the_api_documentation_can_be_switched_on(client, setting, path):
    setting(SAMADCON_API_DOCS="1")
    assert client.get(path).status_code == 200


def test_the_setting_is_off_unless_given():
    assert Settings(_env_file=None).api_docs is False  # type: ignore[call-arg]


# --- the server list ------------------------------------------------------


def test_the_server_list_names_no_domain_controllers(client, monkeypatch):
    profiles = [
        ServerProfile(id="a", label="Kunde A", hosts=["10.0.0.5", "dc2.a.lan"], realm="a.lan"),
        ServerProfile(id="b", hosts=["dc1.b.lan"]),
    ]
    monkeypatch.setattr(targets, "list_profiles", lambda settings: profiles)

    payload = client.get("/api/v1/servers").json()
    text = str(payload)

    for host in ("10.0.0.5", "dc2.a.lan", "dc1.b.lan"):
        assert host not in text
    assert [item["label"] for item in payload["profiles"]] == ["Kunde A", "b"]
    assert payload["profiles"][0]["realm"] == "A.LAN"


def test_the_default_domain_is_named_without_its_controllers(monkeypatch):
    monkeypatch.setenv("SAMADCON_REALM", "example.lan")
    monkeypatch.setenv("SAMADCON_DC_HOSTS", "192.168.1.10")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(targets, "list_profiles", lambda settings: [])

    default = targets.describe_profiles(settings)["default"]
    assert default["realm"] == "EXAMPLE.LAN"
    assert "192.168.1.10" not in str(default)


# --- CSRF -----------------------------------------------------------------


def _open_session(tmp_path) -> str:
    store = get_store()
    ccache = tmp_path / "ccache"
    ccache.write_text("not-a-real-ticket")
    session_id = store.new_id()
    store.create(
        session_id=session_id,
        principal=Principal("admin", "SAMADCON.TEST"),
        target=TARGET,
        ccache=ccache,
        ticket_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    return session_id


@pytest.mark.parametrize(
    "path", ["/api/v1/admx/refresh", "/api/v1/users/certificates/inspect"]
)
def test_these_posts_want_a_csrf_token_too(client, tmp_path, path):
    client.cookies.set("samadcon_session", _open_session(tmp_path))
    response = client.post(path, json={"data": "eA=="} if "inspect" in path else None)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"

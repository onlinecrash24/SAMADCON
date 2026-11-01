"""Who signed in at the identity provider in front of SAMADCON.

A customer runs SAMADCON behind a forward-auth proxy — Authelia, Authentik,
oauth2-proxy for Keycloak — so that the identity provider's sign-in, with its
second factor, comes before SAMADCON's own. The two accounts are usually not
the same: max at the identity provider, max-adm in the directory. The audit
log should hold both.

The proxy names the user in a header. nginx in the container passes it on as
X-Samadcon-Idp-User, and only when the request came from a proxy named in
SAMADCON_TRUSTED_PROXIES; from anyone else the header is dropped. What is
tested here is the application's half: the settings, reading the header,
carrying it in the session and into every audit entry, and refusing a sign-in
without it when that is required — which is what catches someone who goes
round the proxy straight to port 8443.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from samadcon.ad.target import ConnectionTarget
from samadcon.api.common import AuditContext
from samadcon.auth.deps import IDP_USER_HEADER, idp_user
from samadcon.auth.kerberos import Principal
from samadcon.auth.session import Session, get_store, reset_auth_state
from samadcon.config import Settings, get_settings
from samadcon.core.audit import AuditLog

TARGET = ConnectionTarget(realm="SAMADCON.TEST", hosts=("dc1.samadcon.test",))


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name in ("PROXY_USER_HEADER", "PROXY_USER_REQUIRED", "TRUSTED_PROXIES"):
        monkeypatch.delenv(f"SAMADCON_{name}", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


# --- settings ---------------------------------------------------------------


def test_nothing_is_configured_by_default(monkeypatch):
    settings = _settings(monkeypatch)
    assert settings.proxy_user_header is None
    assert settings.proxy_user_required is False


def test_the_header_name_is_taken(monkeypatch):
    settings = _settings(
        monkeypatch,
        SAMADCON_PROXY_USER_HEADER="Remote-User",
        SAMADCON_TRUSTED_PROXIES="172.29.0.1",
    )
    assert settings.proxy_user_header == "Remote-User"


def test_a_header_name_without_a_trusted_proxy_stops_the_start(monkeypatch):
    """nginx would believe it from nobody, and the setting would do nothing
    while looking as if it did."""
    with pytest.raises(ValidationError):
        _settings(monkeypatch, SAMADCON_PROXY_USER_HEADER="Remote-User")


def test_an_empty_header_name_is_unset(monkeypatch):
    """compose turns an unset variable into an empty string."""
    settings = _settings(monkeypatch, SAMADCON_PROXY_USER_HEADER="")
    assert settings.proxy_user_header is None


@pytest.mark.parametrize("bad", ["Remote User", "Remote-User;", "X-User:", "a\nb", "ä-user"])
def test_a_header_name_nginx_cannot_read_stops_the_start(monkeypatch, bad):
    """The entrypoint turns the name into an nginx variable, $http_remote_user.
    Anything that is not a plain header token would end up in nginx's
    configuration as written."""
    with pytest.raises(ValidationError):
        _settings(
            monkeypatch,
            SAMADCON_PROXY_USER_HEADER=bad,
            SAMADCON_TRUSTED_PROXIES="172.29.0.1",
        )


def test_requiring_it_without_naming_it_stops_the_start(monkeypatch):
    with pytest.raises(ValidationError):
        _settings(
            monkeypatch,
            SAMADCON_PROXY_USER_REQUIRED="1",
            SAMADCON_TRUSTED_PROXIES="172.29.0.1",
        )


def test_requiring_it_without_a_trusted_proxy_stops_the_start(monkeypatch):
    """Without a trusted proxy nginx believes the header from nobody, so every
    sign-in would be refused."""
    with pytest.raises(ValidationError):
        _settings(
            monkeypatch,
            SAMADCON_PROXY_USER_HEADER="Remote-User",
            SAMADCON_PROXY_USER_REQUIRED="1",
        )


def test_requiring_it_with_both_is_accepted(monkeypatch):
    settings = _settings(
        monkeypatch,
        SAMADCON_PROXY_USER_HEADER="Remote-User",
        SAMADCON_PROXY_USER_REQUIRED="1",
        SAMADCON_TRUSTED_PROXIES="172.29.0.1",
    )
    assert settings.proxy_user_required is True


# --- reading the header -----------------------------------------------------


def _request(value: str | None) -> Request:
    headers = [] if value is None else [(IDP_USER_HEADER.lower().encode(), value.encode())]
    return Request({"type": "http", "headers": headers, "method": "GET", "path": "/"})


def test_the_header_nginx_passes_on():
    assert IDP_USER_HEADER == "X-Samadcon-Idp-User"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("max", "max"),
        ("  max  ", "max"),
        ("max@example.com", "max@example.com"),
        ("Max Mustermann", "Max Mustermann"),
        (None, None),
        ("", None),
        ("   ", None),
        ("x" * 256, "x" * 256),
        ("x" * 257, None),
        ("max\tadmin", None),
        ("max\x00", None),
    ],
)
def test_idp_user(given, expected):
    assert idp_user(_request(given)) == expected


# --- the audit log ----------------------------------------------------------


def _entries(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_an_entry_names_the_idp_user(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(action="user.create", actor="max-adm@TEST", idp_user="max")
    assert _entries(tmp_path / "audit.jsonl")[0]["idp_user"] == "max"


def test_an_entry_without_one_has_no_field(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(action="user.create", actor="max-adm@TEST")
    assert "idp_user" not in _entries(tmp_path / "audit.jsonl")[0]


def test_an_operation_names_it_whether_it_succeeds_or_fails(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")
    with log.operation("user.create", actor="max-adm@TEST", idp_user="max"):
        pass
    with pytest.raises(ValueError), log.operation("user.delete", actor="max-adm@TEST", idp_user="max"):
        raise ValueError("boom")
    assert [entry["idp_user"] for entry in _entries(tmp_path / "audit.jsonl")] == ["max", "max"]


def _session(tmp_path: Path, idp: str | None) -> Session:
    return Session(
        id="s" * 32,
        principal=Principal("max-adm", "SAMADCON.TEST"),
        target=TARGET,
        ccache=tmp_path / "ccache",
        csrf_token="token",
        ticket_expires_at=datetime.now(UTC) + timedelta(hours=1),
        idle_timeout=timedelta(minutes=60),
        idp_user=idp,
    )


def test_every_entry_of_a_session_names_its_idp_user(tmp_path: Path):
    """Not only the sign-in: what was changed is what an audit is asked about."""
    log = AuditLog(tmp_path / "audit.jsonl")
    context = AuditContext(log, _session(tmp_path, "max"), "192.168.1.55")
    with context.operation("user.create", target="CN=x"):
        pass
    context.record("user.unlock", target="CN=x")
    assert [entry["idp_user"] for entry in _entries(tmp_path / "audit.jsonl")] == ["max", "max"]


def test_a_session_without_one_writes_none(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")
    AuditContext(log, _session(tmp_path, None), None).record("user.unlock", target="CN=x")
    assert "idp_user" not in _entries(tmp_path / "audit.jsonl")[0]


# --- signing in -------------------------------------------------------------


@pytest.fixture
def configured(monkeypatch):
    """Settings from the environment, read afresh, and put back afterwards."""

    def apply(**env: str) -> None:
        for name in ("PROXY_USER_HEADER", "PROXY_USER_REQUIRED", "TRUSTED_PROXIES"):
            monkeypatch.delenv(f"SAMADCON_{name}", raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app()) as test_client:
        yield test_client
    reset_auth_state()


def app():
    from samadcon.main import app as application

    return application


@pytest.fixture
def signs_in(monkeypatch, tmp_path):
    """Everything a sign-in reaches for, stood in for: the target, the KDC, the
    DC. Returns the audit file the sign-in writes to."""
    from samadcon.ad import targets
    from samadcon.api.v1 import auth
    from samadcon.auth import kerberos

    monkeypatch.setattr(targets, "resolve_target", lambda *args, **kwargs: TARGET)
    monkeypatch.setattr(kerberos, "acquire_ticket", lambda *args, **kwargs: None)
    monkeypatch.setattr(kerberos, "ccache_path_for", lambda settings, sid: tmp_path / sid)
    monkeypatch.setattr(kerberos, "ticket_expiry", lambda ccache: None)

    async def read(worker, session, fn, label=None, **kwargs):
        return {"dc_hostname": "dc1.samadcon.test"}

    monkeypatch.setattr(auth, "ad_read", read)
    log = AuditLog(tmp_path / "audit.jsonl")
    monkeypatch.setattr(auth, "get_audit", lambda: log)
    return tmp_path / "audit.jsonl"


BODY = {"username": "max-adm", "password": "secret"}


def test_a_required_idp_user_that_is_missing_refuses_the_sign_in(
    client, configured, monkeypatch
):
    """Before anything else: no target resolved, no ticket asked for."""
    from samadcon.ad import targets
    from samadcon.auth import kerberos

    configured(
        SAMADCON_PROXY_USER_HEADER="Remote-User",
        SAMADCON_PROXY_USER_REQUIRED="1",
        SAMADCON_TRUSTED_PROXIES="172.29.0.1",
    )

    def must_not_run(*args, **kwargs):
        raise AssertionError("reached past the check")

    monkeypatch.setattr(targets, "resolve_target", must_not_run)
    monkeypatch.setattr(kerberos, "acquire_ticket", must_not_run)

    response = client.post("/api/v1/auth/login", json=BODY)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "idp_user_missing"


def test_a_required_idp_user_that_is_present_lets_it_through(client, configured, signs_in):
    configured(
        SAMADCON_PROXY_USER_HEADER="Remote-User",
        SAMADCON_PROXY_USER_REQUIRED="1",
        SAMADCON_TRUSTED_PROXIES="172.29.0.1",
    )
    response = client.post("/api/v1/auth/login", json=BODY, headers={IDP_USER_HEADER: "max"})
    assert response.status_code == 200
    assert response.json()["idp_user"] == "max"


def test_the_sign_in_records_the_idp_user(client, configured, signs_in):
    configured(SAMADCON_PROXY_USER_HEADER="Remote-User", SAMADCON_TRUSTED_PROXIES="172.29.0.1")
    client.post("/api/v1/auth/login", json=BODY, headers={IDP_USER_HEADER: "max"})

    entry = _entries(signs_in)[-1]
    assert entry["action"] == "auth.login"
    assert entry["result"] == "ok"
    assert entry["idp_user"] == "max"
    (session,) = get_store()._sessions.values()
    assert session.idp_user == "max"


def test_without_the_setting_no_idp_user_is_kept(client, configured, signs_in):
    """nginx drops the header then; should one arrive anyway, nothing is
    believed that nobody asked to be believed."""
    configured()
    client.post("/api/v1/auth/login", json=BODY, headers={IDP_USER_HEADER: "max"})

    assert "idp_user" not in _entries(signs_in)[-1]
    (session,) = get_store()._sessions.values()
    assert session.idp_user is None


def test_not_required_and_missing_still_signs_in(client, configured, signs_in):
    configured(SAMADCON_PROXY_USER_HEADER="Remote-User", SAMADCON_TRUSTED_PROXIES="172.29.0.1")
    response = client.post("/api/v1/auth/login", json=BODY)
    assert response.status_code == 200
    assert response.json()["idp_user"] is None


def test_the_session_says_who_signed_in_at_the_identity_provider(
    client, configured, signs_in, monkeypatch
):
    """What the console's top bar shows next to the account after a reload."""
    from samadcon.api.v1 import auth

    configured(SAMADCON_PROXY_USER_HEADER="Remote-User", SAMADCON_TRUSTED_PROXIES="172.29.0.1")
    client.post("/api/v1/auth/login", json=BODY, headers={IDP_USER_HEADER: "max"})
    (session_id,) = get_store()._sessions

    async def read(worker, session, fn, label=None, **kwargs):
        return {"domain": {}, "connection": None}

    monkeypatch.setattr(auth, "ad_read", read)
    client.cookies.set(get_settings().cookie_name, session_id)
    response = client.get("/api/v1/auth/session")
    assert response.status_code == 200
    assert response.json()["idp_user"] == "max"

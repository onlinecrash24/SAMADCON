"""Sign-in: what it gives away, and what it ties up, before anyone is in.

Reported by Rowie against 0.6.28:

- "No such account" and "wrong password" were two answers, each with the
  KDC's own text in ``detail``: the form told a stranger which accounts
  exist. Both are now the same answer; the audit log keeps the real one.
- A worker thread was created before the throttle was asked, and resolving
  the target can wait 30 seconds on a slow DC: 64 hanging attempts filled
  the registry, and real administrators got 503 too_many_sessions. The
  address is now checked first, and only a few sign-ins wait at a time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from samadcon.ad.target import ConnectionTarget
from samadcon.auth.session import LoginThrottle, reset_auth_state
from samadcon.core.audit import AuditLog
from samadcon.core.errors import AuthenticationError, SamadconError

TARGET = ConnectionTarget(realm="SAMADCON.TEST", hosts=("dc1.samadcon.test",))
BODY = {"username": "max-adm", "password": "secret"}


@pytest.fixture
def client():
    from samadcon.main import app

    with TestClient(app) as test_client:
        yield test_client
    reset_auth_state()


@pytest.fixture
def signs_in(monkeypatch, tmp_path):
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


def _kdc_says(monkeypatch, error: SamadconError) -> None:
    from samadcon.auth import kerberos

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(kerberos, "acquire_ticket", fail)


def _last_entry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8").splitlines()[-1])


# --- one answer for both --------------------------------------------------


def test_an_unknown_account_reads_like_a_wrong_password(client, signs_in, monkeypatch):
    _kdc_says(
        monkeypatch,
        AuthenticationError(
            "No such account in this realm.",
            code="user_not_found",
            hint="Log in as user@REALM and check the realm spelling.",
            detail="Client 'nobody@SAMADCON.TEST' not found in Kerberos database",
        ),
    )
    unknown = client.post("/api/v1/auth/login", json=BODY)

    _kdc_says(
        monkeypatch,
        AuthenticationError(
            "Wrong user name or password.",
            code="invalid_credentials",
            detail="Preauthentication failed",
        ),
    )
    wrong = client.post("/api/v1/auth/login", json=BODY)

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert unknown.json()["error"]["code"] == "invalid_credentials"
    assert "detail" not in unknown.json()["error"]
    assert "hint" not in unknown.json()["error"]


def test_the_audit_log_keeps_what_really_happened(client, signs_in, monkeypatch):
    _kdc_says(
        monkeypatch,
        AuthenticationError("No such account.", code="user_not_found", detail="not found"),
    )
    client.post("/api/v1/auth/login", json=BODY)
    assert _last_entry(signs_in)["error_code"] == "user_not_found"


def test_other_sign_in_failures_go_out_without_the_kdcs_text(client, signs_in, monkeypatch):
    _kdc_says(
        monkeypatch,
        AuthenticationError(
            "The clocks differ.", code="clock_skew", hint="Use NTP.", detail="Clock skew too great"
        ),
    )
    response = client.post("/api/v1/auth/login", json=BODY)
    error = response.json()["error"]
    assert error["code"] == "clock_skew"
    assert error["hint"] == "Use NTP."  # what to do about it stays
    assert "detail" not in error


# --- the address first ----------------------------------------------------


def test_an_address_that_is_throttled_gets_no_worker(client, signs_in, monkeypatch):
    from samadcon.ad import targets
    from samadcon.api.v1 import auth

    throttle = LoginThrottle(max_attempts=1, lockout_minutes=5)
    throttle.record_failure("someone-else", "testclient")
    monkeypatch.setattr(auth, "get_throttle", lambda: throttle)

    class Registry:
        def get(self, session_id):
            raise AssertionError("a worker was created for a throttled address")

        def drop(self, session_id):
            pass

    monkeypatch.setattr(auth, "get_registry", lambda: Registry())

    def must_not_run(*args, **kwargs):
        raise AssertionError("the target was resolved for a throttled address")

    monkeypatch.setattr(targets, "resolve_target", must_not_run)

    response = client.post("/api/v1/auth/login", json=BODY)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "login_throttled"


def test_check_address_looks_at_the_address_alone():
    throttle = LoginThrottle(max_attempts=2, lockout_minutes=5)
    throttle.record_failure("a", "10.0.0.1")
    throttle.record_failure("b", "10.0.0.1")
    with pytest.raises(AuthenticationError):
        throttle.check_address("10.0.0.1")
    throttle.check_address("10.0.0.2")
    throttle.check_address(None)


# --- only a few sign-ins wait at a time -----------------------------------


def test_sign_in_slots_refuse_beyond_their_limit_and_free_up_again():
    from samadcon.api.v1.auth import SignInSlots

    slots = SignInSlots(limit=2)
    first = slots.take()
    slots.take()
    with pytest.raises(SamadconError) as excinfo:
        slots.take()
    assert excinfo.value.code == "too_many_sign_ins"
    assert excinfo.value.status_code == 503
    first.release()
    slots.take()


def test_a_sign_in_beyond_the_limit_is_refused_before_a_worker(client, signs_in, monkeypatch):
    from samadcon.api.v1 import auth

    monkeypatch.setattr(auth, "sign_in_slots", auth.SignInSlots(limit=0))

    class Registry:
        def get(self, session_id):
            raise AssertionError("a worker was created beyond the limit")

    monkeypatch.setattr(auth, "get_registry", lambda: Registry())
    response = client.post("/api/v1/auth/login", json=BODY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "too_many_sign_ins"


def test_a_finished_sign_in_gives_its_slot_back(client, signs_in, monkeypatch):
    from samadcon.api.v1 import auth

    slots = auth.SignInSlots(limit=1)
    monkeypatch.setattr(auth, "sign_in_slots", slots)
    assert client.post("/api/v1/auth/login", json=BODY).status_code == 200
    _kdc_says(monkeypatch, AuthenticationError("x", code="invalid_credentials"))
    assert client.post("/api/v1/auth/login", json=BODY).status_code == 401
    # Both came back: a third still gets a slot.
    slots.take().release()

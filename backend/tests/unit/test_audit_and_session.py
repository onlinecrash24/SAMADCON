"""Audit redaction, session lifetime and login throttling.

The redaction tests matter most: an audit log that leaks a password is worse
than no audit log at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from samadcon.ad.target import ConnectionTarget
from samadcon.auth.kerberos import Principal, parse_principal
from samadcon.auth.session import LoginThrottle, Session, SessionStore
from samadcon.core.audit import REDACTED, AuditLog, redact
from samadcon.core.errors import AuthenticationError, SessionExpired

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attribute",
    [
        "unicodePwd",
        "userPassword",
        "clearTextPassword",
        "ms-Mcs-AdmPwd",
        "msLAPS-Password",
        "supplementalCredentials",
        "password",
        "new_password",
    ],
)
def test_credentials_are_redacted(attribute: str):
    assert redact({attribute: "hunter2"})[attribute] == REDACTED


def test_redaction_is_case_insensitive():
    assert redact({"UNICODEPWD": "secret"})["UNICODEPWD"] == REDACTED


def test_redaction_reaches_into_nested_structures():
    payload = {"changes": {"unicodePwd": {"old": "a", "new": "b"}}}
    assert redact(payload)["changes"]["unicodePwd"] == REDACTED


def test_ordinary_values_survive():
    assert redact({"displayName": "Max Muster"})["displayName"] == "Max Muster"


def test_binary_values_become_a_size_marker():
    assert redact({"objectSid": b"\x01\x02\x03"})["objectSid"] == "<3 bytes>"


def test_audit_entry_never_contains_the_password(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(
        action="user.set_password",
        actor="admin@TEST",
        target="CN=Max,DC=test",
        changes={"unicodePwd": {"new": "SuperSecret123!"}},
    )
    written = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "SuperSecret123!" not in written
    assert REDACTED in written


def test_audit_entry_is_valid_jsonl(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(action="user.create", actor="admin@TEST", target="CN=Max,DC=test")
    log.record(action="user.delete", actor="admin@TEST", target="CN=Max,DC=test")

    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["action"] == "user.create"
    assert entry["actor"] == "admin@TEST"
    assert entry["result"] == "ok"
    assert entry["ts"].endswith("Z")


def test_operation_context_records_failures(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")

    with (
        pytest.raises(ValueError),
        log.operation("user.create", actor="admin@TEST", target="CN=X,DC=test"),
    ):
        raise ValueError("boom")

    entry = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip())
    assert entry["result"] == "error"
    assert "boom" in entry["error"]
    assert "duration_ms" in entry


def test_session_id_is_truncated_in_the_log(tmp_path: Path):
    """The full id is a bearer token; the log only needs enough to correlate."""
    log = AuditLog(tmp_path / "audit.jsonl")
    session_id = "0123456789abcdef0123456789abcdef"
    log.record(action="auth.login", actor="admin@TEST", session_id=session_id)

    entry = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip())
    assert entry["session"] == "01234567"
    assert session_id not in json.dumps(entry)


def test_unwritable_audit_path_does_not_raise(tmp_path: Path):
    # A directory where a file is expected: writing must fail quietly.
    target = tmp_path / "blocked"
    target.mkdir()
    log = AuditLog(target)
    log.record(action="user.create", actor="admin@TEST")  # must not raise


# ---------------------------------------------------------------------------
# Principals
# ---------------------------------------------------------------------------


def test_principal_forms():
    assert parse_principal("max", "TEST.LAN") == Principal("max", "TEST.LAN")
    assert parse_principal("max@other.lan", "TEST.LAN") == Principal("max", "OTHER.LAN")
    assert parse_principal("TEST\\max", "TEST.LAN") == Principal("max", "TEST.LAN")


def test_principal_realm_is_uppercased():
    assert parse_principal("max@test.lan", "TEST.LAN").realm == "TEST.LAN"


def test_machine_account_names_are_accepted():
    assert parse_principal("PC01$", "TEST.LAN").username == "PC01$"


@pytest.mark.parametrize("bad", ["", "   ", "max user", "max)evil", "max\nadmin"])
def test_invalid_principals_are_rejected(bad: str):
    with pytest.raises(AuthenticationError):
        parse_principal(bad, "TEST.LAN")


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


TARGET = ConnectionTarget(realm="TEST.LAN", hosts=("dc1.test.lan",))


def _session(tmp_path: Path, **overrides) -> Session:
    defaults = {
        "id": "s" * 32,
        "principal": Principal("admin", "TEST.LAN"),
        "target": TARGET,
        "ccache": tmp_path / "ccache",
        "csrf_token": "token",
        "ticket_expires_at": datetime.now(UTC) + timedelta(hours=10),
        "idle_timeout": timedelta(minutes=60),
    }
    defaults.update(overrides)
    return Session(**defaults)


def test_expiry_is_the_earlier_of_ticket_and_idle(tmp_path: Path):
    session = _session(tmp_path, ticket_expires_at=datetime.now(UTC) + timedelta(minutes=5))
    # Ticket ends in 5 minutes, idle timeout is 60 — the ticket wins.
    assert session.expires_at == session.ticket_expires_at


def test_idle_timeout_wins_when_the_ticket_is_long(tmp_path: Path):
    session = _session(tmp_path, idle_timeout=timedelta(minutes=1))
    assert session.expires_at < session.ticket_expires_at


def test_touch_extends_the_idle_window(tmp_path: Path):
    session = _session(tmp_path, idle_timeout=timedelta(minutes=30))
    before = session.expires_at
    session.last_seen = datetime.now(UTC) + timedelta(minutes=10)
    assert session.expires_at > before


def test_expired_ticket_expires_the_session(tmp_path: Path):
    session = _session(tmp_path, ticket_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert session.is_expired()


def test_store_rejects_unknown_session(tmp_path: Path):
    store = SessionStore()
    with pytest.raises(SessionExpired):
        store.get("does-not-exist")


def test_store_rejects_missing_cookie():
    store = SessionStore()
    with pytest.raises(SessionExpired) as excinfo:
        store.get(None)
    assert excinfo.value.code == "not_authenticated"


def test_store_drops_expired_sessions_on_access(tmp_path: Path):
    store = SessionStore(idle_minutes=60)
    ccache = tmp_path / "ccache"
    ccache.write_text("ticket")
    session = store.create(
        session_id="abc123",
        principal=Principal("admin", "TEST.LAN"),
        target=TARGET,
        ccache=ccache,
        ticket_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert session is not None

    with pytest.raises(SessionExpired):
        store.get("abc123")
    assert store.count() == 0
    # The ticket must be gone from tmpfs, not just forgotten.
    assert not ccache.exists()


def test_drop_destroys_the_ticket(tmp_path: Path):
    store = SessionStore()
    ccache = tmp_path / "ccache"
    ccache.write_text("ticket")
    store.create(
        session_id="abc123",
        principal=Principal("admin", "TEST.LAN"),
        target=TARGET,
        ccache=ccache,
        ticket_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    store.drop("abc123")
    assert not ccache.exists()
    assert store.count() == 0


def test_sweep_removes_only_expired_sessions(tmp_path: Path):
    store = SessionStore()
    for index, offset in enumerate([timedelta(hours=1), timedelta(minutes=-1)]):
        ccache = tmp_path / f"ccache{index}"
        ccache.write_text("t")
        store.create(
            session_id=f"session{index}",
            principal=Principal("admin", "TEST.LAN"),
            target=TARGET,
            ccache=ccache,
            ticket_expires_at=datetime.now(UTC) + offset,
        )

    assert store.sweep() == 1
    assert store.count() == 1


def test_session_ids_are_unpredictable():
    ids = {SessionStore.new_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(len(value) >= 32 for value in ids)


# ---------------------------------------------------------------------------
# Login throttle — the AD lockout guard
# ---------------------------------------------------------------------------


def test_throttle_allows_attempts_below_the_limit():
    throttle = LoginThrottle(max_attempts=3)
    for _ in range(2):
        throttle.check("admin", "10.0.0.1")
        throttle.record_failure("admin", "10.0.0.1")
    throttle.check("admin", "10.0.0.1")  # third attempt is still allowed


def test_throttle_blocks_after_the_limit():
    throttle = LoginThrottle(max_attempts=3)
    for _ in range(3):
        throttle.record_failure("admin", "10.0.0.1")

    with pytest.raises(AuthenticationError) as excinfo:
        throttle.check("admin", "10.0.0.1")
    assert excinfo.value.code == "login_throttled"
    assert excinfo.value.status_code == 429
    assert excinfo.value.context["retry_after_seconds"] > 0


def test_successful_login_clears_the_counter():
    throttle = LoginThrottle(max_attempts=2)
    throttle.record_failure("admin", "10.0.0.1")
    throttle.record_success("admin", "10.0.0.1")
    throttle.record_failure("admin", "10.0.0.1")
    throttle.check("admin", "10.0.0.1")  # counter restarted, still allowed


def test_account_counter_protects_across_addresses():
    """Spreading attempts over many IPs must not defeat the AD lockout guard."""
    throttle = LoginThrottle(max_attempts=3)
    for index in range(3):
        throttle.record_failure("admin", f"10.0.0.{index}")

    with pytest.raises(AuthenticationError):
        throttle.check("admin", "10.0.0.99")


def test_lockout_expires_after_the_window():
    throttle = LoginThrottle(max_attempts=1, lockout_minutes=5)
    throttle.record_failure("admin", "10.0.0.1")
    with pytest.raises(AuthenticationError):
        throttle.check("admin", "10.0.0.1")

    # Age the recorded failure past the lockout window.
    stale = datetime.now(UTC) - timedelta(minutes=6)
    throttle._failures = {key: (count, stale) for key, (count, _) in throttle._failures.items()}

    throttle.check("admin", "10.0.0.1")
    assert throttle._failures == {}  # the stale entry is cleaned up


def test_zero_lockout_minutes_disables_throttling():
    """A zero-length window must mean "never block", not "block forever"."""
    throttle = LoginThrottle(max_attempts=1, lockout_minutes=0)
    assert throttle.enabled is False
    for _ in range(10):
        throttle.record_failure("admin", "10.0.0.1")
    throttle.check("admin", "10.0.0.1")


def test_zero_max_attempts_disables_throttling():
    throttle = LoginThrottle(max_attempts=0, lockout_minutes=5)
    assert throttle.enabled is False
    throttle.record_failure("admin", "10.0.0.1")
    throttle.check("admin", "10.0.0.1")


def test_throttle_without_client_ip():
    throttle = LoginThrottle(max_attempts=1)
    throttle.record_failure("admin", None)
    with pytest.raises(AuthenticationError):
        throttle.check("admin", None)


def test_the_failure_table_does_not_grow_without_bound(monkeypatch):
    """The username half of a key is attacker-chosen, so a run of failures
    against invented names adds an entry each. record_success and check only
    ever remove the one they touch, so without pruning the table would hold
    every name ever tried until the process restarts. Entries past the lockout
    can block no one and are dropped once the table is large."""
    import samadcon.auth.session as session_module

    clock = {"t": datetime(2020, 1, 1, tzinfo=UTC)}
    monkeypatch.setattr(session_module, "_now", lambda: clock["t"])

    throttle = LoginThrottle(max_attempts=3, lockout_minutes=5)
    for index in range(5000):
        throttle.record_failure(f"ghost-{index}")  # no ip: one key each
    assert len(throttle._failures) == 5000  # all fresh, nothing yet to drop

    clock["t"] = clock["t"] + timedelta(minutes=10)
    throttle.record_failure("one-more")
    # The 5000 stale names are past the lockout and have been swept.
    assert len(throttle._failures) < 50

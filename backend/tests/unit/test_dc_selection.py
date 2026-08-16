"""Which address SAMCON binds to, and how failures are reported.

Both matter for signing in through an IP address: Kerberos issues tickets for
ldap/<hostname>@REALM, and when a bind fails the reason lives in Samba's own
message rather than in our summary of it.
"""

from __future__ import annotations

from samcon.ad.connection import discover_dcs
from samcon.ad.target import ConnectionTarget
from samcon.core import errors

LdbError = type("LdbError", (Exception,), {})


def test_the_discovered_hostname_is_tried_before_the_typed_address():
    """A ticket for a bare IP does not exist, so the FQDN has to come first."""
    target = ConnectionTarget(realm="EXAMPLE.LAN", hosts=("192.168.1.10",))
    target = target.with_discovery(dc_hostname="dc1.example.lan")

    assert discover_dcs(target) == ["dc1.example.lan", "192.168.1.10"]


def test_the_typed_address_remains_as_a_fallback():
    """The name may not resolve inside the container; the address does."""
    target = ConnectionTarget(realm="EXAMPLE.LAN", hosts=("192.168.1.10",))
    target = target.with_discovery(dc_hostname="dc1.example.lan")
    assert "192.168.1.10" in discover_dcs(target)


def test_without_discovery_the_configured_hosts_are_used_in_order():
    target = ConnectionTarget(realm="EXAMPLE.LAN", hosts=("dc1.example.lan", "dc2.example.lan"))
    assert discover_dcs(target) == ["dc1.example.lan", "dc2.example.lan"]


def test_no_duplicate_when_address_and_hostname_match():
    target = ConnectionTarget(realm="EXAMPLE.LAN", hosts=("dc1.example.lan",))
    target = target.with_discovery(dc_hostname="dc1.example.lan")
    assert discover_dcs(target) == ["dc1.example.lan"]


def test_operations_error_points_at_the_handshake():
    """Samba reports a failed SASL or TLS handshake as LDAP error 1.

    Reading that as "the server has an internal problem" sends people looking
    in the wrong place, so the hint names the real candidates.
    """
    error = errors.translate(
        LdbError(1, "Unable to bind - LDAP client internal error: NT_STATUS_LOGON_FAILURE")
    )
    assert error.code == "ldap_operations_error"
    hint = (error.hint or "").lower()
    assert "kerberos" in hint or "tls" in hint
    assert "clock" in hint


def test_the_server_message_survives_translation():
    """Whatever Samba said has to reach the operator; it is the only clue."""
    raw = "Failed to connect to ldaps://dc1 - NT_STATUS_CONNECTION_REFUSED"
    error = errors.translate(LdbError(1, raw))
    assert error.detail == raw

"""How the LDAP connection is protected.

These settings caused real sign-in failures against a Samba 4 DC, so the
behaviour is pinned by tests rather than left to review:

* LDAP with GSSAPI sign-and-seal is the primary transport. It is what
  samba-tool and the Windows tools use, it needs no certificate, and it is the
  best-supported path through Samba's client stack.
* Over LDAPS, SASL wrapping must be *plain* — sign/seal on top of TLS is
  refused and every authenticated bind fails with NT_STATUS_INVALID_PARAMETER.
* Samba rejects ``tls verify peer = ca_and_name`` unless a CA source exists
  ("requires 'tls trust system cas', 'tls ca directories' or 'tls cafile'").
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from samadcon.ad.connection import DEFAULT_TRANSPORTS, PROTECTION
from samadcon.auth.kerberos import apply_transport_settings
from samadcon.config import Settings


class FakeLoadParm:
    """Records what would be handed to Samba."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, option: str, value: str) -> None:
        self.values[option] = value


@pytest.fixture
def lp() -> FakeLoadParm:
    return FakeLoadParm()


# ---------------------------------------------------------------------------
# LDAP with GSSAPI sealing
# ---------------------------------------------------------------------------


def test_plain_ldap_seals_with_kerberos(lp: FakeLoadParm):
    """The Kerberos session key encrypts the traffic; no certificate needed."""
    apply_transport_settings(lp, transport="ldap", ca_file=None, insecure=False)
    assert lp.values["client ldap sasl wrapping"] == "seal"


def test_plain_ldap_never_goes_unencrypted(lp: FakeLoadParm):
    """Even with verification relaxed, sealing stays required.

    'seal' is demanded rather than requested, so a server that cannot do it
    fails the connection instead of silently downgrading to cleartext.
    """
    apply_transport_settings(lp, transport="ldap", ca_file=None, insecure=True)
    assert lp.values["client ldap sasl wrapping"] == "seal"


def test_plain_ldap_ignores_certificate_settings(lp: FakeLoadParm):
    apply_transport_settings(
        lp, transport="ldap", ca_file=Path("/etc/samadcon/ca/ca.pem"), insecure=False
    )
    assert "tls cafile" not in lp.values
    assert "tls verify peer" not in lp.values


# ---------------------------------------------------------------------------
# LDAPS
# ---------------------------------------------------------------------------


def test_ldaps_uses_plain_sasl_wrapping(lp: FakeLoadParm):
    """Sealing on top of TLS is what broke every authenticated bind."""
    apply_transport_settings(lp, transport="ldaps", ca_file=None, insecure=False)
    assert lp.values["client ldap sasl wrapping"] == "plain"


def test_ldaps_without_a_ca_file_trusts_the_system_store(lp: FakeLoadParm):
    """Samba refuses ca_and_name unless a CA source exists."""
    apply_transport_settings(lp, transport="ldaps", ca_file=None, insecure=False)
    assert lp.values["tls verify peer"] == "ca_and_name"
    assert lp.values["tls trust system cas"] == "yes"


def test_ldaps_uses_an_explicit_ca_file(lp: FakeLoadParm):
    apply_transport_settings(
        lp, transport="ldaps", ca_file=Path("/etc/samadcon/ca/ca.pem"), insecure=False
    )
    assert lp.values["tls verify peer"] == "ca_and_name"
    assert lp.values["tls cafile"].endswith("ca.pem")
    # The explicit CA is the trust anchor; the system store would only widen it.
    assert "tls trust system cas" not in lp.values


def test_ldaps_insecure_disables_verification(lp: FakeLoadParm):
    apply_transport_settings(lp, transport="ldaps", ca_file=None, insecure=True)
    assert lp.values["tls verify peer"] == "no_check"
    assert lp.values["client ldap sasl wrapping"] == "plain"


def test_ldaps_insecure_configures_no_trust_anchor(lp: FakeLoadParm):
    """Nothing is verified, so naming a CA would only be misleading."""
    apply_transport_settings(
        lp, transport="ldaps", ca_file=Path("/etc/samadcon/ca/ca.pem"), insecure=True
    )
    assert "tls cafile" not in lp.values


# ---------------------------------------------------------------------------
# Transport order
# ---------------------------------------------------------------------------


def test_sealed_ldap_is_tried_before_ldaps_by_default():
    """The certificate-free path first — it is the one that works everywhere.

    Now a default rather than the only order: SAMADCON_LDAP_TRANSPORTS can
    reverse it or drop one. This is what a deployment gets for saying nothing."""
    assert list(DEFAULT_TRANSPORTS) == ["ldap", "ldaps"]
    assert Settings().ldap_transports == ["ldap", "ldaps"]


def test_every_transport_is_encrypted():
    """No entry may be plain LDAP without protection."""
    for transport, protection in PROTECTION.items():
        assert protection, f"{transport} declares no protection"
        assert transport in ("ldap", "ldaps")


def test_a_restriction_is_honoured_and_nothing_else_is_tried():
    """The point of the setting. A deployment that permits one transport
    must not quietly fall back to the other."""
    assert Settings(ldap_transports="ldaps").ldap_transports == ["ldaps"]
    assert Settings(ldap_transports="ldaps,ldap").ldap_transports == ["ldaps", "ldap"]


def test_a_transport_that_does_not_exist_is_refused_by_name():
    """Dropping it silently would leave someone believing they had
    restricted something."""
    with pytest.raises(ValidationError) as raised:
        Settings(ldap_transports="ldaps,smb")
    assert "smb" in str(raised.value)


def test_permitting_nothing_is_refused():
    """An empty list allows no way of reaching a domain controller, which is
    the failure this setting exists to prevent rather than cause."""
    with pytest.raises(ValidationError):
        Settings(ldap_transports="")


# ---------------------------------------------------------------------------
# Connection timeout
# ---------------------------------------------------------------------------


def test_the_connection_attempt_is_bounded(lp: FakeLoadParm):
    """An address nothing answers on must be reported, not waited out.

    The probe has always bounded its own attempts. The connection that follows
    it did not, and Samba's default let a name resolving to an unreachable
    host hang for 135 seconds — measured — while the interface showed nothing.
    """
    from samadcon.auth.kerberos import LDAP_CONNECT_TIMEOUT_SECONDS, _try_set

    _try_set(lp, "ldap connection timeout", str(LDAP_CONNECT_TIMEOUT_SECONDS))

    assert lp.values["ldap connection timeout"] == "10"


def test_an_unknown_tuning_option_is_not_fatal():
    """Samba builds differ in which parameters they accept, and a rejected
    tuning knob must not take the sign-in with it."""
    from samadcon.auth.kerberos import _try_set

    class Refusing:
        def set(self, option: str, value: str) -> None:
            raise RuntimeError("unknown parameter")

    _try_set(Refusing(), "ldap connection timeout", "10")


def test_operation_timeouts_are_left_alone(lp: FakeLoadParm):
    """`ldap timeout` covers whole operations. A paged search over a large
    directory is legitimately slow; bounding that would trade one bad failure
    for another."""
    from samadcon.auth.kerberos import LDAP_CONNECT_TIMEOUT_SECONDS, _try_set

    _try_set(lp, "ldap connection timeout", str(LDAP_CONNECT_TIMEOUT_SECONDS))

    assert "ldap timeout" not in lp.values

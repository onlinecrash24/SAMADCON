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

from samadcon.ad.connection import TRANSPORTS
from samadcon.auth.kerberos import apply_transport_settings


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


def test_sealed_ldap_is_tried_before_ldaps():
    """The certificate-free path first — it is the one that works everywhere."""
    assert [transport for transport, _ in TRANSPORTS] == ["ldap", "ldaps"]


def test_every_transport_is_encrypted():
    """No entry may be plain LDAP without protection."""
    for transport, protection in TRANSPORTS:
        assert protection, f"{transport} declares no protection"
        assert transport in ("ldap", "ldaps")

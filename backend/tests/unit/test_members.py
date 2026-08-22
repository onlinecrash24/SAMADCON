"""What a computer account's trust with the domain is worth.

Asked for as "connected clients and the security status of their connection".
Who holds a session right now lives in smbstatus on the DC and never reaches
the wire; what the directory holds answers the harder half anyway — what each
machine is able to negotiate, and which of them could impersonate a user.

Two rules, and the ones that are deliberately absent matter as much. Tests
keep them absent.
"""

from __future__ import annotations

from typing import Any

from samadcon.ad import diagnostics
from samadcon.core import findings


def member(**overrides: Any) -> dict[str, Any]:
    """A machine nothing is wrong with, so a test changes one thing."""
    base: dict[str, Any] = {
        "dn": "CN=WS01,CN=Computers,DC=example,DC=test",
        "name": "WS01",
        "operating_system": "Windows 11 Pro",
        "enabled": True,
        "is_domain_controller": False,
        "delegation": None,
        "delegates_to": [],
        "encryption": {"configured": True, "value": 0x18, "types": [], "weak": [], "has_aes": True},
    }
    base.update(overrides)
    return base


def ids(found: list[findings.Finding]) -> list[str]:
    return [item.id for item in found]


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def test_unconstrained_delegation_on_a_member_is_a_finding() -> None:
    """Such a machine receives a forwardable TGT from everyone who
    authenticates to it, a domain administrator included. Whoever holds the
    machine holds the domain."""
    found = findings.evaluate(members={"members": [member(delegation="unconstrained")]})

    assert ids(found) == ["member_unconstrained_delegation"]
    assert found[0].severity == "high"
    assert found[0].subject == "WS01"


def test_the_same_setting_on_a_domain_controller_is_not() -> None:
    """It is how a DC works. Reporting it would train people to skip the
    finding, and the one that mattered would go with it."""
    found = findings.evaluate(
        members={"members": [member(delegation="unconstrained", is_domain_controller=True)]}
    )

    assert found == []


def test_constrained_delegation_is_not_flagged() -> None:
    """A different risk and a much smaller one: the ticket only works against
    the services named. Worth showing in the list, not worth an alarm."""
    found = findings.evaluate(
        members={"members": [member(delegation="constrained", delegates_to=["cifs/fs01"])]}
    )

    assert found == []


def test_a_des_cipher_is_a_finding() -> None:
    found = findings.evaluate(
        members={
            "members": [
                member(
                    encryption={
                        "configured": True,
                        "value": 0x03,
                        "types": ["des-cbc-crc", "des-cbc-md5"],
                        "weak": ["des-cbc-crc", "des-cbc-md5"],
                        "has_aes": False,
                    }
                )
            ]
        }
    )

    assert ids(found) == ["member_weak_encryption"]
    assert "des-cbc-crc" in found[0].evidence["ciphers"]


# ---------------------------------------------------------------------------
# What must not become a finding
# ---------------------------------------------------------------------------


def test_an_unset_encryption_list_is_not_a_weakness() -> None:
    """Absent does not mean "supports nothing" — it leaves the choice to the
    KDC, and on a current Samba or Windows that includes AES. A rule here
    would put a red mark on most healthy domains."""
    found = findings.evaluate(
        members={
            "members": [
                member(
                    encryption={
                        "configured": False,
                        "value": None,
                        "types": [],
                        "weak": [],
                        "has_aes": None,
                    }
                )
            ]
        }
    )

    assert found == []


def test_rc4_alone_is_not_flagged() -> None:
    """It is weaker than AES and it is not broken. Saying so at the same
    severity as DES would flatten the difference that matters."""
    found = findings.evaluate(
        members={
            "members": [
                member(
                    encryption={
                        "configured": True,
                        "value": 0x04,
                        "types": ["rc4-hmac"],
                        "weak": [],
                        "has_aes": False,
                    }
                )
            ]
        }
    )

    assert found == []


def test_an_old_operating_system_is_context_and_not_a_finding() -> None:
    """The list shows it. Judging it needs a support timeline this tool does
    not have, and a guess would age badly."""
    found = findings.evaluate(members={"members": [member(operating_system="Windows 7")]})

    assert found == []


# ---------------------------------------------------------------------------
# Reading the attribute
# ---------------------------------------------------------------------------


class Entry:
    """Enough of an LDAP message for values.as_int to read one attribute.

    A list of values, not one value: ldb hands back every attribute that
    way and values.first() indexes into it. Returning the bytes bare made
    this mock yield 50 for 24 — the character code of the first digit.
    """

    def __init__(self, value: int | None) -> None:
        self.value = value

    def get(self, attr: str, idx: int = 0) -> Any:
        if attr != "msDS-SupportedEncryptionTypes" or self.value is None:
            return None
        return [str(self.value).encode()]

    def __getitem__(self, attr: str) -> Any:
        found = self.get(attr)
        if found is None:
            raise KeyError(attr)
        return found


def test_the_bits_are_decoded_to_the_names_the_kdc_uses() -> None:
    """0x18 is AES128 and AES256 — the pair a modern member advertises."""
    found = diagnostics._encryption(Entry(0x18))

    assert found["types"] == ["aes128-cts-hmac-sha1-96", "aes256-cts-hmac-sha1-96"]
    assert found["weak"] == []
    assert found["has_aes"] is True


def test_an_absent_attribute_reads_as_unset_rather_than_empty() -> None:
    found = diagnostics._encryption(Entry(None))

    assert found["configured"] is False
    assert found["has_aes"] is None

"""Telling a Samba DC from a Windows one.

A tester runs SAMADCON against three classic Windows domains. 0.6.15 told
everyone that a GPO's password policy has no effect on domain accounts and
offered to edit the domain object's instead — right for a Samba DC, wrong for
a Windows DC, which copies the Default Domain Policy onto the domain object
and overwrites an edit made there.

Measured on Samba 4.22.11, from its rootDSE:
    vendorName: Samba Team (https://www.samba.org)
    vendorVersion: 4.22.11-Debian-4.22.11+dfsg-0+deb13u1
Microsoft's list of rootDSE attributes has neither.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from samadcon.ad import connection, password_policy
from samadcon.core.errors import Conflict

SAMBA_VENDOR = "Samba Team (https://www.samba.org)"
SAMBA_VERSION = "4.22.11-Debian-4.22.11+dfsg-0+deb13u1"


@pytest.mark.parametrize(
    ("vendor", "samba"),
    [
        (SAMBA_VENDOR, True),
        ("samba team", True),
        (None, False),  # a Windows DC: no vendorName at all
        ("", False),
        ("Some LDAP server", False),
    ],
)
def test_only_samba_is_samba(vendor, samba):
    assert connection.is_samba_vendor(vendor) is samba


class _Root(dict):
    def get(self, name: str, default: Any = None) -> Any:
        for key, value in self.items():
            if key.lower() == name.lower():
                return value
        return default


class _SamDb:
    def __init__(self, root: dict[str, list[bytes]]) -> None:
        self.root = _Root(root)
        self.attrs: list[str] = []

    def search(self, base: str, scope: int, attrs: list[str]) -> list[Any]:
        self.attrs = attrs
        return [self.root]

    def get_domain_sid(self) -> str:
        return "S-1-5-21-1-2-3"


TARGET = types.SimpleNamespace(dns_domain="example.test", realm="EXAMPLE.TEST", netbios_name="EXAMPLE")
ROOT = {"defaultNamingContext": [b"DC=example,DC=test"], "dnsHostName": [b"dc1.example.test"]}


def test_the_rootdse_is_asked_for_the_vendor_and_it_is_kept():
    samdb = _SamDb({**ROOT, "vendorName": [SAMBA_VENDOR.encode()], "vendorVersion": [SAMBA_VERSION.encode()]})
    info = connection._read_domain_info(samdb, "dc1", TARGET)
    assert {"vendorName", "vendorVersion"} <= set(samdb.attrs)
    assert info.dc_vendor == SAMBA_VENDOR
    assert info.dc_vendor_version == SAMBA_VERSION
    assert info.is_samba is True


def test_a_rootdse_without_a_vendor_is_not_samba():
    info = connection._read_domain_info(_SamDb(ROOT), "dc1", TARGET)
    assert info.dc_vendor is None
    assert info.is_samba is False


class _Conn:
    def __init__(self, vendor: str | None) -> None:
        self.info = types.SimpleNamespace(
            base_dn="DC=example,DC=test", is_samba=connection.is_samba_vendor(vendor)
        )
        self.writes = 0

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        raise AssertionError("not even read on a Windows DC")

    def modify(self, message: Any) -> None:
        self.writes += 1


def test_the_domain_password_policy_is_not_written_on_a_windows_dc():
    """It would be overwritten from the Default Domain Policy, silently."""
    conn = _Conn(None)
    with pytest.raises(Conflict) as caught:
        password_policy.set_password_policy(conn, min_length=8)
    assert caught.value.code == "windows_dc_password_policy"
    assert conn.writes == 0

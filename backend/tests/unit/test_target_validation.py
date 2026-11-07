"""A realm or a host name goes into krb5.conf only when it looks like one.

The process-wide krb5.conf is written from the connection target. Until
0.6.29 the realm from the sign-in form went in unchecked: a realm of
``"A\\nB"`` put a line of the caller's choosing into the file, before anyone
had signed in, and the entry stayed until the restart (reported by Rowie;
MIT Kerberos skipped the line, so nothing broke, but a ``[libdefaults]`` or
``[plugins]`` section could have been opened the same way).

Checked where every target is built — the form, a profile, the default and
the probe all go through ConnectionTarget — and once more in krb5conf as the
last line before the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from samadcon.ad import targets
from samadcon.ad.target import ConnectionTarget
from samadcon.auth.krb5conf import Krb5Configuration
from samadcon.core.errors import InvalidRequest

BAD = [
    "A\nB",
    "A\rB",
    "EXAMPLE.LAN }",
    "EXAMPLE.LAN = {",
    "[libdefaults]",
    "EXAMPLE LAN",
    "-EXAMPLE.LAN",
    "EXAMPLE.LAN\x00",
    "A" * 254,
]


@pytest.mark.parametrize("realm", BAD)
def test_a_realm_that_is_not_a_domain_name_is_refused(realm):
    with pytest.raises(InvalidRequest) as excinfo:
        ConnectionTarget(realm=realm)
    assert excinfo.value.code == "invalid_realm"


@pytest.mark.parametrize("realm", ["MYANTISPAM.LOCAL", "example.lan", "spam-deny.local", "UNKNOWN"])
def test_a_domain_name_is_a_realm(realm):
    assert ConnectionTarget(realm=realm).realm == realm.upper()


@pytest.mark.parametrize("host", BAD)
def test_a_host_that_is_not_a_name_or_an_address_is_refused(host):
    with pytest.raises(InvalidRequest) as excinfo:
        ConnectionTarget(realm="EXAMPLE.LAN", hosts=(host,))
    assert excinfo.value.code == "invalid_host"


@pytest.mark.parametrize(
    "host", ["dc1.example.lan", "zmb-ad", "192.168.1.10", "fd00::10", "2001:db8::1"]
)
def test_names_and_addresses_are_hosts(host):
    assert ConnectionTarget(realm="EXAMPLE.LAN", hosts=(host,)).hosts == (host,)


def test_what_the_probe_returns_is_checked_too():
    target = ConnectionTarget(realm="EXAMPLE.LAN", hosts=("192.168.1.10",))
    with pytest.raises(InvalidRequest) as excinfo:
        target.with_discovery(dc_hostname="dc1\n[plugins]")
    assert excinfo.value.code == "invalid_host"
    with pytest.raises(InvalidRequest) as excinfo:
        target.with_discovery(dns_domain="example.lan\nx")
    assert excinfo.value.code == "invalid_realm"


def test_the_default_target_ignores_a_realm_from_the_form(monkeypatch):
    """The operator chose the default domain; the caller does not get to rename it."""

    class Settings:
        default_target = ConnectionTarget(realm="EXAMPLE.LAN")

    target = targets.resolve_target(Settings(), realm="OTHER.LAN")
    assert target.realm == "EXAMPLE.LAN"


@pytest.mark.parametrize("realm", ["A\nB", "X = {", "[plugins]", "EXAMPLE LAN"])
def test_krb5conf_refuses_what_would_change_the_files_structure(tmp_path: Path, realm):
    configuration = Krb5Configuration(tmp_path / "krb5.conf")
    with pytest.raises(ValueError):
        configuration.ensure_realm(realm)
    with pytest.raises(ValueError):
        configuration.set_default_realm(realm)
    with pytest.raises(ValueError):
        configuration.ensure_realm("EXAMPLE.LAN", (f"dc1{realm}",))
    assert not (tmp_path / "krb5.conf").exists()

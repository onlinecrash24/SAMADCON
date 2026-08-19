"""Connection targets, address parsing, realm derivation and krb5.conf.

These cover the path that makes "type an IP address and sign in" work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from samadcon.ad import discovery
from samadcon.ad.target import ConnectionTarget
from samadcon.auth.krb5conf import Krb5Configuration
from samadcon.config import ServerProfile, Settings
from samadcon.core.errors import InvalidRequest, SamadconError
from samadcon.core.ratelimit import RateLimiter

# ---------------------------------------------------------------------------
# ConnectionTarget
# ---------------------------------------------------------------------------


def test_realm_is_normalised_to_upper_case():
    assert ConnectionTarget(realm="example.lan").realm == "EXAMPLE.LAN"


def test_a_target_without_a_realm_is_rejected():
    with pytest.raises(InvalidRequest) as excinfo:
        ConnectionTarget(realm="")
    assert excinfo.value.code == "missing_realm"


def test_netbios_name_is_the_first_label():
    assert ConnectionTarget(realm="corp.example.lan").netbios_name == "CORP"


def test_kdc_order_prefers_the_address_the_user_gave():
    """The typed address is known to answer; the discovered FQDN may not
    resolve from inside the container."""
    target = ConnectionTarget(realm="EXAMPLE.LAN", hosts=("192.168.1.10",))
    target = target.with_discovery(dc_hostname="dc1.example.lan")
    assert target.kdcs == ("192.168.1.10", "dc1.example.lan")


def test_kdcs_are_deduplicated():
    target = ConnectionTarget(realm="EXAMPLE.LAN", hosts=("dc1.example.lan",))
    target = target.with_discovery(dc_hostname="dc1.example.lan")
    assert target.kdcs == ("dc1.example.lan",)


def test_discovery_overrides_a_placeholder_realm():
    target = ConnectionTarget(realm="UNKNOWN", hosts=("192.168.1.10",))
    enriched = target.with_discovery(realm="example.lan", dns_domain="example.lan")
    assert enriched.realm == "EXAMPLE.LAN"
    assert enriched.dns_domain == "example.lan"
    # The original is untouched — targets are immutable.
    assert target.realm == "UNKNOWN"


def test_display_name_prefers_the_label():
    target = ConnectionTarget(realm="EXAMPLE.LAN", label="Production")
    assert target.display_name == "Production"


def test_display_name_falls_back_to_the_dns_domain():
    target = ConnectionTarget(realm="EXAMPLE.LAN", dns_domain="example.lan")
    assert target.display_name == "example.lan"


def test_describe_is_json_serialisable_and_carries_no_secrets():
    ca_file = Path("etc") / "ca.pem"
    described = ConnectionTarget(
        realm="EXAMPLE.LAN", hosts=("dc1",), ca_file=ca_file
    ).describe()

    assert described["realm"] == "EXAMPLE.LAN"
    assert described["hosts"] == ["dc1"]
    assert described["ca_file"] == str(ca_file)
    # The description goes to the browser and the audit log.
    assert "password" not in json.dumps(described).lower()


# ---------------------------------------------------------------------------
# Address normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("dc1.example.lan", "dc1.example.lan"),
        ("  dc1.example.lan  ", "dc1.example.lan"),
        ("ldap://dc1.example.lan", "dc1.example.lan"),
        ("ldaps://dc1.example.lan", "dc1.example.lan"),
        ("https://dc1.example.lan", "dc1.example.lan"),
        ("dc1.example.lan:636", "dc1.example.lan"),
        ("ldaps://dc1.example.lan:636/", "dc1.example.lan"),
        ("dc1.example.lan.", "dc1.example.lan"),
        ("192.168.1.10", "192.168.1.10"),
        ("192.168.1.10:389", "192.168.1.10"),
        ("[2001:db8::1]", "2001:db8::1"),
    ],
)
def test_host_normalisation(raw: str, expected: str):
    """Administrators paste all of these; all of them must work."""
    assert discovery.normalise_host(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", "dc1 example.lan"])
def test_invalid_addresses_are_rejected(bad: str):
    with pytest.raises(InvalidRequest):
        discovery.normalise_host(bad)


# ---------------------------------------------------------------------------
# Realm derivation from the rootDSE
# ---------------------------------------------------------------------------


class FakeElement(list):
    pass


class FakeMessage(dict):
    def get(self, key, default=None):
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


def rootdse(**attrs) -> FakeMessage:
    message = FakeMessage()
    for name, value in attrs.items():
        message[name] = FakeElement([str(value).encode("utf-8")])
    return message


def test_realm_comes_from_ldap_service_name():
    entry = rootdse(ldapServiceName="example.lan:dc1$@EXAMPLE.LAN")
    assert discovery._realm_from_rootdse(entry, "DC=example,DC=lan") == "EXAMPLE.LAN"


def test_realm_service_name_wins_over_the_base_dn():
    """Domains whose DN does not mirror their realm exist; the service name is
    authoritative."""
    entry = rootdse(ldapServiceName="old.lan:dc1$@NEW.EXAMPLE.LAN")
    assert discovery._realm_from_rootdse(entry, "DC=old,DC=lan") == "NEW.EXAMPLE.LAN"


def test_realm_falls_back_to_the_base_dn():
    assert discovery._realm_from_rootdse(rootdse(), "DC=corp,DC=example,DC=lan") == (
        "CORP.EXAMPLE.LAN"
    )


def test_realm_derivation_fails_loudly_when_nothing_is_known():
    with pytest.raises(SamadconError) as excinfo:
        discovery._realm_from_rootdse(rootdse(), "")
    assert excinfo.value.code == "realm_undetermined"


# ---------------------------------------------------------------------------
# krb5.conf
# ---------------------------------------------------------------------------


def test_realm_block_names_the_kdc(tmp_path: Path):
    """Naming the KDC explicitly is what lets an IP address work."""
    config = Krb5Configuration(tmp_path / "krb5.conf")
    config.ensure_realm("EXAMPLE.LAN", ("192.168.1.10",))

    written = (tmp_path / "krb5.conf").read_text(encoding="utf-8")
    assert "[realms]" in written
    assert "EXAMPLE.LAN = {" in written
    assert "kdc = 192.168.1.10" in written
    assert "admin_server = 192.168.1.10" in written


def test_domain_realm_mapping_is_written(tmp_path: Path):
    config = Krb5Configuration(tmp_path / "krb5.conf")
    config.ensure_realm("EXAMPLE.LAN", ("dc1.example.lan",))

    written = (tmp_path / "krb5.conf").read_text(encoding="utf-8")
    assert ".example.lan = EXAMPLE.LAN" in written
    assert "example.lan = EXAMPLE.LAN" in written


def test_several_realms_coexist(tmp_path: Path):
    """KRB5_CONFIG is process-wide, so one file has to serve every session."""
    config = Krb5Configuration(tmp_path / "krb5.conf")
    config.ensure_realm("ONE.LAN", ("10.0.0.1",))
    config.ensure_realm("TWO.LAN", ("10.0.0.2",))

    written = (tmp_path / "krb5.conf").read_text(encoding="utf-8")
    assert "ONE.LAN = {" in written
    assert "TWO.LAN = {" in written
    assert "kdc = 10.0.0.1" in written
    assert "kdc = 10.0.0.2" in written
    assert config.known_realms() == ["ONE.LAN", "TWO.LAN"]


def test_the_first_realm_becomes_the_default(tmp_path: Path):
    config = Krb5Configuration(tmp_path / "krb5.conf")
    config.ensure_realm("ONE.LAN", ("10.0.0.1",))
    config.ensure_realm("TWO.LAN", ("10.0.0.2",))
    assert "default_realm = ONE.LAN" in (tmp_path / "krb5.conf").read_text(encoding="utf-8")


def test_additional_kdcs_are_merged_not_replaced(tmp_path: Path):
    """A second session may have reached the same domain by another address."""
    config = Krb5Configuration(tmp_path / "krb5.conf")
    config.ensure_realm("EXAMPLE.LAN", ("10.0.0.1",))
    config.ensure_realm("EXAMPLE.LAN", ("10.0.0.2",))

    written = (tmp_path / "krb5.conf").read_text(encoding="utf-8")
    assert "kdc = 10.0.0.1" in written
    assert "kdc = 10.0.0.2" in written


def test_a_known_realm_is_not_rewritten(tmp_path: Path):
    config = Krb5Configuration(tmp_path / "krb5.conf")
    config.ensure_realm("EXAMPLE.LAN", ("10.0.0.1",))
    before = (tmp_path / "krb5.conf").stat().st_mtime_ns

    config.ensure_realm("EXAMPLE.LAN", ("10.0.0.1",))
    assert (tmp_path / "krb5.conf").stat().st_mtime_ns == before


def test_no_temporary_files_are_left_behind(tmp_path: Path):
    config = Krb5Configuration(tmp_path / "krb5.conf")
    config.ensure_realm("EXAMPLE.LAN", ("10.0.0.1",))
    assert [p.name for p in tmp_path.iterdir()] == ["krb5.conf"]


def test_realm_without_kdcs_still_registers(tmp_path: Path):
    """DNS discovery stays available for domains reached by name."""
    config = Krb5Configuration(tmp_path / "krb5.conf")
    config.ensure_realm("EXAMPLE.LAN")

    written = (tmp_path / "krb5.conf").read_text(encoding="utf-8")
    assert "dns_lookup_kdc = true" in written
    assert "EXAMPLE.LAN = {" in written


# ---------------------------------------------------------------------------
# Server profiles
# ---------------------------------------------------------------------------


def _settings_with_profiles(tmp_path: Path, payload: object) -> Settings:
    path = tmp_path / "servers.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return Settings(realm="", servers_file=path, _env_file=None)  # type: ignore[call-arg]


def test_profiles_are_loaded(tmp_path: Path):
    settings = _settings_with_profiles(
        tmp_path,
        [{"id": "prod", "label": "Production", "hosts": ["dc1.example.lan"], "realm": "EXAMPLE.LAN"}],
    )
    profiles = settings.load_profiles()
    assert len(profiles) == 1
    assert profiles[0].id == "prod"
    assert profiles[0].realm == "EXAMPLE.LAN"


def test_a_single_host_string_is_accepted(tmp_path: Path):
    settings = _settings_with_profiles(tmp_path, [{"id": "a", "hosts": "dc1,dc2"}])
    assert settings.load_profiles()[0].hosts == ["dc1", "dc2"]


def test_a_broken_profile_is_skipped_not_fatal(tmp_path: Path):
    """One bad entry must not stop the application from starting."""
    settings = _settings_with_profiles(
        tmp_path, [{"id": "good", "hosts": ["dc1"]}, {"no_id": True}]
    )
    profiles = settings.load_profiles()
    assert [p.id for p in profiles] == ["good"]


def test_invalid_json_yields_no_profiles(tmp_path: Path):
    path = tmp_path / "servers.json"
    path.write_text("{ not json", encoding="utf-8")
    settings = Settings(realm="", servers_file=path, _env_file=None)  # type: ignore[call-arg]
    assert settings.load_profiles() == []


def test_missing_profile_file_is_tolerated(tmp_path: Path):
    settings = Settings(realm="", servers_file=tmp_path / "absent.json", _env_file=None)  # type: ignore[call-arg]
    assert settings.load_profiles() == []


def test_profiles_may_be_wrapped_in_an_object(tmp_path: Path):
    settings = _settings_with_profiles(tmp_path, {"servers": [{"id": "a", "hosts": ["dc1"]}]})
    assert [p.id for p in settings.load_profiles()] == ["a"]


def test_no_default_target_without_a_realm():
    assert Settings(realm="", _env_file=None).default_target is None  # type: ignore[call-arg]


def test_default_target_from_the_configured_realm():
    settings = Settings(realm="example.lan", dc_hosts=["dc1"], _env_file=None)  # type: ignore[call-arg]
    target = settings.default_target
    assert target is not None
    assert target.realm == "EXAMPLE.LAN"
    assert target.hosts == ("dc1",)


def test_profile_realm_is_uppercased(tmp_path: Path):
    profile = ServerProfile(id="a", hosts=["dc1"], realm="example.lan")
    assert profile.realm == "EXAMPLE.LAN"


# ---------------------------------------------------------------------------
# Resolving the target to sign in against
# ---------------------------------------------------------------------------


@pytest.fixture
def probed(monkeypatch):
    """Every probe answers, recording which host was asked."""
    from samadcon.ad import targets

    asked: list[str] = []

    def _probe(host, settings, **kwargs):
        asked.append(host)
        return discovery.ServerIdentity(
            host=host,
            dc_hostname="dc1.example.lan",
            # A resolver that serves the domain. The interesting case for this
            # test is the name, not the records.
            srv_lookups=[{"query": "_ldap._tcp.dc._msdcs.example.lan", "found": 1}],
            realm="EXAMPLE.LAN",
            dns_domain="example.lan",
            base_dn="DC=example,DC=lan",
            config_dn=None,
            transport="ldap",
            supports_gssapi=True,
            is_domain_controller=True,
            ldaps_reachable=True,
            ldaps_certificate_trusted=False,
            dc_hostname_resolves=True,
            domain_functional_level=None,
            forest_functional_level=None,
        )

    monkeypatch.setattr(targets.discovery, "probe", _probe)
    return asked


def test_the_configured_domain_learns_the_dc_name(probed):
    """The bug this covers cost an evening.

    A container configured with an IP — the documented way — signed in fine
    through the typed-address path and not at all through its own configured
    domain, because only that path skipped the probe. Kerberos issues tickets
    for ldap/<hostname>, there is no such principal for a bare address, and
    the failure arrives as NT_STATUS_INVALID_PARAMETER at bind time with
    nothing pointing at the name.
    """
    from samadcon.ad import targets

    settings = Settings(realm="example.lan", dc_hosts=["192.168.1.10"], _env_file=None)  # type: ignore[call-arg]
    target = targets.resolve_target(settings)

    assert probed == ["192.168.1.10"]
    assert target.dc_hostname == "dc1.example.lan"


def test_a_probe_that_fails_does_not_block_the_configured_domain(monkeypatch):
    """The realm is already known, so a sign-in that might still work is not
    refused over it — it simply goes ahead without the name."""
    from samadcon.ad import targets

    def _fail(host, settings, **kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(targets.discovery, "probe", _fail)

    settings = Settings(realm="example.lan", dc_hosts=["192.168.1.10"], _env_file=None)  # type: ignore[call-arg]
    target = targets.resolve_target(settings)

    assert target.realm == "EXAMPLE.LAN"
    assert target.dc_hostname is None


def test_a_domain_discovered_by_dns_is_not_probed(probed):
    """Without a configured host there is nothing to ask; the SRV lookup at
    connect time returns names already."""
    from samadcon.ad import targets

    settings = Settings(realm="example.lan", dc_hosts=[], _env_file=None)  # type: ignore[call-arg]
    target = targets.resolve_target(settings)

    assert probed == []
    assert target.hosts == ()


def test_only_addresses_are_reported_as_such():
    """The error that says "check the ports" is wrong when no name was ever
    available, and sends the reader to look at ports that are fine."""
    from samadcon.ad.connection import _is_address

    assert _is_address("192.168.1.10")
    assert _is_address("[2001:db8::1]")
    assert not _is_address("dc1.example.lan")
    assert not _is_address("dc1")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_requests_below_the_limit_pass():
    limiter = RateLimiter(max_events=3, window_seconds=60)
    for _ in range(3):
        limiter.check("10.0.0.1")


def test_the_limit_is_enforced_per_key():
    limiter = RateLimiter(max_events=2, window_seconds=60)
    limiter.check("10.0.0.1")
    limiter.check("10.0.0.1")

    with pytest.raises(SamadconError) as excinfo:
        limiter.check("10.0.0.1")
    assert excinfo.value.code == "rate_limited"
    assert excinfo.value.status_code == 429
    assert excinfo.value.context["retry_after_seconds"] > 0

    # A different caller is unaffected.
    limiter.check("10.0.0.2")


def test_the_window_slides():
    limiter = RateLimiter(max_events=1, window_seconds=0.05)
    limiter.check("a")
    import time

    time.sleep(0.08)
    limiter.check("a")

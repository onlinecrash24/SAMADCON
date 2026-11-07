"""Configuration parsing.

The DC list is the interesting case: docker compose passes it as a plain
comma-separated string, and pydantic-settings would otherwise try to read it
as JSON and fail at startup.
"""

from __future__ import annotations

import pytest

from samadcon.config import Settings


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # An .env file in the working directory must not leak into the test.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_dc_hosts_from_a_comma_separated_env_var(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(
        monkeypatch,
        SAMADCON_REALM="example.lan",
        SAMADCON_DC_HOSTS="dc1.example.lan,dc2.example.lan",
    )
    assert settings.dc_hosts == ["dc1.example.lan", "dc2.example.lan"]


def test_dc_hosts_tolerates_spaces_and_trailing_commas(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(
        monkeypatch,
        SAMADCON_REALM="example.lan",
        SAMADCON_DC_HOSTS=" dc1.example.lan , dc2.example.lan ,",
    )
    assert settings.dc_hosts == ["dc1.example.lan", "dc2.example.lan"]


def test_empty_dc_hosts_means_dns_discovery(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_DC_HOSTS="")
    assert settings.dc_hosts == []


def test_single_dc_host(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(
        monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_DC_HOSTS="dc1.example.lan"
    )
    assert settings.dc_hosts == ["dc1.example.lan"]


def test_realm_is_uppercased(monkeypatch: pytest.MonkeyPatch):
    assert _settings(monkeypatch, SAMADCON_REALM="example.lan").realm == "EXAMPLE.LAN"


def test_netbios_name_falls_back_to_the_first_realm_label(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_WORKGROUP="")
    assert settings.netbios_name == "EXAMPLE"


def test_explicit_workgroup_wins(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_WORKGROUP="corp")
    assert settings.netbios_name == "CORP"


def test_base_dn_is_derived_from_the_realm(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(monkeypatch, SAMADCON_REALM="ad.example.lan")
    assert settings.base_dn == "DC=ad,DC=example,DC=lan"


def test_tls_verification_is_on_by_default(monkeypatch: pytest.MonkeyPatch):
    assert _settings(monkeypatch, SAMADCON_REALM="example.lan").tls_verify_peer == "ca_and_name"


def test_dev_mode_does_not_disable_tls_verification(monkeypatch: pytest.MonkeyPatch):
    """Only an explicit opt-out may turn certificate checking off."""
    settings = _settings(monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_DEV_MODE="1")
    assert settings.tls_verify_peer == "ca_and_name"


def test_insecure_flag_disables_verification(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_LDAP_INSECURE="1")
    assert settings.tls_verify_peer == "no_check"


@pytest.mark.parametrize("variable", ["SAMADCON_LDAP_CA_FILE", "SAMADCON_SERVERS_FILE"])
def test_empty_path_variables_are_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, variable: str
):
    """docker compose substitutes unset variables with an empty string.

    Without normalisation that becomes Path("."), and SAMADCON would hand the
    working directory to Samba as a CA bundle.
    """
    settings = _settings(monkeypatch, SAMADCON_REALM="example.lan", **{variable: ""})
    assert settings.ldap_ca_file is None
    assert settings.servers_file is None


def test_a_real_path_still_works(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(
        monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_LDAP_CA_FILE="/etc/samadcon/ca/ca.pem"
    )
    assert settings.ldap_ca_file is not None
    assert settings.ldap_ca_file.name == "ca.pem"


def test_whitespace_only_path_is_unset(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_LDAP_CA_FILE="   ")
    assert settings.ldap_ca_file is None


def test_log_level_is_uppercased(monkeypatch: pytest.MonkeyPatch):
    assert _settings(monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_LOG_LEVEL="debug").log_level == "DEBUG"


# --- Reserved names and protected OUs ------------------------------------------


def test_reserved_names_and_protected_ous_are_empty_by_default(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(monkeypatch, SAMADCON_REALM="example.lan")
    assert settings.reserved_prefixes == []
    assert settings.reserved_names == []
    assert settings.protected_ous == []


def test_reserved_prefixes_and_names_are_split_trimmed_and_lowercased(
    monkeypatch: pytest.MonkeyPatch,
):
    settings = _settings(
        monkeypatch,
        SAMADCON_REALM="example.lan",
        SAMADCON_RESERVED_PREFIXES=" Havora- , svc_ ,",
        SAMADCON_RESERVED_NAMES="havora, Info@Example.LAN",
    )
    assert settings.reserved_prefixes == ["havora-", "svc_"]
    assert settings.reserved_names == ["havora", "info@example.lan"]


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("SAMADCON_RESERVED_PREFIXES", "havora -"),
        ("SAMADCON_RESERVED_PREFIXES", "hav\tora-"),
        ("SAMADCON_RESERVED_NAMES", "svc backup"),
        ("SAMADCON_RESERVED_NAMES", "svc\x07"),
    ],
)
def test_a_reserved_entry_with_a_space_or_control_character_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=variable):
        _settings(monkeypatch, SAMADCON_REALM="example.lan", **{variable: value})


def test_protected_ous_are_split_on_semicolons_because_dns_carry_commas(
    monkeypatch: pytest.MonkeyPatch,
):
    settings = _settings(
        monkeypatch,
        SAMADCON_REALM="example.lan",
        SAMADCON_PROTECTED_OUS=r" OU=Havora,DC=example,DC=lan ; OU=Service\, Intern,DC=example,DC=lan;",
    )
    assert settings.protected_ous == [
        "OU=Havora,DC=example,DC=lan",
        r"OU=Service\, Intern,DC=example,DC=lan",
    ]


@pytest.mark.parametrize("value", ["Havora", "OU=Havora,example", "OU=,DC=example", "=x,DC=lan"])
def test_a_protected_ou_that_is_not_a_dn_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, value: str
):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="SAMADCON_PROTECTED_OUS"):
        _settings(monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_PROTECTED_OUS=value)


# The same check as for a target (test_target_validation.py), at start-up:
# these values go into krb5.conf and smb.conf, and a typo should stop the
# start with a message, not a broken file.


@pytest.mark.parametrize("value", ["EXAMPLE LAN", "EXAMPLE.LAN}", "[libdefaults]"])
def test_a_realm_that_is_not_a_domain_name_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, value: str
):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="SAMADCON_REALM"):
        _settings(monkeypatch, SAMADCON_REALM=value)


@pytest.mark.parametrize("value", ["dc1 dc2", "dc1;dc2", "dc1}"])
def test_a_dc_host_that_is_not_a_name_or_address_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, value: str
):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="SAMADCON_DC_HOSTS"):
        _settings(monkeypatch, SAMADCON_REALM="example.lan", SAMADCON_DC_HOSTS=value)


def test_an_empty_realm_is_still_fine(monkeypatch: pytest.MonkeyPatch):
    assert _settings(monkeypatch, SAMADCON_REALM="").realm == ""


@pytest.mark.parametrize(
    "profile", [{"id": "a", "realm": "X Y"}, {"id": "a", "hosts": ["dc1 }"]}]
)
def test_a_profile_with_a_broken_realm_or_host_is_refused(profile):
    from pydantic import ValidationError

    from samadcon.config import ServerProfile

    with pytest.raises(ValidationError):
        ServerProfile(**profile)

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

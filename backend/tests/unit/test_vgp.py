"""Samba's own group policies.

Everything asserted here about element names and paths is taken from the
modules that consume these files — ``samba/gp/vgp_*_ext.py`` — and from
``samba-tool gpo manage``, which writes them. That is a better reference than
the byte dumps the Windows formats needed: the reader is open source, so the
contract can be read rather than reconstructed.
"""

from __future__ import annotations

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import vgp


def roundtrip(policy: str, entries: list[dict]) -> list[dict]:
    return vgp.parse(policy, vgp.render(policy, entries).decode("utf-8"))


# ---------------------------------------------------------------------------
# Where the files go
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("policy", "path"),
    [
        ("sudoers", "MACHINE\\VGP\\VTLA\\Sudo\\SudoersConfiguration\\manifest.xml"),
        ("symlink", "MACHINE\\VGP\\VTLA\\Unix\\Symlink\\manifest.xml"),
        ("motd", "MACHINE\\VGP\\VTLA\\Unix\\MOTD\\manifest.xml"),
        ("issue", "MACHINE\\VGP\\VTLA\\Unix\\Issue\\manifest.xml"),
        ("openssh", "MACHINE\\VGP\\VTLA\\SshCfg\\SshD\\manifest.xml"),
        ("access_allow", "MACHINE\\VGP\\VTLA\\VAS\\HostAccessControl\\Allow\\manifest.xml"),
        ("access_deny", "MACHINE\\VGP\\VTLA\\VAS\\HostAccessControl\\Deny\\manifest.xml"),
    ],
)
def test_each_policy_has_the_path_samba_reads(policy, path):
    """A manifest one directory off is a policy nothing applies, and nothing
    reports that either."""
    assert vgp.kind_for(policy).path == path


def test_an_unknown_policy_is_refused():
    with pytest.raises(InvalidRequest) as raised:
        vgp.kind_for("firewall")

    assert raised.value.code == "unknown_vgp_policy"


# ---------------------------------------------------------------------------
# The manifest's shape
# ---------------------------------------------------------------------------


def test_the_declaration_matches_the_one_samba_tool_writes():
    """ElementTree writes single quotes. Matching it keeps a file we wrote and
    one `samba-tool gpo manage` wrote comparable line for line."""
    raw = vgp.render("symlink", [{"source": "/etc/motd", "target": "/tmp/x"}])

    assert raw.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")


def test_the_envelope_is_the_one_the_reader_expects():
    text = vgp.render("symlink", []).decode("utf-8")

    assert "<vgppolicy>" in text
    assert "<policysetting>" in text
    assert "<version>1</version>" in text
    assert "<data" in text


def test_sudoers_carries_its_apply_mode_and_plugin_flag():
    """Both are in samba-tool's writer and in no other policy."""
    text = vgp.render("sudoers", []).decode("utf-8")

    assert "<apply_mode>merge</apply_mode>" in text
    assert "<load_plugin>true</load_plugin>" in text


def test_only_sudoers_has_an_apply_mode():
    assert "apply_mode" not in vgp.render("symlink", []).decode("utf-8")


# ---------------------------------------------------------------------------
# Sudo rights
# ---------------------------------------------------------------------------


def test_a_sudo_rule_survives_the_round_trip():
    entries = [
        {
            "command": "ALL",
            "user": "ALL",
            "principals": ["alice", "DOMAIN\\admins"],
            "password": False,
        }
    ]

    assert roundtrip("sudoers", entries) == entries


def test_asking_for_a_password_is_the_presence_of_an_element():
    """Samba reads it the other way round — no <password> means none is asked
    for — so the flag has to mean what its name says or the editor's checkbox
    does the opposite of its label."""
    with_password = vgp.render("sudoers", [{"command": "ALL", "password": True}]).decode("utf-8")
    without = vgp.render("sudoers", [{"command": "ALL", "password": False}]).decode("utf-8")

    assert "<password" in with_password
    assert "<password" not in without

    assert vgp.parse("sudoers", with_password)[0]["password"] is True
    assert vgp.parse("sudoers", without)[0]["password"] is False


def test_several_principals_land_in_one_listelement():
    text = vgp.render(
        "sudoers", [{"command": "ALL", "user": "ALL", "principals": ["a", "b"]}]
    ).decode("utf-8")

    assert text.count("<listelement>") == 1
    assert text.count("<principal>") == 2


# ---------------------------------------------------------------------------
# The rest of the first wave
# ---------------------------------------------------------------------------


def test_a_symlink_survives_the_round_trip():
    entries = [{"source": "/etc/motd", "target": "/tmp/motd"}]

    assert roundtrip("symlink", entries) == entries


@pytest.mark.parametrize("policy", ["motd", "issue"])
def test_a_banner_is_one_block_of_text(policy):
    parsed = roundtrip(policy, [{"text": "Willkommen\nZutritt nur für Befugte\n"}])

    assert parsed[0]["text"] == "Willkommen\nZutritt nur für Befugte\n"


@pytest.mark.parametrize("policy", ["motd", "issue"])
def test_a_second_block_of_text_is_refused_rather_than_dropped(policy):
    """The manifest holds one <text>. Writing two would keep the first and
    lose the other without a word."""
    with pytest.raises(InvalidRequest) as raised:
        vgp.render(policy, [{"text": "one"}, {"text": "two"}])

    assert raised.value.code == "vgp_single_entry"


def test_ssh_settings_survive_the_round_trip():
    entries = [{"key": "PermitRootLogin", "value": "no"}, {"key": "X11Forwarding", "value": "no"}]

    assert roundtrip("openssh", entries) == entries


def test_the_ssh_section_is_left_unnamed():
    """Samba skips a configsection whose sectionname has text, so the settings
    it reads are the ones in the unnamed section — but the element still has
    to be there."""
    text = vgp.render("openssh", [{"key": "a", "value": "b"}]).decode("utf-8")

    assert "<sectionname />" in text or "<sectionname/>" in text


@pytest.mark.parametrize("policy", ["access_allow", "access_deny"])
def test_a_host_access_entry_survives_the_round_trip(policy):
    entries = [{"name": "alice", "domain": "example.lan"}]

    assert roundtrip(policy, entries) == entries


# ---------------------------------------------------------------------------
# Reading what somebody else wrote
# ---------------------------------------------------------------------------


def test_an_empty_manifest_reads_as_no_entries():
    assert vgp.parse("symlink", vgp.render("symlink", []).decode("utf-8")) == []


def test_a_manifest_that_is_not_xml_reads_as_nothing():
    """A read of a file another tool wrote badly should not take the editor
    down with it."""
    assert vgp.parse("symlink", "this is not xml") == []


def test_a_missing_element_reads_as_empty_rather_than_raising():
    """Samba's own readers call .text on whatever they find; a manifest from
    another tool is still worth showing."""
    text = (
        "<vgppolicy><policysetting><data>"
        "<file_properties><source>/etc/motd</source></file_properties>"
        "</data></policysetting></vgppolicy>"
    )

    assert vgp.parse("symlink", text) == [{"source": "/etc/motd", "target": ""}]


# ---------------------------------------------------------------------------
# Every kind must be handled deliberately
# ---------------------------------------------------------------------------


def test_every_kind_has_a_reader_and_a_writer():
    """The dispatch used to be a chain of ``if kind.id == ...`` ending in a
    fallback, so a kind added to KINDS and forgotten was read as an access
    list and written as `adobject` elements — silently, onto a share every
    domain member reads. This is the check that makes that impossible.
    """
    assert set(vgp.READERS) == set(vgp.KINDS)
    assert set(vgp.WRITERS) == set(vgp.KINDS)

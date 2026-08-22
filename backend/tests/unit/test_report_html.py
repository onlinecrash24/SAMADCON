"""The attachable report, and the line between its words and the domain's.

It goes to a ticket or a change record, so it is written in the language the
console is being used in. What it must not translate is anything the domain
said: a registry key, a section name, an attribute. Translating those would
invent a second name for something that has exactly one.
"""

from __future__ import annotations

from typing import Any

from samadcon.gpo import report


def half(**buckets: Any) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "registry": [],
        "registry_count": 0,
        "security": {},
        "scripts": {},
        "redirection": {},
        "preferences": [],
        "vgp": [],
        "other_files": [],
    }
    empty.update(buckets)
    return empty


def built(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "gpo": {
            "guid": "{AAAA0000-0000-0000-0000-000000000001}",
            "display_name": "Baseline",
            "path": "\\\\example.lan\\sysvol\\example.lan\\Policies\\{AAAA0000}",
            "machine_version": 3,
            "user_version": 0,
            "machine_enabled": True,
            "user_enabled": False,
        },
        "status": {},
        "machine": half(),
        "user": half(),
        "unreadable": [],
        "empty": True,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Its own words
# ---------------------------------------------------------------------------


def test_english_is_what_it_writes_by_default() -> None:
    html = report.to_html(built())

    assert "<html lang=\"en\"" in html
    assert "Identifier" in html
    assert "This policy holds no settings." in html


def test_german_reaches_the_labels_and_the_lang_attribute() -> None:
    html = report.to_html(built(), "de")

    assert "<html lang=\"de\"" in html
    assert "Kennung" in html
    assert "Diese Richtlinie enthält keine Einstellungen." in html
    assert "Identifier" not in html


def test_the_half_heading_is_a_template_and_not_a_join() -> None:
    """"Computer configuration" in English is one word in German. Sticking two
    labels together would produce "Computer Konfiguration"."""
    machine = half(registry=[{"key": "Software\\Policies", "values": []}])

    assert "Computer configuration" in report.to_html(built(machine=machine, empty=False))
    assert "Computerkonfiguration" in report.to_html(built(machine=machine, empty=False), "de")


def test_a_language_we_have_no_table_for_falls_back_to_english() -> None:
    """A missing translation should cost a reader familiarity, not the report."""
    html = report.to_html(built(), "fr")

    assert "Identifier" in html


# ---------------------------------------------------------------------------
# The domain's words, which are not ours to translate
# ---------------------------------------------------------------------------


def test_a_registry_key_is_passed_through_untouched() -> None:
    machine = half(
        registry=[
            {
                "key": "Software\\Policies\\Samba",
                "values": [{"value": "ldap timeout", "type": "REG_DWORD", "display": "15"}],
            }
        ]
    )
    html = report.to_html(built(machine=machine, empty=False), "de")

    assert "Software\\Policies\\Samba" in html
    assert "ldap timeout" in html
    assert "REG_DWORD" in html


def test_a_security_section_keeps_the_name_gpmc_wrote() -> None:
    """[System Access] is what is in the file. A German heading over it would
    be a second name for a section that has one."""
    machine = half(security={"System Access": [{"name": "MinimumPasswordLength", "value": "12"}]})
    html = report.to_html(built(machine=machine, empty=False), "de")

    assert "System Access" in html
    assert "MinimumPasswordLength" in html
    # Ours, though — the heading above it is the report speaking.
    assert "Sicherheitseinstellungen" in html


def test_an_empty_samba_manifest_says_so_in_the_reader_s_language() -> None:
    """A heading with nothing under it reads as a report that gave up, which
    is why the sentence exists at all."""
    machine = half(vgp=[{"path": "x\\manifest.xml", "name": "", "entries": []}])
    html = report.to_html(built(machine=machine, empty=False), "de")

    assert "Keine Einträge." in html
    assert "Samba-Richtlinie" in html

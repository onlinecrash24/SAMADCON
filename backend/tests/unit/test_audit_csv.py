"""The advanced audit policy, audit.csv.

Every assertion about the format comes from the file the German GPMC wrote for
the reference GPO "SAMADCON-Referenz-Audit" (tests/data/audit.csv): UTF-8
without a byte-order mark, CRLF, seven columns, header and texts in German.
"""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import audit_csv, cse, report
from tests.conftest import reference

GPMC_REFERENCE = reference("audit.csv")

LOGON = "{0cce9215-69ae-11d9-bed3-505054503030}"
USER_ACCOUNT_MANAGEMENT = "{0cce9235-69ae-11d9-bed3-505054503030}"
ACCOUNT_LOCKOUT = "{0cce9217-69ae-11d9-bed3-505054503030}"


def lines(raw: bytes) -> list[str]:
    return raw.decode("utf-8").split("\r\n")


# ---------------------------------------------------------------------------
# Reading and writing the reference
# ---------------------------------------------------------------------------


def test_our_output_matches_the_file_gpmc_wrote():
    assert audit_csv.render(audit_csv.parse(GPMC_REFERENCE)) == GPMC_REFERENCE


def test_the_settings_are_read_by_guid_and_number():
    """The header is German here and English elsewhere; the columns are not."""
    assert audit_csv.parse(GPMC_REFERENCE).settings() == {
        USER_ACCOUNT_MANAGEMENT: 1,
        LOGON: 3,
    }


def test_setting_what_is_there_writes_the_same_bytes():
    """Our row for a subcategory is GPMC's row: label, inclusion text, value."""
    parsed = audit_csv.parse(GPMC_REFERENCE)
    again = audit_csv.apply(parsed, {USER_ACCOUNT_MANAGEMENT: 1, LOGON: 3})
    assert audit_csv.render(again) == GPMC_REFERENCE


def test_no_byte_order_mark_and_crlf():
    raw = audit_csv.render(audit_csv.parse(None))
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\r\n")


# ---------------------------------------------------------------------------
# Changing it
# ---------------------------------------------------------------------------


def test_a_new_subcategory_is_written_in_the_file_s_language():
    changed = audit_csv.apply(audit_csv.parse(GPMC_REFERENCE), {ACCOUNT_LOCKOUT: 2})
    assert lines(audit_csv.render(changed))[3] == (
        ",System,Kontosperrung überwachen,{0cce9217-69ae-11d9-bed3-505054503030},Fehler,,2"
    )


def test_not_configured_removes_the_row_and_keeps_the_others():
    changed = audit_csv.apply(audit_csv.parse(GPMC_REFERENCE), {USER_ACCOUNT_MANAGEMENT: None})
    assert changed.settings() == {LOGON: 3}


def test_no_auditing_is_a_row_with_zero_not_an_absent_one():
    """Not configured leaves the subcategory to whatever else sets it; no
    auditing switches it off. They are different, and so are their files."""
    changed = audit_csv.apply(audit_csv.parse(GPMC_REFERENCE), {LOGON: 0})
    assert changed.settings()[LOGON] == 0
    assert "Anmelden überwachen" in audit_csv.render(changed).decode("utf-8")


def test_a_row_this_code_does_not_edit_is_kept():
    """An option row, as GPMC writes for "shut down if unable to log audits"."""
    option = b",System,Option:CrashOnAuditFail,,Aktiviert,,1\r\n"
    raw = GPMC_REFERENCE + option
    changed = audit_csv.apply(audit_csv.parse(raw), {LOGON: 1})
    assert audit_csv.render(changed).endswith(option)


def test_a_new_file_gets_the_english_header_and_texts():
    raw = audit_csv.render(audit_csv.apply(audit_csv.parse(None), {LOGON: 3}))
    assert lines(raw)[:2] == [
        "Machine Name,Policy Target,Subcategory,Subcategory GUID,"
        "Inclusion Setting,Exclusion Setting,Setting Value",
        ",System,Audit Logon,{0cce9215-69ae-11d9-bed3-505054503030},Success and Failure,,3",
    ]


def test_an_upper_case_guid_is_accepted():
    changed = audit_csv.apply(audit_csv.parse(None), {LOGON.upper(): 1})
    assert changed.settings() == {LOGON: 1}


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"{00000000-0000-0000-0000-000000000000}": 1}, "unknown_audit_subcategory"),
        ({LOGON: 4}, "invalid_audit_value"),
    ],
)
def test_what_is_not_a_setting_is_refused(changes, code):
    with pytest.raises(InvalidRequest) as caught:
        audit_csv.apply(audit_csv.parse(None), changes)
    assert caught.value.code == code


# ---------------------------------------------------------------------------
# The catalogue, from auditpol
# ---------------------------------------------------------------------------


def test_the_catalogue_is_what_auditpol_listed():
    """60 subcategories in 9 categories on the Windows 11 it was read from."""
    catalogue = audit_csv.describe_catalogue()
    guids = [sub["guid"] for cat in catalogue["categories"] for sub in cat["subcategories"]]
    assert len(catalogue["categories"]) == 9
    assert len(guids) == 60 == len(set(guids))


def test_the_measured_subcategories_sit_where_windows_puts_them():
    categories = {
        cat["en"]: {sub["guid"] for sub in cat["subcategories"]}
        for cat in audit_csv.describe_catalogue()["categories"]
    }
    assert LOGON in categories["Logon/Logoff"]
    assert USER_ACCOUNT_MANAGEMENT in categories["Account Management"]


def test_windows_html_entity_is_not_carried_into_the_name():
    names = [german for german, _ in audit_csv.SUBCATEGORIES.values()]
    assert "Plug & Play-Ereignisse" in names
    assert not any("&amp;" in name for name in names)


# ---------------------------------------------------------------------------
# The report, and the registration it expects
# ---------------------------------------------------------------------------


class Share:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def read(self, path: str) -> bytes:
        return self.raw


def test_the_report_names_the_subcategories():
    found = report._read_audit(Share(GPMC_REFERENCE), "x\\audit.csv", [])
    assert [(item["de"], item["value"]) for item in found] == [
        ("Anmelden", 3),
        ("Benutzerkontenverwaltung", 1),
    ]


def test_the_audit_extension_is_expected_not_surplus():
    """audit.csv was an unknown file to the report, so the pair GPMC registers
    for it read as surplus — and reconciling would have removed it, leaving
    every client ignoring the policy."""
    half: dict[str, Any] = report._empty_half()
    half["audit"] = report._read_audit(Share(GPMC_REFERENCE), "x\\audit.csv", [])

    assert (cse.AUDIT_CSE, cse.AUDIT_TOOL) in report.required_pairs(half)

    registered = f"[{cse.braced(cse.AUDIT_CSE)}{cse.braced(cse.AUDIT_TOOL)}]"
    differences = report.registration_differences(
        {"machine_extensions": registered, "user_extensions": ""},
        {"machine": half, "user": report._empty_half()},
    )
    assert differences["machine"]["surplus"] == []


# ---------------------------------------------------------------------------
# Writing to a GPO
# ---------------------------------------------------------------------------


class Sysvol:
    def __init__(self, raw: bytes | None) -> None:
        self.raw = raw
        self.written: list[tuple[str, bytes]] = []

    def resolve(self, base: str, relative: str) -> str | None:
        return None if self.raw is None else f"{base}\\{relative}"

    def read(self, path: str) -> bytes:
        assert self.raw is not None
        return self.raw

    def makedirs(self, path: str) -> None:
        pass

    def write(self, path: str, data: bytes) -> None:
        self.written.append((path, data))


@pytest.fixture
def gpo(monkeypatch):
    calls: dict[str, Any] = {"registered": [], "bumped": []}
    share = Sysvol(GPMC_REFERENCE)
    monkeypatch.setattr(
        audit_csv.container,
        "get_gpo",
        lambda conn, dn: {
            "version": 7,
            "path": r"\\example.lan\sysvol\example.lan\Policies\{X}",
            "display_name": "Test",
        },
    )
    monkeypatch.setattr(audit_csv.sysvol, "sysvol_for", lambda conn: share)
    monkeypatch.setattr(
        audit_csv.cse, "register", lambda conn, dn, half, c, t: calls["registered"].append((half, c, t))
    )
    monkeypatch.setattr(
        audit_csv.container,
        "bump_version",
        lambda conn, dn, **kw: calls["bumped"].append(kw) or {"version": 8},
    )
    return share, calls


def test_a_change_is_written_registered_and_counted(gpo):
    share, calls = gpo
    result = audit_csv.write(object(), "CN={X}", {ACCOUNT_LOCKOUT: 1}, expected_version=7)

    assert result == {"dn": "CN={X}", "changed": True, "version": 8}
    assert share.written[0][0].endswith(r"Machine\Microsoft\Windows NT\Audit\audit.csv")
    assert calls["registered"] == [("Machine", cse.AUDIT_CSE, cse.AUDIT_TOOL)]
    assert calls["bumped"] == [{"machine_changed": True, "user_changed": False}]


def test_nothing_changed_writes_nothing(gpo):
    share, calls = gpo
    result = audit_csv.write(object(), "CN={X}", {LOGON: 3})

    assert result["changed"] is False
    assert share.written == [] and calls["registered"] == [] and calls["bumped"] == []


def test_a_stale_form_is_refused(gpo):
    from samadcon.core.errors import Conflict

    with pytest.raises(Conflict):
        audit_csv.write(object(), "CN={X}", {LOGON: 1}, expected_version=6)

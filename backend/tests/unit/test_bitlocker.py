"""BitLocker recovery keys: listed without the secret, read one at a time.

Windows stores each recovery password as a child of the computer account. The
listing is part of the normal detail view and must never carry a password; the
password is read by its own, audited call, and only the one asked for. The
attribute is confidential — the directory hands out an empty value to anyone
without the right, and that must read as "not allowed", not as a key without a
password.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest

from samadcon.ad import computers
from samadcon.api.v1.computers import KeyIdQuery
from samadcon.core.audit import REDACTED, redact
from samadcon.core.errors import NotFound, PermissionDenied

BASE = "DC=example,DC=test"
SCHEMA = f"CN=Schema,CN=Configuration,{BASE}"
COMPUTER = f"CN=PC01,OU=Clients,{BASE}"
KEY_A = "1A2B3C4D-1111-2222-3333-444455556666"
KEY_B = "9F8E7D6C-AAAA-BBBB-CCCC-DDDDEEEEFFFF"
PASSWORD_A = "111111-222222-333333-444444-555555-666666-777777-888888"


def key(computer: str, key_id: str, created: str, password: str | None) -> dict[str, Any]:
    dn = f"CN=2026-09-0{created}T10:00:00-00:00{{{key_id}}},{computer}"
    entry: dict[str, Any] = {
        "distinguishedName": [dn.encode()],
        "name": [dn.split(",")[0][3:].encode()],
        "msFVE-RecoveryGuid": [uuid.UUID(key_id).bytes_le],
        "msFVE-VolumeGuid": [uuid.uuid4().bytes_le],
        "whenCreated": [f"2026090{created}100000.0Z".encode()],
    }
    if password is not None:
        entry["msFVE-RecoveryPassword"] = [password.encode()]
    return entry


def _only(entry: dict[str, Any], attrs: list[str] | None) -> dict[str, Any]:
    """What ldb returns for *attrs*: those, plus the DN, which every entry carries."""
    keep = {"distinguishedName", *(attrs or entry)}
    return {k: v for k, v in entry.items() if k in keep}


class Directory:
    """A computer with recovery children, and a record of what was asked for."""

    class Info:
        base_dn = BASE
        schema_dn = SCHEMA

    def __init__(self, keys: list[dict[str, Any]], *, schema_knows_class: bool = True) -> None:
        self.info = Directory.Info()
        self.keys = keys
        self.schema_knows_class = schema_knows_class
        self.requested: list[list[str] | None] = []
        self.filters: list[str] = []

    def exists(self, dn: str) -> bool:
        return dn == COMPUTER

    def search(self, base: str, *, scope: int, expression: str, attrs=None, max_results=0):
        self.requested.append(attrs)
        self.filters.append(expression)
        if base == SCHEMA:
            return [{"lDAPDisplayName": [b"msFVE-RecoveryInformation"]}] if self.schema_knows_class else []
        return [_only(entry, attrs) for entry in self.keys]

    def get(self, dn: str, attrs=None):
        self.requested.append(attrs)
        for entry in self.keys:
            if entry["distinguishedName"][0].decode() == dn:
                return _only(entry, attrs)
        return None


def directory(**kwargs: Any) -> Directory:
    return Directory(
        [key(COMPUTER, KEY_A, "1", PASSWORD_A), key(COMPUTER, KEY_B, "5", "999999-" * 7 + "000000")],
        **kwargs,
    )


def test_the_listing_carries_ids_and_dates_but_no_password():
    conn = directory()
    result = computers.bitlocker_keys(conn, COMPUTER)

    assert result["available"] is True
    assert [k["key_id"] for k in result["keys"]] == [KEY_B, KEY_A]  # newest first
    assert result["keys"][1]["key_id_short"] == "1A2B3C4D"
    assert "RecoveryPassword" not in repr(result)
    # Not merely dropped afterwards: never asked of the directory.
    assert all(attrs and "msFVE-RecoveryPassword" not in attrs for attrs in conn.requested)


def test_a_schema_without_the_class_is_not_the_same_as_no_keys():
    result = computers.bitlocker_keys(directory(schema_knows_class=False), COMPUTER)
    assert result == {"available": False, "keys": []}


def test_a_missing_computer_is_not_found():
    with pytest.raises(NotFound):
        computers.bitlocker_keys(directory(), f"CN=NOPE,{BASE}")


def test_reveal_reads_the_one_password_asked_for():
    conn = directory()
    result = computers.read_bitlocker_key(conn, COMPUTER, "{" + KEY_A.lower() + "}")

    assert result["recovery_password"] == PASSWORD_A
    assert result["key_id"] == KEY_A
    reads = [attrs for attrs in conn.requested if attrs and "msFVE-RecoveryPassword" in attrs]
    assert reads == [["msFVE-RecoveryPassword"]]


def test_an_unknown_key_id_is_not_found():
    with pytest.raises(NotFound) as caught:
        computers.read_bitlocker_key(directory(), COMPUTER, "00000000-0000-0000-0000-000000000000")
    assert caught.value.code == "bitlocker_key_not_found"


def test_a_key_whose_password_the_directory_withholds_is_not_allowed():
    """A confidential attribute comes back empty to an account without the
    right. That is a refusal, and has to be reported as one."""
    conn = Directory([key(COMPUTER, KEY_A, "1", None)])
    with pytest.raises(PermissionDenied) as caught:
        computers.read_bitlocker_key(conn, COMPUTER, KEY_A)
    assert caught.value.code == "bitlocker_unreadable"


def test_the_search_finds_the_computer_and_reads_no_password():
    conn = Directory([key(COMPUTER, KEY_A, "1", PASSWORD_A)])
    result = computers.find_bitlocker_key(conn, "1a2b3c4d")

    assert "(name=*{1A2B3C4D*)" in conn.filters[-1]
    assert [(k["computer"], k["key_id"]) for k in result["keys"]] == [("PC01", KEY_A)]
    assert result["keys"][0]["computer_dn"] == COMPUTER
    assert "msFVE-RecoveryPassword" not in (conn.requested[-1] or [])
    assert PASSWORD_A not in repr(result)


def test_the_search_drops_a_name_match_whose_id_does_not_start_with_the_prefix():
    """name=*{PREFIX* also matches the prefix in the middle of a GUID."""
    conn = Directory([key(COMPUTER, "00001A2B-3C4D-2222-3333-444455556666", "1", PASSWORD_A)])
    assert computers.find_bitlocker_key(conn, "1A2B3C4D")["keys"] == []


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("1A2B3C4D", True),
        ("1a2b3c4d", True),
        (KEY_A, True),
        ("{" + KEY_A + "}", True),
        ("1A2B3C", False),  # shorter than the recovery screen shows
        ("1A2B3C4D*", False),
        ("1A2B)(name=*", False),
        ("ZZZZZZZZ", False),
    ],
)
def test_the_key_id_parameter_accepts_ids_and_nothing_else(value: str, accepted: bool):
    pattern = KeyIdQuery.__metadata__[0].metadata[0].pattern
    assert bool(re.match(pattern, value)) is accepted


def test_the_recovery_password_is_redacted_from_the_audit_log():
    assert redact({"recovery_password": PASSWORD_A})["recovery_password"] == REDACTED
    assert redact({"msFVE-RecoveryPassword": PASSWORD_A})["msFVE-RecoveryPassword"] == REDACTED

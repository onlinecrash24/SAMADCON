"""The password reset writes a message, not a string of LDIF.

It used to build ``dn: {dn}\\nchangetype: modify\\n…`` and hand it to
modify_ldif, with the DN from a query parameter checked for nothing but its
length. A DN carrying a line break turned into further LDIF records: the
audit log said user.set_password on one object, and the directory did
something else as well. Found by an outside review.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from samadcon.ad import users
from samadcon.api.common import DnQuery, OptionalDnQuery

DN = "CN=Anna,CN=Users,DC=example,DC=test"


class FakeLdb(types.ModuleType):
    """Just enough of pyldb to build a message on a machine without Samba."""

    FLAG_MOD_REPLACE = 2

    class Dn:
        def __init__(self, samdb: Any, text: str) -> None:
            self.text = text

    class MessageElement:
        def __init__(self, value: Any, flags: int, name: str) -> None:
            self.value, self.flags, self.name = value, flags, name

    class Message(dict):
        dn: Any = None


class SamDB:
    def __init__(self) -> None:
        self.ldif: list[str] = []

    def modify_ldif(self, ldif: str) -> None:
        self.ldif.append(ldif)


class Connection:
    def __init__(self) -> None:
        self.samdb = SamDB()
        self.messages: list[Any] = []

    def modify(self, message: Any) -> None:
        self.messages.append(message)


@pytest.fixture
def conn(monkeypatch) -> Connection:
    monkeypatch.setitem(sys.modules, "ldb", FakeLdb("ldb"))
    return Connection()


def test_the_password_goes_as_a_message_and_never_as_ldif(conn):
    users.set_password(conn, DN, "Secret-2026!")

    assert conn.samdb.ldif == []
    password = conn.messages[0]
    assert password.dn.text == DN
    element = password["unicodePwd"]
    assert element.value == '"Secret-2026!"'.encode("utf-16-le")
    assert element.flags == FakeLdb.FLAG_MOD_REPLACE


def test_a_line_break_in_the_dn_cannot_become_another_record(conn):
    """Whatever the DN holds, it is one DN of one message."""
    hostile = DN + "\n\ndn: CN=Other,DC=example,DC=test\nchangetype: delete"
    users.set_password(conn, hostile, "Secret-2026!")
    assert conn.samdb.ldif == []
    assert conn.messages[0].dn.text == hostile


def test_must_change_still_follows(conn):
    users.set_password(conn, DN, "Secret-2026!", must_change=True)
    assert conn.messages[1]["pwdLastSet"].value == "0"


# ---------------------------------------------------------------------------
# And the DN never gets that far: every route takes it through DnQuery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("annotated", [DnQuery, OptionalDnQuery])
@pytest.mark.parametrize("control", ["\n", "\r", "\x00", "\t"])
def test_a_dn_with_a_control_character_is_refused(annotated, control):
    with pytest.raises(ValidationError):
        TypeAdapter(annotated).validate_python(f"CN=a{control}b,DC=example,DC=test")


@pytest.mark.parametrize("annotated", [DnQuery, OptionalDnQuery])
def test_an_escaped_dn_still_passes(annotated):
    """What LDAP escaping looks like: backslashes and hex, no raw control bytes."""
    text = r"CN=Meyer\, Sarah\0A,OU=Vertrieb,DC=example,DC=test"
    assert TypeAdapter(annotated).validate_python(text) == text

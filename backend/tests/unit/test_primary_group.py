"""Setting the primary group: the RID goes in, and only after the rules ADUC
greys its button out for."""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.ad import users, values
from samadcon.core.errors import InvalidRequest, NotFound

DOMAIN = "S-1-5-21-1000-2000-3000"
USER_DN = "CN=anna,OU=Users,DC=example,DC=test"
GROUP_DN = "CN=Staff,OU=Groups,DC=example,DC=test"
OTHER_DN = "CN=Elsewhere,OU=Groups,DC=other,DC=test"


def sid(text: str) -> bytes:
    """The wire form of a SID, the way values.sid_to_str reads it."""
    parts = text.split("-")
    revision, authority, subs = int(parts[1]), int(parts[2]), [int(p) for p in parts[3:]]
    out = bytes([revision, len(subs)]) + authority.to_bytes(6, "big")
    for sub in subs:
        out += sub.to_bytes(4, "little")
    return out


class Directory:
    def __init__(self, member_of: list[str], primary_rid: int = 513) -> None:
        self.entries: dict[str, dict[str, Any]] = {
            USER_DN.lower(): {
                "memberOf": [g.encode() for g in member_of],
                "primaryGroupID": [str(primary_rid).encode()],
                "objectSid": [sid(f"{DOMAIN}-1105")],
            },
            GROUP_DN.lower(): {
                "objectSid": [sid(f"{DOMAIN}-1201")],
                "objectClass": [b"top", b"group"],
            },
            OTHER_DN.lower(): {
                "objectSid": [sid("S-1-5-21-9-9-9-1300")],
                "objectClass": [b"top", b"group"],
            },
        }
        self.modified: list[tuple[str, str]] = []
        self.samdb = object()

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        return self.entries.get(dn.lower())

    def modify(self, message: Any) -> None:
        self.modified.append((str(message.dn), str(message["primaryGroupID"][0])))


@pytest.fixture(autouse=True)
def fake_ldb(monkeypatch):
    """Enough of ldb for the message the writer builds."""
    import sys
    import types

    class Dn:
        def __init__(self, samdb: Any, text: str) -> None:
            self.text = text

        def __str__(self) -> str:
            return self.text

    class MessageElement(list):
        def __init__(self, value: Any, flags: int, name: str) -> None:
            super().__init__([value] if isinstance(value, str) else value)

    class Message(dict):
        dn: Any = None

    fake = types.SimpleNamespace(Dn=Dn, Message=Message, MessageElement=MessageElement, FLAG_MOD_REPLACE=2)
    monkeypatch.setitem(sys.modules, "ldb", fake)


def test_sid_helper_round_trips():
    assert values.sid_to_str(sid(f"{DOMAIN}-1105")) == f"{DOMAIN}-1105"


def test_a_member_becomes_primary_by_rid():
    conn = Directory(member_of=[GROUP_DN])
    applied = users.set_primary_group(conn, USER_DN, GROUP_DN)
    assert conn.modified == [(USER_DN, "1201")]
    assert applied == {"primaryGroupID": {"old": 513, "new": 1201}}


def test_a_non_member_is_refused_with_the_reason():
    conn = Directory(member_of=[])
    with pytest.raises(InvalidRequest) as caught:
        users.set_primary_group(conn, USER_DN, GROUP_DN)
    assert caught.value.code == "primary_group_not_a_member"
    assert conn.modified == []


def test_a_group_from_another_domain_is_refused():
    conn = Directory(member_of=[OTHER_DN])
    with pytest.raises(InvalidRequest) as caught:
        users.set_primary_group(conn, USER_DN, OTHER_DN)
    assert caught.value.code == "primary_group_foreign_domain"


def test_the_current_primary_is_a_no_op():
    conn = Directory(member_of=[GROUP_DN], primary_rid=1201)
    assert users.set_primary_group(conn, USER_DN, GROUP_DN) == {}
    assert conn.modified == []


def test_a_missing_group_is_not_found():
    conn = Directory(member_of=[])
    with pytest.raises(NotFound):
        users.set_primary_group(conn, USER_DN, "CN=Nope,DC=example,DC=test")

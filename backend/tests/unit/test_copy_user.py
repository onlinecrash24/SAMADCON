"""ADUC's "Copy…": an account made from a template account.

The template is an ordinary, disabled account that carries what a department
has in common — its OU, its groups, its department and company, its paths —
and none of what makes a person. The copy takes the first and leaves the
second, and the paths that end in the template's name end in the new one.

Group memberships are added after the account exists. A group the operator may
not write to must be reported, not silently skipped and not a reason to take
back an account that is otherwise ready.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from pydantic import ValidationError

from samadcon.ad import passwords, uac, users, values
from samadcon.core.audit import REDACTED, redact
from samadcon.core.errors import Conflict, InvalidRequest, NotFound, PermissionDenied
from samadcon.schemas.requests import CopyUserRequest

BASE = "DC=example,DC=test"
DOMAIN_SID = "S-1-5-21-1000-2000-3000"
SALES_OU = f"OU=Vertrieb,{BASE}"
OTHER_OU = f"OU=Aussendienst,{BASE}"
TEMPLATE = f"CN=_Vorlage_Vertrieb,{SALES_OU}"
SALES = f"CN=Vertrieb,OU=Gruppen,{BASE}"
VPN = f"CN=VPN-Nutzer,OU=Gruppen,{BASE}"
GUARDED = f"CN=Tresor,OU=Gruppen,{BASE}"
PRIMARY = f"CN=Vertrieb-Primaer,OU=Gruppen,{BASE}"
DOMAIN_USERS = f"CN=Domain Users,CN=Users,{BASE}"
LOGON_HOURS = bytes([0x00, 0xFF, 0x0F] * 7)
EXPIRES = 134_000_000_000_000_000  # a date in 2025, as a FILETIME


def sid_bytes(sid: str) -> bytes:
    parts = sid.split("-")
    subs = [int(part) for part in parts[3:]]
    return (
        bytes([int(parts[1]), len(subs)])
        + int(parts[2]).to_bytes(6, "big")
        + b"".join(sub.to_bytes(4, "little") for sub in subs)
    )


def encoded(value: Any) -> list[bytes]:
    items = value if isinstance(value, list) else [value]
    return [item if isinstance(item, bytes) else str(item).encode() for item in items]


class FakeLdb(types.ModuleType):
    """Just enough of pyldb to build messages on a machine without Samba."""

    FLAG_MOD_ADD = 1
    FLAG_MOD_REPLACE = 2
    FLAG_MOD_DELETE = 4

    class Dn:
        def __init__(self, samdb: Any, text: str) -> None:
            self.text = text

        def __str__(self) -> str:
            return self.text

    class MessageElement:
        def __init__(self, value: Any, flags: int, name: str) -> None:
            self.value, self.flags, self.name = value, flags, name

    class Message(dict):
        dn: Any = None


class Result(list):
    @property
    def entries(self) -> list[Any]:
        return self


class Directory:
    """Objects by DN, memberOf computed from the groups, as the DC does."""

    class Info:
        base_dn = BASE
        dns_domain = "example.test"

    def __init__(self) -> None:
        self.info = Directory.Info()
        self.samdb = None
        self.objects: dict[str, dict[str, list[bytes]]] = {}
        self.refuse: set[str] = set()
        self.next_rid = 1500

    def put(self, dn: str, **attrs: Any) -> None:
        entry = {"distinguishedName": [dn.encode()]}
        entry.update({name: encoded(value) for name, value in attrs.items()})
        self.objects[dn.lower()] = entry

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        stored = self.objects.get(dn.lower())
        if stored is None:
            return None
        entry = dict(stored)
        member_of = [
            group["distinguishedName"][0]
            for group in self.objects.values()
            if dn.lower() in {m.decode().lower() for m in group.get("member", [])}
        ]
        if member_of:
            entry["memberOf"] = member_of
        if attrs is None:
            return entry
        keep = {"distinguishedName", *attrs}
        return {name: value for name, value in entry.items() if name in keep}

    def exists(self, dn: str) -> bool:
        return dn.lower() in self.objects

    def search(self, base: str, *, scope: int, expression: str, attrs=None, max_results=0):
        name, _, wanted = expression.strip("()").partition("=")
        found = Result()
        for entry in self.objects.values():
            for raw in entry.get(name, []):
                text = values.sid_to_str(raw) if name == "objectSid" else raw.decode()
                if text is not None and text.lower() == wanted.lower():
                    found.append(self.get(entry["distinguishedName"][0].decode(), attrs))
        return found

    def add(self, message: Any) -> None:
        dn = message.dn.text
        if self.exists(dn):
            raise Conflict("exists", code="already_exists")
        self.put(dn, **{name: element.value for name, element in message.items()})
        self.objects[dn.lower()]["objectSid"] = [sid_bytes(f"{DOMAIN_SID}-{self.next_rid}")]
        self.objects[dn.lower()].setdefault("primaryGroupID", [b"513"])
        self.next_rid += 1

    def rid(self, dn: str) -> int:
        return int(values.sid_to_str(self.raw(dn, "objectSid")[0]).rsplit("-", 1)[1])

    def by_rid(self, rid: int) -> str:
        return next(
            e["distinguishedName"][0].decode()
            for e in self.objects.values()
            if e.get("objectSid") and values.sid_to_str(e["objectSid"][0]).endswith(f"-{rid}")
        )

    def modify(self, message: Any) -> None:
        dn = message.dn.text
        entry = self.objects[dn.lower()]
        for name, element in message.items():
            if name == "member" and dn.lower() in self.refuse:
                raise PermissionDenied("Insufficient access rights.", code="insufficient_rights")
            if name == "member" and element.flags == FakeLdb.FLAG_MOD_ADD:
                # As Samba does: an account is never an explicit member of its
                # own primary group.
                for member in encoded(element.value):
                    if self.text(member.decode(), "primaryGroupID") == str(self.rid(dn)):
                        raise Conflict(
                            "An object with this name already exists.", code="already_exists"
                        )
            if name == "primaryGroupID":
                # As Samba does: the old primary group becomes an ordinary
                # membership, and the new one stops being one.
                old = self.by_rid(int(self.text(dn, "primaryGroupID") or 513))
                new = self.by_rid(int(element.value))
                self.objects[old.lower()].setdefault("member", []).append(dn.encode())
                members = self.objects[new.lower()].get("member", [])
                self.objects[new.lower()]["member"] = [
                    m for m in members if m.decode().lower() != dn.lower()
                ]
            if element.flags == FakeLdb.FLAG_MOD_ADD:
                entry.setdefault(name, []).extend(encoded(element.value))
            else:
                entry[name] = encoded(element.value)

    def delete(self, dn: str) -> None:
        self.objects.pop(dn.lower(), None)

    def raw(self, dn: str, name: str) -> list[bytes]:
        return self.objects[dn.lower()].get(name, [])

    def text(self, dn: str, name: str) -> str | None:
        found = self.raw(dn, name)
        return found[0].decode() if found else None


def group(directory: Directory, dn: str, rid: int, members: list[str]) -> None:
    directory.put(dn, objectClass=["top", "group"], objectSid=sid_bytes(f"{DOMAIN_SID}-{rid}"),
                  member=members, groupType="-2147483646")


@pytest.fixture
def directory(monkeypatch) -> Directory:
    monkeypatch.setitem(sys.modules, "ldb", FakeLdb("ldb"))
    d = Directory()
    d.put(BASE, objectClass=["domain"], minPwdLength="12", pwdProperties="1")
    for ou in (SALES_OU, OTHER_OU, f"OU=Gruppen,{BASE}"):
        d.put(ou, objectClass=["top", "organizationalUnit"])
    d.put(
        TEMPLATE,
        objectClass=["top", "person", "organizationalPerson", "user"],
        objectSid=sid_bytes(f"{DOMAIN_SID}-1105"),
        sAMAccountName="_Vorlage_Vertrieb",
        userAccountControl=uac.NORMAL_ACCOUNT | uac.ACCOUNTDISABLE | uac.DONT_EXPIRE_PASSWD,
        primaryGroupID="513",
        department="Vertrieb",
        company="Beispiel GmbH",
        l="Berlin",
        c="DE",
        homeDrive="H:",
        homeDirectory=r"\\srv\home\_Vorlage_Vertrieb",
        profilePath=r"\\srv\profiles\_VORLAGE_VERTRIEB",
        scriptPath="vertrieb.cmd",
        logonHours=LOGON_HOURS,
        accountExpires=str(EXPIRES),
        # Who the template is, which no copy should inherit.
        description="Vorlage - nicht loeschen",
        title="Vorlage",
        mail="vorlage@example.test",
        telephoneNumber="+49 30 0000",
        physicalDeliveryOfficeName="Raum 0",
        streetAddress="Hauptstrasse 1",
    )
    group(d, DOMAIN_USERS, 513, [])
    group(d, SALES, 1201, [TEMPLATE])
    group(d, VPN, 1202, [TEMPLATE])
    group(d, GUARDED, 1203, [TEMPLATE])
    return d


def copy(directory: Directory, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("sam_account_name", "mmuster")
    kwargs.setdefault("common_name", "Max Muster")
    kwargs.setdefault("password", "Start-2026!Passwort")
    kwargs.setdefault("attributes", {"first_name": "Max", "last_name": "Muster"})
    return users.copy_user(directory, TEMPLATE, **kwargs)


NEW = f"CN=Max Muster,{SALES_OU}"


# ---------------------------------------------------------------------------
# What comes along
# ---------------------------------------------------------------------------


def test_the_copy_takes_where_the_person_sits_and_not_who_they_are(directory):
    copy(directory)

    assert directory.text(NEW, "department") == "Vertrieb"
    assert directory.text(NEW, "company") == "Beispiel GmbH"
    assert directory.text(NEW, "l") == "Berlin"
    assert directory.text(NEW, "c") == "DE"
    assert directory.text(NEW, "homeDrive") == "H:"
    assert directory.text(NEW, "scriptPath") == "vertrieb.cmd"
    for personal in ("description", "title", "mail", "telephoneNumber",
                     "physicalDeliveryOfficeName", "streetAddress"):
        assert directory.raw(NEW, personal) == [], personal


def test_paths_that_end_in_the_template_name_end_in_the_new_one(directory):
    copy(directory)
    assert directory.text(NEW, "homeDirectory") == r"\\srv\home\mmuster"
    assert directory.text(NEW, "profilePath") == r"\\srv\profiles\mmuster"


def test_only_whole_path_segments_are_renamed():
    assert users.follow_name(r"\\srv\vthome\vt", "VT", "mm") == r"\\srv\vthome\mm"
    assert users.follow_name(r"\\srv\home\%username%", "vt", "mm") == r"\\srv\home\%username%"
    assert users.follow_name("", "vt", "mm") == ""


def test_logon_hours_expiry_and_account_options_come_along_but_not_disabled(directory):
    copy(directory)

    assert directory.raw(NEW, "logonHours") == [LOGON_HOURS]
    assert directory.text(NEW, "accountExpires") == str(EXPIRES)
    final = int(directory.text(NEW, "userAccountControl") or 0)
    assert final & uac.DONT_EXPIRE_PASSWD
    assert not final & uac.ACCOUNTDISABLE


def test_what_the_caller_says_about_the_person_wins(directory):
    copy(directory, attributes={"first_name": "Max", "department": "Innendienst"})
    assert directory.text(NEW, "givenName") == "Max"
    assert directory.text(NEW, "department") == "Innendienst"


def test_the_account_goes_where_the_template_is_unless_told_otherwise(directory):
    assert copy(directory)["user"]["dn"] == NEW
    moved = copy(directory, sam_account_name="eanders", common_name="Eva Anders",
                 parent_dn=OTHER_OU)
    assert moved["user"]["dn"] == f"CN=Eva Anders,{OTHER_OU}"


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def test_every_template_group_is_given_by_default(directory):
    result = copy(directory)
    assert sorted(result["groups_added"]) == sorted([SALES, VPN, GUARDED])
    assert result["failed_groups"] == []
    assert sorted(result["user"]["member_of"]) == sorted([SALES, VPN, GUARDED])


def test_a_group_the_operator_may_not_write_is_reported_and_the_account_stays(directory):
    directory.refuse.add(GUARDED.lower())
    result = copy(directory)

    assert sorted(result["groups_added"]) == sorted([SALES, VPN])
    assert [(f["dn"], f["code"]) for f in result["failed_groups"]] == [
        (GUARDED, "insufficient_rights")
    ]
    assert directory.exists(NEW)


def test_the_groups_can_be_narrowed_to_some_of_the_template_ones(directory):
    result = copy(directory, groups=[SALES.upper()])
    assert result["groups_added"] == [SALES]
    assert result["user"]["member_of"] == [SALES]


def test_a_group_the_template_does_not_have_is_refused_before_anything_is_made(directory):
    stranger = f"CN=Domain Admins,CN=Users,{BASE}"
    with pytest.raises(InvalidRequest) as caught:
        copy(directory, groups=[SALES, stranger])
    assert caught.value.code == "group_not_in_template"
    assert not directory.exists(NEW)


def with_primary_group(directory: Directory) -> None:
    """The template as samba-tool user setprimarygroup leaves it: primary group
    PRIMARY, which it is no longer an explicit member of, and an explicit
    member of Domain Users instead."""
    group(directory, PRIMARY, 1300, [])
    directory.objects[TEMPLATE.lower()]["primaryGroupID"] = [b"1300"]
    directory.objects[DOMAIN_USERS.lower()]["member"] = [TEMPLATE.encode()]


def test_a_primary_group_other_than_domain_users_comes_along(directory):
    with_primary_group(directory)
    result = copy(directory)

    assert PRIMARY in result["groups_added"]
    assert directory.text(NEW, "primaryGroupID") == "1300"


def test_domain_users_is_not_reported_as_a_group_the_copy_could_not_join(directory):
    """Found on a Samba 4.22 DC: the template listed Domain Users, the new
    account already had it as its primary group, the directory refused it a
    second time, and the copy reported a failure for a group it ended up in
    once its primary group was switched."""
    with_primary_group(directory)
    result = copy(directory)

    assert result["failed_groups"] == []
    assert DOMAIN_USERS not in result["groups_added"]
    assert DOMAIN_USERS in result["user"]["member_of"]  # the DC's doing, not the copy's


def test_the_dialog_is_offered_the_groups_the_copy_would_give(directory):
    with_primary_group(directory)
    offered = users.copy_template_groups(directory, TEMPLATE)

    assert {g["dn"]: g["primary"] for g in offered} == {
        SALES: False,
        VPN: False,
        GUARDED: False,
        PRIMARY: True,
    }


def test_domain_users_is_recognised_by_its_sid_not_its_name(directory):
    renamed = f"CN=Domaenen-Benutzer,CN=Users,{BASE}"
    directory.objects.pop(DOMAIN_USERS.lower())
    group(directory, renamed, 513, [TEMPLATE])
    offered = [g["dn"] for g in users.copy_template_groups(directory, TEMPLATE)]
    assert renamed not in offered


# ---------------------------------------------------------------------------
# The password
# ---------------------------------------------------------------------------


def test_a_generated_password_is_written_returned_once_and_must_be_changed(directory):
    result = copy(directory, password=None, generate_password=True)

    generated = result["generated_password"]
    assert len(generated) >= passwords.MIN_LENGTH
    assert directory.raw(NEW, "unicodePwd") == [f'"{generated}"'.encode("utf-16-le")]
    assert directory.text(NEW, "pwdLastSet") == "0"
    assert "muster" not in generated.lower()


def test_a_password_given_is_not_echoed(directory):
    assert copy(directory)["generated_password"] is None


def test_a_password_and_a_generated_one_are_refused_together(directory):
    with pytest.raises(InvalidRequest) as caught:
        copy(directory, generate_password=True)
    assert caught.value.code == "password_conflict"
    with pytest.raises(ValidationError):
        CopyUserRequest(sam_account_name="mmuster", password="x", generate_password=True)


def test_the_generated_password_never_reaches_the_audit_log():
    assert redact({"generated_password": "Secret"})["generated_password"] == REDACTED


# ---------------------------------------------------------------------------
# What cannot be a template
# ---------------------------------------------------------------------------


def test_a_computer_is_not_a_template(directory):
    computer = f"CN=PC01,{SALES_OU}"
    directory.put(computer, objectClass=["top", "person", "user", "computer"],
                  sAMAccountName="PC01$")
    with pytest.raises(InvalidRequest) as caught:
        users.copy_user(directory, computer, sam_account_name="x", password="Start-2026!x")
    assert caught.value.code == "not_a_user_template"


def test_a_missing_template_is_not_found(directory):
    with pytest.raises(NotFound):
        users.copy_user(directory, f"CN=Nobody,{BASE}", sam_account_name="x", password="p")

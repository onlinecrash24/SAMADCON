"""Disabling or deleting an account that administers the domain takes a confirmation.

The objects below carry what the DC returns for them: a binary objectSid,
tokenGroups as binary SIDs with nesting already resolved, and
userAccountControl. The built-in Administrator is provisioned by Samba with
RID 500 (source4/setup/provision_users.ldif).
"""

from __future__ import annotations

import struct
from typing import Any

import pytest

from samadcon.ad import directory, users
from samadcon.core.errors import Conflict

DOMAIN = "S-1-5-21-1111111111-2222222222-3333333333"
DN = "CN=Somebody,CN=Users,DC=example,DC=test"

NORMAL = 512
DISABLED = 512 | 2


def sid(text: str) -> bytes:
    """A SID in the binary form objectSid and tokenGroups carry."""
    parts = text.split("-")
    authority = int(parts[2])
    subauthorities = [int(part) for part in parts[3:]]
    return (
        struct.pack("<BB", int(parts[1]), len(subauthorities))
        + authority.to_bytes(6, "big")
        + b"".join(struct.pack("<I", value) for value in subauthorities)
    )


class Directory:
    """One account, as the DC would answer for it."""

    def __init__(
        self,
        *,
        rid: int,
        groups: tuple[int, ...] = (513,),
        builtin: tuple[int, ...] = (545,),
        uac: int = NORMAL,
    ):
        # tokenGroups carries the builtin groups beside the domain's own:
        # measured on a Samba DC, an ordinary user shows 513 and S-1-5-32-545.
        self.entry: dict[str, list[Any]] = {
            "objectSid": [sid(f"{DOMAIN}-{rid}")],
            "tokenGroups": [sid(f"{DOMAIN}-{group}") for group in groups]
            + [sid(f"S-1-5-32-{group}") for group in builtin],
            "userAccountControl": [str(uac).encode()],
        }
        self.modified: dict[str, Any] | None = None

    def get(self, dn: str, attrs: list[str] | None = None) -> dict[str, list[Any]]:
        return {name: self.entry[name] for name in (attrs or self.entry) if name in self.entry}

    def modify_attributes(self, dn: str, changes: dict[str, Any]) -> dict[str, Any]:
        self.modified = changes
        return {name: {"new": value} for name, value in changes.items()}


@pytest.fixture
def written(monkeypatch) -> list[int]:
    """userAccountControl values that reached the directory."""
    seen: list[int] = []
    monkeypatch.setattr(users, "_set_uac", lambda conn, dn, value: seen.append(value))
    return seen


def refusal(directory: Directory, **kwargs: Any) -> Conflict:
    with pytest.raises(Conflict) as caught:
        users.set_enabled(directory, DN, False, **kwargs)
    assert caught.value.code == "confirm_disable_admin"
    return caught.value


def test_the_builtin_administrator_is_not_disabled_by_one_click(written):
    caught = refusal(Directory(rid=500))
    assert caught.context["role"] == "Administrator"
    assert written == []


def test_it_is_known_by_its_rid_not_its_name(written):
    """Renaming it is a hardening step; the RID stays 500."""
    directory = Directory(rid=500)
    directory.entry["sAMAccountName"] = [b"root-renamed"]
    refusal(directory)


def test_a_rid_that_merely_ends_in_500_is_somebody_else(written):
    users.set_enabled(Directory(rid=1500), DN, False)
    assert written == [DISABLED]


@pytest.mark.parametrize(
    ("group", "role"),
    [(512, "Domain Admins"), (518, "Schema Admins"), (519, "Enterprise Admins")],
)
def test_a_member_of_an_admin_group_needs_the_confirmation(written, group, role):
    caught = refusal(Directory(rid=1105, groups=(513, group)))
    assert caught.context["role"] == role
    assert written == []


def test_a_member_of_builtin_administrators_alone_needs_it_too(written):
    """Administrators on every DC without being in Domain Admins."""
    caught = refusal(Directory(rid=1105, groups=(513,), builtin=(544, 545)))
    assert caught.context["role"] == "Administrators"
    assert written == []


def test_a_domain_admin_is_named_as_one_though_also_in_administrators(written):
    """As measured: Domain Admins brings 544 with it through nesting."""
    caught = refusal(Directory(rid=1108, groups=(512, 513, 1107), builtin=(544, 545)))
    assert caught.context["role"] == "Domain Admins"


def test_a_builtin_sid_is_not_read_as_a_domain_rid(written):
    """Only the domain's own SIDs carry RIDs. A builtin SID ending in 512 does
    not exist, which is the point: were the trailing number all that counted,
    it would pass for Domain Admins, and the check must look at whose SID it is."""
    users.set_enabled(Directory(rid=1109, groups=(513,), builtin=(512, 545)), DN, False)
    assert written == [DISABLED]


def test_membership_through_another_group_counts(written):
    """tokenGroups carries the nested groups too: 1200 sits in Domain Admins."""
    refusal(Directory(rid=1105, groups=(513, 1200, 512)))


def test_an_ordinary_account_is_disabled_without_a_question(written):
    users.set_enabled(Directory(rid=1105, groups=(513, 1200)), DN, False)
    assert written == [DISABLED]


def test_confirming_disables_it(written):
    users.set_enabled(Directory(rid=500), DN, False, confirm_admin=True)
    assert written == [DISABLED]


def test_enabling_an_administrator_asks_nothing(written):
    users.set_enabled(Directory(rid=500, uac=DISABLED), DN, True)
    assert written == [NORMAL]


def test_an_administrator_already_disabled_is_not_asked_about_again(written):
    """Nothing is being taken away, so there is nothing to confirm."""
    users.set_enabled(Directory(rid=500, uac=DISABLED), DN, False)
    assert written == []


def test_a_refusal_leaves_the_rest_of_the_request_unwritten(written):
    """The property sheet sends fields and options together. A refusal that
    came after the fields were saved would leave half a change behind."""
    directory = Directory(rid=500)
    with pytest.raises(Conflict):
        users.update_user(
            directory,
            DN,
            attributes={"description": "retired"},
            flags={"account_disabled": True},
        )
    assert directory.modified is None
    assert written == []


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------


class Deletable(Directory):
    """The same account, with what delete_object reads and a way to be deleted."""

    def __init__(self, *, classes=(b"top", b"person", b"user"), critical=False, **kwargs: Any):
        super().__init__(**kwargs)
        self.entry["objectClass"] = list(classes)
        if critical:
            self.entry["isCriticalSystemObject"] = [b"TRUE"]
        self.deleted: list[str] = []

    def delete(self, dn: str, recursive: bool = False) -> None:
        self.deleted.append(dn)


def test_a_domain_admin_is_not_deleted_by_one_click():
    account = Deletable(rid=1105, groups=(513, 512))
    with pytest.raises(Conflict) as caught:
        directory.delete_object(account, DN)
    assert caught.value.code == "confirm_delete_admin"
    assert caught.value.context["role"] == "Domain Admins"
    assert account.deleted == []


def test_confirming_deletes_it():
    account = Deletable(rid=1105, groups=(513, 512))
    directory.delete_object(account, DN, confirm_admin=True)
    assert account.deleted == [DN]


def test_an_ordinary_account_is_deleted_as_before():
    account = Deletable(rid=1105, groups=(513,))
    directory.delete_object(account, DN)
    assert account.deleted == [DN]


def test_the_builtin_administrator_stays_undeletable_even_confirmed():
    """Samba provisions it as a critical system object; confirming changes nothing."""
    from samadcon.core.errors import InvalidRequest

    account = Deletable(rid=500, critical=True)
    with pytest.raises(InvalidRequest) as caught:
        directory.delete_object(account, DN, confirm_admin=True)
    assert caught.value.code == "critical_system_object"
    assert account.deleted == []


def test_the_question_before_the_dialog_names_the_role():
    account = Deletable(rid=1105, groups=(513, 512))
    assert users.account_administrative_role(account, DN) == "Domain Admins"


def test_the_question_before_the_dialog_is_none_for_an_ordinary_account():
    assert users.account_administrative_role(Deletable(rid=1105, groups=(513,)), DN) is None


def test_the_question_before_the_dialog_reads_no_groups_for_an_ou(monkeypatch):
    def must_not_be_called(conn, dn):
        raise AssertionError("administrative_role was consulted for an OU")

    monkeypatch.setattr(users, "administrative_role", must_not_be_called)
    ou = Deletable(rid=1105, classes=(b"top", b"organizationalUnit"))
    assert users.account_administrative_role(ou, DN) is None


def test_something_that_is_not_an_account_is_never_asked_about(monkeypatch):
    """An OU has no SID and no groups; tokenGroups is not even read for it."""
    def must_not_be_called(conn, dn):
        raise AssertionError("administrative_role was consulted for an OU")

    monkeypatch.setattr(users, "administrative_role", must_not_be_called)
    ou = Deletable(rid=1105, classes=(b"top", b"organizationalUnit"))
    directory.delete_object(ou, DN)
    assert ou.deleted == [DN]

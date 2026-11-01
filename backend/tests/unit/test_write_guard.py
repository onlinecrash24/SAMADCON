"""Reserved names and protected OUs: refused before anything is written.

An operator can reserve prefixes and names (SAMADCON_RESERVED_PREFIXES,
SAMADCON_RESERVED_NAMES) that SAMADCON will not give to sAMAccountName,
userPrincipalName, mail or proxyAddresses, and name OUs (SAMADCON_PROTECTED_OUS)
whose objects SAMADCON only shows. Asked for by a tester whose internal
services use accounts named havora-…

Every write goes through DirectoryConnection, so that is where both are
checked: the dialogs, the attribute editor, the password reset and the ACL
editor all land there. These run without Samba; the samdb and pyldb are fakes.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from samadcon.ad import write_guard
from samadcon.ad.connection import DirectoryConnection, DomainInfo
from samadcon.config import Settings
from samadcon.core.errors import InvalidRequest, PermissionDenied

INFO = DomainInfo(
    dc_hostname="dc1.example.test",
    base_dn="DC=example,DC=test",
    config_dn="CN=Configuration,DC=example,DC=test",
    schema_dn="CN=Schema,CN=Configuration,DC=example,DC=test",
    root_domain_dn="DC=example,DC=test",
    domain_sid="S-1-5-21-1-2-3",
    dns_domain="example.test",
    netbios_name="EXAMPLE",
    domain_functional_level=7,
    forest_functional_level=7,
)

HAVORA = "OU=Havora,DC=example,DC=test"


# --- The pure part ---------------------------------------------------------


def test_dn_keys_ignore_case_and_spaces_around_separators():
    assert write_guard.dn_key("OU=Havora, DC=Example,DC=test") == write_guard.dn_key(
        "ou = havora,dc=example, dc=TEST"
    )


def test_an_escaped_comma_stays_inside_its_component():
    assert write_guard.dn_key("OU=Service\\, Intern,DC=example,DC=test") == (
        "ou=service\\, intern",
        "dc=example",
        "dc=test",
    )


@pytest.mark.parametrize(
    "dn",
    [
        HAVORA,
        "ou=havora,dc=example,dc=test",
        f"CN=havora-admin,{HAVORA}",
        f"CN=PC1,OU=Clients,{HAVORA}",
    ],
)
def test_the_ou_itself_and_everything_below_it_is_protected(dn: str):
    assert write_guard.protecting_ou(dn, [HAVORA]) == HAVORA


@pytest.mark.parametrize(
    "dn",
    [
        "OU=Havora2,DC=example,DC=test",
        "CN=Havora,CN=Users,DC=example,DC=test",
        "OU=Havora,OU=Other,DC=example,DC=test",
        "DC=example,DC=test",
        "CN=Users,DC=example,DC=test",
    ],
)
def test_a_lookalike_or_a_parent_is_not_protected(dn: str):
    assert write_guard.protecting_ou(dn, [HAVORA]) is None


def test_a_protected_ou_below_a_container_is_found():
    nested = "OU=Inner,OU=Outer,DC=example,DC=test"
    assert write_guard.protected_below("OU=Outer,DC=example,DC=test", [nested]) == nested
    assert write_guard.protected_below("DC=example,DC=test", [nested]) == nested
    # Itself is not "below", and a sibling holds nothing.
    assert write_guard.protected_below(nested, [nested]) is None
    assert write_guard.protected_below("OU=Elsewhere,DC=example,DC=test", [nested]) is None


@pytest.mark.parametrize(
    ("attribute", "value", "expected"),
    [
        ("sAMAccountName", "havora-test", ("prefix", "havora-")),
        ("sAMAccountName", "HAVORA-Test", ("prefix", "havora-")),
        ("samaccountname", "havora-pc1$", ("prefix", "havora-")),
        ("userPrincipalName", "havora-x@example.test", ("prefix", "havora-")),
        ("mail", "Havora-X@Example.TEST", ("prefix", "havora-")),
        ("proxyAddresses", "SMTP:havora-x@example.test", ("prefix", "havora-")),
        ("proxyAddresses", "smtp:havora-x@example.test", ("prefix", "havora-")),
        ("sAMAccountName", "havora", ("name", "havora")),
        ("sAMAccountName", "HAVORA$", ("name", "havora")),
        ("mail", "havora@other.example", ("name", "havora")),
        ("mail", "info@example.test", ("name", "info@example.test")),
        ("proxyAddresses", "smtp:INFO@example.test", ("name", "info@example.test")),
    ],
)
def test_reserved_values_are_found(attribute: str, value: str, expected: tuple[str, str]):
    hit = write_guard.reserved_hit(
        attribute, value, prefixes=["havora-"], names=["havora", "info@example.test"]
    )
    assert hit == expected


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("sAMAccountName", "anna"),
        ("sAMAccountName", "havoraner"),
        ("sAMAccountName", "my-havora-x"),
        ("mail", "info@other.example"),
        ("mail", "x@havora-intern.example"),
        ("proxyAddresses", "x500:/o=havora-x"),
        # Not one of the four attributes.
        ("displayName", "havora-test"),
        ("cn", "havora"),
    ],
)
def test_other_values_pass(attribute: str, value: str):
    assert (
        write_guard.reserved_hit(
            attribute, value, prefixes=["havora-"], names=["havora", "info@example.test"]
        )
        is None
    )


def test_a_name_is_exact_and_not_a_prefix():
    assert write_guard.reserved_hit("sAMAccountName", "administrator", [], ["admin"]) is None
    assert write_guard.reserved_hit("sAMAccountName", "Admin", [], ["admin"]) == ("name", "admin")


# --- At the connection -----------------------------------------------------


class FakeLdb(types.ModuleType):
    """pyldb as far as a message goes: elements iterate as bytes, like the real ones."""

    FLAG_MOD_ADD = 1
    FLAG_MOD_REPLACE = 2
    FLAG_MOD_DELETE = 3

    class Dn:
        def __init__(self, samdb: Any, text: str) -> None:
            self.text = text

        def __str__(self) -> str:
            return self.text

    class MessageElement:
        def __init__(self, value: Any, flags: int = 0, name: str = "") -> None:
            items = value if isinstance(value, list) else [value]
            self._values = [v if isinstance(v, bytes) else str(v).encode() for v in items]
            self._flags = flags
            self._name = name

        def __iter__(self):
            return iter(self._values)

        def __len__(self) -> int:
            return len(self._values)

        def flags(self) -> int:
            return self._flags

    class Message(dict):
        dn: Any = None


class Samdb:
    """Records writes; answers a base search with what *current* holds."""

    def __init__(self, current: dict[str, dict[str, list[str]]] | None = None) -> None:
        self.current = current or {}
        self.writes: list[tuple[str, Any]] = []
        self.searches = 0

    def add(self, message: Any, controls: Any = None) -> None:
        self.writes.append(("add", message))

    def modify(self, message: Any, controls: Any = None) -> None:
        self.writes.append(("modify", (message, controls)))

    def delete(self, dn: str, controls: Any = None) -> None:
        self.writes.append(("delete", (dn, controls)))

    def rename(self, old: str, new: str) -> None:
        self.writes.append(("rename", (old, new)))

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.searches += 1
        entry = self.current.get(str(kwargs.get("base", "")).lower())
        return [{"dn": kwargs.get("base"), **entry}] if entry is not None else []


@pytest.fixture
def ldb(monkeypatch: pytest.MonkeyPatch) -> FakeLdb:
    fake = FakeLdb("ldb")
    monkeypatch.setitem(sys.modules, "ldb", fake)
    return fake


def connection(samdb: Samdb, **settings: Any) -> DirectoryConnection:
    return DirectoryConnection(samdb, "dc1.example.test", INFO, Settings(**settings))


GUARDED = {
    "reserved_prefixes": ["havora-"],
    "reserved_names": ["havora"],
    "protected_ous": [HAVORA],
}


def message(ldb: FakeLdb, dn: str, flags: int, **attributes: Any) -> Any:
    msg = ldb.Message()
    msg.dn = ldb.Dn(None, dn)
    for name, value in attributes.items():
        msg[name] = ldb.MessageElement(value, flags, name)
    return msg


def test_a_new_account_with_a_reserved_prefix_is_refused_before_it_is_written(ldb):
    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    new = message(
        ldb,
        "CN=Test,CN=Users,DC=example,DC=test",
        ldb.FLAG_MOD_ADD,
        objectClass="user",
        sAMAccountName="HAVORA-test",
    )
    with pytest.raises(InvalidRequest) as refused:
        conn.add(new)
    assert refused.value.code == "reserved_name"
    assert refused.value.context == {
        "attribute": "sAMAccountName",
        "value": "HAVORA-test",
        "rule": "havora-",
        "reason": "prefix",
    }
    assert samdb.writes == []


def test_a_reserved_address_among_several_is_found(ldb):
    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    new = message(
        ldb,
        "CN=Test,CN=Users,DC=example,DC=test",
        ldb.FLAG_MOD_ADD,
        proxyAddresses=["SMTP:test@example.test", "smtp:havora@example.test"],
    )
    with pytest.raises(InvalidRequest) as refused:
        conn.add(new)
    assert refused.value.context["reason"] == "name"
    assert samdb.writes == []


def test_an_ordinary_account_is_written(ldb):
    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    conn.add(
        message(ldb, "CN=Anna,CN=Users,DC=example,DC=test", ldb.FLAG_MOD_ADD, sAMAccountName="anna")
    )
    assert [kind for kind, _ in samdb.writes] == ["add"]


def test_a_new_reserved_mail_on_an_existing_account_is_refused(ldb):
    anna = "CN=Anna,CN=Users,DC=example,DC=test"
    samdb = Samdb({anna.lower(): {"mail": ["anna@example.test"]}})
    conn = connection(samdb, **GUARDED)
    with pytest.raises(InvalidRequest):
        conn.modify(message(ldb, anna, ldb.FLAG_MOD_REPLACE, mail="havora-x@example.test"))
    assert samdb.writes == []


def test_a_reserved_value_the_account_already_has_may_stay(ldb):
    """havora-admin itself stays editable: modify_attributes writes the whole
    list of proxyAddresses back with REPLACE, the old reserved one included."""
    admin = "CN=havora-admin,CN=Users,DC=example,DC=test"
    samdb = Samdb({admin.lower(): {"proxyAddresses": ["SMTP:havora-admin@example.test"]}})
    conn = connection(samdb, **GUARDED)
    conn.modify(
        message(
            ldb,
            admin,
            ldb.FLAG_MOD_REPLACE,
            proxyAddresses=["smtp:havora-admin@example.test", "smtp:helpdesk@example.test"],
        )
    )
    assert [kind for kind, _ in samdb.writes] == ["modify"]


def test_removing_a_reserved_value_is_never_refused(ldb):
    admin = "CN=havora-admin,CN=Users,DC=example,DC=test"
    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    conn.modify(message(ldb, admin, ldb.FLAG_MOD_DELETE, mail=[]))
    assert [kind for kind, _ in samdb.writes] == ["modify"]
    assert samdb.searches == 0


def test_without_the_settings_nothing_is_looked_up_or_refused(ldb):
    samdb = Samdb()
    conn = connection(samdb)
    conn.add(message(ldb, f"CN=x,{HAVORA}", ldb.FLAG_MOD_ADD, sAMAccountName="havora-test"))
    conn.modify(message(ldb, f"CN=x,{HAVORA}", ldb.FLAG_MOD_REPLACE, mail="havora@example.test"))
    conn.rename(f"CN=x,{HAVORA}", "CN=x,CN=Users,DC=example,DC=test")
    conn.delete(HAVORA, recursive=True)
    assert [kind for kind, _ in samdb.writes] == ["add", "modify", "rename", "delete"]
    assert samdb.searches == 0


def test_an_unrelated_change_does_not_cost_a_search(ldb):
    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    conn.modify(
        message(
            ldb, "CN=Anna,CN=Users,DC=example,DC=test", ldb.FLAG_MOD_REPLACE, telephoneNumber="1"
        )
    )
    assert samdb.searches == 0


@pytest.mark.parametrize(
    "dn", [HAVORA, f"CN=havora-admin,{HAVORA}", "cn=pc1,ou=clients,ou=havora,dc=example,dc=test"]
)
def test_changing_anything_in_a_protected_ou_is_refused(ldb, dn: str):
    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    with pytest.raises(PermissionDenied) as refused:
        conn.modify(message(ldb, dn, ldb.FLAG_MOD_REPLACE, description="x"))
    assert refused.value.code == "protected_ou"
    assert refused.value.context == {"dn": dn, "protected_ou": HAVORA, "reason": "inside"}
    assert samdb.writes == []


def test_creating_in_a_protected_ou_is_refused(ldb):
    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    with pytest.raises(PermissionDenied):
        conn.add(message(ldb, f"CN=New,{HAVORA}", ldb.FLAG_MOD_ADD, sAMAccountName="new"))
    assert samdb.writes == []


def test_moving_out_of_into_and_above_a_protected_ou_is_refused(ldb):
    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    users = "CN=Users,DC=example,DC=test"

    with pytest.raises(PermissionDenied) as out:
        conn.rename(f"CN=x,{HAVORA}", f"CN=x,{users}")
    assert out.value.context["reason"] == "inside"

    with pytest.raises(PermissionDenied) as into:
        conn.rename(f"CN=x,{users}", f"CN=x,{HAVORA}")
    assert into.value.context["reason"] == "move_in"

    nested = connection(samdb, protected_ous=["OU=Havora,OU=Outer,DC=example,DC=test"])
    with pytest.raises(PermissionDenied) as above:
        nested.rename("OU=Outer,DC=example,DC=test", "OU=Renamed,DC=example,DC=test")
    assert above.value.context["reason"] == "ancestor"

    assert samdb.writes == []


def test_deleting_a_protected_ou_or_a_tree_holding_one_is_refused(ldb):
    samdb = Samdb()
    conn = connection(samdb, protected_ous=["OU=Havora,OU=Outer,DC=example,DC=test"])

    with pytest.raises(PermissionDenied):
        conn.delete("CN=x,OU=Havora,OU=Outer,DC=example,DC=test")
    with pytest.raises(PermissionDenied) as tree:
        conn.delete("OU=Outer,DC=example,DC=test", recursive=True)
    assert tree.value.context["reason"] == "ancestor"
    assert samdb.writes == []

    conn.delete("OU=Sibling,OU=Outer,DC=example,DC=test", recursive=True)
    assert [kind for kind, _ in samdb.writes] == ["delete"]


def test_a_protected_user_may_join_an_ordinary_group(ldb):
    """Only the group changes, as in ADUC: member is written on the group."""
    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    conn.modify(
        message(
            ldb,
            "CN=Staff,CN=Users,DC=example,DC=test",
            ldb.FLAG_MOD_ADD,
            member=f"CN=havora-admin,{HAVORA}",
        )
    )
    assert [kind for kind, _ in samdb.writes] == ["modify"]


def test_the_acl_editor_goes_through_the_guard_and_keeps_its_control(ldb, monkeypatch):
    from samadcon.ad import sacl

    class Descriptor:
        @staticmethod
        def from_sddl(sddl: str, sid: Any) -> str:
            return sddl

    security = types.SimpleNamespace(descriptor=Descriptor, dom_sid=lambda text: text)
    dcerpc = types.ModuleType("samba.dcerpc")
    dcerpc.security = security  # type: ignore[attr-defined]
    ndr = types.ModuleType("samba.ndr")
    ndr.ndr_pack = lambda value: str(value).encode()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "samba", types.ModuleType("samba"))
    monkeypatch.setitem(sys.modules, "samba.dcerpc", dcerpc)
    monkeypatch.setitem(sys.modules, "samba.ndr", ndr)
    monkeypatch.setattr(sacl, "_domain_sid", lambda conn: "S-1-5-21-1-2-3")

    samdb = Samdb()
    conn = connection(samdb, **GUARDED)
    with pytest.raises(PermissionDenied):
        sacl.write_sddl(conn, f"CN=havora-admin,{HAVORA}", "D:(A;;RP;;;AU)")
    assert samdb.writes == []

    sacl.write_sddl(conn, "CN=Anna,CN=Users,DC=example,DC=test", "D:(A;;RP;;;AU)")
    [(kind, (_, controls))] = samdb.writes
    assert kind == "modify"
    assert controls == ["sd_flags:1:4"]


def test_nothing_writes_past_the_connection():
    """The guard holds only while every write goes through DirectoryConnection."""
    package = Path(write_guard.__file__).resolve().parent.parent
    direct = re.compile(r"\bsamdb\.(add|modify|delete|rename)\(")
    offenders = [
        f"{path.relative_to(package)}:{number}"
        for path in package.rglob("*.py")
        if path.name != "connection.py"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if direct.search(line)
    ]
    assert offenders == []

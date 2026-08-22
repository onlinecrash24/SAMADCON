"""Which containers the group policy tree may show, and where that is decided.

The console listed Users, Computers, Builtin, ForeignSecurityPrincipals and
Managed Service Accounts as places to link a policy. They are not — reported
from a live domain with a screenshot.

The classes that can carry a gPLink were already written down in gpmc, and
were used by nothing. Everything here checks that the one statement still
reaches the three places it has to: the LDAP search the tree runs, the flag the
browser is handed, and the probe that decides whether a branch is worth an
expander. Written out a second time, those three drift apart in silence — a
container simply stops being offered, or starts being offered where a link
would do nothing.

No directory: the connection is stood in for, because what is worth testing is
which question gets asked, not what a domain answers.
"""

from __future__ import annotations

from typing import Any

from samadcon.ad import directory
from samadcon.gpo import gpmc

# ---------------------------------------------------------------------------
# The statement itself
# ---------------------------------------------------------------------------


def test_a_plain_container_is_not_somewhere_a_policy_can_be_linked() -> None:
    """CN=Users, CN=Computers, CN=ForeignSecurityPrincipals and CN=Managed
    Service Accounts are all objectClass=container, and CN=Builtin is a
    builtinDomain. All five were on screen; none of them belongs there."""
    assert directory.type_for_class("container") not in gpmc.LINKABLE_TYPES
    assert directory.type_for_class("builtinDomain") not in gpmc.LINKABLE_TYPES


def test_an_organizational_unit_the_domain_and_a_site_are() -> None:
    assert directory.type_for_class("organizationalUnit") in gpmc.LINKABLE_TYPES
    assert directory.type_for_class("domainDNS") in gpmc.LINKABLE_TYPES
    assert directory.type_for_class("site") in gpmc.LINKABLE_TYPES


def test_the_types_are_derived_from_the_classes_rather_than_listed_again() -> None:
    """One statement, three vocabularies. This is the one that would rot: the
    browser compares against a type, the directory against a class."""
    assert frozenset(
        directory.type_for_class(name) for name in gpmc.LINKABLE_CLASSES
    ) == gpmc.LINKABLE_TYPES


def test_type_for_class_and_object_type_give_the_same_answer() -> None:
    """The lookup by name exists so that a caller holding a class need not
    build an entry to ask. If the two ever disagreed, the flag and the search
    would be answering different questions."""
    for class_name in ("organizationalUnit", "container", "builtinDomain", "domainDNS"):
        entry = FakeEntry("CN=x,DC=example,DC=test", {"objectClass": [class_name.encode()]})
        assert directory.type_for_class(class_name) == directory.object_type(entry)


def test_an_unknown_class_is_not_linkable() -> None:
    assert directory.type_for_class("nosuchClass") == "object"
    assert "object" not in gpmc.LINKABLE_TYPES


# ---------------------------------------------------------------------------
# The search
# ---------------------------------------------------------------------------


def test_every_linkable_class_reaches_the_search() -> None:
    for name in gpmc.LINKABLE_CLASSES:
        assert f"(objectClass={name})" in gpmc.LINK_TREE_FILTER


def test_the_search_also_finds_a_container_that_already_links_something() -> None:
    """Deliberately wider than the classes. A link on a plain container is a
    live link, and this tree is the only view that reports links by location —
    dropping the row would hide it rather than fix it."""
    assert "(gPLink=*)" in gpmc.LINK_TREE_FILTER


def test_a_plain_container_is_not_searched_for_on_its_own() -> None:
    """The wider clause is about links, not about containers. Without this,
    "(objectClass=container)" could creep back in and the five rows return."""
    assert "(objectClass=container)" not in gpmc.LINK_TREE_FILTER
    assert "(objectClass=builtinDomain)" not in gpmc.LINK_TREE_FILTER


def test_the_advanced_exclusion_wraps_whichever_filter_it_is_given() -> None:
    filtered = directory._tree_filter(False, gpmc.LINK_TREE_FILTER)

    assert gpmc.LINK_TREE_FILTER in filtered
    assert "(!(showInAdvancedViewOnly=TRUE))" in filtered
    assert directory._tree_filter(True, gpmc.LINK_TREE_FILTER) == gpmc.LINK_TREE_FILTER


# ---------------------------------------------------------------------------
# The expander
# ---------------------------------------------------------------------------


class FakeDn:
    """Stands in for ldb.Dn: stringifies, but is not iterable."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __str__(self) -> str:
        return self.text

    def __iter__(self):
        raise TypeError("'ldb.Dn' object is not iterable")


class FakeEntry:
    """Enough of an ldb.Message for summarize()."""

    def __init__(self, dn: str, attributes: dict[str, list[bytes]]) -> None:
        self.dn = FakeDn(dn)
        self._attributes = {"distinguishedName": [dn.encode()], **attributes}

    def keys(self) -> list[str]:
        return ["dn", *self._attributes]

    def __getitem__(self, name: str) -> Any:
        if name.lower() == "dn":
            return self.dn
        return self._attributes[name]

    def get(self, name: str, default: Any = None) -> Any:
        for key, value in self._attributes.items():
            if key.lower() == name.lower():
                return value
        return default


class RecordingConnection:
    """Answers every search with the same one child, and remembers the asking."""

    def __init__(self) -> None:
        self.expressions: list[str] = []

    def search(self, dn: str, *, expression: str, **rest: Any) -> list[FakeEntry]:
        self.expressions.append(expression)
        return [
            FakeEntry(
                f"OU=Workstations,{dn}",
                {"objectClass": [b"organizationalUnit"], "name": [b"Workstations"]},
            )
        ]


def test_the_expander_probe_asks_the_same_question_as_the_listing() -> None:
    """Two searches, one filter. Given the wider directory filter, the probe
    would report children for an OU whose only child is CN=Users — an expander
    that opens onto nothing, which is worse than no expander at all."""
    conn = RecordingConnection()

    nodes = directory.list_tree_children(
        conn, "DC=example,DC=test", container_filter=gpmc.LINK_TREE_FILTER
    )

    assert len(conn.expressions) == 2, "one listing, one expander probe"
    assert all(gpmc.LINK_TREE_FILTER in asked for asked in conn.expressions)
    assert nodes[0]["has_children"] is True


def test_the_directory_tree_still_asks_its_own_wider_question() -> None:
    """The filter is a parameter, not a replacement. The directory console
    shows everything that can hold children, and has to keep doing so."""
    conn = RecordingConnection()

    directory.list_tree_children(conn, "DC=example,DC=test")

    assert all(directory.CONTAINER_FILTER in asked for asked in conn.expressions)
    assert all("(gPLink=*)" not in asked for asked in conn.expressions)

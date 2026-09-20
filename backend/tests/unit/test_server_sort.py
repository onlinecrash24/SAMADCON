"""Lists are sorted by the server, before it cuts, in the column asked for.

A list capped at 2 000 of 10 000 objects is only "the first 2 000" if the
server orders them before it cuts. Sorted here afterwards, the 2 000 were
whichever the server returned first — the tester saw user 000140, then
000497, then 000581, in a list that claimed to be sorted.
"""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.ad import directory
from samadcon.ad.connection import SearchResult
from samadcon.core.errors import InvalidRequest


def entry(name: str, *, container: bool = False, description: str = "") -> dict[str, list[bytes]]:
    cls = b"organizationalUnit" if container else b"user"
    return {
        "distinguishedName": [f"CN={name},OU=Lab,DC=example,DC=test".encode()],
        "name": [name.encode()],
        "objectClass": [b"top", cls],
        "objectCategory": [b"CN=Organizational-Unit" if container else b"CN=Person"],
        "description": [description.encode()] if description else [],
    }


class OrderedConnection:
    """Returns entries in a fixed order — the server's — and records the controls."""

    class Info:
        base_dn = "DC=example,DC=test"

    def __init__(self, entries: list[Any]) -> None:
        self.info = OrderedConnection.Info()
        self.entries = entries
        self.controls: list[str] = []

    def search(self, base: str, *, controls: list[str] | None = None, **rest: Any) -> SearchResult:
        self.controls = list(controls or [])
        return SearchResult(entries=list(self.entries))


def test_the_sort_control_is_ldbs_string_form():
    # server_sort:<critical>:<reverse>:<attribute> — from ldb_controls.c.
    assert directory.sort_control("name", False) == "server_sort:0:0:name"
    assert directory.sort_control("name", True) == "server_sort:0:1:name"
    assert directory.sort_control("description", True) == "server_sort:0:1:description"
    # The type column is objectCategory: single-valued, unlike objectClass.
    assert directory.sort_control("type", False) == "server_sort:0:0:objectCategory"


def test_an_unknown_column_is_refused_not_guessed():
    with pytest.raises(InvalidRequest) as caught:
        directory.sort_control("sAMAccountName", False)
    assert caught.value.code == "unknown_sort_column"


def test_children_ask_the_server_to_sort_and_keep_its_order():
    # The server, asked for description descending, answers c, b, a — names
    # that would come out a, b, c if anything re-sorted them by name here.
    conn = OrderedConnection([
        entry("a", description="LAB 000003"),
        entry("b", description="LAB 000002"),
        entry("c", description="LAB 000001"),
    ][::-1])

    listing = directory.list_children(
        conn, "OU=Lab,DC=example,DC=test", sort="description", descending=True,
    )

    assert conn.controls == ["server_sort:0:1:description"]
    assert [item["name"] for item in listing["entries"]] == ["c", "b", "a"]


def test_containers_still_come_first_without_disturbing_the_order():
    conn = OrderedConnection([
        entry("zeta"),
        entry("Users", container=True),
        entry("alpha"),
        entry("Admins", container=True),
    ])

    listing = directory.list_children(conn, "OU=Lab,DC=example,DC=test")

    # Containers first, each half in the server's order — not re-sorted.
    assert [item["name"] for item in listing["entries"]] == ["Users", "Admins", "zeta", "alpha"]


def test_the_default_is_by_name_ascending():
    conn = OrderedConnection([entry("x")])
    directory.list_children(conn, "OU=Lab,DC=example,DC=test")
    assert conn.controls == ["server_sort:0:0:name"]


def test_search_asks_the_server_to_sort_too():
    conn = OrderedConnection([entry("b"), entry("a")])
    result = directory.search_objects(conn, query="lab", sort="name", descending=True)
    assert conn.controls == ["server_sort:0:1:name"]
    # And does not undo it.
    assert [item["name"] for item in result["entries"]] == ["b", "a"]

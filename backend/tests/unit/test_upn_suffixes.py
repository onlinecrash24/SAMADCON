"""The UPN suffix list is read from the forest, not typed."""

from __future__ import annotations

from typing import Any

from samadcon.ad import directory
from samadcon.ad.connection import SearchResult


class ForestConnection:
    """A forest with one extra domain and two hand-added suffixes."""

    class Info:
        base_dn = "DC=example,DC=test"
        config_dn = "CN=Configuration,DC=example,DC=test"
        dns_domain = "example.test"

    def __init__(self, upn_suffixes: list[str] | None = None) -> None:
        self.info = ForestConnection.Info()
        self.upn_suffixes = upn_suffixes
        self.asked: list[tuple[str, str]] = []

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        self.asked.append(("get", dn))
        assert dn == "CN=Partitions,CN=Configuration,DC=example,DC=test"
        if self.upn_suffixes is None:
            return {}
        return {"uPNSuffixes": [s.encode() for s in self.upn_suffixes]}

    def search(self, base: str, *, scope: int, expression: str, attrs: list[str]) -> SearchResult:
        self.asked.append(("search", expression))
        assert base == "CN=Partitions,CN=Configuration,DC=example,DC=test"
        assert scope == directory.SCOPE_ONELEVEL
        # The two domains, the config partition and an application partition —
        # only the two with a nETBIOSName are domains, and the filter says so.
        assert "(nETBIOSName=*)" in expression
        return SearchResult(entries=[
            {"dnsRoot": [b"example.test"]},
            {"dnsRoot": [b"child.example.test"]},
        ])


def test_the_domain_comes_first_then_hand_added_then_forest_domains():
    conn = ForestConnection(upn_suffixes=["corp.example.com", "Example.Test"])

    assert directory.upn_suffixes(conn) == [
        "example.test",
        "corp.example.com",
        "child.example.test",
    ]
    # "Example.Test" is the domain again in different case, and was not added twice.


def test_a_forest_with_nothing_added_offers_its_domains():
    conn = ForestConnection(upn_suffixes=None)
    assert directory.upn_suffixes(conn) == ["example.test", "child.example.test"]


def test_the_partitions_container_is_read_once_and_the_domains_once():
    conn = ForestConnection(upn_suffixes=[])
    directory.upn_suffixes(conn)
    assert [kind for kind, _ in conn.asked] == ["get", "search"]

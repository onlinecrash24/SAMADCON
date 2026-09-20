"""Hand-added UPN suffixes: read apart from the forest's domains, validated
before they are written, written as one replace."""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.ad import upn
from samadcon.ad.connection import SearchResult
from samadcon.core.errors import InvalidRequest


class Forest:
    class Info:
        config_dn = "CN=Configuration,DC=example,DC=test"
        dns_domain = "example.test"

    def __init__(self, added: list[str]) -> None:
        self.info = Forest.Info()
        self.added = added
        self.written: dict[str, Any] | None = None

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        assert dn == "CN=Partitions,CN=Configuration,DC=example,DC=test"
        return {"uPNSuffixes": [s.encode() for s in self.added]}

    def search(self, base: str, **rest: Any) -> SearchResult:
        return SearchResult(entries=[{"dnsRoot": [b"example.test"]}, {"dnsRoot": [b"child.example.test"]}])

    def modify_attributes(self, dn: str, changes: dict[str, Any]) -> dict[str, Any]:
        assert dn == "CN=Partitions,CN=Configuration,DC=example,DC=test"
        self.written = changes
        return {"uPNSuffixes": {"old": self.added, "new": changes["uPNSuffixes"]}}


def test_the_two_lists_are_kept_apart():
    conn = Forest(added=["corp.example.com"])
    assert upn.describe(conn) == {
        "added": ["corp.example.com"],
        "domains": ["example.test", "child.example.test"],
    }


def test_a_replace_writes_the_cleaned_list():
    conn = Forest(added=["old.example.org"])
    upn.set_suffixes(conn, [" Corp.Example.com ", "corp.example.COM", "mail.example.org"])
    assert conn.written == {"uPNSuffixes": ["Corp.Example.com", "mail.example.org"]}


def test_an_empty_list_clears_the_attribute():
    conn = Forest(added=["x.example.org"])
    upn.set_suffixes(conn, [])
    # modify_attributes turns [] into a delete of the attribute.
    assert conn.written == {"uPNSuffixes": []}


@pytest.mark.parametrize("bad", ["no spaces.example", "a@b.example", "-lead.example", "trail-.example", "a..b", "x" * 256])
def test_a_suffix_that_is_not_a_dns_name_is_refused(bad: str):
    conn = Forest(added=[])
    with pytest.raises(InvalidRequest) as caught:
        upn.set_suffixes(conn, [bad])
    assert caught.value.code == "invalid_upn_suffix"
    assert conn.written is None


def test_a_domain_of_the_forest_cannot_be_added_as_a_suffix():
    conn = Forest(added=[])
    with pytest.raises(InvalidRequest) as caught:
        upn.set_suffixes(conn, ["Child.Example.Test"])
    assert caught.value.code == "suffix_is_a_domain"
    assert conn.written is None

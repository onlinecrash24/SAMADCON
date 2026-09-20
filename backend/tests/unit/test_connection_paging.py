"""A search walks every page the server offers, not only the first.

SamDB is opened without ldb's client-side paged_searches module, so the
paged_results control this sends is answered with one page and a cookie. The
cookie has to be read out of the reply and sent back; until it was, every
container showed exactly one page — 500 objects in a 100 000-object OU, with
no truncation notice because the notice compared against a limit one page
could never reach.

These run without a domain: the samdb is a fake that hands out pages the way
libldb prints them.
"""

from __future__ import annotations

from typing import Any

from samadcon.ad.connection import DirectoryConnection, DomainInfo, _paging_cookie
from samadcon.config import Settings

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


class ReplyControl:
    """What str() of an ldb reply control looks like: name, criticality, cookie."""

    def __init__(self, cookie: str) -> None:
        self.cookie = cookie

    def __str__(self) -> str:
        return f"paged_results:0:{self.cookie}"


class Page(list):
    """An ldb.Result stand-in: iterable over its messages, with .controls."""

    def __init__(self, entries: list[Any], cookie: str) -> None:
        super().__init__(entries)
        self.controls = [ReplyControl(cookie)]


class PagingSamdb:
    """Hands out pages in order and records the control string of every call."""

    def __init__(self, pages: list[Page]) -> None:
        self.pages = pages
        self.calls: list[list[str]] = []

    def search(self, **kwargs: Any) -> Page:
        self.calls.append(list(kwargs["controls"]))
        return self.pages[len(self.calls) - 1]


def connection(samdb: PagingSamdb, **settings: Any) -> DirectoryConnection:
    return DirectoryConnection(samdb, "dc1.example.test", INFO, Settings(**settings))


def test_every_page_is_fetched_and_the_cookie_travels_back():
    samdb = PagingSamdb([
        Page([f"u{i}" for i in range(500)], cookie="Zmlyc3Q="),
        Page([f"u{i}" for i in range(500, 1000)], cookie="c2Vjb25k"),
        Page([f"u{i}" for i in range(1000, 1300)], cookie=""),
    ])
    result = connection(samdb, ldap_page_size=500).search(expression="(objectClass=user)")

    assert len(result) == 1300
    assert result.truncated is False
    assert len(samdb.calls) == 3

    # The first request has no cookie; each later one carries exactly the
    # cookie the previous reply handed back, after the page size.
    assert samdb.calls[0] == ["paged_results:1:500"]
    assert samdb.calls[1] == ["paged_results:1:500:Zmlyc3Q="]
    assert samdb.calls[2] == ["paged_results:1:500:c2Vjb25k"]


def test_the_ceiling_stops_paging_and_marks_the_result():
    pages = [Page([f"u{i}" for i in range(500 * n, 500 * (n + 1))], cookie=f"c{n}") for n in range(10)]
    samdb = PagingSamdb(pages)
    result = connection(samdb, ldap_page_size=500).search(
        expression="(objectClass=user)", max_results=1200,
    )

    assert len(result) == 1200
    assert result.truncated is True
    # 500, 1000, 1500 > 1200 — the third page tipped it, no fourth was asked for.
    assert len(samdb.calls) == 3


def test_a_callers_own_controls_ride_along_on_every_page():
    samdb = PagingSamdb([Page(["a"], cookie="eA=="), Page(["b"], cookie="")])
    connection(samdb, ldap_page_size=1).search(
        expression="(objectClass=*)", controls=["show_deleted:1"],
    )
    assert samdb.calls == [
        ["show_deleted:1", "paged_results:1:1"],
        ["show_deleted:1", "paged_results:1:1:eA=="],
    ]


def test_the_cookie_is_read_from_either_shape_libldb_prints():
    class C:
        def __init__(self, text: str) -> None:
            self.text = text

        def __str__(self) -> str:
            return self.text

    # Reply shape: name, criticality, cookie.
    assert _paging_cookie([C("paged_results:0:YWJj")]) == "YWJj"
    # Request shape, should a build print it that way: name, crit, size, cookie.
    assert _paging_cookie([C("paged_results:1:500:YWJj")]) == "YWJj"
    # An empty cookie means the last page.
    assert _paging_cookie([C("paged_results:0:")]) == ""
    # Other controls are not cookies, and no controls at all is not either.
    assert _paging_cookie([C("show_deleted:1")]) == ""
    assert _paging_cookie(None) == ""

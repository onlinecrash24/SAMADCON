"""Extra list columns: read only when asked, rendered as text, dates as ISO."""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.ad import directory
from samadcon.ad.connection import SearchResult
from samadcon.core.errors import InvalidRequest


class Recorder:
    class Info:
        base_dn = "DC=example,DC=test"

    def __init__(self, entries: list[Any]) -> None:
        self.info = Recorder.Info()
        self.entries = entries
        self.attrs: list[str] = []

    def search(self, base: str, *, attrs: list[str], **rest: Any) -> SearchResult:
        self.attrs = attrs
        return SearchResult(entries=list(self.entries))


def user(**extra: Any) -> dict[str, list[bytes]]:
    base = {
        "distinguishedName": [b"CN=anna,OU=Users,DC=example,DC=test"],
        "name": [b"anna"],
        "objectClass": [b"top", b"person", b"user"],
        "objectCategory": [b"CN=Person,CN=Schema"],
    }
    base.update({k: [v.encode() if isinstance(v, str) else v] for k, v in extra.items()})
    return base


def test_only_the_asked_for_attributes_are_read():
    conn = Recorder([user()])
    directory.list_children(conn, "OU=Users,DC=example,DC=test", columns=["department", "title"])
    extra = [a for a in conn.attrs if a not in directory.SUMMARY_ATTRS]
    assert extra == ["department", "title"]


def test_nothing_extra_is_read_when_nothing_is_asked_for():
    conn = Recorder([user()])
    listing = directory.list_children(conn, "OU=Users,DC=example,DC=test")
    assert conn.attrs == directory.SUMMARY_ATTRS
    assert listing["entries"][0]["columns"] == {}


def test_columns_come_back_as_text_and_absent_as_none():
    conn = Recorder([user(department="IT", telephoneNumber="+49 30 1")])
    listing = directory.list_children(
        conn, "OU=Users,DC=example,DC=test", columns=["department", "telephone", "company"],
    )
    assert listing["entries"][0]["columns"] == {
        "department": "IT",
        "telephone": "+49 30 1",
        "company": None,
    }


def test_the_two_date_encodings_both_come_out_as_iso():
    # whenChanged is GeneralizedTime; lastLogonTimestamp is a FILETIME, 100 ns
    # ticks since 1601 — computed here rather than typed, so the test cannot
    # be wrong about the epoch in the same way the code could.
    from datetime import UTC, datetime

    moment = datetime(2022, 6, 27, 18, 40, tzinfo=UTC)
    ticks = (int(moment.timestamp()) + 11644473600) * 10_000_000
    conn = Recorder([user(whenChanged="20260923161530.0Z", lastLogonTimestamp=str(ticks))])
    listing = directory.list_children(
        conn, "OU=Users,DC=example,DC=test", columns=["when_changed", "last_logon"],
    )
    cols = listing["entries"][0]["columns"]
    assert cols["when_changed"].startswith("2026-09-23T16:15:30")
    assert cols["last_logon"].startswith("2022-06-27T18:40:00")


def test_an_unknown_column_is_refused_before_anything_is_read():
    conn = Recorder([user()])
    with pytest.raises(InvalidRequest) as caught:
        directory.list_children(conn, "OU=Users,DC=example,DC=test", columns=["password"])
    assert caught.value.code == "unknown_column"
    assert conn.attrs == []


def test_every_column_can_be_sorted_on_the_server():
    for column in directory.LIST_COLUMNS:
        assert directory.sort_control(column, False) == f"server_sort:0:0:{directory.LIST_COLUMNS[column]}"

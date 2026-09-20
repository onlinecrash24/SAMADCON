"""The "Other…" lists: read as lists, written as lists, and the two shapes
kept apart from the single-valued fields."""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.ad import users
from samadcon.core.errors import InvalidRequest


class Recorder:
    class Info:
        base_dn = "DC=example,DC=test"

    def __init__(self) -> None:
        self.info = Recorder.Info()
        self.changes: dict[str, Any] | None = None

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        return {"userAccountControl": [b"512"]}

    def modify_attributes(self, dn: str, changes: dict[str, Any]) -> dict[str, Any]:
        self.changes = changes
        return {k: {"old": None, "new": v} for k, v in changes.items()}


def test_the_other_lists_are_fetched_and_rendered_as_lists():
    for attribute in users.USER_MULTI_FIELDS.values():
        assert attribute in users.DETAIL_ATTRS, attribute
    # A rendered user carries them as lists, empty when absent.
    conn = Recorder()
    entry = {
        "distinguishedName": [b"CN=a,DC=example,DC=test"],
        "otherTelephone": [b"+49 30 1", b"+49 30 2"],
        "objectClass": [b"user"],
    }
    detail = users._render_user(conn, entry)
    assert detail["attributes"]["other_telephone"] == ["+49 30 1", "+49 30 2"]
    assert detail["attributes"]["other_web_page"] == []


def test_a_list_is_written_as_a_list_trimmed_and_without_blanks():
    conn = Recorder()
    users.update_user(conn, "CN=a,DC=example,DC=test", attributes={
        "other_telephone": [" +49 30 1 ", "", "+49 30 2"],
    })
    assert conn.changes == {"otherTelephone": ["+49 30 1", "+49 30 2"]}


def test_a_single_string_to_a_list_field_is_one_value_and_null_clears_it():
    conn = Recorder()
    users.update_user(conn, "CN=a,DC=example,DC=test", attributes={"other_pager": "123"})
    assert conn.changes == {"otherPager": ["123"]}
    users.update_user(conn, "CN=a,DC=example,DC=test", attributes={"other_pager": None})
    assert conn.changes == {"otherPager": []}


def test_a_list_to_a_single_valued_field_is_refused():
    conn = Recorder()
    with pytest.raises(InvalidRequest) as caught:
        users.update_user(conn, "CN=a,DC=example,DC=test", attributes={"telephone": ["1", "2"]})
    assert caught.value.code == "field_takes_one_value"
    assert conn.changes is None


def test_a_non_string_inside_a_list_is_refused():
    conn = Recorder()
    with pytest.raises(InvalidRequest) as caught:
        users.update_user(conn, "CN=a,DC=example,DC=test", attributes={"other_mobile": ["1", 2]})
    assert caught.value.code == "field_takes_a_list"

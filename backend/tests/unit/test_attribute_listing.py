"""Rendering an object's raw attributes.

An ldb.Message is not a dict: ``keys()`` includes "dn", whose value is an
ldb.Dn rather than a list of values. Iterating it raises, which is exactly how
the attribute editor first broke against a live DC. These tests reproduce that
shape without needing Samba.
"""

from __future__ import annotations

from typing import Any

import pytest

from samcon.ad.directory import get_attributes
from samcon.core.errors import NotFound


class FakeDn:
    """Stands in for ldb.Dn: stringifies, but is not iterable."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __str__(self) -> str:
        return self.text

    def __iter__(self):
        raise TypeError("'ldb.Dn' object is not iterable")


class FakeMessage:
    """Enough of an ldb.Message for the listing code."""

    def __init__(self, dn: str, attributes: dict[str, list[bytes]]) -> None:
        self.dn = FakeDn(dn)
        self._attributes = attributes

    def keys(self) -> list[str]:
        # The real thing puts "dn" in here alongside the attributes.
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


class FakeConnection:
    def __init__(self, entry: Any) -> None:
        self.entry = entry

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        return self.entry


DN = "CN=Max,OU=Users,DC=test,DC=lan"


def listing(**attributes: list[bytes]) -> dict[str, Any]:
    entry = FakeMessage(DN, attributes)
    return get_attributes(FakeConnection(entry), DN)


def test_dn_is_not_treated_as_an_attribute():
    """The regression this file exists for: iterating entry["dn"] raises."""
    result = listing(cn=[b"Max"])
    assert "dn" not in result["attributes"]
    assert result["dn"] == DN


def test_text_values_are_returned_as_text():
    result = listing(cn=[b"Max Muster"])
    assert result["attributes"]["cn"]["values"] == [{"text": "Max Muster"}]


def test_multi_valued_attributes_keep_every_value():
    result = listing(memberOf=[b"CN=A,DC=t", b"CN=B,DC=t"])
    values = result["attributes"]["memberOf"]["values"]
    assert [value["text"] for value in values] == ["CN=A,DC=t", "CN=B,DC=t"]


def test_binary_values_are_reported_as_base64_with_a_size():
    raw = bytes([1, 5, 0, 0, 0, 0, 0, 5, 0xFF, 0xFE])
    value = listing(objectSid=[raw])["attributes"]["objectSid"]["values"][0]
    assert value["size"] == len(raw)
    assert "binary" in value
    assert "text" not in value


def test_binary_attributes_are_not_editable():
    """Retyping a base64 blob by hand corrupts the object."""
    raw = bytes([0x00, 0xFF, 0xFE])
    assert listing(objectSid=[raw])["attributes"]["objectSid"]["editable"] is False


def test_directory_managed_attributes_are_not_editable():
    result = listing(objectClass=[b"user"], name=[b"Max"], memberOf=[b"CN=G,DC=t"])
    assert result["attributes"]["objectClass"]["editable"] is False
    # name follows the RDN; editing it here would desynchronise the two.
    assert result["attributes"]["name"]["editable"] is False
    # Membership is maintained from the group's side.
    assert result["attributes"]["memberOf"]["editable"] is False


def test_the_logon_name_stays_editable_in_the_raw_editor():
    """Deliberate: changing a logon name is a legitimate act, and the directory
    enforces uniqueness itself. The typed property sheet omits it because
    renaming is its own action — the raw editor is the escape hatch."""
    assert listing(sAMAccountName=[b"max"])["attributes"]["sAMAccountName"]["editable"] is True


def test_ordinary_attributes_are_editable():
    result = listing(comment=[b"anything"], department=[b"QA"])
    assert result["attributes"]["comment"]["editable"] is True
    assert result["attributes"]["department"]["editable"] is True


def test_utf8_survives():
    result = listing(displayName=["Müller, Jörg".encode()])
    assert result["attributes"]["displayName"]["values"][0]["text"] == "Müller, Jörg"


def test_a_missing_object_raises_not_found():
    class Empty:
        def get(self, dn: str, attrs: list[str] | None = None) -> Any:
            return None

    with pytest.raises(NotFound):
        get_attributes(Empty(), DN)

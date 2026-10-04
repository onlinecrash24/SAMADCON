"""Rendering an object's raw attributes.

An ldb.Message is not a dict: ``keys()`` includes "dn", whose value is an
ldb.Dn rather than a list of values. Iterating it raises, which is exactly how
the attribute editor first broke against a live DC. These tests reproduce that
shape without needing Samba.
"""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.ad.directory import get_attributes
from samadcon.core.errors import NotFound


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


# ---------------------------------------------------------------------------
# Attributes without a value, as RSAT's attribute editor lists them
# ---------------------------------------------------------------------------

SCHEMA_DN = "CN=Schema,CN=Configuration,DC=test,DC=lan"

# Measured on a Samba 4.22 DC (CN=Administrator): 391 attributes allowed,
# 279 of them writable for the administrator, 38 with a value. The schema
# entries below are the ones it returned for these six.
MEASURED_SCHEMA = {
    "objectGUID": {"attributeSyntax": b"2.5.5.10", "isSingleValued": b"TRUE",
                   "systemOnly": b"TRUE", "systemFlags": b"19"},
    "otherMobile": {"attributeSyntax": b"2.5.5.12", "isSingleValued": b"FALSE",
                    "systemOnly": b"FALSE", "systemFlags": b"16"},
    "info": {"attributeSyntax": b"2.5.5.12", "isSingleValued": b"TRUE",
             "systemOnly": b"FALSE", "systemFlags": b"16"},
    "tokenGroups": {"attributeSyntax": b"2.5.5.17", "isSingleValued": b"FALSE",
                    "systemOnly": b"FALSE", "systemFlags": b"134217748"},
    "thumbnailPhoto": {"attributeSyntax": b"2.5.5.10", "isSingleValued": b"TRUE",
                       "systemOnly": b"FALSE", "systemFlags": b"16"},
    "memberOf": {"attributeSyntax": b"2.5.5.1", "isSingleValued": b"FALSE",
                 "systemOnly": b"TRUE", "systemFlags": b"17", "linkID": b"3"},
    "department": {"attributeSyntax": b"2.5.5.12", "isSingleValued": b"TRUE",
                   "systemOnly": b"FALSE", "systemFlags": b"16"},
    "cn": {"attributeSyntax": b"2.5.5.12", "isSingleValued": b"TRUE",
           "systemOnly": b"FALSE", "systemFlags": b"16"},
}


def schema_entry(name: str) -> FakeMessage:
    fields = {key: [value] for key, value in MEASURED_SCHEMA[name].items()}
    return FakeMessage(f"CN={name},{SCHEMA_DN}", {"lDAPDisplayName": [name.encode()], **fields})


class SchemaConnection(FakeConnection):
    def __init__(self, entry: Any) -> None:
        super().__init__(entry)
        self.info = type("Info", (), {"schema_dn": SCHEMA_DN})()
        self.asked: list[str] = []

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        self.asked = list(attrs or [])
        return self.entry

    def search(self, base: str, **kwargs: Any) -> list[FakeMessage]:
        assert base == SCHEMA_DN
        return [schema_entry(name) for name in MEASURED_SCHEMA]


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    from samadcon.core.cache import schema_cache

    schema_cache.clear()
    yield
    schema_cache.clear()


ALLOWED = [b"cn", b"department", b"info", b"otherMobile", b"thumbnailPhoto",
           b"tokenGroups", b"memberOf", b"objectGUID"]
WRITABLE = [b"cn", b"department", b"info", b"otherMobile", b"thumbnailPhoto"]


def full_listing(include_empty: bool = True) -> tuple[dict[str, Any], SchemaConnection]:
    entry = FakeMessage(DN, {
        "cn": [b"Max"],
        "allowedAttributes": ALLOWED,
        "allowedAttributesEffective": WRITABLE,
    })
    conn = SchemaConnection(entry)
    return get_attributes(conn, DN, include_empty=include_empty)["attributes"], conn


def test_without_the_switch_only_attributes_with_a_value_are_listed():
    attributes, conn = full_listing(include_empty=False)
    assert set(attributes) == {"cn"}
    assert "allowedAttributes" not in conn.asked


def test_with_the_switch_every_allowed_attribute_is_listed():
    attributes, conn = full_listing()
    assert set(attributes) == {name.decode() for name in ALLOWED}
    assert {"allowedAttributes", "allowedAttributesEffective"} <= set(conn.asked)


def test_the_lists_that_answer_the_question_are_not_attributes_of_the_object():
    attributes, _ = full_listing()
    assert "allowedAttributes" not in attributes
    assert "allowedAttributesEffective" not in attributes


def test_an_empty_text_attribute_the_account_may_write_is_editable():
    attributes, _ = full_listing()
    assert attributes["info"] == {"values": [], "editable": True, "single_valued": True,
                                  "empty": True, "note": None}
    assert attributes["otherMobile"]["single_valued"] is False
    assert attributes["otherMobile"]["editable"] is True


@pytest.mark.parametrize(
    ("name", "note"),
    [
        ("thumbnailPhoto", "binary"),
        ("tokenGroups", "constructed"),
        ("memberOf", "backlink"),
        ("objectGUID", "system_only"),
    ],
)
def test_empty_attributes_that_cannot_be_typed_in_say_why(name, note):
    attributes, _ = full_listing()
    assert attributes[name]["editable"] is False
    assert attributes[name]["note"] == note


def test_an_attribute_the_account_may_not_write_is_not_offered():
    entry = FakeMessage(DN, {
        "cn": [b"Max"],
        "allowedAttributes": [b"cn", b"info"],
        "allowedAttributesEffective": [b"cn"],
    })
    attributes = get_attributes(SchemaConnection(entry), DN, include_empty=True)["attributes"]
    assert attributes["info"]["editable"] is False
    assert attributes["info"]["note"] == "not_permitted"


def test_attributes_with_a_value_say_whether_they_take_one_or_many():
    attributes, _ = full_listing()
    assert attributes["cn"]["single_valued"] is True
    assert attributes["cn"]["values"] == [{"text": "Max"}]


def test_names_are_matched_without_regard_to_case():
    """allowedAttributes and the object can spell a name differently."""
    entry = FakeMessage(DN, {
        "CN": [b"Max"],
        "allowedAttributes": [b"cn"],
        "allowedAttributesEffective": [b"cn"],
    })
    attributes = get_attributes(SchemaConnection(entry), DN, include_empty=True)["attributes"]
    assert list(attributes) == ["CN"]

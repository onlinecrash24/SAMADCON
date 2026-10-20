"""SAMADCON's own settings, kept in the domain it manages.

A tester runs Authelia, which needs a mail address on every account, and
asked for mandatory fields whenever a user is registered. The maintainer
wanted the setting in AD itself rather than in the container: one object,
one JSON document, the same for every SAMADCON instance on the domain.

Measured on zmb-ad (Samba 4.22.11, 2026-10-20):
- ``msDS-App-Configuration`` exists, subclass of ``applicationSettings``,
  possSuperiors include ``container``;
- ``msDS-Settings`` comes with it: Unicode string, multi-valued, rangeUpper
  1000000;
- ``CN=Program Data`` is a container; its read entry for Authenticated Users
  (A;;LCRPLORC;;;AU) is not inheritable, so the object gets one of its own.
"""

from __future__ import annotations

import json

import pytest

from samadcon.ad import app_settings, users
from samadcon.core.errors import Conflict, InvalidRequest

BASE = "DC=myantispam,DC=local"


class _Info:
    base_dn = BASE


class _Conn:
    info = _Info()


def test_the_settings_live_under_program_data():
    assert app_settings.settings_dn(_Conn()) == f"CN=SAMADCON,CN=Program Data,{BASE}"
    assert app_settings.OBJECT_CLASS == "msDS-App-Configuration"
    assert app_settings.ATTRIBUTE == "msDS-Settings"
    assert app_settings.READ_ACE == "(A;;LCRPLORC;;;AU)"


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


def test_no_document_means_the_defaults():
    # A new user's CN from first and last name, as ADUC builds it.
    assert app_settings.parse(None) == {
        "version": 1,
        "users": {"required_fields": [], "cn_source": "name"},
    }


def test_a_document_reads_as_written():
    text = json.dumps({"version": 1, "users": {"required_fields": ["mail"]}})
    assert app_settings.parse(text)["users"]["required_fields"] == ["mail"]


def test_a_broken_document_is_reported_not_replaced():
    with pytest.raises(Conflict) as caught:
        app_settings.parse("{not json")
    assert caught.value.code == "settings_corrupt"


def test_what_this_version_does_not_know_is_kept():
    """A newer SAMADCON may have written more; saving here must not drop it."""
    text = json.dumps(
        {"version": 1, "users": {"required_fields": [], "naming": "x"}, "gpo": {"y": 1}}
    )
    written = json.loads(app_settings.render(text, required_fields=["mail"]))
    assert written == {
        "version": 1,
        "users": {"required_fields": ["mail"], "naming": "x", "cn_source": "name"},
        "gpo": {"y": 1},
    }


def test_a_new_document_starts_from_the_defaults():
    assert json.loads(app_settings.render(None, required_fields=["mail"])) == {
        "version": 1,
        "users": {"required_fields": ["mail"], "cn_source": "name"},
    }


def test_the_cn_can_come_from_the_logon_name():
    """One tester wanted the logon name as the CN, another the person's name."""
    text = app_settings.render(None, required_fields=[], cn_source="logon")
    assert app_settings.parse(text)["users"]["cn_source"] == "logon"


def test_leaving_the_cn_source_out_keeps_what_was_set():
    text = app_settings.render(None, required_fields=[], cn_source="logon")
    again = app_settings.render(text, required_fields=["mail"])
    assert app_settings.parse(again)["users"]["cn_source"] == "logon"


def test_a_cn_source_that_does_not_exist_is_refused():
    with pytest.raises(InvalidRequest) as caught:
        app_settings.render(None, required_fields=[], cn_source="initials")
    assert caught.value.code == "invalid_setting"
    assert caught.value.context == {"setting": "users.cn_source", "given": "initials"}


# ---------------------------------------------------------------------------
# Which fields may be required
# ---------------------------------------------------------------------------


def test_required_fields_are_checked_and_deduplicated_in_order():
    assert app_settings.clean_required(["mail", "department", "mail"]) == ["mail", "department"]


@pytest.mark.parametrize("field", ["no_such_field", "upn", "manager"])
def test_a_field_that_cannot_be_required_is_refused(field):
    # upn is always set; manager is a reference, not something typed.
    with pytest.raises(InvalidRequest) as caught:
        app_settings.clean_required(["mail", field])
    assert caught.value.code == "field_not_requirable"
    assert caught.value.context == {"field": field}


def test_the_requirable_fields_are_the_typed_user_fields():
    requirable = app_settings.REQUIRABLE_USER_FIELDS
    assert "mail" in requirable and "department" in requirable
    assert "upn" not in requirable and "manager" not in requirable
    assert set(requirable) <= set(users.USER_FIELDS)


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


class _Stored:
    info = _Info()

    def __init__(self, text: str | None):
        self.text = text

    def get(self, dn, attrs=None):
        return None if self.text is None else {"msDS-Settings": [self.text]}


def test_a_save_against_a_changed_document_is_refused():
    conn = _Stored(json.dumps({"version": 1, "users": {"required_fields": ["mail"]}}))
    with pytest.raises(Conflict) as caught:
        app_settings.write(conn, required_fields=[], expected="something older")
    assert caught.value.code == "settings_changed"


# ---------------------------------------------------------------------------
# Creating a user
# ---------------------------------------------------------------------------


def test_a_new_user_without_a_required_field_is_refused_before_anything_is_written(
    monkeypatch,
):
    monkeypatch.setattr(users, "required_user_fields", lambda conn: ["mail"])
    with pytest.raises(InvalidRequest) as caught:
        users.create_user(
            None,
            parent_dn=f"OU=Staff,{BASE}",
            sam_account_name="anna",
            password="Secret-123",
            attributes={"first_name": "Anna", "mail": "   "},
        )
    assert caught.value.code == "required_field_missing"
    assert caught.value.context == {"fields": ["mail"]}


@pytest.mark.parametrize("mail", ["anna", "anna@", "@example.test", "anna @example.test"])
def test_a_mail_address_that_is_not_one_is_refused(monkeypatch, mail):
    monkeypatch.setattr(users, "required_user_fields", lambda conn: [])
    with pytest.raises(InvalidRequest) as caught:
        users.create_user(
            None,
            parent_dn=f"OU=Staff,{BASE}",
            sam_account_name="anna",
            password="Secret-123",
            attributes={"mail": mail},
        )
    assert caught.value.code == "invalid_mail"

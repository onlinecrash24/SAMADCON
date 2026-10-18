""""Must change password at next logon" and "Password never expires".

ADUC treats the two as exclusive: ticking one clears the other. SAMADCON let
both stand. A tester ticked "must change", saved with "never expires", and
reopened the account with both ticked; a copy of a template whose password
never expires came out the same way. The server now refuses the pair
wherever it could be written, before anything is written.
"""

from __future__ import annotations

import pytest

from samadcon.ad import uac, users
from samadcon.core.errors import Conflict, InvalidRequest


def test_a_new_account_with_both_is_refused_before_anything_is_written():
    # conn=None: the refusal has to come before the directory is touched.
    with pytest.raises(InvalidRequest) as caught:
        users.create_user(
            None,
            parent_dn="OU=Staff,DC=example,DC=lan",
            sam_account_name="anna",
            password="Secret-123",
            must_change_password=True,
            flags={"password_never_expires": True},
        )
    assert caught.value.code == "must_change_with_never_expires"


def test_a_copy_takes_never_expires_from_the_template():
    template = uac.NORMAL_ACCOUNT | uac.DONT_EXPIRE_PASSWD
    assert users.copied_flags(template, None)["password_never_expires"] is True


def test_a_copy_can_drop_never_expires_from_the_template():
    template = uac.NORMAL_ACCOUNT | uac.DONT_EXPIRE_PASSWD
    assert users.copied_flags(template, False)["password_never_expires"] is False


def test_a_copy_can_add_never_expires():
    assert users.copied_flags(uac.NORMAL_ACCOUNT, True)["password_never_expires"] is True


def test_must_change_wins_over_never_expires_the_template_only_implied():
    template = uac.NORMAL_ACCOUNT | uac.DONT_EXPIRE_PASSWD
    assert "password_never_expires" not in users.copied_flags(template, None, must_change=True)


def test_a_copy_never_takes_the_disabled_state():
    template = uac.NORMAL_ACCOUNT | uac.ACCOUNTDISABLE
    assert "account_disabled" not in users.copied_flags(template, None)


class _Account:
    """An account whose userAccountControl is known; records any write."""

    def __init__(self, value: int):
        self.value = value
        self.writes = 0

    def get(self, dn, attrs=None):
        return {"userAccountControl": [str(self.value)]}

    def modify(self, message):
        self.writes += 1


NEVER_EXPIRES = uac.NORMAL_ACCOUNT | uac.DONT_EXPIRE_PASSWD


def test_must_change_is_refused_on_an_account_whose_password_never_expires():
    conn = _Account(NEVER_EXPIRES)
    with pytest.raises(Conflict) as caught:
        users.set_must_change_password(conn, "CN=anna,DC=example,DC=lan", True)
    assert caught.value.code == "must_change_with_never_expires"
    assert conn.writes == 0


def test_a_reset_with_must_change_is_refused_before_the_password_is_set():
    """Otherwise the password would be changed and the flag refused after."""
    conn = _Account(NEVER_EXPIRES)
    with pytest.raises(Conflict):
        users.set_password(conn, "CN=anna,DC=example,DC=lan", "Secret-123", must_change=True)
    assert conn.writes == 0

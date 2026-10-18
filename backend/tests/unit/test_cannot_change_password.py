"""ADUC's "User cannot change password", as ADUC writes it.

Not a bit of userAccountControl — KB 305144 says PASSWD_CANT_CHANGE cannot be
set there, and ADUC does not touch it. The option lives in the ACL, on the
"Change Password" right (ab721a53-…). Measured on zmb-ad (Samba 4.22.11)
with ADUC on WIN11-PVE, 2026-10-18, on CN=testmann:

    before:   (OA;;CR;ab721a53-…;;PS)(OA;;CR;ab721a53-…;;WD)   uAC 512
    ticked:   (OD;;CR;ab721a53-…;;PS)(OD;;CR;ab721a53-…;;WD)   uAC 512
    cleared:  (OA;;CR;ab721a53-…;;WD)(OA;;CR;ab721a53-…;;WD)   uAC 512

ADUC turns both allow entries into denies. Clearing it again left Everyone
twice and SELF missing; SAMADCON restores what was there before instead —
SELF and Everyone, once each. Together with "User must change password at
next logon" ADUC refuses to save: "Die zwei Optionen … dürfen nicht zusammen
für denselben Benutzer ausgewählt werden."
"""

from __future__ import annotations

import pytest

from samadcon.ad import users
from samadcon.core.errors import Conflict

G = "ab721a53-1e2f-11d0-9819-00aa0040529b"
DOMAIN = "S-1-5-21-1-2-3"

ALLOW_SELF = f"(OA;;CR;{G};;PS)"
ALLOW_EVERYONE = f"(OA;;CR;{G};;WD)"
DENY_SELF = f"(OD;;CR;{G};;PS)"
DENY_EVERYONE = f"(OD;;CR;{G};;WD)"
ADMINS = "(A;;RPWPCRCCDCLCLORCWOWDSDDTSW;;;DA)"
INHERITED = (
    "(OA;CIID;RP;4c164200-20c0-11d0-a768-00aa006e0529;bf967aba-0de6-11d0-a285-00aa003049e2;RU)"
)

BEFORE = [ALLOW_SELF, ALLOW_EVERYONE, ADMINS, INHERITED]
TICKED = [DENY_SELF, DENY_EVERYONE, ADMINS, INHERITED]
CLEARED_BY_ADUC = [ALLOW_EVERYONE, ALLOW_EVERYONE, ADMINS, INHERITED]


def test_the_measured_states_read_as_aduc_shows_them():
    assert users.cannot_change_in(BEFORE, DOMAIN) is False
    assert users.cannot_change_in(TICKED, DOMAIN) is True
    assert users.cannot_change_in(CLEARED_BY_ADUC, DOMAIN) is False


def test_ticking_turns_both_allows_into_denies_ahead_of_the_rest():
    assert users.with_cannot_change(BEFORE, True, DOMAIN) == TICKED


def test_clearing_puts_back_self_and_everyone_before_the_inherited_entries():
    assert users.with_cannot_change(TICKED, False, DOMAIN) == [
        ADMINS,
        ALLOW_SELF,
        ALLOW_EVERYONE,
        INHERITED,
    ]


def test_clearing_mends_what_aduc_left_behind():
    """Everyone twice and SELF missing becomes SELF and Everyone, once each."""
    assert users.with_cannot_change(CLEARED_BY_ADUC, False, DOMAIN) == [
        ADMINS,
        ALLOW_SELF,
        ALLOW_EVERYONE,
        INHERITED,
    ]


def test_samba_s_spelling_is_recognised():
    spelled = [f"(OD;;CR;{G.upper()};;S-1-5-10)", f"(OD;;0x00000100;{G};;S-1-1-0)", ADMINS]
    assert users.cannot_change_in(spelled, DOMAIN) is True
    # Already says it, in another spelling: nothing to write.
    assert users.with_cannot_change(spelled, True, DOMAIN) == spelled


def test_setting_what_is_already_there_changes_nothing():
    assert users.with_cannot_change(TICKED, True, DOMAIN) == TICKED


def test_an_inherited_deny_is_neither_counted_nor_removed():
    inherited_deny = f"(OD;CIID;CR;{G};;WD)"
    aces = [ALLOW_SELF, ALLOW_EVERYONE, inherited_deny]
    assert users.cannot_change_in(aces, DOMAIN) is False
    assert inherited_deny in users.with_cannot_change(aces, True, DOMAIN)


# ---------------------------------------------------------------------------
# Together with "must change at next logon"
# ---------------------------------------------------------------------------


class _Account:
    def __init__(self, pwd_last_set: str = "133000000000000000", uac: str = "512"):
        self.values = {"pwdLastSet": [pwd_last_set], "userAccountControl": [uac]}
        self.writes = 0

    def get(self, dn, attrs=None):
        return self.values

    def modify(self, message):
        self.writes += 1


def test_cannot_change_is_refused_while_the_user_must_change(monkeypatch):
    conn = _Account(pwd_last_set="0")
    monkeypatch.setattr(users, "cannot_change_password", lambda c, d: False)
    with pytest.raises(Conflict) as caught:
        users.set_cannot_change_password(conn, "CN=testmann", True)
    assert caught.value.code == "must_change_with_cannot_change"
    assert conn.writes == 0


def test_must_change_is_refused_while_the_user_cannot_change(monkeypatch):
    conn = _Account()
    monkeypatch.setattr(users, "cannot_change_password", lambda c, d: True)
    with pytest.raises(Conflict) as caught:
        users.set_must_change_password(conn, "CN=testmann", True)
    assert caught.value.code == "must_change_with_cannot_change"
    assert conn.writes == 0


def test_a_reset_with_must_change_is_refused_before_the_password_is_set(monkeypatch):
    conn = _Account()
    monkeypatch.setattr(users, "cannot_change_password", lambda c, d: True)
    with pytest.raises(Conflict):
        users.set_password(conn, "CN=testmann", "Secret-123", must_change=True)
    assert conn.writes == 0

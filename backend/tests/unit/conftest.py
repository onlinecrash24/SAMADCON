"""Fixtures for the unit tests only.

The directory fakes in these tests model attributes, not security
descriptors. Reading a user now also reads its ACL, for "User cannot change
password", which lives there and not in userAccountControl; in a fake that
ACL is simply clear. Tests about the option itself set it themselves, and
their monkeypatch wins over this one.
"""

from __future__ import annotations

import pytest

from samadcon.ad import users


@pytest.fixture(autouse=True)
def _no_acl_in_fake_directories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users, "cannot_change_password", lambda conn, dn: False, raising=False)

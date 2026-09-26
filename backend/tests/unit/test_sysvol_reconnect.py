"""A dropped SYSVOL connection is opened again, and a refusal is not "missing".

Found on a Samba 4.22 DC during the template import test. `smbcontrol smbd
close-share sysvol` — the documented way to end a client's lease on the
central store — ended this session's connection to the share too. It was
cached for the session and never reopened, and is_directory turned every
failure into False: the central store read as absent, the policy editor
offered to create one, and the configured policies had no templates to be
shown with, until the administrator signed out and in again.
"""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.core.errors import SamadconError
from samadcon.gpo.sysvol import SysvolConnection, _Reopening

STORE = "example.lan\\Policies\\PolicyDefinitions"
NETWORK_NAME_DELETED = 0xC00000C9
ACCESS_DENIED = 0xC0000022
OBJECT_NAME_NOT_FOUND = 0xC0000034


class NtStatusError(Exception):
    """Shaped like samba.NTSTATUSError: a number and a sentence."""

    def __init__(self, code: int, message: str = "status") -> None:
        super().__init__(code, message)


class Client:
    """libsmb's Conn as the binding behaves: chkpath says False to every failure."""

    def __init__(self, *, listing: list[dict[str, Any]] | None = None,
                 fails_with: int | None = None) -> None:
        self.listing = listing or []
        self.fails_with = fails_with
        self.calls: list[str] = []

    def chkpath(self, path: str) -> bool:
        self.calls.append(f"chkpath {path}")
        return False if self.fails_with else any(
            e["name"].lower() == path.rsplit("\\", 1)[-1].lower() and e["attrib"] & 0x10
            for e in self.listing
        )

    def list(self, path: str, attribs: int | None = None) -> list[dict[str, Any]]:
        self.calls.append(f"list {path}")
        if self.fails_with:
            raise NtStatusError(self.fails_with)
        return self.listing

    def write(self, fnum: int, data: bytes, offset: int) -> None:
        self.calls.append("write")
        if self.fails_with:
            raise NtStatusError(self.fails_with)


POLICIES = [{"name": "PolicyDefinitions", "attrib": 0x10, "size": 0}]


def reopening(first: Client, then: Client) -> tuple[_Reopening, list[Client]]:
    opened: list[Client] = []

    def reopen() -> Client:
        opened.append(then)
        return then

    return _Reopening(first, reopen), opened


# ---------------------------------------------------------------------------
# The dropped connection
# ---------------------------------------------------------------------------


def test_a_connection_the_server_dropped_is_opened_again_and_the_call_repeated():
    dropped = Client(fails_with=NETWORK_NAME_DELETED)
    fresh = Client(listing=POLICIES)
    client, opened = reopening(dropped, fresh)

    assert SysvolConnection(client, "dc1", "example.lan").is_directory(STORE) is True
    assert opened == [fresh]


def test_a_refusal_is_not_answered_by_opening_the_connection_again():
    refused = Client(fails_with=ACCESS_DENIED)
    client, opened = reopening(refused, Client(listing=POLICIES))

    with pytest.raises(SamadconError):
        SysvolConnection(client, "dc1", "example.lan").is_directory(STORE)
    assert opened == []


def test_a_call_that_holds_a_file_handle_is_not_repeated():
    """The handle belongs to the connection that is gone."""
    client, opened = reopening(Client(fails_with=NETWORK_NAME_DELETED), Client())
    with pytest.raises(NtStatusError):
        client.write(42, b"x", 0)
    assert opened == []


# ---------------------------------------------------------------------------
# What is_directory may call "no"
# ---------------------------------------------------------------------------


def test_a_missing_store_is_still_a_plain_no():
    share = SysvolConnection(Client(listing=[]), "dc1", "example.lan")
    assert share.is_directory(STORE) is False


def test_a_missing_parent_is_a_plain_no():
    share = SysvolConnection(Client(fails_with=OBJECT_NAME_NOT_FOUND), "dc1", "example.lan")
    assert share.is_directory(STORE) is False


def test_a_file_where_the_directory_should_be_is_a_no():
    listing = [{"name": "PolicyDefinitions", "attrib": 0x20, "size": 10}]
    share = SysvolConnection(Client(listing=listing), "dc1", "example.lan")
    assert share.is_directory(STORE) is False


def test_a_store_the_account_may_not_read_is_reported_not_called_missing():
    share = SysvolConnection(Client(fails_with=ACCESS_DENIED), "dc1", "example.lan")
    with pytest.raises(SamadconError) as caught:
        share.is_directory(STORE)
    assert "PolicyDefinitions" in (caught.value.detail or "")

"""Writing a file onto SYSVOL, including the ones Windows leaves hidden.

The failure this covers reads as a permission problem and is not one. GPMC
marks its policy files hidden — ``scripts.ini``, ``fdeploy1.ini`` and
``fdeploy.ini`` — and ``savefile`` opens with FILE_OVERWRITE and normal
attributes, which SMB refuses on such a file with ACCESS_DENIED. Nothing in
the message says "attribute"; it cost an afternoon of reading ACLs that were
correct all along.

Covered here rather than against a domain because every policy the integration
tests touch was created by SAMCON with plain attributes — which is exactly why
none of them saw this.
"""

from __future__ import annotations

import pytest

from samcon.core.errors import SamconError
from samcon.gpo.sysvol import SysvolConnection

ACCESS_DENIED = "NT_STATUS_ACCESS_DENIED"
SHARING_VIOLATION = "NT_STATUS_SHARING_VIOLATION"


class FakeConn:
    """Enough of libsmb's Conn to exercise the write paths.

    *refuse_savefile* is the status ``savefile`` raises; the in-place path is
    recorded so a test can say which one ran.
    """

    def __init__(self, refuse_savefile: str | None = None, attrib: int = 0x22):
        self.refuse_savefile = refuse_savefile
        # 0x22 = archive + hidden, the way GPMC leaves a policy file.
        self.attrib = attrib
        self.saved: list[tuple[str, bytes]] = []
        self.opened: list[dict[str, object]] = []
        self.written: list[tuple[int, bytes, int]] = []
        self.closed: list[int] = []
        self.unlinked: list[str] = []

    def list(self, path: str, attribs: int | None = None) -> list[dict[str, object]]:
        return [{"name": "scripts.ini", "attrib": self.attrib, "size": 0}]

    def savefile(self, path: str, data: bytes) -> None:
        if self.refuse_savefile:
            raise RuntimeError(self.refuse_savefile)
        self.saved.append((path, data))

    def create(self, **kwargs: object) -> int:
        self.opened.append(kwargs)
        return 42

    def write(self, fnum: int, data: bytes, offset: int) -> None:
        self.written.append((fnum, data, offset))

    def close(self, fnum: int) -> None:
        self.closed.append(fnum)

    def unlink(self, path: str) -> None:
        self.unlinked.append(path)
        self.refuse_savefile = None


def share(conn: FakeConn) -> SysvolConnection:
    return SysvolConnection(conn, "dc1.example.lan", "example.lan")


def test_an_ordinary_file_goes_through_savefile():
    conn = FakeConn()

    share(conn).write("a\\b.ini", b"hello")

    assert conn.saved == [("a\\b.ini", b"hello")]
    assert conn.opened == []


def test_a_hidden_file_is_overwritten_with_its_own_attributes():
    """Naming the attributes the file already has removes the disagreement.

    The overwrite disposition does the shortening, so nothing has to be
    truncated afterwards — which matters, because the binding's `truncate` is
    an SMB1 call and comes back as REVISION_MISMATCH on an SMB3 connection.
    """
    conn = FakeConn(refuse_savefile=ACCESS_DENIED, attrib=0x22)

    share(conn).write("a\\scripts.ini", b"new contents")

    assert conn.saved == []
    assert len(conn.opened) == 1
    assert conn.opened[0]["Name"] == "a\\scripts.ini"
    assert conn.opened[0]["CreateDisposition"] == 0x5  # FILE_OVERWRITE_IF
    assert conn.opened[0]["FileAttributes"] == 0x22
    assert conn.written == [(42, b"new contents", 0)]
    assert conn.closed == [42]


def test_a_file_whose_attributes_cannot_be_read_is_opened_as_normal():
    """Nothing to preserve, so nothing is claimed — but the write still has
    to happen."""
    conn = FakeConn(refuse_savefile=ACCESS_DENIED, attrib=0)

    share(conn).write("a\\scripts.ini", b"x")

    assert conn.opened[0]["FileAttributes"] == 0x80  # FILE_ATTRIBUTE_NORMAL


def test_a_refused_open_falls_back_to_replacing_the_file():
    """An editor that cannot touch a policy Windows created is worse than one
    that clears a cosmetic attribute and says so."""
    conn = FakeConn(refuse_savefile=ACCESS_DENIED)
    conn.create = _raise  # type: ignore[method-assign]

    share(conn).write("a\\scripts.ini", b"short")

    assert conn.written == []
    assert conn.unlinked == ["a\\scripts.ini"]
    assert conn.saved == [("a\\scripts.ini", b"short")]


def test_the_fallback_is_announced(caplog):
    """Losing the hidden flag is a trade, not a detail. A silent one would be
    a change to somebody else's policy that no diff would show."""
    conn = FakeConn(refuse_savefile=ACCESS_DENIED)
    conn.create = _raise  # type: ignore[method-assign]

    with caplog.at_level("WARNING"):
        share(conn).write("a\\scripts.ini", b"x")

    assert any("attributes" in record.message for record in caplog.records)


def _raise(**kwargs: object) -> int:
    raise RuntimeError("NT_STATUS_REVISION_MISMATCH")


def test_the_handle_is_closed_even_when_writing_fails():
    """Leaking it would keep the file open for the life of the session, and
    the next write would then fail for a different reason entirely."""
    conn = FakeConn(refuse_savefile=ACCESS_DENIED)

    def explode(fnum: int, data: bytes, offset: int) -> None:
        raise RuntimeError("disk full")

    conn.write = explode  # type: ignore[method-assign]

    share(conn).write("a\\scripts.ini", b"x")

    assert conn.closed == [42]


def test_a_file_held_open_elsewhere_is_still_replaced():
    """The other fallback, unchanged: a reader holding a handle blocks the
    overwrite, and unlinking first lets a fresh file take its place."""
    conn = FakeConn(refuse_savefile=SHARING_VIOLATION)

    share(conn).write("a\\b.ini", b"hello")

    assert conn.unlinked == ["a\\b.ini"]
    assert conn.saved == [("a\\b.ini", b"hello")]
    assert conn.opened == []


def test_another_refusal_is_not_swallowed():
    conn = FakeConn(refuse_savefile="NT_STATUS_DISK_FULL")

    with pytest.raises(SamconError) as raised:
        share(conn).write("a\\b.ini", b"hello")

    assert conn.opened == []
    assert raised.value.code != "insufficient_access"

"""Creating a GPO: the SYSVOL permissions, and when they are set.

Measured on a Samba 4.22 DC, a GPO from SAMADCON next to one from
``samba-tool gpo create``:

- The GPO folders carried the same rights, but SAMADCON's descriptor had
  SEC_DESC_SACL_PRESENT set with no SACL (type 0x9814 against 0x9004). The
  descriptor had been read whole, SACL included, and ``dsacl2fsacl`` copies
  the header flags. Samba passes over that; on a Synology Directory Server the
  same call is refused with ACCESS_DENIED, and no new GPO could be created.
- ``Machine``, ``User`` and ``GPT.INI`` had the share's permissions, not the
  GPO's: they were created before the GPO's permissions were set, and over
  SMB setting a folder's permissions does not reach what is already in it.
  ``samba-tool ntacl sysvolcheck`` stopped at the first such file.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from samadcon.gpo import container


class _FakeLdb(types.ModuleType):
    """Just enough of ``ldb`` for create_gpo to build its messages."""

    FLAG_MOD_ADD = 1

    def __init__(self) -> None:
        super().__init__("ldb")

    class Message(dict):
        dn: Any = None

    @staticmethod
    def Dn(_samdb: Any, dn: str) -> str:  # noqa: N802 - ldb's name
        return dn

    @staticmethod
    def MessageElement(value: Any, _flag: int, _name: str) -> Any:  # noqa: N802 - ldb's name
        return value


class _Share:
    def __init__(self, events: list[str], fail_on: str | None = None) -> None:
        self.events = events
        self.fail_on = fail_on

    def _do(self, event: str) -> None:
        self.events.append(event)
        if event == self.fail_on:
            raise RuntimeError(event)

    def makedirs(self, path: str) -> None:
        self._do("makedirs")

    def mkdir(self, path: str) -> None:
        self._do("mkdir " + path.rsplit("\\", 1)[-1])

    def write(self, path: str, data: bytes) -> None:
        self._do("write " + path.rsplit("\\", 1)[-1])

    def delete_tree(self, path: str) -> None:
        self.events.append("delete_tree")


class _Conn:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.samdb = object()
        self.info = types.SimpleNamespace(dns_domain="example.test")

    def add(self, message: Any) -> None:
        self.events.append("add " + message.dn.split(",", 1)[0])

    def delete(self, dn: str, recursive: bool = False) -> None:
        self.events.append("delete")


@pytest.fixture()
def created(monkeypatch):
    events: list[str] = []
    conn = _Conn(events)

    def setup(fail_on: str | None = None) -> tuple[_Conn, list[str]]:
        share = _Share(events, fail_on)
        monkeypatch.setitem(sys.modules, "ldb", _FakeLdb())
        monkeypatch.setattr(container, "list_gpos", lambda conn: [])
        monkeypatch.setattr(container, "gpo_dn", lambda conn, guid: f"CN={guid},CN=Policies")
        monkeypatch.setattr(container, "get_gpo", lambda conn, dn: {"dn": dn})
        monkeypatch.setattr(container.sysvol, "sysvol_for", lambda conn: share)

        def acl(conn: Any, dn: str, share_path: str) -> str:
            share._do("acl")
            return ""

        monkeypatch.setattr(container, "apply_sysvol_acl", acl)
        return conn, events

    return setup


def test_the_permissions_go_on_the_empty_folder_before_anything_is_put_in_it(created):
    """What is created afterwards inherits them, as with samba-tool. Copying and
    restoring a policy write into these folders too, through create_gpo."""
    conn, events = created()
    container.create_gpo(conn, "Neu")
    sysvol_steps = [event for event in events if not event.startswith("add ")]
    assert sysvol_steps == ["makedirs", "acl", "mkdir Machine", "mkdir User", "write GPT.INI"]


def test_a_refused_acl_still_rolls_both_halves_back(created):
    conn, events = created(fail_on="acl")
    with pytest.raises(RuntimeError):
        container.create_gpo(conn, "Neu")
    assert events[-2:] == ["delete_tree", "delete"]


def test_the_descriptor_is_read_without_its_sacl():
    """sd_flags 7 is owner, group and DACL — what samba-tool asks for."""
    asked: dict[str, Any] = {}

    class Conn:
        def search(self, base: str, **kwargs: Any) -> Any:
            asked.update(kwargs, base=base)
            entry = {"nTSecurityDescriptor": [b"\x01\x00"]}
            return types.SimpleNamespace(entries=[entry])

    assert container._directory_descriptor(Conn(), "CN={X},CN=Policies") == b"\x01\x00"
    assert asked["base"] == "CN={X},CN=Policies"
    assert asked["controls"] == ["sd_flags:1:7"]
    assert asked["attrs"] == ["nTSecurityDescriptor"]

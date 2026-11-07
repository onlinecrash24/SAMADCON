"""Where a GPO's files are: derived from its GUID, not taken from the directory.

``gPCFileSysPath`` is an attribute like any other. Whoever may edit a GPO —
Group Policy Creator Owners, a delegated "Edit settings" — may also point it
at another policy's folder, the Default Domain Controllers Policy's say, or at
the domain's whole Policies folder. SAMADCON used to follow it with the
signed-in administrator's ticket: a startup script saved into such a GPO
landed in the DC policy, and deleting the GPO ran deltree over every policy
in the domain. Reported by Rowie against 0.6.28.

The folder now comes from the realm and the GPO's own GUID. The stored path
has to name that same folder — the host part aside, which has never been
used — and when it does not, nothing is read, written or deleted there.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import container, sysvol

REALM = "example.lan"
GUID = "{6F1E3A2B-1C2D-4E5F-8A9B-0C1D2E3F4A5B}"
DC_POLICY = "{6AC1786C-016F-11D2-945F-00C04FB984F9}"
OWN = f"\\\\{REALM}\\sysvol\\{REALM}\\Policies\\{GUID}"


def gpo(path: str | None = OWN, name: str = GUID) -> dict[str, Any]:
    return {
        "dn": f"CN={name},CN=Policies,CN=System,DC=example,DC=lan",
        "name": name,
        "guid": name,
        "display_name": "Test",
        "path": path,
        "version": 0,
    }


# ---------------------------------------------------------------------------
# parse_unc
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unc",
    [
        f"\\\\x\\sysvol\\{REALM}\\Policies\\..\\..",
        f"\\\\x\\sysvol\\{REALM}\\Policies\\{GUID}\\..",
        f"\\\\x\\sysvol\\{REALM}\\.\\Policies\\{GUID}",
        f"\\\\x\\sysvol\\{REALM}\\\\Policies\\{GUID}",
        f"\\\\x\\sysvol\\C:\\Policies\\{GUID}",
        f"\\\\x\\sysvol\\{REALM}\\Policies\\{GUID}\x00",
        f"\\\\x\\sysvol\\{REALM}\\Poli\ncies\\{GUID}",
        "//x/sysvol/../etc",
    ],
)
def test_a_path_that_climbs_or_names_a_drive_is_refused(unc):
    with pytest.raises(InvalidRequest) as excinfo:
        sysvol.parse_unc(unc)
    assert excinfo.value.code == "invalid_unc"


def test_a_trailing_backslash_is_not_a_component():
    _, _, path = sysvol.parse_unc(OWN + "\\")
    assert path == f"{REALM}\\Policies\\{GUID}"


# ---------------------------------------------------------------------------
# policy_folder
# ---------------------------------------------------------------------------


class Share:
    realm = REALM

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()
        self.deleted: list[str] = []
        self.written: list[str] = []

    def exists(self, path: str) -> bool:
        return path in self.existing

    def delete_tree(self, path: str) -> None:
        self.deleted.append(path)

    def write(self, path: str, data: bytes) -> None:
        self.written.append(path)

    def makedirs(self, path: str) -> None:
        pass


@pytest.mark.parametrize(
    "stored",
    [
        OWN,
        OWN.upper(),
        OWN.replace("sysvol", "SysVol"),
        f"\\\\dc1.{REALM}\\sysvol\\{REALM}\\Policies\\{GUID}",
        OWN.replace("\\", "/"),
        f"\\\\{REALM}\\sysvol\\{REALM}\\Policies\\{GUID.lower()}",
    ],
)
def test_the_policys_own_folder_is_accepted_however_it_is_written(stored):
    folder = sysvol.policy_folder(Share(), gpo(stored))
    assert folder.casefold() == f"{REALM}\\Policies\\{GUID}".casefold()


@pytest.mark.parametrize(
    "stored",
    [
        # Another policy's folder: the Default Domain Controllers Policy.
        f"\\\\{REALM}\\sysvol\\{REALM}\\Policies\\{DC_POLICY}",
        # Every policy in the domain.
        f"\\\\{REALM}\\sysvol\\{REALM}\\Policies",
        f"\\\\{REALM}\\sysvol\\{REALM}",
        # The scripts share of the domain, every logon script.
        f"\\\\{REALM}\\sysvol\\{REALM}\\scripts",
        # Below its own folder is not its own folder either.
        f"{OWN}\\Machine",
        # Another domain, another share.
        f"\\\\other.lan\\sysvol\\other.lan\\Policies\\{GUID}",
        f"\\\\{REALM}\\netlogon\\{REALM}\\Policies\\{GUID}",
    ],
)
def test_any_other_folder_is_refused_with_both_paths_named(stored):
    with pytest.raises(InvalidRequest) as excinfo:
        sysvol.policy_folder(Share(), gpo(stored))
    assert excinfo.value.code == "gpo_path_mismatch"
    assert excinfo.value.context["path"] == stored
    assert excinfo.value.context["expected"] == sysvol.gpo_unc(REALM, GUID)


def test_a_name_that_is_not_a_guid_matches_nothing():
    with pytest.raises(InvalidRequest) as excinfo:
        sysvol.policy_folder(Share(), gpo(f"\\\\{REALM}\\sysvol\\{REALM}\\Policies\\x", name="x"))
    assert excinfo.value.code == "gpo_path_mismatch"


def test_an_unusable_path_stays_invalid_unc():
    with pytest.raises(InvalidRequest) as excinfo:
        sysvol.policy_folder(Share(), gpo("not-a-path"))
    assert excinfo.value.code == "invalid_unc"


# ---------------------------------------------------------------------------
# What uses it
# ---------------------------------------------------------------------------


def test_the_consistency_check_reports_a_foreign_path(monkeypatch):
    share = Share({f"{REALM}\\Policies\\{DC_POLICY}"})
    monkeypatch.setattr(container.sysvol, "sysvol_for", lambda conn: share)
    foreign = gpo(f"\\\\{REALM}\\sysvol\\{REALM}\\Policies\\{DC_POLICY}")

    report = container.status(object(), foreign)

    assert report["problems"] == ["path_mismatch"]
    assert report["sysvol_present"] is False


class Conn:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        self.deleted.append(dn)


@pytest.fixture
def deleting(monkeypatch):
    from samadcon.gpo import gpmc

    own = f"{REALM}\\Policies\\{GUID}"
    share = Share({own, f"{REALM}\\Policies\\{DC_POLICY}", f"{REALM}\\Policies"})
    monkeypatch.setattr(container.sysvol, "sysvol_for", lambda conn: share)
    monkeypatch.setattr(gpmc, "find_links", lambda conn, name: [])

    def run(stored: str | None) -> tuple[dict[str, Any], Share, Conn]:
        monkeypatch.setattr(container, "get_gpo", lambda conn, dn: gpo(stored))
        conn = Conn()
        result = container.delete_gpo(conn, gpo(stored)["dn"])
        return result, share, conn

    return run


def test_deleting_a_policy_with_its_own_path_deletes_its_folder(deleting):
    result, share, conn = deleting(OWN)
    assert share.deleted == [f"{REALM}\\Policies\\{GUID}"]
    assert conn.deleted
    assert not result.get("path_mismatch")


@pytest.mark.parametrize(
    "stored",
    [
        f"\\\\{REALM}\\sysvol\\{REALM}\\Policies\\{DC_POLICY}",
        f"\\\\{REALM}\\sysvol\\{REALM}\\Policies",
        f"\\\\{REALM}\\sysvol\\{REALM}\\Policies\\..\\..",
    ],
)
def test_deleting_a_policy_with_a_foreign_path_deletes_only_its_own_folder(deleting, stored):
    result, share, conn = deleting(stored)
    # Never the folder the attribute names — only the one the GUID names.
    assert share.deleted == [f"{REALM}\\Policies\\{GUID}"]
    assert conn.deleted
    assert result["path_mismatch"] is True


def test_saving_a_script_into_a_policy_with_a_foreign_path_writes_nothing(monkeypatch):
    from samadcon.gpo import scripts

    share = Share()
    foreign = gpo(f"\\\\{REALM}\\sysvol\\{REALM}\\Policies\\{DC_POLICY}")
    monkeypatch.setattr(scripts.sysvol, "sysvol_for", lambda conn: share)
    monkeypatch.setattr(scripts.container, "get_gpo", lambda conn, dn: foreign)
    monkeypatch.setattr(scripts, "_read_file", lambda conn, gpo, half, engine: None)

    with pytest.raises(InvalidRequest) as excinfo:
        scripts.write(
            object(),
            foreign["dn"],
            "Machine",
            "Startup",
            "cmd",
            [scripts.Script(command="evil.cmd", parameters="")],
        )

    assert excinfo.value.code == "gpo_path_mismatch"
    assert share.written == []


def test_nothing_in_samadcon_takes_a_gpo_path_from_the_directory_unchecked():
    """Every SYSVOL access of a GPO goes through policy_folder."""
    root = Path(__file__).resolve().parents[2] / "samadcon"
    pattern = re.compile(r"parse_unc\(\s*\w+\[\"path\"\]")
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path.name != "sysvol.py" and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []

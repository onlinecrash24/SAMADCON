"""The domain and forest functional level: where it stands, what a raise
needs, and the samba-tool command that does it.

SAMADCON shows the raise and does not perform it. msDS-Behavior-Version is
systemOnly; ``samba-tool domain level raise`` writes it on the DC, as system.
Over LDAP a Samba DC refuses it to everyone, and the relax control does not
help: rootdse_filter_controls (source4/dsdb/samdb/ldb_modules/rootdse.c)
drops a control no module registered from an LDAP request, and relax is not
registered. Measured on a throwaway Samba 4.22 DC: with relax:0 the write
fails as without it, with relax:1 as a critical non-registered control.

What samba-tool leaves to the administrator is checked here, so that the
command is shown only once it will work:

- Every DC's NTDS Settings carries the level it runs at. A Samba DC writes
  its ``ad dc functional level`` from smb.conf there when it starts, and
  refuses to start once that is below the domain's level
  (dsdb_check_and_update_fl, source4/dsdb/common/util.c).
- ``samba-tool domain functionalprep`` leaves a revision on
  CN=ActiveDirectoryUpdate under ForestUpdates and DomainUpdates
  (forest_update.py and domain_update.py, functional_level_to_version).
- The 4.19 release notes ask for ``schemaupgrade --schema=2019`` before
  2016; that schema is objectVersion 88. A domain provisioned with 4.22
  already has it, and both revisions at 16.
- samba-tool's own rules (python/samba/netcmd/domain/level.py): only
  upwards, the domain never above the weakest DC, the forest never above
  the domain.

On a Windows DC the state is shown; the prep and the schema come with the
Windows Server version a DC is installed with, and Windows has its own tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from samadcon.ad import values
from samadcon.ad.connection import SCOPE_ONELEVEL, SCOPE_SUBTREE, DirectoryConnection
from samadcon.ad.diagnostics import _server_of_ntds, level_name

# The levels samba-tool accepts, by their smb.conf / samba-tool spelling.
SAMBA_LEVELS: dict[int, str] = {
    2: "2003",
    3: "2008",
    4: "2008_R2",
    5: "2012",
    6: "2012_R2",
    7: "2016",
}
# Windows Server 2025 is 10; 8 and 9 were never given out.
WINDOWS_LEVELS = (2, 3, 4, 5, 6, 7, 10)

# functionalprep's revisions, per level (functional_level_to_version).
FOREST_PREP: dict[int, int] = {3: 2, 4: 5, 5: 11, 6: 15, 7: 16}
DOMAIN_PREP: dict[int, int] = {3: 3, 4: 5, 5: 9, 6: 10, 7: 16}

SCHEMA_2019 = 88

LEVEL_2016 = 7

LEVEL = "msDS-Behavior-Version"
MIXED = "nTMixedDomain"
_DOMAIN_CROSS_REFS = "(&(objectClass=crossRef)(systemFlags:1.2.840.113556.1.4.803:=2))"


@dataclass(frozen=True)
class Controller:
    name: str
    level: int


@dataclass(frozen=True)
class State:
    is_samba: bool
    domain_level: int
    forest_level: int
    mixed: bool
    # The other domains of the forest; the forest may not pass any of them.
    other_domain_levels: tuple[int, ...]
    controllers: tuple[Controller, ...]
    forest_revision: int
    domain_revision: int
    schema_version: int | None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _dn(entry: Any) -> str:
    dn = getattr(entry, "dn", None)
    return str(dn) if dn is not None else values.as_str(entry, "distinguishedName") or ""


def _revision(conn: DirectoryConnection, dn: str) -> int:
    entry = conn.get(dn, attrs=["revision"])
    return (values.as_int(entry, "revision", 0) or 0) if entry is not None else 0


def _cross_refs(conn: DirectoryConnection) -> list[Any]:
    return conn.search(
        f"CN=Partitions,{conn.info.config_dn}",
        scope=SCOPE_ONELEVEL,
        expression=_DOMAIN_CROSS_REFS,
        attrs=["distinguishedName", "nCName", LEVEL, MIXED],
    ).entries


def _is_own(conn: DirectoryConnection, cross_ref: Any) -> bool:
    return (values.as_str(cross_ref, "nCName") or "").lower() == conn.info.base_dn.lower()


def read_state(conn: DirectoryConnection) -> State:
    info = conn.info
    domain = conn.get(info.base_dn, attrs=[LEVEL, MIXED])
    partitions = conn.get(f"CN=Partitions,{info.config_dn}", attrs=[LEVEL])
    schema = conn.get(info.schema_dn, attrs=["objectVersion"])

    others = tuple(
        values.as_int(entry, LEVEL, 0) or 0
        for entry in _cross_refs(conn)
        if not _is_own(conn, entry)
    )

    # A DC without the attribute is a Windows 2000 one, as samba-tool counts it.
    dsas = conn.search(
        f"CN=Sites,{info.config_dn}",
        scope=SCOPE_SUBTREE,
        expression="(objectClass=nTDSDSA)",
        attrs=["distinguishedName", LEVEL],
    ).entries
    controllers = sorted(
        (
            Controller(
                _server_of_ntds(_dn(entry)) or _dn(entry),
                values.as_int(entry, LEVEL, 0) or 0,
            )
            for entry in dsas
        ),
        key=lambda controller: controller.name.lower(),
    )

    return State(
        is_samba=info.is_samba,
        domain_level=values.as_int(domain, LEVEL, 0) or 0,
        forest_level=values.as_int(partitions, LEVEL, 0) or 0,
        mixed=(values.as_int(domain, MIXED, 0) or 0) != 0,
        other_domain_levels=others,
        controllers=tuple(controllers),
        forest_revision=_revision(
            conn, f"CN=ActiveDirectoryUpdate,CN=ForestUpdates,{info.config_dn}"
        ),
        domain_revision=_revision(
            conn, f"CN=ActiveDirectoryUpdate,CN=DomainUpdates,CN=System,{info.base_dn}"
        ),
        schema_version=values.as_int(schema, "objectVersion"),
    )


# ---------------------------------------------------------------------------
# What a level needs
# ---------------------------------------------------------------------------


def _setting(level: int) -> str:
    return f"ad dc functional level = {SAMBA_LEVELS[level]}"


def _prep_command(level: int) -> str:
    # functionalprep knows 2008_R2 and up; below that it has nothing to do.
    return f"samba-tool domain functionalprep --function-level={SAMBA_LEVELS[max(level, 4)]}"


SCHEMA_COMMAND = "samba-tool domain schemaupgrade --schema=2019"


def missing(state: State, level: int) -> list[dict[str, Any]]:
    """What stands between the domain and *level*, in the order to do it."""
    steps: list[dict[str, Any]] = []

    below = [controller.name for controller in state.controllers if controller.level < level]
    if below:
        step: dict[str, Any] = {"step": "dc_level", "controllers": below}
        if state.is_samba:
            step["setting"] = _setting(level)
        steps.append(step)

    if not state.is_samba:
        return steps

    if level >= LEVEL_2016 and (state.schema_version or 0) < SCHEMA_2019:
        steps.append({"step": "schema", "command": SCHEMA_COMMAND})
    if state.forest_revision < FOREST_PREP.get(level, 0) or state.domain_revision < DOMAIN_PREP.get(
        level, 0
    ):
        steps.append({"step": "prep", "command": _prep_command(level)})
    return steps


def targets(state: State) -> list[dict[str, Any]]:
    """Each level above the forest's, with what it would take."""
    known = SAMBA_LEVELS if state.is_samba else WINDOWS_LEVELS
    return [
        {
            "level": level,
            "name": level_name(level),
            "domain": level > state.domain_level,
            "missing": missing(state, level),
            "raise": raise_commands(state, level),
        }
        for level in known
        if level > state.forest_level
    ]


# ---------------------------------------------------------------------------
# The command for the DC
# ---------------------------------------------------------------------------


def raise_commands(state: State, level: int) -> list[dict[str, str]]:
    """The samba-tool commands that raise to *level*, one per scope that
    samba-tool would accept: domain and forest together or the domain alone
    while the domain is below, the forest alone once it is not."""
    if not state.is_samba or level not in SAMBA_LEVELS:
        return []
    name = SAMBA_LEVELS[level]
    raise_ = "samba-tool domain level raise"
    forest_fits = all(level <= other for other in state.other_domain_levels)

    out: list[dict[str, str]] = []
    if level > state.domain_level:
        if forest_fits:
            out.append(
                {
                    "scope": "both",
                    "command": f"{raise_} --domain-level={name} --forest-level={name}",
                }
            )
        out.append({"scope": "domain", "command": f"{raise_} --domain-level={name}"})
    elif level > state.forest_level and forest_fits:
        out.append({"scope": "forest", "command": f"{raise_} --forest-level={name}"})
    return out


def overview(conn: DirectoryConnection) -> dict[str, Any]:
    state = read_state(conn)
    return {
        "is_samba": state.is_samba,
        "domain_level": state.domain_level,
        "domain_level_name": level_name(state.domain_level),
        "forest_level": state.forest_level,
        "forest_level_name": level_name(state.forest_level),
        "mixed": state.mixed,
        "controllers": [
            {"name": c.name, "level": c.level, "level_name": level_name(c.level)}
            for c in state.controllers
        ],
        "forest_revision": state.forest_revision,
        "domain_revision": state.domain_revision,
        "schema_version": state.schema_version,
        "targets": targets(state),
    }

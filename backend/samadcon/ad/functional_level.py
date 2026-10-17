"""The domain and forest functional level: where it stands, what a raise
needs, and the raise itself.

Raising is ``samba-tool domain level raise`` (Samba 4.22.11,
python/samba/netcmd/domain/level.py): the same rules — only upwards, the
domain never above the weakest DC, the forest never above the domain — and
the same writes in the same order. It cannot be undone; nothing lowers a
level again.

samba-tool leaves the rest to the administrator. Here it is checked, because
a console that raises a level should know whether the domain is ready:

- Every DC's NTDS Settings carries the level it runs at. A Samba DC writes
  its ``ad dc functional level`` from smb.conf there when it starts, and
  refuses to start once that is below the domain's level
  (dsdb_check_and_update_fl, source4/dsdb/common/util.c).
- ``samba-tool domain functionalprep`` leaves a revision on
  CN=ActiveDirectoryUpdate under ForestUpdates and DomainUpdates
  (forest_update.py and domain_update.py, functional_level_to_version).
- The 4.19 release notes ask for ``schemaupgrade --schema=2019`` before
  2016; that schema is objectVersion 88.

On a Windows DC this is shown, not written. The prep and the schema come with
the Windows Server version a DC is installed with, and Windows has its own
tools for the raise; SAMADCON has not been measured against them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from samadcon.ad import values
from samadcon.ad.connection import SCOPE_ONELEVEL, SCOPE_SUBTREE, DirectoryConnection
from samadcon.ad.diagnostics import _server_of_ntds, level_name
from samadcon.core.errors import Conflict, InvalidRequest, SamadconError

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
    dns_domain: str
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
        dns_domain=info.dns_domain,
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
        }
        for level in known
        if level > state.forest_level
    ]


# ---------------------------------------------------------------------------
# Raising
# ---------------------------------------------------------------------------


def check_raise(state: State, *, domain: int | None, forest: int | None, confirm: str) -> None:
    """Refuse a raise samba-tool would refuse, or that the domain is not ready for."""
    if not state.is_samba:
        raise Conflict(
            "SAMADCON raises the functional level on Samba domain controllers only.",
            code="windows_dc_functional_level",
            hint="On Windows, raise it with Active Directory Domains and Trusts or "
            "Set-ADDomainMode and Set-ADForestMode.",
        )
    if domain is None and forest is None:
        raise InvalidRequest("Nothing to change.", code="no_changes")
    if confirm.strip().lower() != state.dns_domain.lower():
        raise InvalidRequest(
            "Type the domain's name to confirm; a raise cannot be undone.",
            code="functional_level_confirm",
            context={"domain": state.dns_domain},
        )

    for level in (domain, forest):
        if level is not None and level not in SAMBA_LEVELS:
            raise InvalidRequest(
                "Samba does not know this functional level.",
                code="functional_level_unknown",
                context={"level": level},
            )

    if domain is not None and domain <= state.domain_level and not state.mixed:
        raise InvalidRequest(
            "A functional level can only be raised.",
            code="functional_level_not_higher",
            context={"reason": "domain", "current": level_name(state.domain_level)},
        )
    if forest is not None and forest <= state.forest_level:
        raise InvalidRequest(
            "A functional level can only be raised.",
            code="functional_level_not_higher",
            context={"reason": "forest", "current": level_name(state.forest_level)},
        )

    # The domain goes first when both are raised, as in samba-tool.
    domain_after = domain if domain is not None else state.domain_level
    if forest is not None and forest > min((domain_after, *state.other_domain_levels)):
        raise Conflict(
            "The forest cannot be raised above a domain of the forest.",
            code="functional_level_forest_above_domain",
            context={"domain": level_name(domain_after)},
        )

    target = max(level for level in (domain, forest) if level is not None)
    steps = {step["step"]: step for step in missing(state, target)}
    if "dc_level" in steps:
        raise Conflict(
            "A domain controller does not run at this level yet.",
            code="functional_level_above_dc",
            context={
                "controllers": ", ".join(steps["dc_level"]["controllers"]),
                "setting": steps["dc_level"]["setting"],
                "level": level_name(target),
            },
        )
    for reason in ("schema", "prep"):
        if reason in steps:
            raise Conflict(
                "The domain is not prepared for this level.",
                code="functional_level_not_prepared",
                context={
                    "reason": reason,
                    "command": steps[reason]["command"],
                    "level": level_name(target),
                },
            )


def writes(state: State, *, domain: int | None, forest: int | None) -> list[tuple[str, str, str]]:
    """(object, attribute, value) in samba-tool's order: the domain object,
    then its crossRef, then CN=Partitions for the forest."""
    out: list[tuple[str, str, str]] = []
    if domain is not None:
        if state.mixed:
            out += [("domain", MIXED, "0"), ("crossref", MIXED, "0")]
        out += [("domain", LEVEL, str(domain)), ("crossref", LEVEL, str(domain))]
    if forest is not None:
        out.append(("partitions", LEVEL, str(forest)))
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


def raise_levels(
    conn: DirectoryConnection,
    *,
    domain_level: int | None = None,
    forest_level: int | None = None,
    confirm: str = "",
) -> dict[str, Any]:
    """Raise the domain and/or the forest; return what was written and the
    levels as they now read."""
    state = read_state(conn)
    check_raise(state, domain=domain_level, forest=forest_level, confirm=confirm)

    import ldb

    own = [entry for entry in _cross_refs(conn) if _is_own(conn, entry)]
    targets_dn = {
        "domain": conn.info.base_dn,
        "crossref": _dn(own[0]) if own else None,
        "partitions": f"CN=Partitions,{conn.info.config_dn}",
    }

    applied: list[dict[str, str]] = []
    for target, attribute, value in writes(state, domain=domain_level, forest=forest_level):
        dn = targets_dn[target]
        if dn is None:
            continue
        message = ldb.Message()
        message.dn = ldb.Dn(conn.samdb, dn)
        message[attribute] = ldb.MessageElement(value, ldb.FLAG_MOD_REPLACE, attribute)
        try:
            conn.modify(message)
        except SamadconError as exc:
            # samba-tool passes over a crossRef the server will not take.
            if target == "crossref" and exc.code == "unwilling_to_perform":
                continue
            raise
        applied.append({"dn": dn, "attribute": attribute, "value": value})

    return {"applied": applied, "levels": overview(conn)}

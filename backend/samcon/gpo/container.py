"""The directory half of a GPO, and creating both halves together.

A GPO is created in two places that can each fail on their own. The order here
is the one ``samba-tool gpo create`` uses and the one that fails safest: the
directory object first, then the files, then the SYSVOL permissions derived
from the object. If a later step fails, the earlier ones are rolled back —
a GPO that exists in only one half is worse than no GPO, because it shows up
in every console and does nothing.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from samcon.ad import values
from samcon.ad.connection import SCOPE_ONELEVEL, DirectoryConnection
from samcon.core.errors import Conflict, InvalidRequest, NotFound
from samcon.gpo import sysvol

logger = logging.getLogger(__name__)

# groupPolicyContainer flags (MS-GPOL 2.2.6).
GPO_FLAG_USER_DISABLED = 0x00000001
GPO_FLAG_MACHINE_DISABLED = 0x00000002

# The value every GPO written since Windows 2000 carries.
GPC_FUNCTIONALITY_VERSION = 2

GPO_ATTRS = [
    "distinguishedName",
    "name",
    "displayName",
    "gPCFileSysPath",
    "versionNumber",
    "flags",
    "gPCMachineExtensionNames",
    "gPCUserExtensionNames",
    "gPCWQLFilter",
    "whenCreated",
    "whenChanged",
    "objectGUID",
]


def policies_dn(conn: DirectoryConnection) -> str:
    return f"CN=Policies,CN=System,{conn.info.base_dn}"


def gpo_dn(conn: DirectoryConnection, guid: str) -> str:
    return f"CN={normalise_guid(guid)},{policies_dn(conn)}"


def normalise_guid(guid: str) -> str:
    """A GPO name is a GUID in braces, upper case.

    Windows writes it that way and compares gPLink entries as text, so a GPO
    named with lower-case letters is linkable but the link does not match what
    GPMC writes. Rejecting anything else keeps that out of the directory.
    """
    text = (guid or "").strip()
    if not text:
        raise InvalidRequest("The policy is missing.", code="missing_gpo")
    bare = text.strip("{}")
    try:
        parsed = uuid.UUID(bare)
    except ValueError as exc:
        raise InvalidRequest(
            "This is not a valid policy identifier.",
            code="invalid_gpo_guid",
            context={"value": guid},
        ) from exc
    return f"{{{str(parsed).upper()}}}"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def list_gpos(conn: DirectoryConnection) -> list[dict[str, Any]]:
    """Every GPO in the domain."""
    result = conn.search(
        policies_dn(conn),
        scope=SCOPE_ONELEVEL,
        expression="(objectClass=groupPolicyContainer)",
        attrs=GPO_ATTRS,
    )

    gpos = [_summary(entry) for entry in result]
    gpos.sort(key=lambda gpo: (gpo["display_name"] or gpo["name"]).lower())
    return gpos


def _summary(entry: Any) -> dict[str, Any]:
    dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
    name = values.as_str(entry, "name") or values.name_from_dn(dn)
    version = values.as_int(entry, "versionNumber", 0) or 0
    machine_version, user_version = sysvol.split_version(version)
    flags = values.as_int(entry, "flags", 0) or 0

    return {
        "dn": dn,
        "name": name,
        "guid": name,
        "display_name": values.as_str(entry, "displayName"),
        "path": values.as_str(entry, "gPCFileSysPath"),
        "version": version,
        "machine_version": machine_version,
        "user_version": user_version,
        "machine_enabled": not (flags & GPO_FLAG_MACHINE_DISABLED),
        "user_enabled": not (flags & GPO_FLAG_USER_DISABLED),
        "flags": flags,
        # The client-side extensions that have written something into this GPO.
        # Empty means the policy contains nothing a client would apply.
        "machine_extensions": values.as_str(entry, "gPCMachineExtensionNames"),
        "user_extensions": values.as_str(entry, "gPCUserExtensionNames"),
        "wmi_filter": values.as_str(entry, "gPCWQLFilter"),
        "created": values.as_generalized_time(entry, "whenCreated"),
        "changed": values.as_generalized_time(entry, "whenChanged"),
    }


def get_gpo(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    entry = conn.get(dn, attrs=GPO_ATTRS)
    if entry is None:
        raise NotFound("The group policy does not exist.", code="gpo_not_found", context={"dn": dn})
    return _summary(entry)


def find_gpo(conn: DirectoryConnection, name: str) -> dict[str, Any]:
    """Look a GPO up by GUID or by display name.

    Display names are not unique in AD — nothing stops two GPOs called
    "Default Domain Policy". A name that matches several is refused rather
    than resolved arbitrarily.
    """
    text = (name or "").strip()
    if not text:
        raise InvalidRequest("The policy is missing.", code="missing_gpo")

    if text.startswith("{") or _looks_like_guid(text):
        return get_gpo(conn, gpo_dn(conn, text))

    matches = [gpo for gpo in list_gpos(conn) if (gpo["display_name"] or "") == text]
    if not matches:
        raise NotFound(
            "No group policy of this name exists.", code="gpo_not_found", context={"name": text}
        )
    if len(matches) > 1:
        raise Conflict(
            "Several group policies carry this name.",
            code="ambiguous_gpo",
            hint="Use the policy's identifier instead.",
            context={"name": text, "guids": [gpo["name"] for gpo in matches]},
        )
    return matches[0]


def _looks_like_guid(text: str) -> bool:
    try:
        uuid.UUID(text.strip("{}"))
    except ValueError:
        return False
    return True


def status(conn: DirectoryConnection, gpo: dict[str, Any]) -> dict[str, Any]:
    """Compare the two halves of a GPO and report what does not line up.

    This is the check that catches the failure mode group policy is famous
    for: a version in ``GPT.INI`` that disagrees with ``versionNumber`` means
    clients either skip a change or re-apply one forever, and nothing in the
    directory says so.
    """
    share = sysvol.sysvol_for(conn)
    report: dict[str, Any] = {
        "directory_version": gpo["version"],
        "sysvol_version": None,
        "sysvol_present": False,
        "consistent": False,
        "problems": [],
    }

    if not gpo["path"]:
        report["problems"].append("no_path")
        return report

    try:
        _, _, path = sysvol.parse_unc(gpo["path"])
    except InvalidRequest:
        report["problems"].append("invalid_path")
        return report

    if not share.exists(path):
        report["problems"].append("sysvol_missing")
        return report

    report["sysvol_present"] = True
    ini_path = sysvol.join(path, sysvol.GPT_INI)
    if not share.exists(ini_path):
        report["problems"].append("gpt_ini_missing")
        return report

    parsed = sysvol.parse_gpt_ini(share.read_text(ini_path))
    report["sysvol_version"] = parsed["version"]
    if parsed["version"] != gpo["version"]:
        report["problems"].append("version_mismatch")

    for half in ("Machine", "User"):
        if not share.exists(sysvol.join(path, half)):
            report["problems"].append(f"{half.lower()}_folder_missing")

    report["consistent"] = not report["problems"]
    return report


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


def create_gpo(conn: DirectoryConnection, display_name: str) -> dict[str, Any]:
    """Create a GPO in both halves.

    Order matters and is the same one ``samba-tool gpo create`` uses:

    1. the directory object and its two child containers,
    2. the SYSVOL directories and ``GPT.INI``,
    3. the SYSVOL permissions, derived from the object's own ACL.

    Step 3 is the one that is easy to skip and impossible to notice: without
    it the files inherit the share's permissions, and the security filtering
    set on the object has no effect on who can read the policy.
    """
    import ldb

    name = (display_name or "").strip()
    if not name:
        raise InvalidRequest("The name is missing.", code="missing_name")

    for existing in list_gpos(conn):
        if (existing["display_name"] or "").lower() == name.lower():
            raise Conflict(
                "A group policy with this name already exists.",
                code="gpo_exists",
                hint="Display names are not unique in the directory, but two "
                "policies with the same name are indistinguishable in every console.",
                context={"name": name},
            )

    guid = f"{{{str(uuid.uuid4()).upper()}}}"
    dn = gpo_dn(conn, guid)
    realm = conn.info.dns_domain
    unc = sysvol.gpo_unc(realm, guid)
    share_path = sysvol.gpo_path(realm, guid)

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["objectClass"] = ldb.MessageElement(
        ["top", "container", "groupPolicyContainer"], ldb.FLAG_MOD_ADD, "objectClass"
    )
    message["displayName"] = ldb.MessageElement(name, ldb.FLAG_MOD_ADD, "displayName")
    message["gPCFileSysPath"] = ldb.MessageElement(unc, ldb.FLAG_MOD_ADD, "gPCFileSysPath")
    message["versionNumber"] = ldb.MessageElement("0", ldb.FLAG_MOD_ADD, "versionNumber")
    message["gpcFunctionalityVersion"] = ldb.MessageElement(
        str(GPC_FUNCTIONALITY_VERSION), ldb.FLAG_MOD_ADD, "gpcFunctionalityVersion"
    )
    message["flags"] = ldb.MessageElement("0", ldb.FLAG_MOD_ADD, "flags")
    conn.add(message)

    created_ldap = True
    created_sysvol = False
    try:
        for half in ("User", "Machine"):
            child = ldb.Message()
            child.dn = ldb.Dn(conn.samdb, f"CN={half},{dn}")
            child["objectClass"] = ldb.MessageElement(
                ["top", "container"], ldb.FLAG_MOD_ADD, "objectClass"
            )
            conn.add(child)

        share = sysvol.sysvol_for(conn)
        share.makedirs(share_path)
        created_sysvol = True
        share.mkdir(sysvol.join(share_path, "Machine"))
        share.mkdir(sysvol.join(share_path, "User"))
        share.write(sysvol.join(share_path, sysvol.GPT_INI), sysvol.format_gpt_ini(0))

        apply_sysvol_acl(conn, dn, share_path)
    except Exception:
        logger.exception("creating GPO %s failed; rolling back", guid)
        if created_sysvol:
            _try(lambda: sysvol.sysvol_for(conn).delete_tree(share_path))
        if created_ldap:
            _try(lambda: conn.delete(dn, recursive=True))
        raise

    logger.info("created GPO %s (%s)", guid, name)
    return get_gpo(conn, dn)


def _try(action: Any) -> None:
    """Best-effort cleanup; the original failure is what gets reported."""
    try:
        action()
    except Exception:
        logger.warning("rollback step failed", exc_info=True)


def apply_sysvol_acl(conn: DirectoryConnection, dn: str, share_path: str) -> str:
    """Derive the SYSVOL permissions from the GPO's own directory ACL.

    ``dsacl2fsacl`` is Samba's own translation, the same one ``samba-tool``
    uses — the mapping between directory rights and file rights is not
    something to reinvent, and getting it wrong means either a policy nobody
    can read or one everybody can rewrite.
    """
    from samba.dcerpc import security
    from samba.ndr import ndr_unpack
    from samba.ntacls import dsacl2fsacl

    entry = conn.get(dn, attrs=["nTSecurityDescriptor"])
    if entry is None:
        raise NotFound("The group policy does not exist.", code="gpo_not_found", context={"dn": dn})

    raw = values.as_bytes(entry, "nTSecurityDescriptor")
    if not raw:
        raise InvalidRequest(
            "The policy object has no security descriptor to derive from.",
            code="no_security_descriptor",
            context={"dn": dn},
        )

    ds_sddl = ndr_unpack(security.descriptor, raw).as_sddl()
    domain_sid = security.dom_sid(str(conn.samdb.get_domain_sid()))
    fs_descriptor = dsacl2fsacl(ds_sddl, domain_sid, as_sddl=False)

    sysvol.sysvol_for(conn).set_acl(share_path, fs_descriptor)
    return ds_sddl


# ---------------------------------------------------------------------------
# Changing
# ---------------------------------------------------------------------------


def rename_gpo(conn: DirectoryConnection, dn: str, display_name: str) -> dict[str, Any]:
    """Change a GPO's display name.

    The object itself keeps its GUID — that is what links point at, so a
    rename that moved the object would break every link to it.
    """
    name = (display_name or "").strip()
    if not name:
        raise InvalidRequest("The name is missing.", code="missing_name")

    gpo = get_gpo(conn, dn)
    conn.modify_attributes(dn, {"displayName": name})

    # GPT.INI carries the name too, for consoles that read the files directly.
    if gpo["path"]:
        try:
            share = sysvol.sysvol_for(conn)
            _, _, path = sysvol.parse_unc(gpo["path"])
            ini_path = sysvol.join(path, sysvol.GPT_INI)
            if share.exists(ini_path):
                current = sysvol.parse_gpt_ini(share.read_text(ini_path))
                if current["display_name"]:
                    share.write(ini_path, sysvol.format_gpt_ini(current["version"], name))
        except Exception:  # the directory is what counts
            logger.warning("could not update GPT.INI after renaming %s", dn, exc_info=True)

    return get_gpo(conn, dn)


def set_status(
    conn: DirectoryConnection,
    dn: str,
    *,
    machine_enabled: bool | None = None,
    user_enabled: bool | None = None,
) -> dict[str, Any]:
    """Enable or disable either half of a policy.

    Disabling the half a GPO does not use is a real optimisation: clients skip
    reading it entirely, which is why GPMC offers it.
    """
    gpo = get_gpo(conn, dn)
    flags = gpo["flags"]

    if machine_enabled is not None:
        flags = (
            flags & ~GPO_FLAG_MACHINE_DISABLED
            if machine_enabled
            else flags | GPO_FLAG_MACHINE_DISABLED
        )
    if user_enabled is not None:
        flags = flags & ~GPO_FLAG_USER_DISABLED if user_enabled else flags | GPO_FLAG_USER_DISABLED

    if flags == gpo["flags"]:
        return gpo

    conn.modify_attributes(dn, {"flags": str(flags)})
    return get_gpo(conn, dn)


def bump_version(
    conn: DirectoryConnection,
    dn: str,
    *,
    machine_changed: bool = False,
    user_changed: bool = False,
) -> dict[str, Any]:
    """Advance the version in both halves.

    Windows re-reads a policy only when this number changes, and it compares
    the one in the directory with the one in ``GPT.INI``. Writing one without
    the other is the single most common way a policy edit ends up doing
    nothing.
    """
    if not machine_changed and not user_changed:
        return get_gpo(conn, dn)

    gpo = get_gpo(conn, dn)
    machine, user = sysvol.split_version(gpo["version"])
    if machine_changed:
        machine = (machine + 1) & 0xFFFF
    if user_changed:
        user = (user + 1) & 0xFFFF
    version = sysvol.combine_version(machine, user)

    conn.modify_attributes(dn, {"versionNumber": str(version)})

    if gpo["path"]:
        share = sysvol.sysvol_for(conn)
        _, _, path = sysvol.parse_unc(gpo["path"])
        ini_path = sysvol.join(path, sysvol.GPT_INI)
        name = None
        if share.exists(ini_path):
            name = sysvol.parse_gpt_ini(share.read_text(ini_path))["display_name"]
        share.write(ini_path, sysvol.format_gpt_ini(version, name))

    return get_gpo(conn, dn)


def delete_gpo(conn: DirectoryConnection, dn: str, *, force: bool = False) -> dict[str, Any]:
    """Delete a GPO in both halves.

    Links to it are not cleaned up here — they live on OUs and sites all over
    the domain, and removing them is a separate, visible step. A GPO deleted
    while still linked leaves those links pointing at nothing, which every
    console reports; *force* is how an administrator says they know.
    """
    from samcon.gpo import gpmc

    gpo = get_gpo(conn, dn)
    links = gpmc.find_links(conn, gpo["name"])
    if links and not force:
        raise Conflict(
            "The group policy is still linked.",
            code="gpo_linked",
            hint="Remove the links first, or delete it anyway.",
            context={"links": [link["container"] for link in links]},
        )

    # Files first: an orphaned directory object can still be found and cleaned
    # up, an orphaned SYSVOL tree is invisible in every console.
    if gpo["path"]:
        try:
            _, _, path = sysvol.parse_unc(gpo["path"])
            share = sysvol.sysvol_for(conn)
            if share.exists(path):
                share.delete_tree(path)
        except InvalidRequest:
            logger.warning("GPO %s has an unusable path, skipping SYSVOL", gpo["name"])

    conn.delete(dn, recursive=True)
    return {"dn": dn, "name": gpo["name"], "links_left": len(links)}

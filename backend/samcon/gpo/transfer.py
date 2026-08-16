"""Copying, backing up and restoring a policy.

All three move the same thing: a directory object and a SYSVOL tree that have
to arrive together. Copying does it inside one domain, backup and restore do
it through a file an administrator can keep.

The backup is a ZIP holding the SYSVOL tree plus the two extension-name
attributes as ``.SAMBAEXT`` files — the same two files ``samba-tool gpo
backup`` writes, under the same names. Unpacked, the archive is therefore a
directory ``samba-tool gpo restore`` accepts, and a backup taken here can be
restored on a DC without SAMCON. That compatibility is the reason for the
format; a ZIP of our own design would have been less work and less use.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import UTC, datetime
from typing import Any

from samcon.ad.connection import DirectoryConnection
from samcon.core.errors import Conflict, InvalidRequest
from samcon.gpo import container, sysvol

logger = logging.getLogger(__name__)

# The names samba-tool uses for the two LDAP attributes it carries alongside
# the files. Kept byte for byte so both tools read each other's backups.
MACHINE_EXT_FILE = "gPCMachineExtensionNames.SAMBAEXT"
USER_EXT_FILE = "gPCUserExtensionNames.SAMBAEXT"

# Ours, and ignored by samba-tool: what the policy was called and where it
# came from. A backup that cannot say which policy it is has to be identified
# by its file name, which is how restores end up on the wrong object.
MANIFEST_FILE = "samcon-backup.json"

# A policy is a handful of small files. The ceiling is here so a share that
# somehow holds something enormous cannot be pulled into memory whole.
MAX_BACKUP_BYTES = 64 * 1024 * 1024


# ---------------------------------------------------------------------------
# Copying
# ---------------------------------------------------------------------------


def copy_gpo(conn: DirectoryConnection, dn: str, display_name: str) -> dict[str, Any]:
    """Duplicate a policy under a new name.

    The copy gets a new identifier and its own permissions — derived from its
    own object, as for any new policy. Carrying the source's permissions over
    is what GPMC offers as a second option, and the reason it asks is that a
    copy with inherited filtering silently applies to whoever the original
    applied to.

    Links are not copied. A link says *where* a policy applies, which is
    exactly the decision the person making a copy still has to take.
    """
    source = container.get_gpo(conn, dn)
    created = container.create_gpo(conn, display_name)

    try:
        if source["path"]:
            _copy_tree(conn, source, created)

        changes: dict[str, Any] = {}
        for attribute, key in (
            ("gPCMachineExtensionNames", "machine_extensions"),
            ("gPCUserExtensionNames", "user_extensions"),
        ):
            if source[key]:
                changes[attribute] = source[key]
        # The version comes along: a copy that claims version 0 while holding
        # the source's settings would be re-read by clients only after the
        # next edit.
        if source["version"]:
            changes["versionNumber"] = str(source["version"])
        if source["flags"]:
            changes["flags"] = str(source["flags"])
        if changes:
            conn.modify_attributes(created["dn"], changes)

        if source["version"]:
            _write_version(conn, created, source["version"], display_name)
    except Exception:
        logger.exception("copying %s failed; removing the incomplete copy", source["guid"])
        try:
            container.delete_gpo(conn, created["dn"], force=True)
        except Exception:
            logger.warning("could not remove the incomplete copy", exc_info=True)
        raise

    return container.get_gpo(conn, created["dn"])


def _copy_tree(conn: DirectoryConnection, source: dict[str, Any], target: dict[str, Any]) -> None:
    share = sysvol.sysvol_for(conn)
    _, _, from_path = sysvol.parse_unc(source["path"])
    _, _, to_path = sysvol.parse_unc(target["path"])

    for entry in _entries(share, from_path):
        relative = entry["path"][len(from_path) + 1 :]
        destination = sysvol.join(to_path, relative)
        if entry["is_directory"]:
            if not share.is_directory(destination):
                share.mkdir(destination)
        else:
            share.write(destination, share.read(entry["path"]))


def _entries(
    share: sysvol.SysvolConnection, base: str, *, depth: int = 8
) -> list[dict[str, Any]]:
    """Everything below *base*, directories before the files inside them."""
    if depth <= 0:
        return []

    found: list[dict[str, Any]] = []
    for entry in share.listdir(base):
        found.append(entry)
        if entry["is_directory"]:
            found.extend(_entries(share, entry["path"], depth=depth - 1))
    return found


def _write_version(
    conn: DirectoryConnection, gpo: dict[str, Any], version: int, display_name: str
) -> None:
    share = sysvol.sysvol_for(conn)
    _, _, path = sysvol.parse_unc(gpo["path"])
    share.write(sysvol.join(path, sysvol.GPT_INI), sysvol.format_gpt_ini(version, display_name))


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def backup_gpo(conn: DirectoryConnection, dn: str) -> tuple[str, bytes]:
    """Pack a policy into a ZIP. Returns a suggested file name and the bytes."""
    gpo = container.get_gpo(conn, dn)
    if not gpo["path"]:
        raise InvalidRequest(
            "This policy has no SYSVOL path to back up.",
            code="no_path",
            context={"dn": dn},
        )

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])

    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in _entries(share, base):
            if entry["is_directory"]:
                continue
            data = share.read(entry["path"])
            total += len(data)
            if total > MAX_BACKUP_BYTES:
                raise InvalidRequest(
                    "This policy is too large to back up in one file.",
                    code="backup_too_large",
                    context={"limit_bytes": MAX_BACKUP_BYTES},
                )
            # Forward slashes inside the archive: that is what the format
            # says, and what every unpacker on either platform expects.
            archive.writestr(entry["path"][len(base) + 1 :].replace("\\", "/"), data)

        # Only when the attribute is actually set. An empty .SAMBAEXT file is
        # not the same as an absent one: `samba-tool gpo restore` writes back
        # whatever the file contains, and LDB refuses an attribute with an
        # empty value — so a policy that simply has no user extensions would
        # produce an archive that samba-tool cannot restore.
        if gpo["machine_extensions"]:
            archive.writestr(MACHINE_EXT_FILE, gpo["machine_extensions"])
        if gpo["user_extensions"]:
            archive.writestr(USER_EXT_FILE, gpo["user_extensions"])
        archive.writestr(
            MANIFEST_FILE,
            json.dumps(
                {
                    "guid": gpo["guid"],
                    "display_name": gpo["display_name"],
                    "version": gpo["version"],
                    "flags": gpo["flags"],
                    "domain": conn.info.dns_domain,
                    "taken": datetime.now(UTC).isoformat(),
                },
                indent=2,
            ),
        )

    name = (gpo["display_name"] or gpo["guid"]).strip()
    safe = "".join(char if char.isalnum() or char in "-_ " else "_" for char in name).strip()
    return f"{safe or 'policy'}.zip", buffer.getvalue()


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def restore_gpo(
    conn: DirectoryConnection, archive_bytes: bytes, *, display_name: str | None = None
) -> dict[str, Any]:
    """Create a policy from a backup.

    Always a *new* policy with a new identifier, never an overwrite of the
    one it came from. Restoring onto the original would silently discard
    whatever has happened to it since, and the identifier is what every link
    in the domain points at — a restore that keeps it cannot be undone.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise InvalidRequest(
            "This file is not a policy backup.", code="invalid_backup"
        ) from exc

    manifest = _read_manifest(archive)
    name = (display_name or manifest.get("display_name") or "").strip()
    if not name:
        raise InvalidRequest(
            "The backup does not say what the policy was called.",
            code="missing_name",
            hint="Give a name for the restored policy.",
        )

    for existing in container.list_gpos(conn):
        if (existing["display_name"] or "").lower() == name.lower():
            raise Conflict(
                "A group policy with this name already exists.",
                code="gpo_exists",
                context={"name": name},
            )

    created = container.create_gpo(conn, name)
    try:
        _unpack(conn, archive, created)

        changes: dict[str, Any] = {}
        machine = _read_member(archive, MACHINE_EXT_FILE)
        user = _read_member(archive, USER_EXT_FILE)
        if machine:
            changes["gPCMachineExtensionNames"] = machine
        if user:
            changes["gPCUserExtensionNames"] = user
        version = int(manifest.get("version") or 0)
        if version:
            changes["versionNumber"] = str(version)
        flags = int(manifest.get("flags") or 0)
        if flags:
            changes["flags"] = str(flags)
        if changes:
            conn.modify_attributes(created["dn"], changes)
        if version:
            _write_version(conn, created, version, name)
    except Exception:
        logger.exception("restoring into %s failed; removing it again", created["guid"])
        try:
            container.delete_gpo(conn, created["dn"], force=True)
        except Exception:
            logger.warning("could not remove the incomplete policy", exc_info=True)
        raise

    return container.get_gpo(conn, created["dn"])


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    """Our own metadata, if the backup carries it.

    A backup written by ``samba-tool`` has none, and that is fine — it just
    means the name has to be given.
    """
    raw = _read_member(archive, MANIFEST_FILE)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("the backup's manifest is not readable")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _read_member(archive: zipfile.ZipFile, name: str) -> str:
    try:
        return archive.read(name).decode("utf-8", "replace").strip()
    except KeyError:
        return ""


def _unpack(conn: DirectoryConnection, archive: zipfile.ZipFile, gpo: dict[str, Any]) -> None:
    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])

    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if name in (MACHINE_EXT_FILE, USER_EXT_FILE, MANIFEST_FILE):
            continue

        relative = _safe_relative(name)
        if relative is None:
            logger.warning("skipping %s in the backup: unsafe path", name)
            continue
        if info.file_size > MAX_BACKUP_BYTES:
            raise InvalidRequest(
                "A file in this backup is too large.",
                code="backup_too_large",
                context={"file": name},
            )

        target = sysvol.join(base, relative)
        parent = target.rsplit("\\", 1)[0]
        if parent != base:
            share.makedirs(parent)
        share.write(target, archive.read(info))


def _safe_relative(name: str) -> str | None:
    """Turn an archive member name into a path inside the policy, or nothing.

    A ZIP can name any path it likes, including ones with ``..`` in them or an
    absolute root. Unpacked onto SYSVOL by an administrator's own ticket, such
    an entry would write wherever it pointed — so anything that is not a plain
    relative path is dropped rather than sanitised into something else.
    """
    cleaned = name.replace("\\", "/").strip()
    if not cleaned or cleaned.startswith("/"):
        return None

    parts = []
    for part in cleaned.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)

    if not parts:
        return None
    return "\\".join(parts)

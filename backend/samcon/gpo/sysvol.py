"""The SYSVOL half of a GPO, over SMB.

Everything else in SAMCON speaks LDAP. This module is the exception: the files
a group policy consists of live on the ``sysvol`` share, and there is no way to
reach them through the directory.

The share is opened with the signed-in administrator's Kerberos ticket, the
same one the LDAP connection uses — so file permissions on SYSVOL apply exactly
as they would to that person at a Windows client, and nothing here runs with
rights the administrator does not have.

Paths inside this module are share-relative and use backslashes, because that
is what the SMB client expects: ``example.lan\\Policies\\{GUID}\\GPT.INI``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from samcon.ad.connection import DirectoryConnection
from samcon.core.errors import InvalidRequest, SamconError, translate

logger = logging.getLogger(__name__)

SHARE = "sysvol"

# The file that tells a client which version of a policy it last applied.
GPT_INI = "GPT.INI"

# What a directory listing must ask for. Windows marks its policy files hidden
# — scripts.ini, fdeploy1.ini and fdeploy.ini among them — and a listing that
# omits them reports a policy as emptier than it is. The same mask Samba's own
# ntacls and gpo tooling passes: read-only, hidden, system, directory, archive.
LISTING_ATTRIBUTES = 0x1 | 0x2 | 0x4 | 0x10 | 0x20

# Fields of the SMB2 CREATE request, for opening a file that already exists
# without saying anything about its attributes. Written as literals rather
# than imported from the bindings: they are wire constants, fixed for as long
# as the protocol is, and keeping them here is what lets the write paths be
# tested without a domain controller — which is the gap that let a hidden file
# break the editor unnoticed in the first place.
FILE_OVERWRITE_IF = 0x5  # truncate it if it is there, create it if not
SHARE_READ_WRITE = 0x1 | 0x2
WRITE_ACCESS = 0x2 | 0x4 | 0x00100000  # write data, append data, synchronize
FILE_ATTRIBUTE_NORMAL = 0x80

# A UNC path as AD stores it in gPCFileSysPath.
_UNC_RE = re.compile(r"^\\\\(?P<host>[^\\]+)\\(?P<share>[^\\]+)\\(?P<path>.*)$")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def parse_unc(unc: str) -> tuple[str, str, str]:
    """Split ``\\\\host\\share\\path`` into its three parts.

    Forward slashes are accepted because they turn up in hand-edited
    attributes, and the difference is not one an administrator should have to
    care about.
    """
    text = (unc or "").strip().replace("/", "\\")
    match = _UNC_RE.match(text)
    if match is None:
        raise InvalidRequest(
            "This is not a usable SYSVOL path.",
            code="invalid_unc",
            context={"path": unc},
        )
    return match.group("host"), match.group("share"), match.group("path")


def gpo_unc(realm: str, guid: str) -> str:
    """The path AD records in ``gPCFileSysPath``."""
    return f"\\\\{realm}\\{SHARE}\\{realm}\\Policies\\{guid}"


def gpo_path(realm: str, guid: str) -> str:
    """The same location, relative to the share."""
    return f"{realm}\\Policies\\{guid}"


def join(*parts: str) -> str:
    return "\\".join(part.strip("\\") for part in parts if part)


# ---------------------------------------------------------------------------
# The connection
# ---------------------------------------------------------------------------


class SysvolConnection:
    """An open SMB session to the ``sysvol`` share of one DC."""

    def __init__(self, conn: Any, host: str, realm: str) -> None:
        self.conn = conn
        self.host = host
        self.realm = realm

    # -- reading -----------------------------------------------------------

    def is_directory(self, path: str) -> bool:
        """Whether *path* is a directory.

        ``chkpath`` answers exactly that and nothing else: on a file it fails
        with NT_STATUS_NOT_A_DIRECTORY. It therefore cannot stand in for an
        existence check — which is why :meth:`exists` does not use it alone.
        """
        try:
            return bool(self.conn.chkpath(path))
        except Exception:  # noqa: BLE001
            # A missing path, a file, or one we may not look at — none of them
            # is a directory we can use.
            return False

    def exists(self, path: str) -> bool:
        """Whether *path* exists, as a file or as a directory."""
        if self.is_directory(path):
            return True

        parent, _, name = path.rpartition("\\")
        if not name:
            return False
        try:
            entries = self.conn.list(parent)
        except Exception:  # noqa: BLE001 — an unreadable parent means no
            return False

        wanted = name.lower()
        for entry in entries:
            found = entry["name"] if isinstance(entry, dict) else getattr(entry, "name", "")
            if str(found).lower() == wanted:
                return True
        return False

    def read(self, path: str) -> bytes:
        try:
            return bytes(self.conn.loadfile(path))
        except Exception as exc:
            raise _translate_smb(exc, path) from exc

    def resolve(self, base: str, relative: str) -> str | None:
        """The real path of ``base\\relative``, or None if it is not there.

        Each component is matched against a listing rather than probed
        directly, because names on SYSVOL come in whatever case the tool that
        wrote them used — Samba's provisioning writes ``MACHINE``, Windows
        writes ``Machine`` — and whether the share hides that difference is a
        server setting.
        """
        current = base
        for part in [item for item in relative.replace("/", "\\").split("\\") if item]:
            try:
                entries = self.listdir(current)
            except Exception:  # noqa: BLE001 — an unreadable parent means no
                return None

            wanted = part.lower()
            found = next(
                (entry["path"] for entry in entries if entry["name"].lower() == wanted), None
            )
            if found is None:
                return None
            current = found
        return current

    def read_text(self, path: str) -> str:
        """Read a policy file as text.

        Group policy files are a mix of encodings — ``GPT.INI`` is ASCII,
        ``GptTmpl.inf`` is UTF-16 with a BOM, and ``Registry.pol`` is binary
        and must not come through here at all. Decoding is by BOM, falling
        back to UTF-8 with replacement so a damaged file is still readable
        rather than an exception in the middle of a listing.
        """
        raw = self.read(path)
        if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
            return raw.decode("utf-16")
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw.decode("utf-8-sig")
        return raw.decode("utf-8", "replace")

    def listdir(self, path: str) -> list[dict[str, Any]]:
        """Entries directly below *path*, without ``.`` and ``..``.

        Hidden and system entries are asked for explicitly. Windows marks its
        policy files hidden — ``scripts.ini`` and ``fdeploy1.ini`` among them —
        and a listing that leaves them out does not fail: the settings report
        shows a policy with less in it than it has, and a backup quietly
        travels without them. Samba's own tooling passes the same mask.
        """
        try:
            entries = self.conn.list(path, attribs=LISTING_ATTRIBUTES)
        except TypeError:
            # An older binding without the keyword. Its default may already
            # include them; either way this is better than not listing at all.
            entries = self.conn.list(path)
        except Exception as exc:
            raise _translate_smb(exc, path) from exc

        result = []
        for entry in entries:
            name = entry["name"] if isinstance(entry, dict) else getattr(entry, "name", None)
            if name in (None, ".", ".."):
                continue
            attrib = entry.get("attrib", 0) if isinstance(entry, dict) else 0
            # Whatever timestamp the build offers, under one name. Used to
            # tell whether a cached copy of a file is still current; a build
            # that offers none falls back to the size, which catches most
            # edits but not all.
            changed = None
            if isinstance(entry, dict):
                for field in ("mtime", "write_time", "change_time"):
                    if entry.get(field):
                        changed = entry[field]
                        break
            result.append(
                {
                    "changed": changed,
                    "name": name,
                    "path": join(path, name),
                    # Kept raw as well: overwriting a file means naming the
                    # attributes it already has, or SMB refuses the open.
                    "attributes": attrib,
                    # FILE_ATTRIBUTE_DIRECTORY
                    "is_directory": bool(attrib & 0x10),
                    "size": entry.get("size", 0) if isinstance(entry, dict) else 0,
                }
            )
        result.sort(key=lambda item: (not item["is_directory"], item["name"].lower()))
        return result

    # -- writing -----------------------------------------------------------

    def write(self, path: str, data: bytes) -> None:
        try:
            self.conn.savefile(path, data)
        except Exception as exc:
            error = _translate_smb(exc, path)

            if error.code == "insufficient_access":
                # Almost certainly not a permission at all. `savefile` opens
                # with FILE_OVERWRITE and normal attributes, and SMB refuses
                # that on a file marked hidden or read-only — with
                # ACCESS_DENIED, which sends the reader to look at ACLs that
                # are fine. GPMC marks scripts.ini, fdeploy1.ini and
                # fdeploy.ini hidden, so this is every policy file Windows
                # wrote, not an edge case.
                logger.info("%s refused a plain overwrite; opening it in place", path)
                try:
                    self._overwrite_in_place(path, data)
                    return
                except Exception as retry:  # noqa: BLE001 — the fallback covers all of them
                    # Keep going rather than leave the file uneditable. The
                    # in-place path depends on parts of the SMB binding whose
                    # shape varies between Samba builds; replacing the file
                    # works everywhere and costs only the DOS attributes,
                    # which are cosmetic — Windows hides these files so they
                    # stay out of Explorer, and nothing reads them.
                    #
                    # Said out loud on purpose. A silent change to somebody
                    # else's policy is the thing worth refusing; an announced
                    # one is a trade.
                    logger.warning(
                        "%s could not be written in place (%s); replacing it, "
                        "which clears its hidden and read-only attributes",
                        path,
                        retry,
                    )

                try:
                    self.conn.unlink(path)
                    self.conn.savefile(path, data)
                except Exception as retry:
                    raise _translate_smb(retry, path) from retry
                return

            if error.code != "file_in_use":
                raise error from exc

            # Something else has the file open, and SMB will not let a second
            # writer in. Replacing it — remove, then create — succeeds where
            # overwriting does not, because the old file is only unlinked from
            # the directory while the other reader keeps its own handle.
            logger.info("%s is open elsewhere; replacing it instead", path)
            try:
                self.conn.unlink(path)
                self.conn.savefile(path, data)
            except Exception as retry:
                raise _translate_smb(retry, path) from retry

    def _overwrite_in_place(self, path: str, data: bytes) -> None:
        """Replace a file's contents while keeping its DOS attributes.

        ``savefile`` opens with normal attributes, and SMB refuses that on a
        file marked hidden or read-only. Naming the attributes the file
        already has removes the disagreement, and the *overwrite* disposition
        does the shortening — so nothing has to be truncated afterwards.

        That matters more than it sounds: the binding's ``truncate`` is an
        SMB1 call, and against an SMB3 connection it comes back as
        NT_STATUS_REVISION_MISMATCH. There is no truncate to reach for here.
        """
        attributes = self._attributes_of(path) or FILE_ATTRIBUTE_NORMAL

        fnum = self.conn.create(
            Name=path,
            DesiredAccess=WRITE_ACCESS,
            ShareAccess=SHARE_READ_WRITE,
            CreateDisposition=FILE_OVERWRITE_IF,
            FileAttributes=attributes,
        )
        try:
            self.conn.write(fnum, data, 0)
        finally:
            self.conn.close(fnum)

    def _attributes_of(self, path: str) -> int:
        """The DOS attributes of one file, or 0 when it cannot be told.

        Read from the parent's listing rather than queried: the listing is
        already asked for hidden and system entries, and one round trip that
        may be cached beats a second call shape to get wrong.
        """
        parent, _, name = path.rpartition("\\")
        try:
            for entry in self.listdir(parent):
                if entry["name"].lower() == name.lower():
                    return int(entry["attributes"])
        except SamconError:
            # Not being able to read them is not a reason to refuse the write;
            # the caller falls back to plain attributes.
            logger.debug("cannot read the attributes of %s", path, exc_info=True)
        return 0

    def mkdir(self, path: str) -> None:
        try:
            self.conn.mkdir(path)
        except Exception as exc:
            raise _translate_smb(exc, path) from exc

    def makedirs(self, path: str) -> None:
        """Create *path* and any missing parent below the share root.

        Checks for a directory rather than for existence: a file where a
        directory belongs is not something to skip over silently.
        """
        parts = [part for part in path.split("\\") if part]
        current = ""
        for part in parts:
            current = join(current, part)
            if not self.is_directory(current):
                self.mkdir(current)

    def unlink(self, path: str) -> None:
        try:
            self.conn.unlink(path)
        except Exception as exc:
            raise _translate_smb(exc, path) from exc

    def delete_tree(self, path: str) -> None:
        try:
            self.conn.deltree(path)
        except Exception as exc:
            raise _translate_smb(exc, path) from exc

    # -- permissions -------------------------------------------------------

    def set_acl(self, path: str, descriptor: Any) -> None:
        """Stamp a security descriptor onto a SYSVOL directory.

        The DACL is marked protected on purpose: a GPO's file permissions are
        derived from its directory object, and inheriting the share's
        permissions on top of that would quietly widen who can read the policy.
        """
        from samba.dcerpc import security

        info = (
            security.SECINFO_OWNER
            | security.SECINFO_GROUP
            | security.SECINFO_DACL
            | security.SECINFO_PROTECTED_DACL
        )
        try:
            self.conn.set_acl(path, descriptor, info)
        except Exception as exc:
            raise _translate_smb(exc, path) from exc

    def get_acl_sddl(self, path: str) -> str | None:
        from samba.dcerpc import security

        info = security.SECINFO_OWNER | security.SECINFO_GROUP | security.SECINFO_DACL
        try:
            descriptor = self.conn.get_acl(path, info)
        except Exception:
            logger.debug("cannot read the ACL of %s", path, exc_info=True)
            return None
        try:
            return descriptor.as_sddl()
        except Exception:
            logger.debug("ACL of %s is not renderable as SDDL", path, exc_info=True)
            return None

    def close(self) -> None:
        """Hang up, rather than waiting for the garbage collector.

        A dropped reference eventually closes the session, but "eventually" is
        long enough for the server to still hold handles on files this session
        touched — and the next write to one of them is refused.
        """
        client, self.conn = self.conn, None
        if client is None:
            return
        for name in ("disconnect", "close"):
            method = getattr(client, name, None)
            if callable(method):
                try:
                    method()
                except Exception:  # teardown must not raise
                    logger.debug("SYSVOL %s() failed", name, exc_info=True)
                return


# ---------------------------------------------------------------------------
# Opening it
# ---------------------------------------------------------------------------


# enum smb_signing_setting, in case the binding does not export it.
SMB_SIGNING_REQUIRED = 3


def _signing_required() -> int:
    try:
        from samba import credentials
    except ImportError:  # pragma: no cover - the image always has it
        return SMB_SIGNING_REQUIRED
    return int(getattr(credentials, "SMB_SIGNING_REQUIRED", SMB_SIGNING_REQUIRED))


def smb_loadparm(conn: DirectoryConnection, *, from_file: bool = True) -> Any:
    """The loadparm the SMB bindings need.

    Not the one the LDAP connection uses. ``libsmb`` is a binding over the
    source3 code base and wants a **source3** loadparm context; handing it the
    ``samba.param.LoadParm`` that SamDB takes produces
    ``NT_STATUS_INVALID_PARAMETER_MIX`` — a status that names neither the
    parameter nor the mix. Samba's own tooling says as much in a one-line
    comment in ``samba/netcmd/gpcommon.py``, and does exactly what happens
    here.

    Realm and workgroup are deliberately *not* set on it. The s3 context is
    process-global, so writing a session's realm into it would reach into every
    other session signed in to a different domain. The SMB connection does not
    need them: the principal comes from the ticket.
    """
    from samba.samba3 import param as s3param

    lp = s3param.get_context()
    config = conn.settings.smb_conf
    if from_file and config.exists():
        lp.load(str(config))
    else:
        lp.load_default()
    return lp


def smb_credentials(
    conn: DirectoryConnection, lp: Any, *, force_signing: bool = True
) -> Any:
    """Credentials for the SMB client, from the session's ticket.

    A second object rather than the one the LDAP bind used: Samba's
    credentials carry negotiated state, and handing a used one to a different
    protocol stack is not something the bindings promise to support.

    Signing is required rather than left to negotiation, which is what
    ``samba-tool`` does before every SYSVOL connection. Group policy files
    decide what runs on every domain member; an unsigned connection to fetch
    them is worth refusing.
    """
    from samba.credentials import MUST_USE_KERBEROS, Credentials

    from samcon.auth.kerberos import CRED_SPECIFIED, ccache_url

    if conn.ccache is None:
        raise SamconError(
            "This connection carries no Kerberos ticket for SYSVOL.",
            code="sysvol_unavailable",
            hint="The directory connection was built without one.",
        )

    creds = Credentials()
    creds.guess(lp)
    creds.set_kerberos_state(MUST_USE_KERBEROS)

    if force_signing:
        creds.set_smb_signing(_signing_required())

    name = ccache_url(conn.ccache)
    for attempt in (
        lambda: creds.set_named_ccache(name, CRED_SPECIFIED, lp),
        lambda: creds.set_named_ccache(name, lp),
        lambda: creds.set_named_ccache(name),
    ):
        try:
            attempt()
            return creds
        except TypeError:
            continue
    raise SamconError(
        "The Kerberos credential cache could not be attached to the SMB connection.",
        code="ccache_unsupported",
    )


def connect(conn: DirectoryConnection) -> SysvolConnection:
    """Open the SYSVOL share of the DC this session is already talking to.

    Deliberately the same DC as the LDAP connection: SYSVOL replicates between
    DCs on its own schedule, and writing the files to one while the directory
    half goes to another produces a policy that is briefly inconsistent for no
    reason.

    Samba's SMB client rejects some combinations of loadparm and credentials
    with a single opaque status — NT_STATUS_INVALID_PARAMETER_MIX — that names
    neither the parameter nor the combination. Rather than pin one form, the
    documented variants are tried in order of preference and every failure is
    reported, so a build that wants a different one says so instead of leaving
    the whole SYSVOL half unusable.
    """
    try:
        from samba.samba3 import libsmb_samba_internal as libsmb
    except ImportError as exc:  # pragma: no cover - the image always has it
        raise SamconError(
            "The Samba SMB bindings are not available.",
            code="samba_missing",
            hint="The container image must provide python3-samba.",
        ) from exc

    host = conn.info.dc_hostname or conn.host
    if not host:
        raise SamconError(
            "No domain controller name is known for the SMB connection.",
            code="sysvol_unavailable",
            hint="The rootDSE did not report a dnsHostName.",
        )

    failures: list[str] = []
    for label, build in _connection_variants(conn):
        try:
            lp, creds = build()
            client = libsmb.Conn(host, SHARE, lp=lp, creds=creds)
        except Exception as exc:  # noqa: BLE001 — the next variant may work
            failures.append(f"{label}: {exc}")
            logger.info("SYSVOL on %s rejected the %s form: %s", host, label, exc)
            continue

        logger.info("opened SYSVOL on %s (%s)", host, label)
        return SysvolConnection(client, host, conn.info.dns_domain)

    raise SamconError(
        "The SYSVOL share could not be opened.",
        code="sysvol_unavailable",
        status_code=502,
        detail="; ".join(failures),
        hint=(
            "Group policy needs SMB to the domain controller in addition to LDAP. "
            "Check that port 445 is reachable and that the signed-in account may "
            "read the share."
        ),
        context={"host": host, "share": SHARE},
    )


def _connection_variants(conn: DirectoryConnection) -> list[tuple[str, Any]]:
    """The forms to try, most correct first.

    Each is a different hypothesis about what the SMB client objects to, and
    they are ordered so the first success is also the one we would have chosen
    deliberately.
    """
    # Both forms require signing. There is no unsigned fallback on purpose:
    # these files decide what runs on every domain member, so a connection
    # that cannot be signed is one to refuse rather than to fall back to.
    return [
        # What samba-tool does: the s3 loadparm from our smb.conf.
        ("s3 loadparm + signing", lambda: _pair(conn, from_file=True, force_signing=True)),
        # Samba's built-in defaults, in case our smb.conf is what it objects to.
        ("s3 defaults + signing", lambda: _pair(conn, from_file=False, force_signing=True)),
    ]


def _pair(conn: DirectoryConnection, *, from_file: bool, force_signing: bool) -> tuple[Any, Any]:
    lp = smb_loadparm(conn, from_file=from_file)
    return lp, smb_credentials(conn, lp, force_signing=force_signing)


def sysvol_for(conn: DirectoryConnection) -> SysvolConnection:
    """The session's SYSVOL connection, opening it on first use.

    Cached on the directory connection, which is per session and per worker
    thread — so this is a second handle on the same authenticated session, not
    a shared one.
    """
    if conn.sysvol is None:
        conn.sysvol = connect(conn)
    return conn.sysvol


def _translate_smb(exc: Exception, path: str) -> SamconError:
    """Turn an SMB failure into something that names the path.

    Samba's SMB errors carry an NT_STATUS but no context, and "access denied"
    without saying to what is not a message anyone can act on.
    """
    error = translate(exc)
    if not error.context.get("path"):
        error.context["path"] = path

    # The path belongs in the detail, not only in the context: the context is
    # not shown, and "access denied" without saying *to what* leaves no way to
    # tell an SMB refusal from an LDAP one — which is the first question.
    located = f"{path}: {error.detail}" if error.detail else path
    error.detail = located

    if error.code == "insufficient_access":
        # Replaces whatever generic advice came with it. This one is about the
        # share, and the two permissions are granted in different places.
        error.hint = (
            "The signed-in account needs write access to the SYSVOL share, "
            "not only to the directory object."
        )
    return error


# ---------------------------------------------------------------------------
# GPT.INI
# ---------------------------------------------------------------------------


def parse_gpt_ini(text: str) -> dict[str, Any]:
    """Read ``GPT.INI``.

    A tiny INI with one section that matters. Written by hand rather than with
    configparser: the file uses CRLF and a fixed key order that Windows tools
    expect back, and round-tripping it through configparser loses both.
    """
    values: dict[str, str] = {}
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        if section != "general" or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip().lower()] = value.strip()

    try:
        version = int(values.get("version", "0"))
    except ValueError:
        version = 0

    machine, user = split_version(version)
    return {
        "version": version,
        "machine_version": machine,
        "user_version": user,
        "display_name": values.get("displayname"),
    }


def format_gpt_ini(version: int, display_name: str | None = None) -> bytes:
    """Write ``GPT.INI`` the way Windows writes it.

    CRLF line endings, ``[General]`` first. The file is read by clients that
    predate anyone's patience for parser robustness.
    """
    lines = ["[General]", f"Version={version}"]
    if display_name:
        lines.append(f"displayName={display_name}")
    return ("\r\n".join(lines) + "\r\n").encode("ascii", "replace")


def combine_version(machine: int, user: int) -> int:
    """The single number GPT.INI and ``versionNumber`` both carry.

    The **low** word counts changes to the computer half, the **high** word
    the user half — that way round, which is easy to get backwards and shows
    up only as a version that seems not to move.

    Two independent confirmations: a domain's drive-mapping policy, all user
    configuration, reads 0x00100001 — sixteen user changes, one computer
    change; and Samba's own writer advances the low word when it is handed a
    MACHINE-class value.
    """
    return ((user & 0xFFFF) << 16) | (machine & 0xFFFF)


def split_version(version: int) -> tuple[int, int]:
    """(computer, user) — in the order the halves are usually spoken of."""
    return version & 0xFFFF, (version >> 16) & 0xFFFF

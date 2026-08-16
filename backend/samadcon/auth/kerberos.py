"""Kerberos ticket handling.

Each session gets its own credential cache below /dev/shm. All later LDAP and
SMB work runs from that cache, so every operation carries the rights of the
administrator who signed in — SAMADCON itself never needs a privileged account.

The password is used once, to obtain the ticket, and is never written anywhere.

Two ways to acquire a ticket are implemented:

1. ``Credentials.get_named_ccache()`` from the Samba bindings — preferred,
   because it is the same code path samba-tool uses.
2. ``kinit`` as a subprocess with the password on stdin — fallback for Samba
   builds whose binding signature differs.

The second path exists because that binding's signature has varied across
Samba releases; :func:`acquire_ticket` tries the first and falls back without
bothering the caller.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from samadcon.ad.target import ConnectionTarget
from samadcon.config import Settings
from samadcon.core.errors import AuthenticationError, SamadconError, translate

logger = logging.getLogger(__name__)

# How long to wait for a domain controller to accept a connection. Generous
# enough for a DC across a slow link, short enough that an address nothing
# answers on is reported rather than waited out.
LDAP_CONNECT_TIMEOUT_SECONDS = 10

# samba's enum credentials_obtained. Spelled out because the numeric values
# are easy to mix up: CRED_GUESS_ENV is 3, and passing that instead leaves the
# credential cache at guess priority — the bind then fails with a parameter
# error rather than saying what is wrong. Read from the bindings when they are
# available so a future renumbering cannot silently break us.
try:  # pragma: no cover - depends on python3-samba being installed
    from samba.credentials import CRED_SPECIFIED
except ImportError:  # pragma: no cover
    CRED_SPECIFIED = 6

# Anything else is not a valid sAMAccountName / UPN local part and is rejected
# before it reaches the KDC.
_PRINCIPAL_RE = re.compile(r"^[A-Za-z0-9._\-$]{1,256}$")
_KLIST_EXPIRY_RE = re.compile(
    r"^\s*(\d{2}/\d{2}/\d{2,4}|\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s+"
    r"(\d{2}/\d{2}/\d{2,4}|\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s+krbtgt/",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Principal:
    """A parsed ``user@REALM``."""

    username: str
    realm: str

    @property
    def full(self) -> str:
        return f"{self.username}@{self.realm}"


def parse_principal(raw: str, default_realm: str) -> Principal:
    """Split user input into user and realm.

    Accepts ``user``, ``user@realm`` and ``DOMAIN\\user``.
    """
    value = raw.strip()
    if not value:
        raise AuthenticationError("User name is missing.", code="missing_username")

    if "\\" in value:
        _, _, value = value.partition("\\")

    if "@" in value:
        username, _, realm = value.partition("@")
        realm = realm.upper()
    else:
        username, realm = value, default_realm.upper()

    if not _PRINCIPAL_RE.match(username):
        raise AuthenticationError(
            "The user name contains invalid characters.", code="invalid_username"
        )
    if not username or not realm:
        raise AuthenticationError("User name or realm is missing.", code="missing_username")

    return Principal(username=username, realm=realm)


def ccache_path_for(settings: Settings, session_id: str) -> Path:
    return settings.ccache_dir / f"tkt-{session_id}"


def ccache_url(ccache: Path | str) -> str:
    """Credential cache name in the form the Kerberos library expects.

    The type prefix is not decoration: a bare path is rejected, and the bind
    then fails with NT_STATUS_INVALID_PARAMETER long after the ticket was
    obtained successfully. samba-tool's --use-krb5-ccache does the same
    prefixing.
    """
    text = str(ccache)
    # Already carries a type (FILE:, DIR:, KEYRING:, KCM:, ...). A Windows
    # drive letter is not one, hence the second condition.
    if ":" in text and text[1:2] != ":":
        return text
    return f"FILE:{text}"


def load_loadparm(settings: Settings, target: ConnectionTarget, *, transport: str = "ldap"):
    """Build a LoadParm for one connection target and transport.

    Realm and transport settings come from the target rather than from the
    process-wide configuration: two sessions may be signed in to different
    domains, with different certificates and different trust decisions.
    """
    from samba.param import LoadParm

    lp = LoadParm()
    if settings.smb_conf.exists():
        lp.load(str(settings.smb_conf))
    else:
        lp.load_default()

    lp.set("realm", target.realm)
    lp.set("workgroup", target.netbios_name)

    apply_transport_settings(
        lp,
        transport=transport,
        ca_file=target.ca_file or settings.ldap_ca_file,
        # Either the target or the container-wide switch may relax validation.
        insecure=target.insecure or settings.ldap_insecure,
    )

    # Bound the connection attempt. Samba's own default let an address that
    # nothing answers on hang for 135 seconds — measured, against a name that
    # resolved to an unreachable host — and the interface showed nothing at
    # all in the meantime. The probe has always bounded this; the connection
    # that follows it did not, which is the asymmetry that made a name
    # resolving to the wrong address look like a frozen sign-in.
    #
    # Only the *connection* phase is bounded. `ldap timeout` covers whole
    # operations, and a paged search over a large directory is legitimately
    # slow: cutting that short would trade one bad failure for another.
    _try_set(lp, "ldap connection timeout", str(LDAP_CONNECT_TIMEOUT_SECONDS))

    # Applied here rather than left to smb.conf, so raising
    # SAMADCON_SAMBA_LOG_LEVEL takes effect without rebuilding the container.
    # Samba then writes its protocol trace to stderr, i.e. into `docker logs`.
    if settings.samba_log_level:
        lp.set("log level", str(settings.samba_log_level))
    return lp


def _try_set(lp: Any, option: str, value: str) -> None:
    """Set a loadparm option, ignoring ones this Samba build does not know."""
    try:
        lp.set(option, value)
    except Exception:  # noqa: BLE001 — an unknown tuning option is not fatal
        logger.debug("loadparm does not accept %r", option)


def apply_transport_settings(
    lp: Any, *, transport: str, ca_file: Path | None, insecure: bool
) -> None:
    """Configure how the LDAP connection is protected.

    Two transports, and the difference matters:

    ``ldap`` — plain LDAP on port 389 with **GSSAPI sign and seal**. The
    Kerberos session key encrypts the traffic, so no certificate is involved at
    all. This is what samba-tool uses, and what Windows tools do by default; it
    is the best-supported path through Samba's client stack.

    ``ldaps`` — LDAP over TLS on port 636. SASL wrapping must be *plain* here,
    because sign/seal on top of TLS is refused and every authenticated bind
    then fails with NT_STATUS_INVALID_PARAMETER. Note that Samba also rejects
    ``tls verify peer = ca_and_name`` unless a CA source exists, hence the
    fallback to the system trust store.

    In neither case does traffic go over the wire unencrypted: `seal` is
    required rather than requested, so a server that cannot do it fails the
    connection instead of silently downgrading.
    """
    if transport == "ldap":
        lp.set("client ldap sasl wrapping", "seal")
        return

    lp.set("client ldap sasl wrapping", "plain")

    if insecure:
        lp.set("tls verify peer", "no_check")
        return

    if ca_file is not None:
        lp.set("tls cafile", str(ca_file))
    else:
        lp.set("tls trust system cas", "yes")
    lp.set("tls verify peer", "ca_and_name")


def _acquire_via_bindings(
    principal: Principal,
    password: str,
    ccache: Path,
    settings: Settings,
    target: ConnectionTarget,
) -> bool:
    """Obtain a TGT through the Samba bindings. Returns False if unsupported."""
    try:
        from samba.credentials import MUST_USE_KERBEROS, Credentials
    except ImportError:  # pragma: no cover - only on hosts without python3-samba
        return False

    lp = load_loadparm(settings, target)
    creds = Credentials()
    creds.guess(lp)
    creds.set_kerberos_state(MUST_USE_KERBEROS)
    creds.set_username(principal.username)
    creds.set_realm(principal.realm)
    creds.set_password(password)

    try:
        creds.get_named_ccache(lp, ccache_url(ccache))
    except TypeError:
        # Older/newer binding signature — let the caller fall back to kinit
        # rather than guessing at argument orders.
        logger.info("Credentials.get_named_ccache signature mismatch, falling back to kinit")
        return False
    return True


def _acquire_via_kinit(
    principal: Principal, password: str, ccache: Path, settings: Settings
) -> None:
    """Obtain a TGT by running kinit with the password on stdin.

    The password goes through a pipe, never through argv, so it does not show
    up in the process list.
    """
    from samadcon.auth.krb5conf import get_krb5_configuration

    env = dict(os.environ)
    env["KRB5CCNAME"] = ccache_url(ccache)
    # The generated configuration knows every realm SAMADCON has been pointed
    # at, including the KDC address for domains reached by IP.
    env.update(get_krb5_configuration().environment())

    try:
        result = subprocess.run(
            ["kinit", "-f", "-r", "7d", principal.full],
            input=password.encode("utf-8") + b"\n",
            capture_output=True,
            env=env,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SamadconError(
            "Neither the Samba bindings nor kinit could obtain a Kerberos ticket.",
            code="kerberos_unavailable",
            hint="The container image is incomplete: krb5-user is missing.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise translate(
            TimeoutError("kinit did not answer; the KDC is probably unreachable")
        ) from exc

    if result.returncode != 0:
        message = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise translate(RuntimeError(message or "kinit failed"))


def acquire_ticket(
    principal: Principal,
    password: str,
    ccache: Path,
    settings: Settings,
    target: ConnectionTarget,
) -> None:
    """Fetch a TGT for *principal* in *target*'s realm into *ccache*.

    Raises a :class:`~samadcon.core.errors.SamadconError` subclass on failure; the
    caller must not distinguish between the two acquisition paths.
    """
    from samadcon.auth.krb5conf import get_krb5_configuration

    if not password:
        raise AuthenticationError("Password is missing.", code="missing_password")

    # Register the realm before asking for a ticket. This is what lets an IP
    # address work: the KDC is named explicitly instead of being looked up in
    # DNS the container may not be able to query.
    get_krb5_configuration().ensure_realm(target.realm, target.kdcs)

    ccache.parent.mkdir(parents=True, exist_ok=True)
    # Create the file with tight permissions before anything writes secrets to
    # it — otherwise there is a window where the umask decides.
    fd = os.open(ccache, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.close(fd)

    try:
        if not _acquire_via_bindings(principal, password, ccache, settings, target):
            _acquire_via_kinit(principal, password, ccache, settings)
    except Exception as exc:
        destroy_ticket(ccache)
        raise translate(exc) from exc

    # A cache file exists at this point even when nothing was written to it,
    # and a bind with an empty cache fails later as an opaque handshake error.
    # Ask klist whether a usable ticket is actually in there.
    if has_ticket(ccache) is False:
        destroy_ticket(ccache)
        raise AuthenticationError(
            "No Kerberos ticket was issued.",
            code="no_ticket",
            hint=(
                "The credential cache stayed empty. Check the realm spelling, the "
                "clock difference to the KDC, and that the account exists in this domain."
            ),
        )

    if not ccache.exists() or ccache.stat().st_size == 0:
        destroy_ticket(ccache)
        raise AuthenticationError(
            "No Kerberos ticket was issued.",
            code="no_ticket",
            hint="Check the realm spelling and that the KDC is reachable.",
        )


def has_ticket(ccache: Path) -> bool | None:
    """Whether *ccache* holds a valid ticket.

    ``klist -s`` exits 0 only when there is one, which makes it a cheap and
    reliable check. Returns ``None`` when klist is unavailable — then the
    caller must not treat the outcome as a failure.
    """
    from samadcon.auth.krb5conf import get_krb5_configuration

    env = dict(os.environ)
    env.update(get_krb5_configuration().environment())

    try:
        result = subprocess.run(
            ["klist", "-s", "-c", ccache_url(ccache)],
            capture_output=True,
            env=env,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def destroy_ticket(ccache: Path) -> None:
    """Remove a credential cache. Never raises."""
    try:
        ccache.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - tmpfs failure
        logger.warning("could not remove ccache %s: %s", ccache, exc)


def ticket_expiry(ccache: Path) -> datetime | None:
    """Read the TGT's expiry time via klist.

    Returns ``None`` when it cannot be determined; the caller then falls back
    to its configured session lifetime.
    """
    from samadcon.auth.krb5conf import get_krb5_configuration

    env = dict(os.environ)
    env.update(get_krb5_configuration().environment())

    try:
        result = subprocess.run(
            ["klist", "-c", ccache_url(ccache)],
            capture_output=True,
            env=env,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    match = _KLIST_EXPIRY_RE.search(result.stdout.decode("utf-8", "replace"))
    if match is None:
        return None

    date_part, time_part = match.group(3), match.group(4)
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(f"{date_part} {time_part}", fmt)
        except ValueError:
            continue
        # klist prints local time; the container runs in UTC.
        return naive.replace(tzinfo=UTC)
    return None


def default_expiry(hours: int = 10) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)

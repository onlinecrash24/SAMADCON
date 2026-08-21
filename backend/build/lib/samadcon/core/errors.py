"""Error model and translation of Samba/LDAP failures.

Raw LDAP result codes and NT_STATUS strings are useless in a user interface.
Everything raised below the API layer is funnelled through :func:`translate`,
which produces a :class:`SamadconError` carrying

* a stable machine-readable ``code`` (the front end translates it to DE/EN),
* a technical English ``message`` for logs and for admins who want the detail,
* an optional ``hint`` naming the usual cause.

This module deliberately does not import the samba bindings at module level so
the translation logic stays unit-testable on machines without python3-samba.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class SamadconError(Exception):
    """Base class for everything the API layer turns into an HTTP response."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        hint: str | None = None,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.hint = hint
        self.detail = detail
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        if self.detail:
            payload["detail"] = self.detail
        if self.context:
            payload["context"] = self.context
        return payload


class AuthenticationError(SamadconError):
    status_code = 401
    code = "authentication_failed"


class SessionExpired(SamadconError):
    status_code = 401
    code = "session_expired"


class PermissionDenied(SamadconError):
    status_code = 403
    code = "insufficient_access"


class NotFound(SamadconError):
    status_code = 404
    code = "not_found"


class Conflict(SamadconError):
    status_code = 409
    code = "conflict"


class InvalidRequest(SamadconError):
    status_code = 400
    code = "invalid_request"


class ConstraintViolation(SamadconError):
    status_code = 400
    code = "constraint_violation"


class UpstreamUnavailable(SamadconError):
    status_code = 502
    code = "dc_unavailable"


class OperationTimeout(SamadconError):
    status_code = 504
    code = "timeout"


# ---------------------------------------------------------------------------
# LDAP result codes (RFC 4511 numbering, as used by ldb)
# ---------------------------------------------------------------------------

LDB_ERR_OPERATIONS_ERROR = 1
LDB_ERR_PROTOCOL_ERROR = 2
LDB_ERR_TIME_LIMIT_EXCEEDED = 3
LDB_ERR_SIZE_LIMIT_EXCEEDED = 4
LDB_ERR_AUTH_METHOD_NOT_SUPPORTED = 7
LDB_ERR_STRONG_AUTH_REQUIRED = 8
LDB_ERR_REFERRAL = 10
LDB_ERR_ADMIN_LIMIT_EXCEEDED = 11
LDB_ERR_UNSUPPORTED_CRITICAL_EXTENSION = 12
LDB_ERR_NO_SUCH_ATTRIBUTE = 16
LDB_ERR_UNDEFINED_ATTRIBUTE_TYPE = 17
LDB_ERR_INAPPROPRIATE_MATCHING = 18
LDB_ERR_CONSTRAINT_VIOLATION = 19
LDB_ERR_ATTRIBUTE_OR_VALUE_EXISTS = 20
LDB_ERR_INVALID_ATTRIBUTE_SYNTAX = 21
LDB_ERR_NO_SUCH_OBJECT = 32
LDB_ERR_INVALID_DN_SYNTAX = 34
LDB_ERR_INVALID_CREDENTIALS = 49
LDB_ERR_INSUFFICIENT_ACCESS_RIGHTS = 50
LDB_ERR_BUSY = 51
LDB_ERR_UNAVAILABLE = 52
LDB_ERR_UNWILLING_TO_PERFORM = 53
LDB_ERR_LOOP_DETECT = 54
LDB_ERR_NAMING_VIOLATION = 64
LDB_ERR_OBJECT_CLASS_VIOLATION = 65
LDB_ERR_NOT_ALLOWED_ON_NON_LEAF = 66
LDB_ERR_NOT_ALLOWED_ON_RDN = 67
LDB_ERR_ENTRY_ALREADY_EXISTS = 68
LDB_ERR_OBJECT_CLASS_MODS_PROHIBITED = 69
LDB_ERR_AFFECTS_MULTIPLE_DSAS = 71
LDB_ERR_OTHER = 80

# code -> (exception class, slug, message, hint)
_LDAP_ERRORS: dict[int, tuple[type[SamadconError], str, str, str | None]] = {
    # Samba reports a failed SASL/GSSAPI or TLS handshake as an operations
    # error, which is why the hint enumerates those rather than suggesting a
    # server fault.
    LDB_ERR_OPERATIONS_ERROR: (
        UpstreamUnavailable,
        "ldap_operations_error",
        "The directory server refused the connection.",
        (
            "Usually a failed Kerberos or TLS handshake: no service principal for the "
            "address used, a clock difference of more than five minutes, or a "
            "certificate the client will not accept."
        ),
    ),
    LDB_ERR_TIME_LIMIT_EXCEEDED: (
        OperationTimeout,
        "ldap_time_limit",
        "The directory server aborted the search after its time limit.",
        "Narrow the search scope or add a more selective filter.",
    ),
    LDB_ERR_SIZE_LIMIT_EXCEEDED: (
        InvalidRequest,
        "ldap_size_limit",
        "The search returned more entries than the server allows.",
        "Add a filter; SAMADCON pages results but the server limit still applies.",
    ),
    LDB_ERR_STRONG_AUTH_REQUIRED: (
        AuthenticationError,
        "ldap_strong_auth_required",
        "The directory server requires a signed or encrypted connection.",
        "Check that LDAPS is reachable and the DC certificate is trusted.",
    ),
    LDB_ERR_ADMIN_LIMIT_EXCEEDED: (
        InvalidRequest,
        "ldap_admin_limit",
        "The directory server's administrative limit was exceeded.",
        None,
    ),
    LDB_ERR_NO_SUCH_ATTRIBUTE: (
        InvalidRequest,
        "no_such_attribute",
        "The attribute does not exist on this object.",
        None,
    ),
    LDB_ERR_UNDEFINED_ATTRIBUTE_TYPE: (
        InvalidRequest,
        "undefined_attribute",
        "The attribute is not defined in the schema.",
        None,
    ),
    LDB_ERR_CONSTRAINT_VIOLATION: (
        ConstraintViolation,
        "constraint_violation",
        "The value violates a directory constraint.",
        None,
    ),
    LDB_ERR_ATTRIBUTE_OR_VALUE_EXISTS: (
        Conflict,
        "value_exists",
        "The attribute already carries this value.",
        None,
    ),
    LDB_ERR_INVALID_ATTRIBUTE_SYNTAX: (
        InvalidRequest,
        "invalid_syntax",
        "The value does not match the attribute's syntax.",
        None,
    ),
    LDB_ERR_NO_SUCH_OBJECT: (
        NotFound,
        "not_found",
        "The directory object does not exist.",
        "It may have been deleted or moved by someone else in the meantime.",
    ),
    LDB_ERR_INVALID_DN_SYNTAX: (
        InvalidRequest,
        "invalid_dn",
        "The distinguished name is malformed.",
        None,
    ),
    LDB_ERR_INVALID_CREDENTIALS: (
        AuthenticationError,
        "invalid_credentials",
        "Authentication against the directory failed.",
        None,
    ),
    LDB_ERR_INSUFFICIENT_ACCESS_RIGHTS: (
        PermissionDenied,
        "insufficient_access",
        "Your account is not allowed to perform this operation.",
        "Check the delegation on the target object or its parent OU.",
    ),
    LDB_ERR_BUSY: (
        UpstreamUnavailable,
        "dc_busy",
        "The domain controller is busy.",
        None,
    ),
    LDB_ERR_UNAVAILABLE: (
        UpstreamUnavailable,
        "dc_unavailable",
        "The domain controller is unavailable.",
        None,
    ),
    LDB_ERR_UNWILLING_TO_PERFORM: (
        InvalidRequest,
        "unwilling_to_perform",
        "The directory server refused the operation.",
        "Often a protected object, a disallowed attribute change, or a policy restriction.",
    ),
    LDB_ERR_NAMING_VIOLATION: (
        InvalidRequest,
        "naming_violation",
        "The name violates the directory's naming rules.",
        None,
    ),
    LDB_ERR_OBJECT_CLASS_VIOLATION: (
        InvalidRequest,
        "object_class_violation",
        "The object does not satisfy its object class definition.",
        "A mandatory attribute is probably missing.",
    ),
    LDB_ERR_NOT_ALLOWED_ON_NON_LEAF: (
        Conflict,
        "not_empty",
        "The object still contains child objects.",
        "Empty the container first, or delete it recursively.",
    ),
    LDB_ERR_NOT_ALLOWED_ON_RDN: (
        InvalidRequest,
        "rdn_change_not_allowed",
        "This attribute is part of the object's name and cannot be changed here.",
        "Rename the object instead.",
    ),
    LDB_ERR_ENTRY_ALREADY_EXISTS: (
        Conflict,
        "already_exists",
        "An object with this name already exists.",
        None,
    ),
    LDB_ERR_OBJECT_CLASS_MODS_PROHIBITED: (
        InvalidRequest,
        "object_class_immutable",
        "The object class cannot be modified after creation.",
        None,
    ),
    LDB_ERR_OTHER: (
        SamadconError,
        "ldap_other",
        "The directory server reported an unspecified error.",
        None,
    ),
}

# AD's extended sub-status, appended to bind failures as "data 52e".
_AD_BIND_SUBCODES: dict[str, tuple[str, str, str | None]] = {
    "525": ("user_not_found", "No such account in this domain.", None),
    "52e": ("invalid_credentials", "Wrong user name or password.", None),
    "52f": (
        "restricted_account",
        "The account is restricted by policy.",
        None,
    ),
    "530": (
        "logon_time_restriction",
        "The account may not log on at this time.",
        None,
    ),
    "531": (
        "workstation_restriction",
        "The account may not log on from this machine.",
        "SAMADCON authenticates from the container — check the account's logon workstations.",
    ),
    "532": (
        "password_expired",
        "The password has expired.",
        "Change the password first, e.g. on a domain member or via another admin.",
    ),
    "533": ("account_disabled", "The account is disabled.", None),
    "701": ("account_expired", "The account has expired.", None),
    "773": (
        "password_must_change",
        "The password must be changed before the account can be used.",
        None,
    ),
    "775": (
        "account_locked_out",
        "The account is locked out.",
        "Wait for the lockout window to pass or have the account unlocked.",
    ),
}

# NT_STATUS values that reach us through SMB, Kerberos and DCE/RPC.
_NT_STATUS: dict[str, tuple[type[SamadconError], str, str, str | None]] = {
    "NT_STATUS_LOGON_FAILURE": (
        AuthenticationError,
        "invalid_credentials",
        "Wrong user name or password.",
        None,
    ),
    "NT_STATUS_ACCOUNT_LOCKED_OUT": (
        AuthenticationError,
        "account_locked_out",
        "The account is locked out.",
        None,
    ),
    "NT_STATUS_ACCOUNT_DISABLED": (
        AuthenticationError,
        "account_disabled",
        "The account is disabled.",
        None,
    ),
    "NT_STATUS_ACCOUNT_EXPIRED": (
        AuthenticationError,
        "account_expired",
        "The account has expired.",
        None,
    ),
    "NT_STATUS_PASSWORD_EXPIRED": (
        AuthenticationError,
        "password_expired",
        "The password has expired.",
        None,
    ),
    "NT_STATUS_PASSWORD_MUST_CHANGE": (
        AuthenticationError,
        "password_must_change",
        "The password must be changed before this account can be used.",
        None,
    ),
    "NT_STATUS_ACCESS_DENIED": (
        PermissionDenied,
        "insufficient_access",
        "Access denied.",
        "Your account lacks the required permission on the target.",
    ),
    "NT_STATUS_OBJECT_NAME_NOT_FOUND": (
        NotFound,
        "not_found",
        "The file or directory does not exist on SYSVOL.",
        None,
    ),
    "NT_STATUS_OBJECT_PATH_NOT_FOUND": (
        NotFound,
        "not_found",
        "The SYSVOL path does not exist.",
        None,
    ),
    "NT_STATUS_OBJECT_NAME_COLLISION": (
        Conflict,
        "already_exists",
        "The file or directory already exists on SYSVOL.",
        None,
    ),
    "NT_STATUS_SHARING_VIOLATION": (
        Conflict,
        "file_in_use",
        "The file is currently in use on SYSVOL.",
        "Another administrator may be editing the same GPO.",
    ),
    "NT_STATUS_DIRECTORY_NOT_EMPTY": (
        Conflict,
        "not_empty",
        "The directory is not empty.",
        None,
    ),
    # Samba locates a domain controller with a netlogon ping, and that needs
    # the domain's SRV records. A container given only `extra_hosts` resolves
    # the names and has no SRV, so a configured address connects while this
    # fails — which reads like anything but DNS. Verified twice, in two
    # domains, after a wrong diagnosis sent the reader to check clocks.
    "NT_STATUS_NO_LOGON_SERVERS": (
        UpstreamUnavailable,
        "no_logon_servers",
        "No domain controller could be located for this domain.",
        "Samba looks one up through the domain's DNS SRV records. Give the "
        "container a resolver that serves the domain — in docker compose that is "
        "`dns:` with the DC's address. An `extra_hosts` entry resolves the name "
        "but carries no SRV records, which is not enough.",
    ),
    "NT_STATUS_CONNECTION_REFUSED": (
        UpstreamUnavailable,
        "dc_unreachable",
        "The domain controller refused the connection.",
        None,
    ),
    "NT_STATUS_HOST_UNREACHABLE": (
        UpstreamUnavailable,
        "dc_unreachable",
        "The domain controller is unreachable.",
        None,
    ),
    "NT_STATUS_NETWORK_UNREACHABLE": (
        UpstreamUnavailable,
        "dc_unreachable",
        "The domain controller is unreachable.",
        None,
    ),
    "NT_STATUS_IO_TIMEOUT": (
        OperationTimeout,
        "dc_timeout",
        "The domain controller did not answer in time.",
        None,
    ),
    "NT_STATUS_BAD_NETWORK_NAME": (
        NotFound,
        "share_not_found",
        "The SYSVOL share was not found on this domain controller.",
        None,
    ),
    "NT_STATUS_INVALID_PARAMETER": (
        InvalidRequest,
        "invalid_parameter",
        "The server rejected a parameter of the request.",
        None,
    ),
    "NT_STATUS_PASSWORD_RESTRICTION": (
        ConstraintViolation,
        "password_policy_violation",
        "The password does not satisfy the domain password policy.",
        "Check length, complexity, minimum age and password history.",
    ),
    "NT_STATUS_WRONG_PASSWORD": (
        AuthenticationError,
        "invalid_credentials",
        "Wrong password.",
        None,
    ),
    "NT_STATUS_NO_SUCH_USER": (
        AuthenticationError,
        "user_not_found",
        "No such account in this domain.",
        None,
    ),
    "NT_STATUS_TIME_DIFFERENCE_AT_DC": (
        AuthenticationError,
        "clock_skew",
        "The clocks of SAMADCON and the domain controller differ too much.",
        "Kerberos tolerates about five minutes — synchronise the container's clock via NTP.",
    ),
}

# Kerberos failures surface as plain text, not as NT_STATUS.
_KRB_PATTERNS: list[tuple[re.Pattern[str], type[SamadconError], str, str, str | None]] = [
    (
        re.compile(r"clock skew", re.I),
        AuthenticationError,
        "clock_skew",
        "The clocks of SAMADCON and the domain controller differ too much.",
        "Kerberos tolerates about five minutes — synchronise the container's clock via NTP.",
    ),
    (
        re.compile(r"pre-?authentication fail", re.I),
        AuthenticationError,
        "invalid_credentials",
        "Wrong user name or password.",
        None,
    ),
    (
        re.compile(r"(cannot|unable to) (contact|find|reach) any? ?kdc", re.I),
        UpstreamUnavailable,
        "kdc_unreachable",
        "No key distribution centre could be reached.",
        "Check SAMADCON_DC_HOSTS, DNS SRV records and that port 88 is open.",
    ),
    (
        re.compile(r"client .* not found in kerberos database", re.I),
        AuthenticationError,
        "user_not_found",
        "No such account in this realm.",
        "Log in as user@REALM and check the realm spelling.",
    ),
    (
        re.compile(r"(server|principal) .* not found in kerberos database", re.I),
        UpstreamUnavailable,
        "spn_not_found",
        "The requested service principal does not exist in this realm.",
        None,
    ),
    (
        re.compile(r"key(tab)? .*(not found|no such)", re.I),
        AuthenticationError,
        "kerberos_error",
        "Kerberos could not read its credentials.",
        None,
    ),
    (
        re.compile(r"ticket expired|credentials? (have )?expired", re.I),
        SessionExpired,
        "session_expired",
        "The Kerberos ticket has expired.",
        "Sign in again.",
    ),
    (
        re.compile(r"certificate verify failed|unable to get local issuer", re.I),
        UpstreamUnavailable,
        "tls_verification_failed",
        "The domain controller's TLS certificate could not be verified.",
        "Point SAMADCON_LDAP_CA_FILE at the CA that signed it.",
    ),
]

_NT_STATUS_RE = re.compile(r"NT_STATUS_[A-Z0-9_]+")
_AD_DATA_RE = re.compile(r"data\s+([0-9a-fA-F]{2,4})")


def _password_policy_hit(text: str) -> bool:
    lowered = text.lower()
    return "password" in lowered and any(
        marker in lowered
        for marker in ("complexity", "restriction", "history", "too short", "minimum", "policy")
    )


def translate(exc: BaseException) -> SamadconError:
    """Turn any exception from the Samba layer into a :class:`SamadconError`."""
    if isinstance(exc, SamadconError):
        return exc

    text = str(exc)

    ldap_error = _translate_ldap(exc, text)
    if ldap_error is not None:
        return ldap_error

    name = _nt_status_name(exc, text)
    if name is not None:
        entry = _NT_STATUS.get(name)
        if entry is not None:
            cls, code, message, hint = entry
            return cls(message, code=code, hint=hint, detail=text)
        return SamadconError(
            "The server reported an error.", code="nt_status_error", detail=text
        )

    for pattern, cls, code, message, hint in _KRB_PATTERNS:
        if pattern.search(text):
            return cls(message, code=code, hint=hint, detail=text)

    if isinstance(exc, TimeoutError):
        return OperationTimeout(
            "The operation did not finish in time.", code="timeout", detail=text
        )
    if isinstance(exc, (ConnectionError, OSError)):
        return UpstreamUnavailable(
            "The domain controller could not be reached.",
            code="dc_unreachable",
            detail=text,
        )

    return SamadconError("An unexpected error occurred.", detail=text)


def _nt_status_name(exc: BaseException, text: str) -> str | None:
    """The NT_STATUS symbol behind an exception, however it spells itself.

    LDAP failures carry the name in their text. The SMB bindings do not: an
    ``NTSTATUSError`` reads ``(3221225539, 'A file cannot be opened because
    the share access flags are incompatible.')`` — the number and a sentence,
    never the symbol. Without the lookup below, every SMB failure arrives as
    "an unexpected error occurred", which is what it did until a sharing
    violation went unexplained for a round trip.
    """
    match = _NT_STATUS_RE.search(text)
    if match:
        return match.group(0)

    for arg in getattr(exc, "args", ()):
        if isinstance(arg, int):
            found = _numeric_nt_status().get(arg)
            if found is not None:
                return found
    return None


_NUMERIC_NT_STATUS: dict[int, str] | None = None


def _numeric_nt_status() -> dict[int, str]:
    """The numbers behind the symbols we translate, from Samba itself.

    Built from :data:`_NT_STATUS` rather than typed out, so a symbol added
    there is recognised in both forms without anyone remembering to look up
    its number.
    """
    global _NUMERIC_NT_STATUS
    if _NUMERIC_NT_STATUS is not None:
        return _NUMERIC_NT_STATUS

    mapping: dict[int, str] = {}
    try:
        from samba import ntstatus
    except ImportError:  # pragma: no cover - only on hosts without the bindings
        _NUMERIC_NT_STATUS = mapping
        return mapping

    for name in _NT_STATUS:
        value = getattr(ntstatus, name, None)
        try:
            mapping[int(value)] = name  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue

    _NUMERIC_NT_STATUS = mapping
    return mapping


def _translate_ldap(exc: BaseException, text: str) -> SamadconError | None:
    """Handle ldb.LdbError, whose args are ``(code, message)``."""
    if type(exc).__name__ != "LdbError":
        return None

    args = getattr(exc, "args", ())
    code_num: int | None = None
    detail = text
    if args:
        if isinstance(args[0], int):
            code_num = args[0]
        if len(args) > 1 and isinstance(args[1], str):
            detail = args[1]

    if code_num is None:
        return SamadconError("The directory server reported an error.", detail=detail)

    cls, code, message, hint = _LDAP_ERRORS.get(
        code_num,
        (SamadconError, "ldap_error", "The directory server reported an error.", None),
    )

    # Bind failures carry AD's extended reason in the message body; it is far
    # more useful than the bare "invalid credentials".
    if code_num == LDB_ERR_INVALID_CREDENTIALS:
        sub = _AD_DATA_RE.search(detail)
        if sub is not None:
            entry = _AD_BIND_SUBCODES.get(sub.group(1).lower())
            if entry is not None:
                code, message, hint = entry

    # A constraint violation on a password change is by far the most common
    # case and deserves its own message.
    if code_num == LDB_ERR_CONSTRAINT_VIOLATION and _password_policy_hit(detail):
        return ConstraintViolation(
            "The password does not satisfy the domain password policy.",
            code="password_policy_violation",
            hint="Check length, complexity, minimum age and password history.",
            detail=detail,
        )

    return cls(message, code=code, status_code=cls.status_code, hint=hint, detail=detail)

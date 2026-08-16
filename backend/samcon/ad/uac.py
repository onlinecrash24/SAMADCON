"""userAccountControl flags.

The attribute is a bit field carrying most of what ADUC shows on the "Account"
tab. Two options that look like they belong here do not:

* *User must change password at next logon* is ``pwdLastSet = 0``,
* *User cannot change password* is an ACE on the object, not a flag —
  the UAC bit 0x40 exists but Active Directory ignores it.

Both are handled in :mod:`samcon.ad.users`, not here.
"""

from __future__ import annotations

from typing import Final

SCRIPT: Final = 0x00000001
ACCOUNTDISABLE: Final = 0x00000002
HOMEDIR_REQUIRED: Final = 0x00000008
LOCKOUT: Final = 0x00000010
PASSWD_NOTREQD: Final = 0x00000020
PASSWD_CANT_CHANGE: Final = 0x00000040
ENCRYPTED_TEXT_PWD_ALLOWED: Final = 0x00000080
TEMP_DUPLICATE_ACCOUNT: Final = 0x00000100
NORMAL_ACCOUNT: Final = 0x00000200
INTERDOMAIN_TRUST_ACCOUNT: Final = 0x00000800
WORKSTATION_TRUST_ACCOUNT: Final = 0x00001000
SERVER_TRUST_ACCOUNT: Final = 0x00002000
DONT_EXPIRE_PASSWD: Final = 0x00010000
MNS_LOGON_ACCOUNT: Final = 0x00020000
SMARTCARD_REQUIRED: Final = 0x00040000
TRUSTED_FOR_DELEGATION: Final = 0x00080000
NOT_DELEGATED: Final = 0x00100000
USE_DES_KEY_ONLY: Final = 0x00200000
DONT_REQ_PREAUTH: Final = 0x00400000
PASSWORD_EXPIRED: Final = 0x00800000
TRUSTED_TO_AUTH_FOR_DELEGATION: Final = 0x01000000
PARTIAL_SECRETS_ACCOUNT: Final = 0x04000000

# API name -> bit. Only flags an administrator may toggle directly.
EDITABLE_FLAGS: Final[dict[str, int]] = {
    "account_disabled": ACCOUNTDISABLE,
    "password_never_expires": DONT_EXPIRE_PASSWD,
    "password_not_required": PASSWD_NOTREQD,
    "smartcard_required": SMARTCARD_REQUIRED,
    "trusted_for_delegation": TRUSTED_FOR_DELEGATION,
    "not_delegated": NOT_DELEGATED,
    "use_des_key_only": USE_DES_KEY_ONLY,
    "no_preauth_required": DONT_REQ_PREAUTH,
    "encrypted_text_password_allowed": ENCRYPTED_TEXT_PWD_ALLOWED,
    "home_directory_required": HOMEDIR_REQUIRED,
}

# Reported but never written: the DC owns these.
READONLY_FLAGS: Final[dict[str, int]] = {
    "locked_out": LOCKOUT,
    "password_expired": PASSWORD_EXPIRED,
    "normal_account": NORMAL_ACCOUNT,
    "workstation_account": WORKSTATION_TRUST_ACCOUNT,
    "server_account": SERVER_TRUST_ACCOUNT,
    "interdomain_trust_account": INTERDOMAIN_TRUST_ACCOUNT,
    "partial_secrets_account": PARTIAL_SECRETS_ACCOUNT,
    "trusted_to_auth_for_delegation": TRUSTED_TO_AUTH_FOR_DELEGATION,
}

ALL_FLAGS: Final[dict[str, int]] = {**EDITABLE_FLAGS, **READONLY_FLAGS}

# Security-relevant options that deserve a warning in the UI.
DANGEROUS_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "password_not_required",
        "no_preauth_required",  # opens the account to AS-REP roasting
        "trusted_for_delegation",  # unconstrained delegation
        "use_des_key_only",  # DES is broken
        "encrypted_text_password_allowed",  # reversible password storage
    }
)


def decode(uac: int | None) -> dict[str, bool]:
    """Expand the bit field into named booleans."""
    if uac is None:
        return {}
    return {name: bool(uac & bit) for name, bit in ALL_FLAGS.items()}


def apply(uac: int, changes: dict[str, bool | None]) -> int:
    """Return *uac* with the named flags set or cleared.

    Unknown or read-only names raise, so a typo in an API payload cannot
    silently do nothing.
    """
    from samcon.core.errors import InvalidRequest

    result = uac
    for name, enabled in changes.items():
        if enabled is None:
            continue
        bit = EDITABLE_FLAGS.get(name)
        if bit is None:
            if name in READONLY_FLAGS:
                raise InvalidRequest(
                    f"The account option '{name}' is controlled by the domain controller.",
                    code="readonly_account_flag",
                    context={"flag": name},
                )
            raise InvalidRequest(
                f"Unknown account option '{name}'.",
                code="unknown_account_flag",
                context={"flag": name},
            )
        if enabled:
            result |= bit
        else:
            result &= ~bit
    return result


def is_disabled(uac: int | None) -> bool:
    return bool(uac and uac & ACCOUNTDISABLE)


def is_locked(uac: int | None) -> bool:
    """Only a hint.

    AD does not reliably clear the LOCKOUT bit; ``lockoutTime`` combined with
    the domain's lockout duration is authoritative. See
    :func:`samcon.ad.users.is_locked_out`.
    """
    return bool(uac and uac & LOCKOUT)


def account_type(uac: int | None) -> str:
    if uac is None:
        return "unknown"
    if uac & SERVER_TRUST_ACCOUNT:
        return "domain_controller"
    if uac & WORKSTATION_TRUST_ACCOUNT:
        return "computer"
    if uac & INTERDOMAIN_TRUST_ACCOUNT:
        return "trust"
    return "user"

"""Reserved names and protected OUs, checked before anything is written.

Two optional lists an operator sets when deploying:

* SAMADCON_RESERVED_PREFIXES and SAMADCON_RESERVED_NAMES: values SAMADCON will
  not give to sAMAccountName, userPrincipalName, mail or proxyAddresses.
  Asked for by a tester whose internal services run on accounts named
  havora-…; a second account by that name would collide with them.
* SAMADCON_PROTECTED_OUS: OUs whose objects SAMADCON shows but does not
  change, move, rename or delete.

Both are a help inside SAMADCON, not protection. Every change runs with the
signed-in administrator's ticket, and the same administrator reaches these
objects with samba-tool or ADUC. What protects them is the directory's own
rights.

DirectoryConnection calls in here from add, modify, rename and delete, which
every write goes through (tests/unit/test_write_guard.py keeps it that way).
This module is pure, so it is tested without Samba.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from samadcon.ad import values

#: The attributes a reserved name is checked in, by their lower-case names.
CHECKED_ATTRIBUTES = ("samaccountname", "userprincipalname", "mail", "proxyaddresses")

# The flags pyldb gives a MessageElement, mirrored so this imports without it.
FLAG_MOD_DELETE = 3


# --- Protected OUs ----------------------------------------------------------


def _component(rdn: str) -> str:
    kind, _, value = rdn.partition("=")
    value = value.strip(" ")
    # An escaped trailing space belongs to the value.
    if value.endswith("\\"):
        value += " "
    return f"{kind.strip().lower()}={value.lower()}"


def dn_key(dn: str) -> tuple[str, ...]:
    """A DN as comparable components: lower case, no space around separators."""
    components: list[str] = []
    rest: str | None = dn.strip()
    while rest:
        rdn = values.rdn_of(rest)
        components.append(_component(rdn))
        rest = values.parent_dn(rest)
    return tuple(components)


def _within(key: tuple[str, ...], ancestor: tuple[str, ...]) -> bool:
    return len(key) >= len(ancestor) and key[len(key) - len(ancestor) :] == ancestor


def protecting_ou(dn: str, protected: Iterable[str]) -> str | None:
    """The protected OU that is *dn* or holds it, as configured."""
    key = dn_key(dn)
    for ou in protected:
        if _within(key, dn_key(ou)):
            return ou
    return None


def protected_below(dn: str, protected: Iterable[str]) -> str | None:
    """A protected OU somewhere under *dn*, not *dn* itself.

    Renaming, moving or deleting the tree around one would change the
    protected OU's DN, and the list would then name something that no longer
    exists.
    """
    key = dn_key(dn)
    for ou in protected:
        ou_key = dn_key(ou)
        if len(ou_key) > len(key) and _within(ou_key, key):
            return ou
    return None


# --- Reserved names ---------------------------------------------------------


def reserved_hit(
    attribute: str, value: str, prefixes: Iterable[str], names: Iterable[str]
) -> tuple[str, str] | None:
    """``(reason, rule)`` when *value* is reserved, else None.

    The local part before @ is what is compared, so a prefix catches an
    account, its UPN and its addresses alike. proxyAddresses loses its type
    (``SMTP:``, ``smtp:``) and a computer's sAMAccountName its ``$``. A name
    with @ in it stands for one whole address.
    """
    name = attribute.lower()
    if name not in CHECKED_ATTRIBUTES:
        return None
    text = value.strip().lower()
    if name == "proxyaddresses":
        kind, colon, address = text.partition(":")
        if not colon or kind != "smtp":
            return None
        text = address
    local = text.partition("@")[0]
    if name == "samaccountname":
        local = local.removesuffix("$")

    for prefix in prefixes:
        if local.startswith(prefix):
            return "prefix", prefix
    for reserved in names:
        if (text if "@" in reserved else local) == reserved:
            return "name", reserved
    return None


# --- Reading a message ------------------------------------------------------


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _flags(element: Any) -> int:
    flags = getattr(element, "flags", 0)
    return int(flags() if callable(flags) else flags)


def message_dn(message: Any) -> str:
    return str(message.dn)


def checked_values(message: Any) -> Iterator[tuple[str, int, list[str]]]:
    """``(attribute, flags, values)`` for the attributes a reserved name is
    checked in. Other attributes are not decoded at all: unicodePwd is
    UTF-16, and nTSecurityDescriptor is binary."""
    for attribute in message.keys():  # noqa: SIM118 — an ldb.Message, not a dict
        if attribute.lower() not in CHECKED_ATTRIBUTES:
            continue
        element = message[attribute]
        yield attribute, _flags(element), [_text(value) for value in element]

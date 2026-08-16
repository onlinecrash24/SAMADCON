"""The ``gPLink`` format.

Which policies apply to a container is one string attribute on that container::

    [LDAP://cn={GUID},cn=policies,cn=system,DC=example,DC=lan;0]
    [LDAP://cn={OTHER},cn=policies,cn=system,DC=example,DC=lan;2]

Two things about it decide whether an edit works:

* **Order is meaning.** Later entries in the string are applied *earlier*, so
  the first entry in the attribute is the one that wins a conflict. GPMC shows
  this as a link order counting from 1 at the top, which is the reverse of the
  string. Getting that backwards silently inverts every precedence in the
  domain, which is why it is converted in exactly one place — here.
* **There is no escaping.** A DN containing ``]`` or ``;`` cannot be
  represented. AD sidesteps this by only ever linking objects whose DN is a
  GUID in braces, and so do we.

Kept free of Samba imports so the parsing can be tested anywhere.
"""

from __future__ import annotations

import re
from typing import Any

from samcon.core.errors import InvalidRequest

# gPLink option bits (MS-ADTS 6.4.2).
LINK_DISABLED = 0x00000001
LINK_ENFORCED = 0x00000002

# gPOptions on the container.
BLOCK_INHERITANCE = 0x00000001

_LINK_RE = re.compile(r"\[LDAP://(?P<dn>[^;\]]+);(?P<options>\d+)\]")


def parse(gplink: str | None) -> list[dict[str, Any]]:
    """Read a ``gPLink`` value into links, in GPMC's order.

    The returned list is in the order an administrator sees: index 0 is link
    order 1, the one that takes precedence.
    """
    if not gplink:
        return []

    links = []
    for match in _LINK_RE.finditer(gplink):
        options = int(match.group("options"))
        links.append(
            {
                "dn": match.group("dn").strip(),
                "options": options,
                "enabled": not (options & LINK_DISABLED),
                "enforced": bool(options & LINK_ENFORCED),
            }
        )

    # The attribute is written in reverse precedence: the last entry applies
    # first and is therefore overridden by everything before it.
    links.reverse()
    for position, link in enumerate(links, start=1):
        link["order"] = position
    return links


def format(links: list[dict[str, Any]]) -> str:
    """Write links back, taking the same order :func:`parse` returns."""
    parts = []
    for link in reversed(links):
        options = link.get("options")
        if options is None:
            options = (0 if link.get("enabled", True) else LINK_DISABLED) | (
                LINK_ENFORCED if link.get("enforced") else 0
            )
        dn = str(link["dn"]).strip()
        _check_dn(dn)
        parts.append(f"[LDAP://{dn};{options}]")
    return "".join(parts)


def _check_dn(dn: str) -> None:
    """The format has no escaping, so a DN with its delimiters cannot go in.

    In practice this never fires — links point at ``CN={GUID},CN=Policies,…``
    — but writing such a DN would corrupt every other link in the attribute,
    so it is refused rather than trusted.
    """
    if not dn:
        raise InvalidRequest("A link without a target.", code="invalid_link")
    for char in ("]", "[", ";"):
        if char in dn:
            raise InvalidRequest(
                "This policy's name cannot be written into a link.",
                code="invalid_link_dn",
                context={"dn": dn, "character": char},
            )


def options_for(*, enabled: bool = True, enforced: bool = False) -> int:
    return (0 if enabled else LINK_DISABLED) | (LINK_ENFORCED if enforced else 0)


def find(links: list[dict[str, Any]], gpo_dn: str) -> int | None:
    """Position of a link in the list, or None. DNs compare case-insensitively."""
    wanted = gpo_dn.strip().lower()
    for index, link in enumerate(links):
        if link["dn"].strip().lower() == wanted:
            return index
    return None


def move(links: list[dict[str, Any]], index: int, target: int) -> list[dict[str, Any]]:
    """Move one link to another position, renumbering the rest."""
    if not 0 <= index < len(links):
        raise InvalidRequest("This link does not exist.", code="link_not_found")
    target = max(0, min(target, len(links) - 1))

    reordered = list(links)
    reordered.insert(target, reordered.pop(index))
    for position, link in enumerate(reordered, start=1):
        link["order"] = position
    return reordered

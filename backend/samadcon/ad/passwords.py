"""Passwords the console makes up, for accounts it creates.

Generated on the server, from ``secrets``, and fitted to the domain's policy:
at least the domain's minimum length and never shorter than 16, and with
complexity on, a character from each of the four classes. Characters that
are easily confused when read out or typed from a printout — 0 and O, 1, l
and I — are left out, and so is anything a shell, a CSV file or a mail client
treats specially.

Complexity in AD also forbids the account's own name in the password:
any token of three or more characters from the logon name or the display name,
compared without regard to case. A random password hits one rarely, but
rarely is not never, and the failure would look like a policy the console did
not understand — so such a password is drawn again.

A fine-grained password policy is not read. One stricter than the domain's
makes the password write fail, and the creation is rolled back with the
directory's message.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable
from typing import Any

UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
LOWER = "abcdefghijkmnopqrstuvwxyz"
DIGITS = "23456789"
SYMBOLS = "!#$%&*+-=?@_"
CLASSES = (UPPER, LOWER, DIGITS, SYMBOLS)

MIN_LENGTH = 16
#: minPwdLength cannot exceed this in AD, and neither does anything made here.
MAX_LENGTH = 128
#: The DOMAIN_PASSWORD_COMPLEX bit of pwdProperties (MS-ADTS 2.2.16).
COMPLEX = 0x1

# AD splits the display name at these characters when it checks complexity.
_DELIMITERS = re.compile(r"[,.\-_#\s\t]+")


def forbidden_tokens(names: Iterable[str | None]) -> list[str]:
    """The pieces of *names* that complexity forbids in a password: the whole
    logon name, and every token of three or more characters."""
    tokens: list[str] = []
    for name in names:
        if not name:
            continue
        tokens.append(name.lower())
        tokens.extend(part.lower() for part in _DELIMITERS.split(name) if len(part) >= 3)
    return [token for token in tokens if len(token) >= 3]


def _draw(length: int, complex_: bool) -> str:
    alphabet = "".join(CLASSES)
    chars = [secrets.choice(alphabet) for _ in range(length)]
    if complex_:
        # One of each class, at positions drawn at random, so that where the
        # guaranteed characters sit gives nothing away.
        positions = list(range(length))
        for kind in CLASSES:
            chars[positions.pop(secrets.randbelow(len(positions)))] = secrets.choice(kind)
    return "".join(chars)


def generate(length: int, *, complex_: bool = True, avoid: Iterable[str | None] = ()) -> str:
    """A random password of *length* characters, at least MIN_LENGTH."""
    length = max(MIN_LENGTH, min(length, MAX_LENGTH))
    forbidden = forbidden_tokens(avoid)
    while True:
        password = _draw(length, complex_)
        lowered = password.lower()
        if not any(token in lowered for token in forbidden):
            return password


def for_domain(conn: Any, *, avoid: Iterable[str | None] = ()) -> str:
    """A password the domain's own policy accepts, for an account named in *avoid*."""
    from samadcon.ad import values

    minimum, properties = 0, COMPLEX
    head = conn.get(conn.info.base_dn, attrs=["minPwdLength", "pwdProperties"])
    if head is not None:
        minimum = values.as_int(head, "minPwdLength", 0) or 0
        properties = values.as_int(head, "pwdProperties", COMPLEX) or 0
    return generate(minimum, complex_=bool(properties & COMPLEX), avoid=avoid)

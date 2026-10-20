"""SAMADCON's own settings, kept in the domain it manages.

One object, ``CN=SAMADCON,CN=Program Data,<domain>``, of the class AD has for
exactly this — ``msDS-App-Configuration`` — holding one JSON document in
``msDS-Settings``. No schema extension, nothing in the container to back up,
and every SAMADCON instance on the domain reads the same rules. Measured on
zmb-ad (Samba 4.22.11): the class exists and may sit under a container, and
``msDS-Settings`` takes up to 1 000 000 characters.

The document is versioned and read leniently: keys this version does not
know are kept on every save, so an older and a newer SAMADCON on the same
domain do not erase each other's settings. A document that is not JSON is
reported, never silently replaced — it may hold settings someone needs.

``CN=Program Data`` lets Authenticated Users read the container itself, but
that entry is not inherited. The object gets a read entry of its own when it
is created; without it a delegated admin who may create users could not read
which fields are mandatory, and the rule would not hold for them.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from samadcon.ad import sacl, values
from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest

logger = logging.getLogger(__name__)

OBJECT_CLASS = "msDS-App-Configuration"
ATTRIBUTE = "msDS-Settings"
# Authenticated Users: list, read, list object, read permissions.
READ_ACE = "(A;;LCRPLORC;;;AU)"

# What a new user's CN — the Name column — starts as: first and last name,
# as ADUC builds it, or the logon name. One tester asked for each.
CN_SOURCES = ("name", "logon")

DEFAULTS: dict[str, Any] = {"version": 1, "users": {"required_fields": [], "cn_source": "name"}}


def _requirable() -> tuple[str, ...]:
    from samadcon.ad.users import USER_FIELDS

    # upn is always set — derived from the logon name when left empty — and
    # manager is a reference to another object, not something typed.
    return tuple(field for field in USER_FIELDS if field not in {"upn", "manager"})


REQUIRABLE_USER_FIELDS = _requirable()


def settings_dn(conn: DirectoryConnection) -> str:
    return f"CN=SAMADCON,CN=Program Data,{conn.info.base_dn}"


def parse(text: str | None) -> dict[str, Any]:
    """The document with the defaults filled in."""
    document = copy.deepcopy(DEFAULTS)
    if not text:
        return document
    try:
        stored = json.loads(text)
    except ValueError as exc:
        raise Conflict(
            "SAMADCON's settings in the directory cannot be read.",
            code="settings_corrupt",
            hint="Check msDS-Settings on CN=SAMADCON,CN=Program Data; it has to be JSON.",
        ) from exc
    if not isinstance(stored, dict):
        raise Conflict(
            "SAMADCON's settings in the directory cannot be read.", code="settings_corrupt"
        )
    document.update({key: value for key, value in stored.items() if key != "users"})
    users = stored.get("users")
    if isinstance(users, dict):
        document["users"] = {**document["users"], **users}
    return document


def clean_required(fields: list[str]) -> list[str]:
    """The fields, checked against what may be required, without repeats."""
    cleaned: list[str] = []
    for field in fields:
        if field not in REQUIRABLE_USER_FIELDS:
            raise InvalidRequest(
                "This field cannot be made mandatory.",
                code="field_not_requirable",
                context={"field": field},
            )
        if field not in cleaned:
            cleaned.append(field)
    return cleaned


def render(current: str | None, *, required_fields: list[str], cn_source: str | None = None) -> str:
    """The document to store: what was there, with the new values set.
    A setting left out (None) keeps what was there."""
    document = parse(current)
    document["version"] = DEFAULTS["version"]
    users = {**document["users"], "required_fields": clean_required(required_fields)}
    if cn_source is not None:
        if cn_source not in CN_SOURCES:
            raise InvalidRequest(
                "This value is not one the setting takes.",
                code="invalid_setting",
                context={"setting": "users.cn_source", "given": cn_source},
            )
        users["cn_source"] = cn_source
    document["users"] = users
    return json.dumps(document, ensure_ascii=False)


def _stored_text(conn: DirectoryConnection) -> tuple[str | None, Any]:
    entry = conn.get(settings_dn(conn), attrs=[ATTRIBUTE, "allowedAttributesEffective"])
    if entry is None:
        return None, None
    return values.as_str(entry, ATTRIBUTE), entry


def read_document(conn: DirectoryConnection) -> dict[str, Any]:
    text, _ = _stored_text(conn)
    return parse(text)


def _writable(conn: DirectoryConnection, entry: Any) -> bool:
    if entry is not None:
        allowed = {name.lower() for name in values.as_list(entry, "allowedAttributesEffective")}
        return ATTRIBUTE.lower() in allowed
    container = conn.get(
        f"CN=Program Data,{conn.info.base_dn}", attrs=["allowedChildClassesEffective"]
    )
    classes = {name.lower() for name in values.as_list(container, "allowedChildClassesEffective")}
    return OBJECT_CLASS.lower() in classes


def read(conn: DirectoryConnection) -> dict[str, Any]:
    """The settings, where they live, whether this account may change them,
    and the text they were read from — passed back on save."""
    text, entry = _stored_text(conn)
    return {
        "dn": settings_dn(conn),
        "exists": entry is not None,
        "writable": _writable(conn, entry),
        "stamp": text or "",
        "settings": parse(text),
        "requirable_user_fields": list(REQUIRABLE_USER_FIELDS),
    }


def write(
    conn: DirectoryConnection,
    *,
    required_fields: list[str],
    expected: str,
    cn_source: str | None = None,
) -> dict[str, Any]:
    """Save, refusing if someone else saved since *expected* was read."""
    current, entry = _stored_text(conn)
    if (current or "") != expected:
        raise Conflict(
            "The settings were changed by someone else in the meantime.",
            code="settings_changed",
            hint="Reload the settings and make the change again.",
        )
    text = render(current, required_fields=required_fields, cn_source=cn_source)

    import ldb

    dn = settings_dn(conn)
    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    if entry is None:
        message["objectClass"] = ldb.MessageElement(OBJECT_CLASS, ldb.FLAG_MOD_ADD, "objectClass")
        message[ATTRIBUTE] = ldb.MessageElement(text, ldb.FLAG_MOD_ADD, ATTRIBUTE)
        conn.add(message)
        try:
            sacl.add_ace(conn, dn, ace=READ_ACE)
        except Conflict as exc:
            if exc.code != "ace_exists":
                raise
        logger.info("created %s", dn)
    else:
        message[ATTRIBUTE] = ldb.MessageElement(text, ldb.FLAG_MOD_REPLACE, ATTRIBUTE)
        conn.modify(message)
    return read(conn)

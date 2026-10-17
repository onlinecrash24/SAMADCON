"""Reading and writing preferences on one GPO.

The mechanics are the ones from 4a — optimistic locking on ``versionNumber``,
extension registration, version increment — with one addition the earlier
features did not need: **a write starts from the file that is already there.**

That is not politeness. A preference item can carry item-level targeting and
attributes no editor here models, and the browser never sees either. Sending a
list of items back would otherwise delete a filter the moment someone renamed
the drive it sits on — silently, and in the direction that grants access to
everyone rather than no one. So the current file is read, items are matched by
their ``uid``, and everything not modelled travels from the old item to the
new one untouched.

The same rule blocks the reverse direction: only the attributes named in the
catalogue can be *set* from outside. A stored drive password (``cpassword``,
encrypted with a key Microsoft published in 2014) is carried through when it
is already there and can never be introduced from here.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest
from samadcon.gpo import container, cse, sysvol
from samadcon.gpo.preferences import catalogue, targeting, xmlfile
from samadcon.gpo.preferences.catalogue import ItemKind, PreferenceType

logger = logging.getLogger(__name__)

HALVES = ("Machine", "User")


def read(conn: DirectoryConnection, dn: str, type_id: str, half: str) -> dict[str, Any]:
    """One preference type of one half."""
    preference = _preference(type_id, half)
    gpo = container.get_gpo(conn, dn)
    raw = _read_file(conn, gpo, preference, half)
    return {
        "dn": dn,
        "type": preference.id,
        "half": half,
        "present": raw is not None,
        "version_number": gpo["version"],
        "items": _parse(preference, raw),
    }


def read_all(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """Every preference type of both halves, for the editor to draw at once."""
    gpo = container.get_gpo(conn, dn)

    types: dict[str, dict[str, Any]] = {}
    for preference in catalogue.TYPES.values():
        halves: dict[str, Any] = {}
        for half in preference.halves:
            raw = _read_file(conn, gpo, preference, half)
            halves[half] = {"present": raw is not None, "items": _parse(preference, raw)}
        types[preference.id] = {"halves": halves}

    return {"dn": dn, "version_number": gpo["version"], "types": types}


def write(
    conn: DirectoryConnection,
    dn: str,
    type_id: str,
    half: str,
    items: list[dict[str, Any]],
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Replace one preference type of one half with *items*."""
    preference = _preference(type_id, half)
    gpo = container.get_gpo(conn, dn)

    if expected_version is not None and gpo["version"] != expected_version:
        raise Conflict(
            "This policy was changed by someone else in the meantime.",
            code="gpo_version_conflict",
            hint="Reload the items and make the change again.",
            context={"expected": expected_version, "current": gpo["version"]},
        )
    if not gpo["path"]:
        raise InvalidRequest(
            "This policy has no SYSVOL path.", code="gpo_without_path", context={"dn": dn}
        )

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    relative = preference.path(half)
    resolved = share.resolve(base, relative)
    current = share.read(resolved) if resolved else None

    if current is not None:
        _refuse_unknown_elements(preference, current)

    existing = {item["uid"]: item for item in _parse(preference, current) if item["uid"]}
    prepared = [
        _prepare(preference, half, _with_directory_names(conn, item), existing) for item in items
    ]

    if not prepared:
        return _clear(conn, dn, preference, half, share, resolved, gpo)

    rendered = xmlfile.render(preference, prepared)
    if current == rendered:
        return {"dn": dn, "changed": False, "version": gpo["version"], "written": len(prepared)}

    target = resolved or sysvol.join(base, relative)
    share.makedirs(target.rsplit("\\", 1)[0])
    share.write(target, rendered)

    cse.register_pairs(conn, dn, half, preference.pairs, present=True)
    after = container.bump_version(
        conn, dn, machine_changed=half == "Machine", user_changed=half == "User"
    )
    logger.info(
        "wrote %d %s preferences (%s) to %s",
        len(prepared),
        preference.id,
        half,
        gpo["display_name"],
    )
    return {"dn": dn, "changed": True, "version": after["version"], "written": len(prepared)}


def _clear(
    conn: DirectoryConnection,
    dn: str,
    preference: PreferenceType,
    half: str,
    share: Any,
    resolved: str | None,
    gpo: dict[str, Any],
) -> dict[str, Any]:
    """The last item is gone: take the file and the registration with it.

    An empty file left behind with its extension still registered makes every
    client in scope fetch the policy on every refresh and find nothing in it.
    """
    if resolved is None:
        return {"dn": dn, "changed": False, "version": gpo["version"], "written": 0}

    share.unlink(resolved)
    cse.register_pairs(conn, dn, half, preference.pairs, present=False)
    after = container.bump_version(
        conn, dn, machine_changed=half == "Machine", user_changed=half == "User"
    )
    logger.info("removed %s preferences (%s) from %s", preference.id, half, gpo["display_name"])
    return {"dn": dn, "changed": True, "version": after["version"], "written": 0}


def _prepare(
    preference: PreferenceType,
    half: str,
    item: dict[str, Any],
    existing: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """One incoming item, merged onto the one already in the file."""
    uid = str(item.get("uid") or "")
    previous = existing.get(uid, {})
    kind = _kind(preference, half, item.get("kind") or previous.get("kind"))

    if not previous and not kind.creatable:
        raise InvalidRequest(
            "This kind of item cannot be created here.",
            code="preference_not_creatable",
            hint=(
                "Scheduled tasks carry a task definition this version reads and "
                "keeps but does not write from scratch. Create it in GPMC; it "
                "stays editable here afterwards."
            ),
            context={"type": preference.id, "kind": kind.id},
        )

    action = ""
    if kind.has_action:
        action = str(item.get("action") or "").upper()
        if action not in catalogue.ACTIONS:
            raise InvalidRequest(
                "Unknown preference action.",
                code="unknown_preference_action",
                hint=f"Expected one of: {', '.join(catalogue.ACTIONS)}.",
                context={"given": item.get("action"), "allowed": list(catalogue.ACTIONS)},
            )

    incoming = {str(name): value for name, value in (item.get("properties") or {}).items()}
    # Start from what the file had, so nothing unmodelled is lost, then let
    # only the catalogue's own fields through from outside. A `secret` field is
    # never among them: it is written at its default for a new item and carried
    # verbatim for an existing one, and nothing from outside can set it.
    properties: dict[str, str] = dict(previous.get("properties") or {})
    for field in kind.fields:
        if field.kind == "action":
            continue
        if field.kind == "secret":
            properties.setdefault(field.name, field.default)
        elif field.name in incoming:
            given = incoming[field.name]
            properties[field.name] = "" if given is None else str(given)
        elif field.name not in properties:
            properties[field.name] = field.default
    properties = catalogue.normalise(kind.id, properties)
    children, properties = _children(kind, item, previous, properties)

    filters, extra, action = _options_and_targeting(kind, half, item, previous, action)

    name = catalogue.display_name(kind.id, properties)
    built = {
        "kind": kind.id,
        "uid": uid or _new_uid(),
        "name": name,
        "status": catalogue.status_text(kind.id, properties, name),
        "image": _image(kind, properties, action, previous),
        "action": action,
        "properties": properties,
        "properties_children": children,
        # Never raw from the client: built from checked conditions, or carried
        # from the file. A block that is not understood is only ever carried.
        "filters": filters,
        "filters_first": previous.get("filters_first", kind.filters_first),
        "extra": extra,
        "order": previous.get("order") or [],
        "properties_order": previous.get("properties_order") or [],
    }
    # The stamp moves only when something else did. Setting it unconditionally
    # would make every save rewrite the file, raise the version and send every
    # client in scope back to re-apply a policy that did not change.
    built["changed"] = (
        previous["changed"]
        if previous and all(previous.get(key) == value for key, value in built.items())
        else _now()
    )
    return built


def _with_directory_names(conn: DirectoryConnection, item: dict[str, Any]) -> dict[str, Any]:
    """Conditions picked in the console get their name and SID from the DC."""
    sent = item.get("targeting")
    if not isinstance(sent, dict) or not isinstance(sent.get("conditions"), list):
        return item
    conditions = targeting.resolve(conn, sent["conditions"])
    return {**item, "targeting": {**sent, "conditions": conditions}}


_NO_OPTIONS = {
    "stop_on_error": False,
    "user_context": False,
    "remove_policy": False,
    "run_once": False,
}


def _options_and_targeting(
    kind: ItemKind,
    half: str,
    item: dict[str, Any],
    previous: dict[str, Any],
    action: str,
) -> tuple[str | None, dict[str, str], str]:
    """The ``<Filters>`` block, the item attributes and the action.

    Untouched unless the editor sent ``options`` or ``targeting``: then the
    file's own spelling of everything else is kept. The options are written
    as the reference GPO shows them:

    - removal is ``removePolicy="1"`` and makes the action Replace;
    - the user's security context is ``userContext="1"``, a user-half option;
    - stopping on error is ``bypassErrors="0"`` (not stopping, "1");
    - apply once is a filter, ``FilterRunOnce``, and excludes removal.

    An option turned off is written "0" where the file had the attribute — a
    group states userContext="0" outright — and left out where it had none.
    """
    filters = previous.get("filters")
    extra = dict(previous.get("extra") or {})
    sent_options = item.get("options")
    sent_targeting = item.get("targeting")
    if sent_options is None and sent_targeting is None:
        return filters, extra, action

    current = targeting.parse(filters)
    read_options = previous.get("options") or {
        **_NO_OPTIONS,
        "run_once": current["run_once"] is not None,
    }
    wanted = {**_NO_OPTIONS, **read_options, **(sent_options or {})}
    wanted = {name: bool(wanted[name]) for name in _NO_OPTIONS}

    if wanted["remove_policy"] and wanted["run_once"]:
        raise InvalidRequest(
            "An item is either removed when it no longer applies or applied once.",
            code="preference_options_conflict",
            hint="GPMC offers only one of the two at a time.",
        )
    if wanted["user_context"] and half == "Machine":
        raise InvalidRequest(
            "Only a user-half item can run in the logged-on user's context.",
            code="preference_user_context_machine",
        )

    run_once_changed = wanted["run_once"] != (current["run_once"] is not None)
    if not current["editable"]:
        if sent_targeting is not None or run_once_changed:
            raise InvalidRequest(
                "This item's targeting can only be changed in GPMC.",
                code="preference_targeting_not_editable",
                hint="It holds a collection or a filter type this version does not edit.",
            )
    else:
        conditions = (
            targeting.validate((sent_targeting or {}).get("conditions") or [])
            if sent_targeting is not None
            else current["conditions"]
        )
        run_once = (
            (current["run_once"] or targeting.new_run_once_id()) if wanted["run_once"] else None
        )
        filters = targeting.render(conditions, run_once)

    if sent_options is not None:
        _set_option(extra, "removePolicy", wanted["remove_policy"])
        _set_option(extra, "userContext", wanted["user_context"])
        if wanted["stop_on_error"]:
            extra["bypassErrors"] = "0"
        elif "bypassErrors" in extra or not previous:
            # GPMC writes it on every item it creates; an old file without it
            # keeps going without it.
            extra["bypassErrors"] = "1"
        if wanted["remove_policy"] and kind.has_action:
            action = "R"
    return filters, extra, action


def _set_option(extra: dict[str, str], name: str, on: bool) -> None:
    if on:
        extra[name] = "1"
    elif name in extra:
        extra[name] = "0"


def _children(
    kind: ItemKind,
    item: dict[str, Any],
    previous: dict[str, Any],
    properties: dict[str, str],
) -> tuple[str, dict[str, str]]:
    """What goes inside ``<Properties>``, and the `value` that goes beside it.

    A REG_MULTI_SZ keeps its lines in a ``<Values>`` block and a space-joined
    summary in the attribute. Every other kind has an empty element, and
    switching a value away from REG_MULTI_SZ therefore has to take the block
    with it — a leftover ``<Values>`` under a REG_SZ is not something any
    reference file shows, so it is not something to leave behind.
    """
    if kind.id == "group":
        given = item.get("members")
        members = list(given if given is not None else previous.get("members") or [])
        return xmlfile.members_block([_member(entry) for entry in members]), properties

    if kind.id != "registry":
        return str(previous.get("properties_children") or ""), properties

    if properties.get("type") != catalogue.MULTI_SZ:
        return "", properties

    given = item.get("values")
    values = [str(line) for line in (given if given is not None else previous.get("values") or [])]
    return xmlfile.values_block(values), {**properties, "value": " ".join(values)}


def _member(entry: dict[str, Any]) -> dict[str, str]:
    """One member of a local group, checked rather than passed through.

    The action decides whether someone is added to a group or taken out of it,
    so an unrecognised value must not fall through to a default — either
    direction would be wrong, and one of them grants access.
    """
    action = str(entry.get("action") or "").upper()
    if action not in xmlfile.MEMBER_ACTIONS:
        raise InvalidRequest(
            "A group member is either added or removed.",
            code="unknown_member_action",
            hint=f"Expected one of: {', '.join(xmlfile.MEMBER_ACTIONS)}.",
            context={"given": entry.get("action"), "allowed": list(xmlfile.MEMBER_ACTIONS)},
        )
    return {
        "name": str(entry.get("name") or ""),
        "action": action,
        "sid": str(entry.get("sid") or ""),
    }


def _image(
    kind: ItemKind, properties: dict[str, str], action: str, previous: dict[str, Any]
) -> int:
    """The icon index, keeping the file's own where we cannot work it out.

    Only five registry value types have been read off a reference file, so an
    item of some other type would otherwise lose its icon on every save. The
    icon has no part in applying the setting — this is about not degrading a
    file GPMC wrote.
    """
    computed = catalogue.image_for(kind, properties, action)
    if computed == 0 and previous.get("image"):
        return int(previous["image"])
    return computed


def _preference(type_id: str, half: str) -> PreferenceType:
    preference = catalogue.type_for(type_id)
    if half not in HALVES:
        raise InvalidRequest(
            "A policy has a computer half and a user half.",
            code="unknown_gpo_half",
            context={"given": half},
        )
    if half not in preference.halves:
        raise InvalidRequest(
            "This preference type does not exist in that half.",
            code="preference_wrong_half",
            hint=f"{preference.id} exists in: {', '.join(preference.halves)}.",
            context={"type": preference.id, "half": half, "allowed": list(preference.halves)},
        )
    return preference


def _kind(preference: PreferenceType, half: str, kind_id: str | None) -> ItemKind:
    """The element kind, checked against the half it would be written into.

    Printers are why this is not the same question as the type's: a shared
    printer exists only in the user half, a port printer only in the computer
    half, and they live in the same file.
    """
    allowed = preference.kinds_in(half)
    kind = preference.kind(kind_id if kind_id or len(allowed) != 1 else allowed[0].id)
    if half not in kind.halves:
        raise InvalidRequest(
            "This kind of item does not exist in that half.",
            code="preference_wrong_half",
            hint=f"{kind.id} exists in: {', '.join(kind.halves)}.",
            context={
                "type": preference.id,
                "kind": kind.id,
                "half": half,
                "allowed": list(kind.halves),
            },
        )
    return kind


def _parse(preference: PreferenceType, raw: bytes | None) -> list[dict[str, Any]]:
    return xmlfile.parse(preference, raw.decode("utf-8", "replace")) if raw else []


def _refuse_unknown_elements(preference: PreferenceType, raw: bytes) -> None:
    """A file holding an element this build does not know is not rewritten.

    Reading skips it; writing would drop it. Refusing keeps a policy that some
    newer console produced intact instead of quietly cutting it down.
    """
    unknown = xmlfile.unknown_tags(preference, raw.decode("utf-8", "replace"))
    if unknown:
        raise InvalidRequest(
            "This file holds settings this version cannot edit.",
            code="preference_unknown_element",
            hint="Edit it in GPMC, or ask for these kinds to be added.",
            context={"type": preference.id, "elements": unknown},
        )


def _read_file(
    conn: DirectoryConnection, gpo: dict[str, Any], preference: PreferenceType, half: str
) -> bytes | None:
    if not gpo["path"]:
        return None
    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    resolved = share.resolve(base, preference.path(half))
    return None if resolved is None else share.read(resolved)


def _new_uid() -> str:
    """A fresh item id, in the spelling the reference files use: braced, upper
    case."""
    return "{" + str(uuid.uuid4()).upper() + "}"


def _now() -> str:
    """The ``changed`` stamp.

    GPMC writes the editing machine's local time. UTC is written here because
    a console that can be reached from anywhere has no meaningful local time,
    and because the attribute is shown in a column and read by nothing.
    """
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

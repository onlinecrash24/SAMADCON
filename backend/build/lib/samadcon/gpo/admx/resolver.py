"""Between a policy's state and the registry values that express it.

Three states — not configured, enabled, disabled — and a handful of element
values on one side; a list of registry entries on the other. Both directions
are needed: writing an edit, and reading back what a GPO currently says so the
form can be filled in.

The rules come from the ADMX schema, and the defaults are the part worth
stating because they are invisible in the files:

* A policy with a ``valueName`` and no ``enabledValue`` writes ``REG_DWORD 1``
  when enabled, and ``REG_DWORD 0`` when disabled. Most templates rely on
  that and specify neither.
* ``enabledList`` and ``disabledList`` are *extra* values written alongside.
* **Elements only apply while the policy is enabled.** Disabled or not
  configured, their values are removed. A form that keeps them is showing
  something that is not in the GPO.
* A ``<delete/>`` value means the entry is removed rather than set — which is
  how most "off" states are actually expressed.

Removal is by comparison rather than by a wildcard: what a policy currently
owns is read, the desired set is computed, and the difference is removed. That
covers lists, whose value names are generated, without needing the
``**delvals.`` instruction and without ever touching a value some other policy
wrote into the same key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import registry_pol
from samadcon.gpo.admx.model import Element, Policy, Value, ValueItem

State = Literal["not_configured", "enabled", "disabled"]

STATES: tuple[State, ...] = ("not_configured", "enabled", "disabled")

# What a policy writes when the template says nothing else.
DEFAULT_ENABLED = Value("decimal", 1)
DEFAULT_DISABLED = Value("decimal", 0)


# How a policy says "remove this value from the client's registry". It is a
# real entry in the file rather than the absence of one: value name prefixed,
# REG_SZ, a single space as data. Verified against a GPO written by GPMC.
DELETE_PREFIX = "**del."
DELETE_DATA = " "


def deletion_of(value_name: str) -> str:
    return f"{DELETE_PREFIX}{value_name}"


def deleted_name(value_name: str) -> str | None:
    """The value a ``**del.`` entry refers to, or None if it is not one."""
    if value_name.lower().startswith(DELETE_PREFIX):
        return value_name[len(DELETE_PREFIX) :]
    return None


@dataclass(frozen=True)
class Entry:
    """One registry value a policy owns."""

    key: str
    value_name: str
    type: int = registry_pol.REG_DWORD
    data: Any = None

    @property
    def ident(self) -> tuple[str, str]:
        """Registry names are case-insensitive; comparisons here are too."""
        return (self.key.lower(), self.value_name.lower())


@dataclass
class Plan:
    """What to write and what to take away."""

    set: list[Entry] = field(default_factory=list)
    remove: list[Entry] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.set and not self.remove


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _entry_for(key: str, value_name: str, value: Value) -> Entry:
    if value.is_delete:
        # Not the absence of an entry — a marker that tells the client to
        # remove the value it may already have. Leaving it out would let a
        # setting made earlier survive being switched off.
        return Entry(
            key=key,
            value_name=deletion_of(value_name),
            type=registry_pol.REG_SZ,
            data=DELETE_DATA,
        )
    if value.kind == "decimal":
        return Entry(
            key=key, value_name=value_name, type=registry_pol.REG_DWORD, data=int(value.data or 0)
        )
    return Entry(
        key=key, value_name=value_name, type=registry_pol.REG_SZ, data=str(value.data or "")
    )


def _list_entries(policy: Policy, items: tuple[ValueItem, ...]) -> list[Entry]:
    """An ``enabledList``/``disabledList`` and its friends."""
    entries = []
    for item in items:
        if not item.value_name:
            continue
        entries.append(_entry_for(item.key or policy.key, item.value_name, item.value))
    return entries


# ---------------------------------------------------------------------------
# State -> entries
# ---------------------------------------------------------------------------


def entries_for(policy: Policy, state: State, values: dict[str, Any] | None = None) -> list[Entry]:
    """The registry entries that express *state* for *policy*.

    Not configured yields nothing: a policy that is not configured owns no
    values, and what has to disappear is worked out by :func:`plan` from what
    is actually there.
    """
    if state not in STATES:
        raise InvalidRequest(
            f"Unknown policy state '{state}'.",
            code="unknown_policy_state",
            context={"supported": list(STATES)},
        )
    if state == "not_configured":
        return []

    entries: list[Entry] = []

    if policy.value_name:
        value = (
            (policy.enabled_value or DEFAULT_ENABLED)
            if state == "enabled"
            else (policy.disabled_value or DEFAULT_DISABLED)
        )
        entries.append(_entry_for(policy.key, policy.value_name, value))

    entries.extend(
        _list_entries(policy, policy.enabled_list if state == "enabled" else policy.disabled_list)
    )

    if state == "enabled":
        for element in policy.elements:
            entries.extend(_element_entries(policy, element, (values or {}).get(element.id)))

    return entries


def _element_entries(policy: Policy, element: Element, value: Any) -> list[Entry]:
    key = element.key or policy.key

    if element.kind == "boolean":
        return _boolean_entries(policy, element, key, value)
    if element.kind == "list":
        return _list_element_entries(element, key, value)

    if value is None or value == "":
        if element.required:
            raise InvalidRequest(
                "This setting needs a value.",
                code="missing_element_value",
                context={"element": element.id},
            )
        # Absent and not required: the value is simply not written, which is
        # what leaving a box empty in GPMC does.
        return []

    if not element.value_name:
        return []

    if element.kind == "decimal":
        number = _number(element, value)
        return [
            Entry(
                key=key,
                value_name=element.value_name,
                type=registry_pol.REG_SZ if element.store_as_text else registry_pol.REG_DWORD,
                data=str(number) if element.store_as_text else number,
            )
        ]
    if element.kind == "longDecimal":
        return [
            Entry(
                key=key,
                value_name=element.value_name,
                type=registry_pol.REG_QWORD,
                data=_number(element, value),
            )
        ]
    if element.kind == "text":
        return [
            Entry(
                key=key,
                value_name=element.value_name,
                type=registry_pol.REG_EXPAND_SZ if element.expandable else registry_pol.REG_SZ,
                data=_text(element, value),
            )
        ]
    if element.kind == "multiText":
        strings = [str(item) for item in value] if isinstance(value, list) else [str(value)]
        return [
            Entry(
                key=key,
                value_name=element.value_name,
                type=registry_pol.REG_MULTI_SZ,
                data=strings,
            )
        ]
    if element.kind == "enum":
        return _enum_entries(policy, element, key, value)

    return []


def _boolean_entries(policy: Policy, element: Element, key: str, value: Any) -> list[Entry]:
    """A checkbox writes one value, and may write a list alongside it."""
    checked = bool(value)
    chosen = (element.true_value or DEFAULT_ENABLED) if checked else (
        element.false_value or DEFAULT_DISABLED
    )

    entries = []
    if element.value_name:
        entries.append(_entry_for(key, element.value_name, chosen))
    entries.extend(_list_entries(policy, element.true_list if checked else element.false_list))
    return entries


def _enum_entries(policy: Policy, element: Element, key: str, value: Any) -> list[Entry]:
    """A dropdown, addressed by the index of the chosen item.

    By index rather than by the stored value: two items may write the same
    value through different value lists, and the index is what the form has.
    """
    try:
        index = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequest(
            "This setting needs one of its listed choices.",
            code="invalid_element_value",
            context={"element": element.id},
        ) from exc

    if not 0 <= index < len(element.items):
        raise InvalidRequest(
            "This choice does not exist.",
            code="invalid_element_value",
            context={"element": element.id, "choices": len(element.items)},
        )

    item = element.items[index]
    entries = []
    if element.value_name:
        entries.append(_entry_for(key, element.value_name, item.value))
    entries.extend(_list_entries(policy, item.value_list))
    return entries


def _list_element_entries(element: Element, key: str, value: Any) -> list[Entry]:
    """A list box: any number of values under one key.

    Two shapes, and the template decides which: with ``explicitValue`` the
    administrator supplies both name and data, otherwise the names are
    generated by numbering the prefix from 1.
    """
    if not value:
        return []

    entries: list[Entry] = []
    if element.explicit_value:
        pairs = value.items() if isinstance(value, dict) else value
        for name, data in pairs:
            if not str(name).strip():
                continue
            entries.append(
                Entry(key=key, value_name=str(name), type=registry_pol.REG_SZ, data=str(data))
            )
        return entries

    prefix = element.value_prefix or ""
    for position, item in enumerate(value, start=1):
        entries.append(
            Entry(
                key=key,
                value_name=f"{prefix}{position}",
                type=registry_pol.REG_SZ,
                data=str(item),
            )
        )
    return entries


def _number(element: Element, value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequest(
            "This setting needs a number.",
            code="invalid_element_value",
            context={"element": element.id, "value": value},
        ) from exc

    if element.min_value is not None and number < element.min_value:
        raise InvalidRequest(
            f"The value must be at least {element.min_value}.",
            code="element_out_of_range",
            context={"element": element.id, "min": element.min_value},
        )
    if element.max_value is not None and number > element.max_value:
        raise InvalidRequest(
            f"The value must be at most {element.max_value}.",
            code="element_out_of_range",
            context={"element": element.id, "max": element.max_value},
        )
    return number


def _text(element: Element, value: Any) -> str:
    text = str(value)
    if element.max_length is not None and len(text) > element.max_length:
        raise InvalidRequest(
            f"The text may be at most {element.max_length} characters long.",
            code="element_too_long",
            context={"element": element.id, "max": element.max_length},
        )
    return text


# ---------------------------------------------------------------------------
# What a policy owns
# ---------------------------------------------------------------------------


def claims(policy: Policy, key: str, value_name: str) -> bool:
    """Whether an existing entry belongs to this policy.

    Needed because removing a setting means removing exactly the values it
    wrote — a key is shared between policies often enough that clearing it
    wholesale would take other settings with it.
    """
    lowered_key = key.lower()
    # A "**del.X" marker belongs to whoever owns X: it is how that value is
    # switched off, and leaving one behind would keep a setting removed after
    # the policy that removed it is gone.
    lowered_name = (deleted_name(value_name) or value_name).lower()

    if (
        policy.value_name
        and lowered_key == policy.key.lower()
        and lowered_name == policy.value_name.lower()
    ):
        return True

    for items in (policy.enabled_list, policy.disabled_list):
        for item in items:
            if not item.value_name:
                continue
            if (item.key or policy.key).lower() == lowered_key and (
                item.value_name.lower() == lowered_name
            ):
                return True

    for element in policy.elements:
        element_key = (element.key or policy.key).lower()
        if element_key != lowered_key:
            continue

        if element.kind == "list":
            if element.explicit_value:
                # Any value under the list's own key belongs to it — that is
                # what an explicit list means, and it is why templates give
                # such lists a key of their own.
                if element.key:
                    return True
                continue
            prefix = re.escape(element.value_prefix or "")
            if re.fullmatch(rf"{prefix}\d+", value_name, re.IGNORECASE):
                return True
            continue

        if element.value_name and element.value_name.lower() == lowered_name:
            return True

        for items in (element.true_list, element.false_list):
            for item in items:
                if item.value_name and item.value_name.lower() == lowered_name:
                    return True
        for enum_item in element.items:
            for item in enum_item.value_list:
                if item.value_name and item.value_name.lower() == lowered_name:
                    return True

    return False


def owned(policy: Policy, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The entries of a ``Registry.pol`` that belong to *policy*."""
    return [entry for entry in entries if claims(policy, entry["key"], entry["value"])]


# ---------------------------------------------------------------------------
# Entries -> state
# ---------------------------------------------------------------------------


def state_of(policy: Policy, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Read a policy's current state out of a parsed ``Registry.pol``.

    Where the state cannot be told apart — a policy whose value is present but
    matches neither the enabled nor the disabled value — it is reported as
    enabled with the values that are there. That is what GPMC shows, and it is
    the reading that loses nothing: the values are visible and can be
    corrected.
    """
    index = {(entry["key"].lower(), entry["value"].lower()): entry for entry in entries}

    state: State = "not_configured"
    if policy.value_name:
        found = index.get((policy.key.lower(), policy.value_name.lower()))
        if found is not None:
            # Disabled is checked first because it is the narrower claim: a
            # value that matches neither is reported as enabled, with whatever
            # is there shown in the form. That is what GPMC does, and it loses
            # nothing — the values stay visible and correctable.
            disabled = policy.disabled_value or DEFAULT_DISABLED
            state = "disabled" if _matches(found, disabled) else "enabled"
        elif _deleted(index, policy.key, policy.value_name):
            # An "off" expressed by removing the value leaves a marker behind,
            # so it is not the same as never having been configured.
            state = "disabled"
    elif policy.enabled_list or policy.disabled_list:
        # Both branches check that the list has anything in it *before* asking
        # whether all of it is present. `all([])` is true, so a policy that
        # carries only a <disabledList> would otherwise report itself enabled
        # in a policy that configures nothing at all — and go on saying so in
        # the status column of every listing.
        if policy.enabled_list and all(
            _present(index, policy, item) for item in policy.enabled_list
        ):
            state = "enabled"
        elif policy.disabled_list and all(
            _present(index, policy, item) for item in policy.disabled_list
        ):
            state = "disabled"

    # Read the elements before deciding, not after: a policy that carries only
    # elements says nothing through a value of its own, and its state *is*
    # whether any of them are there.
    values = _element_values(policy, index)

    if state == "not_configured":
        if not policy.value_name and values:
            state = "enabled"
        else:
            # Values left over from a policy that is no longer configured are
            # not part of its state and would fill the form with fiction.
            values = {}

    return {"state": state, "values": values}


def _matches(entry: dict[str, Any], value: Value) -> bool:
    if value.is_delete:
        # A deletion is not expressed by this entry but by a marker beside it.
        return False
    if value.kind == "decimal":
        return entry.get("data") == int(value.data or 0)
    return str(entry.get("data", "")) == str(value.data or "")


def _deleted(index: dict[tuple[str, str], Any], key: str, value_name: str) -> bool:
    """Whether a ``**del.`` marker for this value is present."""
    return (key.lower(), deletion_of(value_name).lower()) in index


def _present(index: dict[tuple[str, str], Any], policy: Policy, item: ValueItem) -> bool:
    if not item.value_name:
        return False
    return (
        (item.key or policy.key).lower(),
        item.value_name.lower(),
    ) in index


def _element_values(
    policy: Policy, index: dict[tuple[str, str], Any]
) -> dict[str, Any]:
    values: dict[str, Any] = {}

    for element in policy.elements:
        key = (element.key or policy.key).lower()

        if element.kind == "list":
            found = _list_values(element, key, index)
            if found:
                values[element.id] = found
            continue

        if not element.value_name:
            continue
        entry = index.get((key, element.value_name.lower()))
        if entry is None:
            # A checkbox whose "off" removes the value says so with a marker;
            # without this the box would come back unset instead of unticked,
            # which is a different setting.
            if element.kind == "boolean" and _deleted(index, key, element.value_name):
                values[element.id] = False
            continue

        if element.kind == "boolean":
            true_value = element.true_value or DEFAULT_ENABLED
            values[element.id] = _matches(entry, true_value)
        elif element.kind == "enum":
            for position, item in enumerate(element.items):
                if _matches(entry, item.value):
                    values[element.id] = position
                    break
        elif element.kind in ("decimal", "longDecimal"):
            try:
                values[element.id] = int(entry["data"])
            except (TypeError, ValueError):
                values[element.id] = entry["data"]
        else:
            values[element.id] = entry["data"]

    return values


def _list_values(
    element: Element, key: str, index: dict[tuple[str, str], Any]
) -> Any:
    if element.explicit_value:
        found = {
            entry["value"]: entry["data"]
            for (entry_key, _), entry in index.items()
            if entry_key == key
        }
        return found or None

    prefix = re.escape(element.value_prefix or "")
    pattern = re.compile(rf"{prefix}(\d+)$", re.IGNORECASE)

    numbered: list[tuple[int, Any]] = []
    for (entry_key, _), entry in index.items():
        if entry_key != key:
            continue
        match = pattern.fullmatch(entry["value"])
        if match:
            numbered.append((int(match.group(1)), entry["data"]))

    numbered.sort()
    return [data for _, data in numbered] or None


# ---------------------------------------------------------------------------
# Planning a change
# ---------------------------------------------------------------------------


def plan(policy: Policy, current: list[dict[str, Any]], desired: list[Entry]) -> Plan:
    """What to write and what to remove to reach *desired*.

    *current* is the whole parsed ``Registry.pol``; only the entries this
    policy owns are considered for removal.
    """
    wanted = {entry.ident: entry for entry in desired}
    result = Plan(set=list(wanted.values()))

    # Whatever this policy owns and no longer wants goes — including any
    # "**del." markers it left behind, which are its own entries too.
    for entry in owned(policy, current):
        ident = (entry["key"].lower(), entry["value"].lower())
        if ident not in wanted:
            result.remove.append(Entry(key=entry["key"], value_name=entry["value"]))

    # Nothing to do if every desired value is already there unchanged.
    unchanged = []
    index = {(entry["key"].lower(), entry["value"].lower()): entry for entry in current}
    for entry in result.set:
        existing = index.get(entry.ident)
        if existing is not None and _same(existing, entry):
            unchanged.append(entry.ident)
    result.set = [entry for entry in result.set if entry.ident not in unchanged]

    return result


def _same(existing: dict[str, Any], entry: Entry) -> bool:
    if existing.get("type_id") != entry.type:
        return False
    return existing.get("data") == entry.data

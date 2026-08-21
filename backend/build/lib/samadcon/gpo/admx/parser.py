"""Reading ``.admx`` and ``.adml`` files.

Two files describe one template. The ADMX carries the structure — categories,
policies, which registry values each writes — and is language-neutral; every
piece of text in it is a reference like ``$(string.SomeId)`` that resolves
against the ADML for the chosen language.

Three details shape the implementation:

* **Namespaces.** Each ADMX declares a target namespace and a prefix for every
  other namespace it uses. A category reference reads ``prefix:Name`` and only
  means anything once the prefix is resolved against that file's declarations.
  Microsoft's templates hang almost everything under categories defined in
  ``windows.admx``, so getting this wrong produces a tree of orphans.
* **A missing ADML is not fatal.** The policies still exist and still write
  the same registry values; only the labels are missing. Refusing to load the
  template would turn a language problem into missing settings.
* **Parsing with the standard library.** ElementTree resolves no external
  entities, which matters for files taken off a share.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from xml.etree import ElementTree

from samadcon.core.errors import InvalidRequest
from samadcon.gpo.admx.model import (
    Catalogue,
    Category,
    Element,
    EnumItem,
    Policy,
    Value,
    ValueItem,
)

logger = logging.getLogger(__name__)

ADMX_NS = "http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"

# $(string.Id) and $(presentation.Id)
_REFERENCE_RE = re.compile(r"^\$\((?P<kind>[a-zA-Z]+)\.(?P<id>.+)\)$")


def _tag(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def _children(parent: Any, name: str) -> list[Any]:
    return [child for child in parent if _tag(child) == name]


def _child(parent: Any, name: str) -> Any | None:
    for child in parent:
        if _tag(child) == name:
            return child
    return None


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() == "true"


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# ADML — the text
# ---------------------------------------------------------------------------


class Strings:
    """The text of one template in one language."""

    def __init__(
        self, strings: dict[str, str] | None = None, presentations: dict[str, Any] | None = None
    ) -> None:
        self.strings = strings or {}
        self.presentations = presentations or {}

    def resolve(self, reference: str | None) -> str:
        """Turn ``$(string.Id)`` into its text.

        A reference that resolves to nothing keeps its own id as the label.
        An empty string would leave a policy with no name at all, which is
        worse than an ugly one: it cannot be found or talked about.
        """
        if not reference:
            return ""
        match = _REFERENCE_RE.match(reference.strip())
        if match is None:
            return reference
        if match.group("kind").lower() != "string":
            return reference
        key = match.group("id")
        return self.strings.get(key, key)

    def presentation_id(self, reference: str | None) -> str | None:
        if not reference:
            return None
        match = _REFERENCE_RE.match(reference.strip())
        if match is None or match.group("kind").lower() != "presentation":
            return None
        return match.group("id")


def parse_adml(raw: bytes) -> Strings:
    """Read one ``.adml`` file."""
    root = ElementTree.fromstring(raw)
    resources = _child(root, "resources")
    if resources is None:
        return Strings()

    strings: dict[str, str] = {}
    table = _child(resources, "stringTable")
    if table is not None:
        for entry in _children(table, "string"):
            key = entry.get("id")
            if key:
                strings[key] = "".join(entry.itertext()).strip()

    presentations: dict[str, Any] = {}
    table = _child(resources, "presentationTable")
    if table is not None:
        for entry in _children(table, "presentation"):
            key = entry.get("id")
            if key:
                presentations[key] = _parse_presentation(entry)

    return Strings(strings, presentations)


def _parse_presentation(element: Any) -> list[dict[str, Any]]:
    """The controls a policy's form shows, in order.

    Each carries the ``refId`` of the element it belongs to; controls without
    one are captions, which are worth keeping because they are often the only
    explanation of what the inputs below them mean.
    """
    controls: list[dict[str, Any]] = []
    for child in element:
        kind = _tag(child)
        control: dict[str, Any] = {"kind": kind, "ref": child.get("refId")}

        if kind == "text":
            control["text"] = "".join(child.itertext()).strip()
        else:
            label = _child(child, "label")
            control["label"] = (
                "".join(label.itertext()).strip()
                if label is not None
                else "".join(child.itertext()).strip()
            )

        # The schema spells defaults three ways, one per control: an attribute
        # on decimalTextBox, a child element on textBox, and its own attribute
        # name on checkBox and dropdownList.
        if child.get("defaultValue") is not None:
            control["default"] = child.get("defaultValue")
        else:
            default = _child(child, "defaultValue")
            if default is not None:
                control["default"] = "".join(default.itertext()).strip()

        if child.get("defaultChecked") is not None:
            control["default"] = _bool(child.get("defaultChecked"))
        if child.get("defaultItem") is not None:
            control["default_item"] = _int(child.get("defaultItem"))

        for attribute in ("spinStep", "noSortSingleValue"):
            if child.get(attribute) is not None:
                control[attribute] = child.get(attribute)

        controls.append(control)
    return controls


# ---------------------------------------------------------------------------
# ADMX — the structure
# ---------------------------------------------------------------------------


def validate(raw: bytes, name: str) -> None:
    """Refuse a template Windows would choke on.

    Not a nicety. Windows parses the whole central store as one, and a single
    file it cannot read makes it abandon **every** administrative template:
    the Group Policy report then shows one parser error where the settings
    should be, for the entire domain. One bad upload is enough.

    Only what makes the difference between readable and not is checked —
    schema validation would need the schema, and rejecting a template that
    Windows would have accepted is its own kind of damage.
    """
    is_text = name.lower().endswith(".adml")

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise InvalidRequest(
            "This file is not readable XML.",
            code="invalid_template",
            detail=str(exc),
            context={"file": name},
        ) from exc

    expected = "policyDefinitionResources" if is_text else "policyDefinitions"
    if _tag(root) != expected:
        raise InvalidRequest(
            "This file is not an administrative template.",
            code="invalid_template",
            hint=f"Expected a <{expected}> document.",
            context={"file": name, "found": _tag(root)},
        )

    if _child(root, "resources") is None:
        # The element the schema requires and everyone forgets: an ADMX
        # carries an empty <resources> declaring its revision, an ADML the
        # actual strings.
        raise InvalidRequest(
            "This template has no <resources> element.",
            code="invalid_template",
            hint="Every template needs one; Windows refuses the whole store without it.",
            context={"file": name},
        )

    if is_text:
        # And an ADML needs both of these, in this order, before its
        # resources. The schema says so and Windows enforces it — the error it
        # gives names <displayName> and points at <resources>, which reads as
        # a complaint about the wrong element.
        for required in ("displayName", "description"):
            if _child(root, required) is None:
                raise InvalidRequest(
                    f"This text file has no <{required}> element.",
                    code="invalid_template",
                    hint="An .adml needs <displayName> and <description> before <resources>.",
                    context={"file": name},
                )

    if not is_text:
        declarations = _child(root, "policyNamespaces")
        if declarations is None or _child(declarations, "target") is None:
            raise InvalidRequest(
                "This template declares no namespace of its own.",
                code="invalid_template",
                hint="A <policyNamespaces> element with a <target> is required.",
                context={"file": name},
            )


def parse_admx(raw: bytes, strings: Strings, catalogue: Catalogue, *, source: str = "") -> None:
    """Read one ``.admx`` file into *catalogue*."""
    root = ElementTree.fromstring(raw)

    target, prefixes = _namespaces(root)
    # Kept per file: presentation ids are only unique within one template.
    for presentation_id, controls in strings.presentations.items():
        catalogue.presentations[(source, presentation_id)] = controls

    _parse_supported_on(root, strings, catalogue, target)
    _parse_categories(root, strings, catalogue, target, prefixes, source)
    _parse_policies(root, strings, catalogue, target, prefixes, source)


def _parse_supported_on(
    root: Any, strings: Strings, catalogue: Catalogue, target: str
) -> None:
    """The "supported on" texts this file defines.

    Without them a policy shows its reference where GPMC shows "At least
    Windows 7". They go into the catalogue rather than onto the policies
    because the file defining them is usually not the file using them.
    """
    container = _child(root, "supportedOn")
    if container is None:
        return

    definitions = _child(container, "definitions")
    if definitions is None:
        return

    for definition in _children(definitions, "definition"):
        name = definition.get("name")
        if not name:
            continue
        qualified = f"{target}:{name}" if target else name
        catalogue.supported_on[qualified] = strings.resolve(definition.get("displayName"))


def _namespaces(root: Any) -> tuple[str, dict[str, str]]:
    """The file's own namespace, and the prefixes it uses for others."""
    target = ""
    prefixes: dict[str, str] = {}

    declarations = _child(root, "policyNamespaces")
    if declarations is None:
        return target, prefixes

    own = _child(declarations, "target")
    if own is not None:
        target = own.get("namespace", "") or ""
        prefix = own.get("prefix")
        if prefix:
            prefixes[prefix] = target

    for using in _children(declarations, "using"):
        prefix = using.get("prefix")
        namespace = using.get("namespace")
        if prefix and namespace:
            prefixes[prefix] = namespace

    return target, prefixes


def _qualify(reference: str | None, target: str, prefixes: dict[str, str]) -> str | None:
    """``prefix:Name`` -> ``namespace:Name``.

    A reference without a prefix belongs to the file's own namespace. An
    unknown prefix is left as it is rather than dropped: the category it names
    may be defined by a template that is installed later, and an unresolved
    parent still shows up as a root.
    """
    if not reference:
        return None
    text = reference.strip()
    if ":" not in text:
        return f"{target}:{text}" if target else text

    prefix, _, name = text.partition(":")
    namespace = prefixes.get(prefix)
    return f"{namespace}:{name}" if namespace else text


def _parse_categories(
    root: Any,
    strings: Strings,
    catalogue: Catalogue,
    target: str,
    prefixes: dict[str, str],
    source: str,
) -> None:
    container = _child(root, "categories")
    if container is None:
        return

    for element in _children(container, "category"):
        name = element.get("name")
        if not name:
            continue

        parent = _child(element, "parentCategory")
        catalogue.add_category(
            Category(
                id=f"{target}:{name}" if target else name,
                name=name,
                display_name=strings.resolve(element.get("displayName")),
                explain=strings.resolve(element.get("explainText")),
                parent=_qualify(
                    parent.get("ref") if parent is not None else None, target, prefixes
                ),
                source=source,
            )
        )


def _parse_policies(
    root: Any,
    strings: Strings,
    catalogue: Catalogue,
    target: str,
    prefixes: dict[str, str],
    source: str,
) -> None:
    container = _child(root, "policies")
    if container is None:
        return

    for element in _children(container, "policy"):
        name = element.get("name")
        key = element.get("key")
        if not name or not key:
            # Both are required by the schema; a policy without them cannot be
            # written anywhere, so it is skipped rather than half-loaded.
            catalogue.note(source, f"policy without a name or key: {name or '?'}")
            continue

        parent = _child(element, "parentCategory")

        catalogue.add_policy(
            Policy(
                id=f"{target}:{name}" if target else name,
                name=name,
                policy_class=_policy_class(element.get("class")),
                key=key,
                display_name=strings.resolve(element.get("displayName")),
                explain=strings.resolve(element.get("explainText")),
                value_name=element.get("valueName"),
                category=_qualify(
                    parent.get("ref") if parent is not None else None, target, prefixes
                ),
                supported_on=_supported_ref(element, target, prefixes),
                presentation=strings.presentation_id(element.get("presentation")),
                enabled_value=_value_of(_child(element, "enabledValue")),
                disabled_value=_value_of(_child(element, "disabledValue")),
                enabled_list=_value_list(_child(element, "enabledList")),
                disabled_list=_value_list(_child(element, "disabledList")),
                elements=_parse_elements(element, strings),
                source=source,
            )
        )


def _supported_ref(policy: Any, target: str, prefixes: dict[str, str]) -> str | None:
    """The definition a policy points at, qualified like every other reference."""
    element = _child(policy, "supportedOn")
    if element is None:
        return None
    return _qualify(element.get("ref"), target, prefixes)


def _policy_class(value: str | None) -> Any:
    text = (value or "").strip().lower()
    if text == "machine":
        return "Machine"
    if text == "user":
        return "User"
    # "Both" is the schema's default and what an absent attribute means.
    return "Both"


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _value_of(container: Any) -> Value | None:
    """The single value inside an ``enabledValue``/``trueValue`` and friends."""
    if container is None:
        return None
    for child in container:
        kind = _tag(child)
        if kind == "decimal":
            return Value("decimal", _int(child.get("value")) or 0)
        if kind == "longDecimal":
            return Value("decimal", _int(child.get("value")) or 0)
        if kind == "string":
            return Value("string", "".join(child.itertext()).strip())
        if kind == "delete":
            return Value("delete")
    return None


def _value_list(container: Any) -> tuple[ValueItem, ...]:
    """An ``enabledList``/``disabledList``: extra values written alongside."""
    if container is None:
        return ()

    default_key = container.get("defaultKey")
    items = []
    for entry in _children(container, "item"):
        value = _value_of(_child(entry, "value"))
        if value is None:
            continue
        items.append(
            ValueItem(
                value=value,
                key=entry.get("key") or default_key,
                value_name=entry.get("valueName"),
            )
        )
    return tuple(items)


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


def _parse_elements(policy: Any, strings: Strings) -> tuple[Element, ...]:
    container = _child(policy, "elements")
    if container is None:
        return ()

    elements = []
    for child in container:
        kind = _tag(child)
        element_id = child.get("id")
        if not element_id:
            continue

        if kind == "boolean":
            elements.append(
                Element(
                    id=element_id,
                    kind="boolean",
                    value_name=child.get("valueName"),
                    key=child.get("key"),
                    true_value=_value_of(_child(child, "trueValue")),
                    false_value=_value_of(_child(child, "falseValue")),
                    true_list=_value_list(_child(child, "trueList")),
                    false_list=_value_list(_child(child, "falseList")),
                )
            )
        elif kind in ("decimal", "longDecimal"):
            elements.append(
                Element(
                    id=element_id,
                    kind=kind,  # type: ignore[arg-type]
                    value_name=child.get("valueName"),
                    key=child.get("key"),
                    required=_bool(child.get("required")),
                    min_value=_int(child.get("minValue")) or 0,
                    max_value=_int(child.get("maxValue")),
                    store_as_text=_bool(child.get("storeAsText")),
                )
            )
        elif kind == "text":
            elements.append(
                Element(
                    id=element_id,
                    kind="text",
                    value_name=child.get("valueName"),
                    key=child.get("key"),
                    required=_bool(child.get("required")),
                    max_length=_int(child.get("maxLength")),
                    expandable=_bool(child.get("expandable")),
                )
            )
        elif kind == "multiText":
            elements.append(
                Element(
                    id=element_id,
                    kind="multiText",
                    value_name=child.get("valueName"),
                    key=child.get("key"),
                    required=_bool(child.get("required")),
                    max_length=_int(child.get("maxLength")),
                )
            )
        elif kind == "enum":
            elements.append(
                Element(
                    id=element_id,
                    kind="enum",
                    value_name=child.get("valueName"),
                    key=child.get("key"),
                    required=_bool(child.get("required")),
                    items=_enum_items(child, strings),
                )
            )
        elif kind == "list":
            elements.append(
                Element(
                    id=element_id,
                    kind="list",
                    key=child.get("key"),
                    value_prefix=child.get("valuePrefix"),
                    additive=_bool(child.get("additive")),
                    explicit_value=_bool(child.get("explicitValue")),
                )
            )

    return tuple(elements)


def _enum_items(element: Any, strings: Strings) -> tuple[EnumItem, ...]:
    items = []
    for entry in _children(element, "item"):
        value = _value_of(_child(entry, "value"))
        if value is None:
            continue
        items.append(
            EnumItem(
                display_name=strings.resolve(entry.get("displayName")),
                value=value,
                value_list=_value_list(_child(entry, "valueList")),
            )
        )
    return tuple(items)

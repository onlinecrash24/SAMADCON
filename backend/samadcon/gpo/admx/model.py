"""The shape of an administrative template, once parsed.

Deliberately plain data: the parser fills these in, the resolver reads them,
and neither needs the other's machinery. Everything is frozen because a
catalogue is shared between sessions out of a cache — a mutable one would let
one administrator's view change another's.

Names carry their namespace (``prefix:Name`` resolved to
``urn:...:namespace:Name``) because ADMX files reference each other's
categories constantly: Microsoft's own templates hang almost everything under
categories defined in ``windows.admx``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Which half of a GPO a policy writes into.
PolicyClass = Literal["Machine", "User", "Both"]

# The element kinds ADMX defines. "list" is the odd one out: it writes any
# number of values rather than one.
ElementKind = Literal["boolean", "decimal", "longDecimal", "text", "enum", "list", "multiText"]


@dataclass(frozen=True)
class Value:
    """A registry value as ADMX writes it.

    ``delete`` is a value in the same sense the others are: it means the entry
    is removed rather than set, which is how most policies express "off".
    """

    kind: Literal["decimal", "string", "delete"]
    data: int | str | None = None

    @property
    def is_delete(self) -> bool:
        return self.kind == "delete"


@dataclass(frozen=True)
class ValueItem:
    """One entry of an ``enabledList`` or ``disabledList``."""

    value: Value
    key: str | None = None
    value_name: str | None = None


@dataclass(frozen=True)
class EnumItem:
    display_name: str
    value: Value
    # An enum item may write several extra values alongside its own.
    value_list: tuple[ValueItem, ...] = ()


@dataclass(frozen=True)
class Element:
    """One input on a policy's form."""

    id: str
    kind: ElementKind
    value_name: str | None = None
    # An element may write into a different key than its policy.
    key: str | None = None
    required: bool = False

    # decimal / longDecimal
    min_value: int | None = None
    max_value: int | None = None
    # Whether a number is stored as text rather than as a DWORD.
    store_as_text: bool = False

    # text
    max_length: int | None = None
    expandable: bool = False

    # boolean
    true_value: Value | None = None
    false_value: Value | None = None
    true_list: tuple[ValueItem, ...] = ()
    false_list: tuple[ValueItem, ...] = ()

    # enum
    items: tuple[EnumItem, ...] = ()

    # list
    value_prefix: str | None = None
    # Whether the list adds to what is there rather than replacing it.
    additive: bool = False
    # Whether each entry carries its own value name; otherwise they are
    # numbered from the prefix.
    explicit_value: bool = False

    @property
    def label(self) -> str:
        """A fallback label, used when the ADML has no presentation for it."""
        return self.id


@dataclass(frozen=True)
class Policy:
    """One setting, as the editor offers it."""

    # Namespaced, so two templates may both define "Enabled".
    id: str
    name: str
    policy_class: PolicyClass
    key: str
    display_name: str = ""
    explain: str = ""
    value_name: str | None = None
    category: str | None = None
    supported_on: str | None = None
    presentation: str | None = None

    enabled_value: Value | None = None
    disabled_value: Value | None = None
    enabled_list: tuple[ValueItem, ...] = ()
    disabled_list: tuple[ValueItem, ...] = ()
    elements: tuple[Element, ...] = ()

    # Where the definition came from, for diagnosing a template that behaves
    # unexpectedly.
    source: str = ""

    @property
    def halves(self) -> tuple[str, ...]:
        """The halves of a GPO this policy can be set in."""
        if self.policy_class == "Both":
            return ("Machine", "User")
        return (self.policy_class,)

    def element(self, element_id: str) -> Element | None:
        for item in self.elements:
            if item.id == element_id:
                return item
        return None


@dataclass(frozen=True)
class Category:
    """A node of the policy tree."""

    id: str
    name: str
    display_name: str = ""
    explain: str = ""
    parent: str | None = None
    source: str = ""


@dataclass
class Catalogue:
    """Every definition read from a set of templates."""

    categories: dict[str, Category] = field(default_factory=dict)
    policies: dict[str, Policy] = field(default_factory=dict)
    # The controls a policy's form shows, keyed by the file they came from and
    # the id within it. Two templates may each define a presentation called
    # "Settings", so the file is part of the key.
    presentations: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    # "At least Windows 7" and its like, by qualified name. Kept on the
    # catalogue rather than on the policy because the definitions live in one
    # template and are referenced from every other — the same arrangement the
    # categories have, and for the same reason.
    supported_on: dict[str, str] = field(default_factory=dict)
    # Files that could not be read, with the reason. Reported rather than
    # dropped: a missing template shows up as missing settings, and an
    # administrator looking for one needs to know it was not loaded.
    problems: list[dict[str, str]] = field(default_factory=list)
    language: str = ""

    def add_category(self, category: Category) -> None:
        self.categories[category.id] = category

    def add_policy(self, policy: Policy) -> None:
        self.policies[policy.id] = policy

    def note(self, source: str, reason: str) -> None:
        self.problems.append({"source": source, "reason": reason})

    def supported_text(self, policy: Policy) -> str | None:
        """What a policy needs, as text — or nothing when it cannot be said.

        The raw reference used to be passed through when its definition was
        not installed, on the reasoning that half an answer beats none. It
        does not. Samba's templates reference a namespace generated by the
        tool that built them, so a Linux-only smb.conf setting announced
        itself as ``…:SUPPORTED_WIN7`` — which reads as a requirement, and is
        the opposite of true.

        The reference is still available through :meth:`supported_ref`, for a
        reader who wants to know why there is no answer.
        """
        if not policy.supported_on:
            return None
        return self.supported_on.get(policy.supported_on)

    def supported_ref(self, policy: Policy) -> str | None:
        """The unresolved reference, when there is one and it did not resolve."""
        if not policy.supported_on or policy.supported_on in self.supported_on:
            return None
        return policy.supported_on

    def presentation_for(self, policy: Policy) -> list[dict[str, Any]]:
        """The controls for a policy's form.

        Empty when the template names none or its text file is missing. The
        editor then falls back to one input per element, which is plainer than
        what GPMC shows but never leaves an element unreachable.
        """
        if not policy.presentation:
            return []
        return self.presentations.get((policy.source, policy.presentation), [])

    # -- navigation --------------------------------------------------------

    def children_of(self, category_id: str | None) -> list[Category]:
        """Categories directly below one, sorted by what a reader sees."""
        found = [item for item in self.categories.values() if item.parent == category_id]
        found.sort(key=lambda item: (item.display_name or item.name).lower())
        return found

    def policies_in(
        self, category_id: str | None, *, policy_class: str | None = None
    ) -> list[Policy]:
        found = [
            policy
            for policy in self.policies.values()
            if policy.category == category_id
            and (policy_class is None or policy_class in policy.halves)
        ]
        found.sort(key=lambda policy: (policy.display_name or policy.name).lower())
        return found

    def roots(self) -> list[Category]:
        """Top-level categories.

        A category whose parent is missing counts as a root. Templates
        reference each other, and one that is installed without the template
        defining its parent would otherwise vanish from the tree entirely —
        the worst outcome, because the settings are there and unreachable.
        """
        found = [
            item
            for item in self.categories.values()
            if item.parent is None or item.parent not in self.categories
        ]
        found.sort(key=lambda item: (item.display_name or item.name).lower())
        return found

    def path_of(self, category_id: str | None) -> list[Category]:
        """From the root down to a category, for a breadcrumb."""
        path: list[Category] = []
        seen: set[str] = set()
        current = category_id
        while current and current in self.categories and current not in seen:
            seen.add(current)
            category = self.categories[current]
            path.append(category)
            current = category.parent
        path.reverse()
        return path

    def search(self, needle: str, *, limit: int = 200) -> list[Policy]:
        """Policies whose name or explanation mentions *needle*.

        Searching the explanation as well is what makes this useful: nobody
        remembers what a setting is called, but everyone remembers roughly
        what it does.
        """
        text = needle.strip().lower()
        if not text:
            return []

        exact: list[Policy] = []
        partial: list[Policy] = []
        for policy in self.policies.values():
            name = (policy.display_name or policy.name).lower()
            if text in name:
                exact.append(policy)
            elif text in policy.explain.lower():
                partial.append(policy)

        exact.sort(key=lambda policy: (policy.display_name or policy.name).lower())
        partial.sort(key=lambda policy: (policy.display_name or policy.name).lower())
        return (exact + partial)[:limit]

    def summary(self) -> dict[str, Any]:
        return {
            "categories": len(self.categories),
            "policies": len(self.policies),
            "language": self.language,
            "problems": self.problems,
        }

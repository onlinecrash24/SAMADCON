"""Turning parsed templates into what the editor needs.

Separate from the model because the two answer different questions. The model
is what the resolver reads; this is what a form needs in order to be drawn,
which is a smaller thing with different names — an element's ``valueName``
means nothing in a browser, its label and its bounds mean everything.
"""

from __future__ import annotations

from typing import Any

from samcon.gpo.admx.model import Catalogue, Category, Element, Policy, Value


def value_json(value: Value | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"kind": value.kind, "data": value.data}


def element_json(element: Element) -> dict[str, Any]:
    """One input, with everything needed to draw and check it."""
    described: dict[str, Any] = {
        "id": element.id,
        "kind": element.kind,
        "required": element.required,
    }

    if element.kind in ("decimal", "longDecimal"):
        described["min"] = element.min_value
        described["max"] = element.max_value
    elif element.kind == "text" or element.kind == "multiText":
        described["max_length"] = element.max_length
    elif element.kind == "enum":
        described["items"] = [
            {"index": index, "label": item.display_name}
            for index, item in enumerate(element.items)
        ]
    elif element.kind == "list":
        # Whether each entry carries its own name decides which of two forms
        # the editor shows: a plain list, or pairs.
        described["explicit_value"] = element.explicit_value
        described["additive"] = element.additive

    return described


def policy_json(
    policy: Policy,
    catalogue: Catalogue | None = None,
    *,
    full: bool = False,
    state: str | None = None,
) -> dict[str, Any]:
    """A policy for a listing, or with everything for its form.

    *state* is what one particular GPO says about it. A listing without a GPO
    behind it — browsing the store — has none, which is why it is optional
    rather than a second call.
    """
    described: dict[str, Any] = {
        "id": policy.id,
        "name": policy.name,
        "display_name": policy.display_name or policy.name,
        "class": policy.policy_class,
        "halves": list(policy.halves),
        "category": policy.category,
        "source": policy.source,
        "has_elements": bool(policy.elements),
    }
    if state is not None:
        described["state"] = state
    if not full:
        return described

    described.update(
        {
            "explain": policy.explain,
            "key": policy.key,
            "value_name": policy.value_name,
            "supported_on": catalogue.supported_text(policy) if catalogue else policy.supported_on,
            "enabled_value": value_json(policy.enabled_value),
            "disabled_value": value_json(policy.disabled_value),
            "elements": [element_json(element) for element in policy.elements],
            "presentation": catalogue.presentation_for(policy) if catalogue else [],
        }
    )
    return described


def child_index(catalogue: Catalogue) -> dict[str | None, list[str]]:
    """Parent to children, built once for a walk over the whole tree."""
    index: dict[str | None, list[str]] = {}
    for item in catalogue.categories.values():
        index.setdefault(item.parent, []).append(item.id)
    return index


def subtree_ids(index: dict[str | None, list[str]], category_id: str) -> list[str]:
    """A category and every category below it."""
    found = [category_id]
    pending = [category_id]
    while pending:
        for child in index.get(pending.pop(), ()):
            found.append(child)
            pending.append(child)
    return found


def configured_in(
    catalogue: Catalogue,
    index: dict[str | None, list[str]],
    category_id: str,
    configured: set[str],
    *,
    half: str | None = None,
) -> int:
    """How many configured settings sit in a category **or below it**.

    Recursive on purpose: a branch whose settings all live two levels down
    would otherwise count zero and be hidden, while the settings it holds are
    exactly the ones the filter was turned on to find.
    """
    return sum(
        1
        for child in subtree_ids(index, category_id)
        for policy in catalogue.policies_in(child, policy_class=half)
        if policy.id in configured
    )


def category_json(
    category: Category,
    catalogue: Catalogue,
    *,
    half: str | None = None,
    configured: set[str] | None = None,
    index: dict[str | None, list[str]] | None = None,
) -> dict:
    """A node of the tree, with what is below it.

    The counts decide whether the node is worth opening, and whether it should
    show an expander at all — the same question the directory tree answers,
    and for the same reason.

    With *configured* given, the count becomes the number of configured
    settings in the whole subtree rather than the number of settings directly
    inside. The filter is only useful if it can be trusted to hide a branch,
    and that needs the recursive answer.
    """
    children = catalogue.children_of(category.id)
    policies = catalogue.policies_in(category.id, policy_class=half)

    if configured is None:
        count = len(policies)
    else:
        count = configured_in(
            catalogue, index or child_index(catalogue), category.id, configured, half=half
        )

    return {
        "id": category.id,
        "name": category.name,
        "display_name": category.display_name or category.name,
        "explain": category.explain,
        "parent": category.parent,
        "child_count": len(children),
        "policy_count": count,
        "has_children": bool(children) or bool(policies),
    }


def tree_json(
    catalogue: Catalogue,
    category_id: str | None,
    *,
    half: str | None = None,
    states: dict[str, str] | None = None,
    configured: set[str] | None = None,
) -> dict:
    """One level of the policy tree.

    *configured* is the set of policy ids this GPO actually sets. Given one,
    the level is cut down to the branches that lead to one of them — the tree
    then says the same thing as the listing beside it instead of offering
    fifteen categories of which two hold anything.
    """
    if category_id is None:
        categories = catalogue.roots()
        policies: list[Policy] = []
    else:
        categories = catalogue.children_of(category_id)
        policies = catalogue.policies_in(category_id, policy_class=half)

    index = child_index(catalogue) if configured is not None else None
    nodes = [
        category_json(item, catalogue, half=half, configured=configured, index=index)
        for item in categories
    ]
    if configured is not None:
        nodes = [node for node in nodes if node["policy_count"]]
        policies = [policy for policy in policies if policy.id in configured]

    return {
        "category": category_id,
        "path": [
            {"id": item.id, "display_name": item.display_name or item.name}
            for item in catalogue.path_of(category_id)
        ],
        "categories": nodes,
        "policies": [
            policy_json(item, state=states.get(item.id) if states else None) for item in policies
        ],
    }

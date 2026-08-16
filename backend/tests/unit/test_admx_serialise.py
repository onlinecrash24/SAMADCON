"""What the editor gets to draw a form with."""

from __future__ import annotations

from samcon.gpo.admx import parser, serialise
from samcon.gpo.admx.model import Catalogue, Element, EnumItem, Policy, Value
from tests.unit.test_admx_parser import SAMPLE_ADML, SAMPLE_ADMX, WINDOWS_ADML, WINDOWS_ADMX


def build() -> Catalogue:
    catalogue = Catalogue(language="en-US")
    parser.parse_admx(
        WINDOWS_ADMX, parser.parse_adml(WINDOWS_ADML), catalogue, source="windows.admx"
    )
    parser.parse_admx(
        SAMPLE_ADMX, parser.parse_adml(SAMPLE_ADML), catalogue, source="sample.admx"
    )
    return catalogue


def find(catalogue: Catalogue, name: str) -> Policy:
    return next(item for item in catalogue.policies.values() if item.name == name)


# ---------------------------------------------------------------------------
# Presentations
# ---------------------------------------------------------------------------


def test_a_policy_keeps_the_controls_of_its_form():
    """Parsed from the ADML and kept — they are what the form is made of."""
    catalogue = build()
    controls = catalogue.presentation_for(find(catalogue, "AutoUpdate"))

    assert [control["ref"] for control in controls if control["ref"]] == [
        "Interval",
        "Server",
        "Reboot",
        "Behaviour",
        "Exclusions",
        "Notes",
    ]


def test_two_templates_may_name_their_presentations_alike():
    """Which is why the file is part of the key."""
    catalogue = build()
    keys = set(catalogue.presentations)

    assert ("sample.admx", "AutoUpdate") in keys


def test_a_policy_without_a_presentation_gets_an_empty_one():
    """The editor then falls back to one input per element, which is plainer
    than GPMC but never leaves an element unreachable."""
    catalogue = build()
    assert catalogue.presentation_for(find(catalogue, "UserSetting")) == []


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def test_a_listing_carries_only_what_a_list_needs():
    catalogue = build()
    described = serialise.policy_json(find(catalogue, "AutoUpdate"))

    assert described["display_name"] == "Configure automatic updates"
    assert described["halves"] == ["Machine"]
    assert described["has_elements"] is True
    assert "elements" not in described


def test_the_full_form_carries_the_elements_and_the_presentation():
    catalogue = build()
    described = serialise.policy_json(find(catalogue, "AutoUpdate"), catalogue, full=True)

    assert described["key"] == "Software\\Policies\\Example\\Update"
    assert [element["id"] for element in described["elements"]] == [
        "Interval",
        "Server",
        "Reboot",
        "Behaviour",
        "Exclusions",
        "Notes",
    ]
    assert described["presentation"]


def test_a_policy_without_a_display_name_falls_back_to_its_name():
    """A nameless entry in the tree could not be found or discussed."""
    policy = Policy(id="X:Y", name="Y", policy_class="Machine", key="K")
    assert serialise.policy_json(policy)["display_name"] == "Y"


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


def test_a_number_carries_its_bounds():
    described = serialise.element_json(
        Element(id="N", kind="decimal", value_name="N", min_value=1, max_value=24)
    )
    assert (described["min"], described["max"]) == (1, 24)


def test_text_carries_its_limit():
    described = serialise.element_json(Element(id="T", kind="text", max_length=255))
    assert described["max_length"] == 255


def test_a_dropdown_carries_its_choices_with_their_positions():
    """The position is what gets written back."""
    described = serialise.element_json(
        Element(
            id="E",
            kind="enum",
            items=(EnumItem("First", Value("decimal", 2)), EnumItem("Second", Value("decimal", 4))),
        )
    )

    assert described["items"] == [
        {"index": 0, "label": "First"},
        {"index": 1, "label": "Second"},
    ]


def test_a_list_says_which_of_its_two_forms_it_is():
    plain = serialise.element_json(Element(id="L", kind="list", value_prefix="Ex"))
    pairs = serialise.element_json(Element(id="L", kind="list", explicit_value=True))

    assert plain["explicit_value"] is False
    assert pairs["explicit_value"] is True


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


def test_the_root_level_has_categories_and_no_settings():
    """Settings live under a category, never beside the roots."""
    described = serialise.tree_json(build(), None)

    assert [item["display_name"] for item in described["categories"]] == ["System"]
    assert described["policies"] == []
    assert described["path"] == []


def test_a_level_carries_its_categories_and_its_settings():
    described = serialise.tree_json(build(), "Example.Policies.Sample:Updates")

    assert described["categories"] == []
    assert sorted(item["name"] for item in described["policies"]) == [
        "AutoUpdate",
        "UserSetting",
    ]


def test_a_level_can_be_narrowed_to_one_half():
    described = serialise.tree_json(
        build(), "Example.Policies.Sample:Updates", half="User"
    )
    assert [item["name"] for item in described["policies"]] == ["UserSetting"]


def test_a_level_carries_the_path_that_leads_to_it():
    described = serialise.tree_json(build(), "Example.Policies.Sample:Updates")
    assert [item["display_name"] for item in described["path"]] == ["System", "Updates"]


def test_a_node_says_whether_it_is_worth_opening():
    """The same question the directory tree answers, for the same reason: an
    expander that opens nothing is worse than no expander."""
    catalogue = build()
    described = serialise.tree_json(catalogue, None)
    system = described["categories"][0]

    assert system["has_children"] is True
    assert system["child_count"] == 2

    updates = serialise.category_json(
        catalogue.categories["Example.Policies.Sample:Updates"], catalogue
    )
    assert updates["child_count"] == 0
    assert updates["policy_count"] == 2
    assert updates["has_children"] is True

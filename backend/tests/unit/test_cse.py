"""The extension-names attribute.

A policy whose values are written but whose client-side extension is not
registered applies nowhere, and nothing reports it. These are the rules that
decide whether an edit reaches a client at all.

Shared by every part of the editor that writes into a GPO — administrative
templates, scripts, folder redirection — which is why the sorting matters:
each of them has to leave the others' entries in the order the specification
asks for.
"""

from __future__ import annotations

from samadcon.gpo import cse

CSE = "{35378EAC-683F-11D2-A89A-00C04FBBCFA2}"
OTHER = "{827D319E-6EAC-11D2-A4EA-00C04F79F83A}"
TOOL = "{D02B1F72-3407-48AE-BA88-E8213C6761F1}"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_an_empty_attribute_is_no_extensions():
    assert cse.parse(None) == []
    assert cse.parse("") == []


def test_one_group_is_read():
    assert cse.parse(f"[{CSE}]") == [[CSE]]


def test_a_group_carries_its_tool_guids():
    """The first names the extension, the rest name what wrote it."""
    assert cse.parse(f"[{CSE}{TOOL}]") == [[CSE, TOOL]]


def test_several_groups_are_read():
    parsed = cse.parse(f"[{CSE}][{OTHER}{TOOL}]")
    assert parsed == [[CSE], [OTHER, TOOL]]


def test_guids_are_read_in_upper_case():
    """Windows writes them that way, and comparison is by text."""
    assert cse.parse(f"[{CSE.lower()}]") == [[CSE]]


def test_something_that_holds_no_guid_is_skipped():
    assert cse.parse("[]") == []


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_the_groups_come_out_sorted():
    """Out of order, a client may skip entries — and the policy applies
    nowhere while looking perfectly configured in every console."""
    written = cse.render([[OTHER], [CSE]])
    assert written == f"[{CSE}][{OTHER}]"


def test_sorting_ignores_case():
    written = cse.render([[OTHER.lower()], [CSE]])
    assert written.index(CSE) < written.index(OTHER.lower())


def test_no_groups_is_an_empty_attribute():
    assert cse.render([]) == ""
    assert cse.render([[]]) == ""


# ---------------------------------------------------------------------------
# Adding one
# ---------------------------------------------------------------------------


def test_registering_into_an_empty_attribute():
    assert cse.add(None, cse.REGISTRY_CSE) == f"[{CSE}]"


def test_registering_accepts_a_guid_with_or_without_braces():
    assert cse.add(None, CSE) == f"[{CSE}]"
    assert cse.add(None, CSE.strip("{}")) == f"[{CSE}]"


def test_registering_twice_changes_nothing():
    once = cse.add(None, cse.REGISTRY_CSE)
    assert cse.add(once, cse.REGISTRY_CSE) == once


def test_an_extension_that_is_already_there_in_another_case_is_recognised():
    """Not registered twice — but written back the way Windows writes it.

    Clients compare these without regard to case, so normalising costs one
    write the first time an attribute is touched and makes every later
    comparison a plain text one.
    """
    written = cse.add(f"[{CSE.lower()}]", cse.REGISTRY_CSE)

    assert cse.parse(written) == [[CSE]]
    assert written == f"[{CSE}]"


def test_registering_leaves_other_extensions_in_place():
    """Another extension's registration is another feature's setting."""
    written = cse.add(f"[{OTHER}{TOOL}]", cse.REGISTRY_CSE)

    assert cse.parse(written) == [[CSE], [OTHER, TOOL]]


def test_a_new_registration_lands_in_the_right_place():
    written = cse.add(f"[{CSE}]", OTHER)
    assert written == f"[{CSE}][{OTHER}]"


def test_a_tool_guid_can_be_added_to_an_existing_group():
    written = cse.add(f"[{CSE}]", cse.REGISTRY_CSE, [TOOL])
    assert cse.parse(written) == [[CSE, TOOL]]


def test_a_tool_guid_is_not_added_twice():
    once = cse.add(None, cse.REGISTRY_CSE, [TOOL])
    assert cse.add(once, cse.REGISTRY_CSE, [TOOL]) == once


def test_the_attribute_survives_a_round_trip():
    original = f"[{CSE}{TOOL}][{OTHER}]"
    assert cse.render(cse.parse(original)) == original


# ---------------------------------------------------------------------------
# Taking one away
# ---------------------------------------------------------------------------


def test_unregistering_removes_only_that_extension():
    """When the last setting of a kind is deleted. A registered extension with
    nothing behind it makes every client fetch the policy on every refresh and
    find nothing there."""
    written = cse.remove(f"[{CSE}{TOOL}][{OTHER}]", cse.REGISTRY_CSE)

    assert written == f"[{OTHER}]"


def test_unregistering_something_that_is_not_there_changes_nothing():
    assert cse.remove(f"[{OTHER}]", cse.REGISTRY_CSE) == f"[{OTHER}]"


def test_unregistering_the_last_one_empties_the_attribute():
    """Not a stray "[]" — LDB rejects an attribute with an empty value, which
    is how a backup of such a GPO became un-restorable once before."""
    assert cse.remove(f"[{CSE}]", cse.REGISTRY_CSE) == ""


def test_unregistering_ignores_case_and_braces():
    assert cse.remove(f"[{CSE.lower()}]", CSE.strip("{}")) == ""


# ---------------------------------------------------------------------------
# Halves
# ---------------------------------------------------------------------------


def test_each_half_has_its_own_attribute():
    assert cse.HALF_ATTRIBUTE["Machine"] == "gPCMachineExtensionNames"
    assert cse.HALF_ATTRIBUTE["User"] == "gPCUserExtensionNames"

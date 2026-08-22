"""Which extension each piece of content belongs to.

`registration_problems` compares a half as a whole: content on one side,
any registration at all on the other. Its own docstring names what that
misses — a half whose security template is filled while only the registry
extension is registered reads as fine. These tests cover the per-extension
answer that closes it, and the two buckets that must map to nothing.

Nothing here touches a share. The report structure is the input, so it is
built by hand.
"""

from __future__ import annotations

from typing import Any

from samadcon.gpo import cse, report


def half(**buckets: Any) -> dict[str, Any]:
    """A half with nothing in it, so a test fills one bucket."""
    empty: dict[str, Any] = {
        "registry": [],
        "registry_count": 0,
        "security": {},
        "scripts": {},
        "redirection": {},
        "preferences": [],
        "vgp": [],
        "other_files": [],
    }
    empty.update(buckets)
    return empty


def ids(pairs: list[tuple[str, str]]) -> list[str]:
    return [pair[0] for pair in pairs]


# ---------------------------------------------------------------------------
# What content asks for
# ---------------------------------------------------------------------------


def test_registry_content_asks_for_the_registry_extension() -> None:
    found = report.required_pairs(half(registry=[{"key": "Software", "values": []}]))

    assert ids(found) == [cse.REGISTRY_CSE]


def test_each_bucket_maps_to_its_own_extension() -> None:
    """The whole point: per extension, not per half."""
    found = report.required_pairs(
        half(security={"System Access": {}}, scripts={"Startup": [{}]})
    )

    assert set(ids(found)) == {cse.SECURITY_CSE, cse.SCRIPTS_CSE}


def test_a_preference_type_brings_the_pair_gpmc_registers() -> None:
    """Two pairs, not one: GPMC writes the null CSE beside the real one."""
    found = report.required_pairs(
        half(preferences=[{"type": "Drives", "file": "Drives.xml", "items": [{"name": "P:"}]}])
    )

    assert ids(found) == [cse.PREFERENCES_NULL_CSE, cse.DRIVES_CSE]


def test_an_empty_preference_file_asks_for_nothing() -> None:
    """samba-tool and GPMC both leave the file behind when the last item goes.
    A file with no items reaches no client, so it must not register one."""
    found = report.required_pairs(
        half(preferences=[{"type": "Drives", "file": "Drives.xml", "items": []}])
    )

    assert found == []


# ---------------------------------------------------------------------------
# What deliberately maps to nothing
# ---------------------------------------------------------------------------


def test_vgp_registers_no_extension() -> None:
    """Windows ignores these and samba-gpupdate runs every loaded extension
    against every applicable policy. Registering one would claim something no
    client acts on."""
    found = report.required_pairs(half(vgp=[{"path": "x", "entries": [{"command": "ls"}]}]))

    assert found == []


def test_a_file_nobody_understood_registers_nothing() -> None:
    """Not understanding a file is no basis for choosing the extension that
    would apply it, and a wrong choice registers one that then finds nothing."""
    found = report.required_pairs(half(other_files=[{"name": "mystery.dat"}]))

    assert found == []


def test_an_unknown_preference_directory_is_skipped_rather_than_guessed() -> None:
    found = report.required_pairs(
        half(preferences=[{"type": "Wombats", "file": "Wombats.xml", "items": [{"a": "b"}]}])
    )

    assert found == []


# ---------------------------------------------------------------------------
# The difference against what is registered
# ---------------------------------------------------------------------------


def gpo(machine: str = "", user: str = "") -> dict[str, Any]:
    return {"machine_extensions": machine or None, "user_extensions": user or None}


def built(machine: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"machine": machine, "user": user if user is not None else half()}


def test_content_without_its_extension_is_missing() -> None:
    found = report.registration_differences(
        gpo(), built(half(registry=[{"key": "Software", "values": []}]))
    )

    assert found["machine"]["missing"] == [[cse.REGISTRY_CSE, cse.REGISTRY_TOOL]]
    assert found["machine"]["surplus"] == []


def test_the_case_the_whole_half_comparison_misses() -> None:
    """Security content, registry extension registered. The old check sees
    content and a registration and calls it fine; the client applies nothing."""
    registered = f"[{cse.braced(cse.REGISTRY_CSE)}{cse.braced(cse.REGISTRY_TOOL)}]"
    found = report.registration_differences(
        gpo(machine=registered), built(half(security={"System Access": {}}))
    )

    assert found["machine"]["missing"] == [[cse.SECURITY_CSE, cse.SECURITY_TOOL]]
    assert found["machine"]["surplus"] == [[cse.braced(cse.REGISTRY_CSE)]]


def test_an_extension_windows_keeps_is_not_surplus() -> None:
    """Clearing the last security setting leaves the pair registered and an
    empty section behind. Removing it would undo what GPMC does on purpose."""
    registered = f"[{cse.braced(cse.SECURITY_CSE)}{cse.braced(cse.SECURITY_TOOL)}]"
    found = report.registration_differences(gpo(machine=registered), built(half()))

    assert found["machine"]["surplus"] == []


def test_a_matching_policy_needs_no_change() -> None:
    registered = f"[{cse.braced(cse.REGISTRY_CSE)}{cse.braced(cse.REGISTRY_TOOL)}]"
    found = report.registration_differences(
        gpo(machine=registered), built(half(registry=[{"key": "Software", "values": []}]))
    )

    assert found["machine"] == {"missing": [], "surplus": []}
    assert found["user"] == {"missing": [], "surplus": []}

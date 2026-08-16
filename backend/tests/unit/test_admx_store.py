"""Choosing a language, deciding when the cache is stale, and what may be
written into the central store."""

from __future__ import annotations

import pytest

from samadcon.gpo.admx import store

# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------


def test_the_language_that_was_asked_for_wins():
    assert store.choose_language(["en-US", "de-DE", "fr-FR"], "de-DE") == "de-DE"


def test_the_choice_ignores_case():
    """Directory names on SYSVOL are written however the installer felt."""
    assert store.choose_language(["EN-us", "DE-de"], "de-DE") == "DE-de"


def test_another_region_of_the_same_language_will_do():
    """de-AT is the same text as de-DE but for a handful of places."""
    assert store.choose_language(["en-US", "de-AT"], "de-DE") == "de-AT"


def test_english_is_the_last_resort():
    """Every template ships it."""
    assert store.choose_language(["en-US", "fr-FR"], "de-DE") == "en-US"


def test_a_tree_in_the_wrong_language_beats_one_with_no_labels():
    assert store.choose_language(["fr-FR", "it-IT"], "de-DE") == "fr-FR"


def test_without_a_wish_english_is_taken():
    assert store.choose_language(["de-DE", "en-US"], None) == "en-US"


def test_nothing_installed_is_no_language():
    assert store.choose_language([], "de-DE") is None


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def entry(name: str, *, size: int = 100, changed: str | None = "t0", directory: bool = False):
    return {
        "name": name,
        "path": f"store\\{name}",
        "size": size,
        "changed": changed,
        "is_directory": directory,
    }


def test_the_same_directory_gives_the_same_fingerprint():
    entries = [entry("windows.admx"), entry("de-DE", directory=True)]
    assert store._fingerprint(entries, "de-DE") == store._fingerprint(entries, "de-DE")


def test_the_order_of_the_listing_does_not_matter():
    """SMB does not promise one."""
    first = [entry("a.admx"), entry("b.admx")]
    second = [entry("b.admx"), entry("a.admx")]
    assert store._fingerprint(first, "en-US") == store._fingerprint(second, "en-US")


def test_a_changed_size_invalidates():
    before = [entry("windows.admx", size=100)]
    after = [entry("windows.admx", size=120)]
    assert store._fingerprint(before, "en-US") != store._fingerprint(after, "en-US")


def test_a_changed_timestamp_invalidates():
    """An edit that keeps the size would slip past otherwise."""
    before = [entry("windows.admx", changed="t0")]
    after = [entry("windows.admx", changed="t1")]
    assert store._fingerprint(before, "en-US") != store._fingerprint(after, "en-US")


def test_a_new_template_invalidates():
    before = [entry("windows.admx")]
    after = [entry("windows.admx"), entry("example.admx")]
    assert store._fingerprint(before, "en-US") != store._fingerprint(after, "en-US")


def test_a_different_language_is_a_different_cache_entry():
    entries = [entry("windows.admx")]
    assert store._fingerprint(entries, "de-DE") != store._fingerprint(entries, "en-US")


def test_forgetting_one_domain_leaves_the_others():
    store.forget()
    store._CACHE[("example.lan", "en-us")] = store._Cached("x", None, None)  # type: ignore[arg-type]
    store._CACHE[("other.lan", "en-us")] = store._Cached("y", None, None)  # type: ignore[arg-type]

    store.forget("EXAMPLE.LAN")

    assert ("example.lan", "en-us") not in store._CACHE
    assert ("other.lan", "en-us") in store._CACHE
    store.forget()


# ---------------------------------------------------------------------------
# What may be written into the store
# ---------------------------------------------------------------------------


def test_a_template_goes_into_the_store_itself():
    assert store._safe_name("example.admx") == "example.admx"


def test_a_text_file_goes_into_its_language_directory():
    assert store._safe_name("de-DE/example.adml") == "de-DE\\example.adml"


def test_backslashes_are_accepted():
    """Packages are shipped as they came off a Windows machine."""
    assert store._safe_name("de-DE\\example.adml") == "de-DE\\example.adml"


@pytest.mark.parametrize(
    "name",
    [
        "../outside.admx",
        "de-DE/../../outside.adml",
        "/etc/passwd",
        "",
        "readme.txt",
        # A template one directory deep is not where one belongs, and a text
        # file at the root has no language.
        "de-DE/example.admx",
        "example.adml",
        "a/b/c/example.adml",
    ],
)
def test_anything_else_is_dropped(name):
    """This writes onto a share every domain member reads."""
    assert store._safe_name(name) is None


def test_the_suffix_is_matched_regardless_of_case():
    assert store._safe_name("Example.ADMX") == "Example.ADMX"
    assert store._safe_name("de-DE/Example.ADML") == "de-DE\\Example.ADML"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def test_the_store_sits_under_the_realm():
    assert store.store_path("example.lan") == "example.lan\\Policies\\PolicyDefinitions"

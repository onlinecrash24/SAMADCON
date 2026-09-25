"""Choosing a language, deciding when the cache is stale, and what may be
written into the central store."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from samadcon.core.errors import Conflict, InvalidRequest
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
        # An absolute path, dropped rather than turned into a relative one.
        "/example.admx",
        # A colon: a drive marker or an ADS selector on the share.
        "de-DE/ex:ploit.adml",
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


# ---------------------------------------------------------------------------
# Which language a template's text comes from
#
# The store settles on one language, but a template may not ship it. Samba's
# own templates exist in en-US and ru-RU only, so a German store — the normal
# state once Microsoft's German templates are installed — resolved every
# Microsoft label and none of Samba's, and the tree showed raw CAT_… ids.
# ---------------------------------------------------------------------------


def test_the_chosen_language_comes_first():
    assert store.language_order(["en-US", "de-DE", "ru-RU"], "de-DE")[0] == "de-DE"


def test_english_follows_the_chosen_one():
    """Not because it is English, but because every template ships it."""
    assert store.language_order(["ru-RU", "en-US", "de-DE"], "de-DE")[:2] == ["de-DE", "en-US"]


def test_every_installed_language_is_tried_before_giving_up():
    """A label in the wrong language beats a raw identifier."""
    assert set(store.language_order(["ru-RU", "fr-FR"], "de-DE")) == {"ru-RU", "fr-FR"}


def test_the_order_keeps_the_spelling_from_the_share():
    """Directory names are written however the installer felt."""
    assert store.language_order(["EN-us", "DE-de"], "de-DE") == ["DE-de", "EN-us"]


def test_no_language_is_named_twice():
    order = store.language_order(["en-US", "de-DE"], "en-US")
    assert order == ["en-US", "de-DE"]


class FakeShare:
    """Just enough of a SYSVOL connection for the text lookup."""

    def __init__(self, tree: dict[str, list[str]]):
        # language directory -> file names in it
        self.tree = tree
        self.listed: list[str] = []

    def listdir(self, path: str):
        self.listed.append(path)
        language = path.rsplit("\\", 1)[-1]
        return [
            {"name": name, "path": f"{path}\\{name}", "size": 1, "is_directory": False}
            for name in self.tree.get(language, [])
        ]


def test_a_template_without_the_chosen_language_falls_back():
    share = FakeShare({"de-DE": ["windows.adml"], "en-US": ["windows.adml", "samba.adml"]})
    texts = store._Texts(share, "base", ["de-DE", "en-US"], "de-DE")

    assert texts.find("windows.admx") == ("de-DE", "base\\de-DE\\windows.adml")
    assert texts.find("samba.admx") == ("en-US", "base\\en-US\\samba.adml")


def test_the_fallback_is_reported_as_such():
    share = FakeShare({"de-DE": [], "en-US": ["samba.adml"]})
    texts = store._Texts(share, "base", ["de-DE", "en-US"], "de-DE")

    language, _ = texts.find("samba.admx")
    assert texts.is_preferred(language) is False


def test_no_other_language_is_read_when_the_chosen_one_has_it():
    """Listing every language directory per template would cost a round trip
    each, for the case that almost never happens."""
    share = FakeShare({"de-DE": ["windows.adml"], "en-US": ["windows.adml"]})
    texts = store._Texts(share, "base", ["de-DE", "en-US"], "de-DE")

    texts.find("windows.admx")

    assert share.listed == ["base\\de-DE"]


def test_a_template_no_language_has_is_not_found():
    share = FakeShare({"en-US": ["windows.adml"]})
    texts = store._Texts(share, "base", ["en-US"], "en-US")

    assert texts.find("nothing.admx") is None


# ---------------------------------------------------------------------------
# Writing: templates the store already has
# ---------------------------------------------------------------------------

NS = 'xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"'
VALID_ADMX = (
    f"<policyDefinitions {NS}><policyNamespaces>"
    '<target prefix="s" namespace="Example.Search" /></policyNamespaces>'
    '<resources minRequiredRevision="1.0" /></policyDefinitions>'
).encode()
VALID_ADML = (
    f"<policyDefinitionResources {NS}><displayName /><description />"
    "<resources /></policyDefinitionResources>"
).encode()

BASE = "example.lan\\Policies\\PolicyDefinitions"


class StoreShare:
    """Enough of SYSVOL to write into: what is there, and what got written."""

    def __init__(self, present=(), busy: str | None = None):
        self.files = {f"{BASE}\\{name}": b"old" for name in present}
        self.written: list[str] = []
        self.busy = busy

    def exists(self, path: str) -> bool:
        return path in self.files

    def makedirs(self, path: str) -> None:
        pass

    def write(self, path: str, data: bytes) -> None:
        if self.busy and path.endswith(self.busy):
            raise Conflict("in use", code="file_in_use")
        self.files[path] = data
        self.written.append(path.rsplit("PolicyDefinitions\\", 1)[1])


@pytest.fixture
def conn():
    return SimpleNamespace(info=SimpleNamespace(dns_domain="example.lan"))


def installed(monkeypatch, share: StoreShare) -> StoreShare:
    monkeypatch.setattr(store.sysvol, "sysvol_for", lambda conn: share)
    return share


PACKAGE = {"Search.admx": VALID_ADMX, "de-DE/Search.adml": VALID_ADML, "en-US/Search.adml": VALID_ADML}


def test_by_default_one_template_already_there_refuses_the_lot(monkeypatch, conn):
    share = installed(monkeypatch, StoreShare(present=["Search.admx"]))
    with pytest.raises(Conflict) as caught:
        store.upload(conn, PACKAGE)
    assert caught.value.code == "template_exists"
    assert share.written == []


def test_skipping_adds_what_is_missing_and_leaves_the_rest(monkeypatch, conn):
    """A second import of Microsoft's package onto a store that has part of it."""
    share = installed(monkeypatch, StoreShare(present=["Search.admx"]))
    result = store.upload(conn, PACKAGE, existing="skip")
    assert result["skipped"] == ["Search.admx"]
    assert sorted(result["added"]) == ["de-DE\\Search.adml", "en-US\\Search.adml"]
    assert result["replaced"] == []
    assert share.files[f"{BASE}\\Search.admx"] == b"old"


def test_replacing_writes_over_what_is_there_and_says_so(monkeypatch, conn):
    share = installed(monkeypatch, StoreShare(present=["Search.admx"]))
    result = store.upload(conn, PACKAGE, existing="replace")
    assert result["replaced"] == ["Search.admx"]
    assert share.files[f"{BASE}\\Search.admx"] == VALID_ADMX


def test_overwrite_still_means_replace(monkeypatch, conn):
    """The bundled-templates endpoint passes overwrite, and keeps working."""
    installed(monkeypatch, StoreShare(present=["Search.admx"]))
    result = store.upload(conn, PACKAGE, overwrite=True)
    assert result["replaced"] == ["Search.admx"]


def test_everything_already_there_is_not_an_error_when_skipping(monkeypatch, conn):
    installed(monkeypatch, StoreShare(present=["Search.admx", "de-DE\\Search.adml", "en-US\\Search.adml"]))
    result = store.upload(conn, PACKAGE, existing="skip")
    assert result["added"] == [] and result["replaced"] == []
    assert len(result["skipped"]) == 3


def test_an_unknown_way_is_refused_before_anything_is_touched(monkeypatch, conn):
    share = installed(monkeypatch, StoreShare())
    with pytest.raises(InvalidRequest) as caught:
        store.upload(conn, PACKAGE, existing="merge")
    assert caught.value.code == "invalid_mode"
    assert share.written == []


def test_a_write_cut_short_says_what_landed(monkeypatch, conn):
    """Checking first keeps bad files out; it cannot stop a lease half way."""
    installed(monkeypatch, StoreShare(busy="en-US\\Search.adml"))
    with pytest.raises(Conflict) as caught:
        store.upload(conn, PACKAGE)
    assert caught.value.code == "file_in_use"
    assert sorted(caught.value.context["written"]) == ["Search.admx", "de-DE\\Search.adml"]

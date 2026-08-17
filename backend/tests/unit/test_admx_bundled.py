"""Templates shipped inside the image.

The tree these read is produced by unpacking Debian's `samba` package, so the
shape is not ours to choose: the ``.admx`` files sit at the top and each
language has its own directory beside them. What is ours to choose is what
gets picked up out of it, and that is the same rule an upload goes through —
because both end on a share every domain member reads.
"""

from __future__ import annotations

from pathlib import Path

from samadcon.gpo.admx import store


def _samba_tree(root: Path) -> Path:
    """A directory laid out the way the samba package lays it out."""
    admx = root / "admx"
    (admx / "en-US").mkdir(parents=True)
    (admx / "ru-RU").mkdir(parents=True)
    (admx / "samba.admx").write_bytes(b"<policyDefinitions/>")
    (admx / "GNOME_Settings.admx").write_bytes(b"<policyDefinitions/>")
    (admx / "en-US" / "samba.adml").write_bytes(b"<policyDefinitionResources/>")
    (admx / "ru-RU" / "samba.adml").write_bytes(b"<policyDefinitionResources/>")
    return admx


def test_describe_lists_templates_and_languages(tmp_path: Path) -> None:
    admx = _samba_tree(tmp_path)

    described = store.bundled_describe(admx)

    assert described["present"] is True
    assert described["templates"] == ["GNOME_Settings.admx", "samba.admx"]
    assert described["languages"] == ["en-US", "ru-RU"]


def test_files_are_keyed_the_way_upload_expects(tmp_path: Path) -> None:
    """Language files carry their directory, and in the store's separator."""
    admx = _samba_tree(tmp_path)

    files = store.bundled_files(admx)

    assert set(files) == {
        "samba.admx",
        "GNOME_Settings.admx",
        "en-US\\samba.adml",
        "ru-RU\\samba.adml",
    }
    assert files["samba.admx"] == b"<policyDefinitions/>"


def test_a_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    """An image built without the templates says so rather than failing.

    The button that offers them is hidden on `present: False`, so this is the
    difference between a missing feature and a broken page.
    """
    described = store.bundled_describe(tmp_path / "nowhere")

    assert described["present"] is False
    assert described["templates"] == []
    assert store.bundled_files(tmp_path / "nowhere") == {}


def test_foreign_files_are_dropped_rather_than_reshaped(tmp_path: Path) -> None:
    """The package holds more than templates, and only templates may pass."""
    admx = _samba_tree(tmp_path)
    (admx / "README").write_bytes(b"not a template")
    (admx / "wscript_build").write_bytes(b"not a template either")
    # An .adml too deep is not a language directory, whatever it is named.
    (admx / "en-US" / "extra").mkdir()
    (admx / "en-US" / "extra" / "deep.adml").write_bytes(b"<policyDefinitionResources/>")

    files = store.bundled_files(admx)

    assert "README" not in files
    assert "wscript_build" not in files
    assert not any("deep.adml" in name for name in files)

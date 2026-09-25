"""Template packages, reshaped for the central store.

The member names below are the ones the three real routes produce: a folder
zipped on Windows, a folder picked in a browser, and Microsoft's MSI as
msiextract lays it out. The last one was taken from the Windows 11 25H2
package (v2.0), extracted on Debian trixie with msitools 0.106.
"""

from __future__ import annotations

import io
import subprocess
import zipfile
from pathlib import Path

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo.admx import package, store

ADMX = b"<policyDefinitions/>"
ADML = b"<policyDefinitionResources/>"

MSI_ROOT = "Program Files/Microsoft Group Policy/Windows 11 Oct 2025 Update (25H2)/PolicyDefinitions"


def members(root: str, languages: tuple[str, ...] = ("en-US", "de-de", "fr-fr")) -> dict[str, bytes]:
    prefix = f"{root}/" if root else ""
    found = {f"{prefix}Search.admx": ADMX, f"{prefix}WinLogon.admx": ADMX}
    for language in languages:
        found[f"{prefix}{language}/Search.adml"] = ADML
        found[f"{prefix}{language}/WinLogon.adml"] = ADML
    return found


# ---------------------------------------------------------------------------
# Language directories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("de-de", "de-DE"),
        ("en-US", "en-US"),
        ("zh-tw", "zh-TW"),
        ("PT-BR", "pt-BR"),
        # Not language-region: left alone rather than guessed at.
        ("sr-Latn-RS", "sr-Latn-RS"),
        ("Deutsch", "Deutsch"),
        ("de-1", "de-1"),
    ],
)
def test_a_language_is_spelled_as_windows_spells_it(given, expected):
    assert package.canonical_language(given) == expected


# ---------------------------------------------------------------------------
# Finding the templates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "root",
    [
        "",
        # The folder zipped with "Send to > Compressed folder", or picked in a
        # browser: the folder's own name comes first.
        "PolicyDefinitions",
        # Microsoft's MSI, as msiextract lays it out.
        MSI_ROOT,
    ],
)
def test_every_route_arrives_in_the_same_shape(root):
    shaped = package.reshape(members(root))
    assert sorted(shaped.files) == [
        "Search.admx",
        "WinLogon.admx",
        "de-DE/Search.adml",
        "de-DE/WinLogon.adml",
        "en-US/Search.adml",
        "en-US/WinLogon.adml",
        "fr-FR/Search.adml",
        "fr-FR/WinLogon.adml",
    ]


def test_what_comes_out_passes_the_stores_own_gate():
    """This module reshapes; it must not become a way around the store's rule."""
    shaped = package.reshape(members(MSI_ROOT))
    for name in shaped.files:
        assert store._safe_name(name) is not None, name


def test_backslashes_are_read_as_separators():
    shaped = package.reshape({"PolicyDefinitions\\Search.admx": ADMX, "PolicyDefinitions\\de-de\\Search.adml": ADML})
    assert sorted(shaped.files) == ["Search.admx", "de-DE/Search.adml"]


def test_text_files_alone_are_a_language_added_later():
    shaped = package.reshape({"PolicyDefinitions/it-it/Search.adml": ADML})
    assert list(shaped.files) == ["it-IT/Search.adml"]


def test_two_folders_of_templates_are_not_merged():
    """Two releases in one ZIP: which one wins would be an accident."""
    found = members("Windows 10/PolicyDefinitions")
    found.update(members("Windows 11/PolicyDefinitions"))
    with pytest.raises(InvalidRequest) as caught:
        package.reshape(found)
    assert caught.value.code == "ambiguous_package"


def test_a_package_without_templates_is_refused():
    with pytest.raises(InvalidRequest) as caught:
        package.reshape({"readme.txt": b"hello"})
    assert caught.value.code == "no_templates"


@pytest.mark.parametrize(
    "name",
    [
        "../Search.admx",
        "PolicyDefinitions/../../Search.adml",
        "/etc/Search.admx",
        "PolicyDefinitions/de-de/ex:ploit.adml",
    ],
)
def test_a_name_that_climbs_or_points_elsewhere_is_left_out(name):
    found = members("PolicyDefinitions")
    found[name] = ADMX
    shaped = package.reshape(found)
    assert all(".." not in key and ":" not in key for key in shaped.files)
    assert shaped.ignored == 1


def test_anything_beside_the_templates_is_counted_and_left_out():
    found = members("PolicyDefinitions")
    found["PolicyDefinitions/readme.txt"] = b"x"
    found["PolicyDefinitions/de-de/nested/Search.adml"] = ADML
    found["Other/fr-fr/Search.adml"] = ADML
    shaped = package.reshape(found)
    assert shaped.ignored == 3
    assert "de-DE/nested/Search.adml" not in shaped.files


# ---------------------------------------------------------------------------
# Choosing the languages
# ---------------------------------------------------------------------------


def test_only_the_chosen_languages_are_taken():
    shaped = package.reshape(members(MSI_ROOT), ["de-DE", "en-US"])
    assert sorted(name for name in shaped.files if name.endswith(".adml")) == [
        "de-DE/Search.adml",
        "de-DE/WinLogon.adml",
        "en-US/Search.adml",
        "en-US/WinLogon.adml",
    ]
    assert shaped.languages == ["de-DE", "en-US", "fr-FR"]
    assert shaped.imported_languages == ["de-DE", "en-US"]


def test_the_choice_ignores_how_the_package_spells_it():
    shaped = package.reshape(members(MSI_ROOT), ["DE-de"])
    assert shaped.imported_languages == ["de-DE"]


def test_the_templates_come_along_whatever_the_choice():
    """Text without definitions describes nothing; definitions without text still work."""
    shaped = package.reshape(members(MSI_ROOT), [])
    assert sorted(shaped.files) == ["Search.admx", "WinLogon.admx"]


def test_a_language_the_package_lacks_is_reported():
    shaped = package.reshape(members(MSI_ROOT), ["de-DE", "it-IT"])
    assert shaped.missing_languages == ["it-IT"]


def test_no_choice_takes_every_language():
    shaped = package.reshape(members(MSI_ROOT))
    assert shaped.imported_languages == ["de-DE", "en-US", "fr-FR"]
    assert shaped.missing_languages == []


def test_a_generator_of_languages_is_read_once_and_used_twice():
    shaped = package.reshape(members(MSI_ROOT), (item for item in ["de-DE", "it-IT"]))
    assert shaped.imported_languages == ["de-DE"]
    assert shaped.missing_languages == ["it-IT"]


# ---------------------------------------------------------------------------
# ZIP
# ---------------------------------------------------------------------------


def zipped(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_a_zip_yields_its_templates_and_nothing_else():
    data = zipped({**members("PolicyDefinitions"), "PolicyDefinitions/readme.txt": b"x"})
    unpacked = package.unpack_zip(data)
    assert "PolicyDefinitions/readme.txt" not in unpacked
    assert "PolicyDefinitions/de-de/Search.adml" in unpacked


def test_a_zip_is_bounded_before_it_is_inflated(monkeypatch):
    monkeypatch.setattr(package, "MAX_UNPACKED_BYTES", 10)
    with pytest.raises(InvalidRequest) as caught:
        package.unpack_zip(zipped(members("PolicyDefinitions")))
    assert caught.value.code == "upload_too_large"


def test_something_that_is_not_a_zip_is_refused():
    with pytest.raises(InvalidRequest) as caught:
        package.unpack_zip(b"PK\x03\x04 but not really")
    assert caught.value.code == "invalid_package"


# ---------------------------------------------------------------------------
# MSI
# ---------------------------------------------------------------------------


MSI_BYTES = package._MSI_MAGIC + b"rest of an OLE compound file"


def fake_msiextract(monkeypatch, layout: dict[str, bytes], *, fail: bool = False):
    """Stand in for msiextract: write ``layout`` under the -C directory."""
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        if fail:
            raise subprocess.CalledProcessError(1, command, stderr=b"not an MSI")
        target = Path(command[command.index("-C") + 1])
        for name, data in layout.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(package.shutil, "which", lambda name: "/usr/bin/msiextract")
    monkeypatch.setattr(package.subprocess, "run", run)
    return calls


def test_an_msi_is_unpacked_to_the_same_shape(monkeypatch):
    layout = members(MSI_ROOT)
    layout["Program Files/Microsoft Group Policy/Windows 11 Oct 2025 Update (25H2)/readme.rtf"] = b"x"
    calls = fake_msiextract(monkeypatch, layout)

    shaped = package.open_package([("Administrative Templates.msi", MSI_BYTES)], ["de-DE", "en-US"])

    assert calls and calls[0][0] == "/usr/bin/msiextract"
    assert sorted(shaped.files) == [
        "Search.admx",
        "WinLogon.admx",
        "de-DE/Search.adml",
        "de-DE/WinLogon.adml",
        "en-US/Search.adml",
        "en-US/WinLogon.adml",
    ]


def test_an_msi_is_recognised_by_its_bytes_not_its_name(monkeypatch):
    fake_msiextract(monkeypatch, members(MSI_ROOT))
    shaped = package.open_package([("download", MSI_BYTES)])
    assert "Search.admx" in shaped.files


def test_without_msiextract_an_msi_is_refused_with_the_way_around(monkeypatch):
    monkeypatch.setattr(package.shutil, "which", lambda name: None)
    with pytest.raises(InvalidRequest) as caught:
        package.open_package([("templates.msi", MSI_BYTES)])
    assert caught.value.code == "msi_unsupported"
    assert "PolicyDefinitions" in (caught.value.hint or "")


def test_an_msi_msiextract_cannot_read_is_refused(monkeypatch):
    fake_msiextract(monkeypatch, {}, fail=True)
    with pytest.raises(InvalidRequest) as caught:
        package.open_package([("templates.msi", MSI_BYTES)])
    assert caught.value.code == "invalid_package"


# ---------------------------------------------------------------------------
# Mixed uploads
# ---------------------------------------------------------------------------


def test_a_browser_folder_upload_is_many_single_files():
    uploads = list(members("PolicyDefinitions").items())
    shaped = package.open_package(uploads, ["de-DE"])
    assert "de-DE/Search.adml" in shaped.files
    assert "fr-FR/Search.adml" not in shaped.files


def test_a_zip_is_recognised_by_its_bytes_not_its_name():
    shaped = package.open_package([("templates.bin", zipped(members("PolicyDefinitions")))])
    assert "Search.admx" in shaped.files

"""Finding the parts of a policy on a share.

Names on SYSVOL come in whatever case the tool that created them used: Samba's
provisioning writes MACHINE and USER, Windows writes Machine and User. Whether
a share hides that difference is a server setting, so the report matches on a
listing instead of relying on it.
"""

from __future__ import annotations

from samadcon.gpo import report


def entry(path: str, *, directory: bool = False) -> dict:
    return {
        "name": path.rsplit("\\", 1)[-1],
        "path": path,
        "is_directory": directory,
        "size": 0,
    }


# ---------------------------------------------------------------------------
# Matching a child by name
# ---------------------------------------------------------------------------


def test_a_child_is_found_by_name():
    entries = [entry("policy\\Machine", directory=True), entry("policy\\User", directory=True)]
    assert report._match(entries, "Machine") == "policy\\Machine"


def test_a_child_written_in_upper_case_is_still_found():
    """Which is how Samba's own provisioning writes it."""
    entries = [entry("policy\\MACHINE", directory=True), entry("policy\\USER", directory=True)]

    assert report._match(entries, "Machine") == "policy\\MACHINE"
    assert report._match(entries, "User") == "policy\\USER"


def test_a_child_that_is_not_there_is_not_found():
    assert report._match([entry("policy\\GPT.INI")], "Machine") is None
    assert report._match([], "Machine") is None


# ---------------------------------------------------------------------------
# Finding a file inside a half
# ---------------------------------------------------------------------------

FILES = [
    "policy\\MACHINE\\Registry.pol",
    "policy\\MACHINE\\Microsoft\\Windows NT\\SecEdit\\GptTmpl.inf",
    "policy\\MACHINE\\Scripts\\scripts.ini",
    "policy\\MACHINE\\Preferences\\Drives\\Drives.xml",
    "policy\\MACHINE\\VGP\\VTLA\\Unix\\Sudo\\manifest.xml",
    "policy\\MACHINE\\Something\\else.dat",
]


def test_a_file_is_found_regardless_of_case():
    assert report._find(FILES, "policy\\MACHINE", "Registry.pol") == FILES[0]
    assert report._find(FILES, "policy\\machine", "registry.pol") == FILES[0]


def test_a_nested_file_is_found_by_its_relative_path():
    """The path has a space in it and mixed case, both of which are normal."""
    assert report._find(FILES, "policy\\MACHINE", report.SECEDIT_PATH) == FILES[1]


def test_a_file_that_is_not_there_is_not_found():
    assert report._find(FILES, "policy\\MACHINE", "Nothing.pol") is None


def test_a_partial_match_is_not_a_match():
    """Registry.pol.bak is a different file."""
    assert report._find(["policy\\MACHINE\\Registry.pol.bak"], "policy\\MACHINE", "Registry.pol") is None


# ---------------------------------------------------------------------------
# Files below a directory
# ---------------------------------------------------------------------------


def test_files_under_a_directory_are_collected():
    found = report._under(FILES, "policy\\MACHINE", "Preferences")
    assert found == ["policy\\MACHINE\\Preferences\\Drives\\Drives.xml"]


def test_the_directory_name_is_matched_without_regard_to_case():
    found = report._under(FILES, "policy\\machine", "preferences")
    assert len(found) == 1


def test_a_directory_with_nothing_in_it_yields_nothing():
    assert report._under(FILES, "policy\\MACHINE", "Nowhere") == []


def test_a_similarly_named_directory_is_not_included():
    """PreferencesOld is not Preferences."""
    files = ["policy\\MACHINE\\PreferencesOld\\x.xml"]
    assert report._under(files, "policy\\MACHINE", "Preferences") == []


# ---------------------------------------------------------------------------
# Emptiness
# ---------------------------------------------------------------------------


def test_a_half_with_nothing_in_it_reports_as_empty():
    assert report._has_content(report._empty_half()) is False


def test_an_unrecognised_file_alone_makes_a_half_non_empty():
    """Otherwise a policy full of files we cannot parse reads as empty."""
    half = report._empty_half()
    half["other_files"] = [{"path": "policy\\MACHINE\\odd.dat", "name": "odd.dat"}]
    assert report._has_content(half) is True


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def test_the_html_escapes_what_came_off_the_share():
    """A share more accounts can write to than one might assume."""
    gpo = {
        "display_name": "<script>alert(1)</script>",
        "guid": "{A}",
        "path": "\\\\x\\sysvol\\y",
        "machine_version": 0,
        "user_version": 0,
        "machine_enabled": True,
        "user_enabled": True,
    }
    html = report.to_html(
        {
            "gpo": gpo,
            "machine": report._empty_half(),
            "user": report._empty_half(),
            "unreadable": [],
            "empty": True,
        }
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_html_says_when_a_policy_is_empty():
    html = report.to_html(
        {
            "gpo": {
                "display_name": "Test",
                "guid": "{A}",
                "path": "",
                "machine_version": 0,
                "user_version": 0,
                "machine_enabled": True,
                "user_enabled": True,
            },
            "machine": report._empty_half(),
            "user": report._empty_half(),
            "unreadable": [],
            "empty": True,
        }
    )
    assert "holds no settings" in html


# ---------------------------------------------------------------------------
# Samba policy manifests
#
# Read with their own reader rather than the generic one used for preferences.
# That walks the root's children, and a manifest has exactly one — the
# `policysetting` wrapper — so every Samba policy in a report showed the single
# line "policysetting", identically whether it held ten entries or none.
# ---------------------------------------------------------------------------

SYMLINK_MANIFEST = b"""<?xml version='1.0' encoding='UTF-8'?>
<vgppolicy>
  <policysetting>
    <version>1</version>
    <name>Symlink Policy</name>
    <description>Specifies symbolic link data</description>
    <data>
      <file_properties>
        <source>/tmp/source</source>
        <target>/tmp/target</target>
      </file_properties>
    </data>
  </policysetting>
</vgppolicy>"""

EMPTY_MANIFEST = b"""<?xml version='1.0' encoding='UTF-8'?>
<vgppolicy>
  <policysetting>
    <version>1</version>
    <name>Symlink Policy</name>
    <description>Specifies symbolic link data</description>
    <data />
  </policysetting>
</vgppolicy>"""


class OneFile:
    """A share holding a single file."""

    def __init__(self, raw: bytes):
        self.raw = raw

    def read(self, path: str) -> bytes:
        return self.raw


def read(raw: bytes):
    unreadable: list = []
    return report._read_vgp_manifest(OneFile(raw), "p\\manifest.xml", unreadable), unreadable


def test_the_policy_name_comes_from_the_manifest():
    manifest, _ = read(SYMLINK_MANIFEST)
    assert manifest["name"] == "Symlink Policy"


def test_entries_are_read_from_below_data():
    manifest, _ = read(SYMLINK_MANIFEST)
    assert [entry["element"] for entry in manifest["entries"]] == ["file_properties"]


def test_an_entry_carries_its_fields_as_text():
    """Manifests put the content in child text, not in attributes — which is
    the other half of why the generic reader showed nothing useful."""
    manifest, _ = read(SYMLINK_MANIFEST)
    assert manifest["entries"][0]["fields"] == [
        {"name": "source", "value": "/tmp/source"},
        {"name": "target", "value": "/tmp/target"},
    ]


def test_an_emptied_manifest_holds_no_entries():
    """What samba-tool leaves behind: cmd_remove_symlink drops the element and
    writes the file back, it never deletes it."""
    manifest, unreadable = read(EMPTY_MANIFEST)
    assert manifest["entries"] == []
    assert manifest["name"] == "Symlink Policy"
    assert unreadable == []


def test_xml_that_is_not_a_manifest_is_reported_unreadable():
    """Rather than as empty: the file is there and says something we did not
    understand, which is not the same as saying nothing."""
    manifest, unreadable = read(b"<vgppolicy><something-else /></vgppolicy>")
    assert manifest is None
    assert len(unreadable) == 1


def test_an_emptied_manifest_does_not_make_a_policy_look_configured():
    half = report._empty_half()
    half["vgp"] = [{"path": "p", "name": "Symlink Policy", "description": "", "entries": []}]

    # Still shown — the file exists and hiding it would lose a fact.
    assert report._has_content(half) is True
    # But it reaches no client, so the report must not call the policy filled.
    assert report._applies_anything(half) is False


def test_a_manifest_with_entries_counts_as_configured():
    half = report._empty_half()
    half["vgp"] = [
        {"path": "p", "name": "Symlink Policy", "description": "", "entries": [{"element": "x"}]}
    ]
    assert report._applies_anything(half) is True

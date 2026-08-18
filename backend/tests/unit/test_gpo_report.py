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


# ---------------------------------------------------------------------------
# GptTmpl.inf
# ---------------------------------------------------------------------------


class OneText:
    """A share holding a single text file."""

    def __init__(self, text: str):
        self.text = text

    def read_text(self, path: str) -> str:
        return self.text


BARE_TEMPLATE = """[Unicode]
Unicode=yes
[Version]
signature="$CHICAGO$"
Revision=1
"""

WITH_POLICY = BARE_TEMPLATE + """[System Access]
MinimumPasswordLength=14
"""


def sections(text: str):
    return report._read_ini_sections(OneText(text), "GptTmpl.inf", [])


def test_the_header_sections_are_not_settings():
    """Every tool writes them, and they configure nothing. Reported as
    settings, a template holding no policy looked like one holding two."""
    assert sections(BARE_TEMPLATE) == {}


def test_real_sections_survive_the_filter():
    assert sections(WITH_POLICY) == {
        "System Access": [{"name": "MinimumPasswordLength", "value": "14"}]
    }


def test_a_template_with_only_headers_leaves_the_half_empty():
    half = report._empty_half()
    half["security"] = sections(BARE_TEMPLATE)
    assert report._applies_anything(half) is False


# ---------------------------------------------------------------------------
# Content against registration
#
# Two silent failure modes, opposite directions. Neither shows up anywhere in
# the directory, which is why cse.py opens by saying a policy written without
# its extension "applies nowhere, and nothing reports it".
# ---------------------------------------------------------------------------


def gpo(*, machine: str = "", user: str = "") -> dict:
    return {"machine_extensions": machine or None, "user_extensions": user or None}


def built(*, machine=None, user=None) -> dict:
    report_ = {"machine": report._empty_half(), "user": report._empty_half()}
    if machine:
        report_["machine"].update(machine)
    if user:
        report_["user"].update(user)
    return report_


def test_settings_without_a_registration_are_reported():
    problems = report.registration_problems(
        gpo(), built(machine={"registry": [{"key": "K", "value_name": "V"}]})
    )
    assert problems == ["machine_content_without_extension"]


def test_a_registration_without_settings_is_reported():
    problems = report.registration_problems(gpo(machine="[{35378EAC-...}]"), built())
    assert problems == ["machine_extension_without_content"]


def test_the_two_halves_are_judged_separately():
    problems = report.registration_problems(
        gpo(user="[{25537BA6-...}]"),
        built(machine={"registry": [{"key": "K", "value_name": "V"}]}),
    )
    assert problems == [
        "machine_content_without_extension",
        "user_extension_without_content",
    ]


def test_agreement_raises_nothing():
    assert (
        report.registration_problems(
            gpo(machine="[{35378EAC-...}]"),
            built(machine={"registry": [{"key": "K", "value_name": "V"}]}),
        )
        == []
    )


def test_an_empty_policy_with_no_registration_is_fine():
    """The ordinary state of a GPO nobody has filled in yet."""
    assert report.registration_problems(gpo(), built()) == []


def test_an_unrecognised_file_does_not_claim_a_client_would_apply_it():
    """It was not parsed, so there is no ground to say it reaches anyone —
    and the finding would name a fault nobody can act on."""
    other = {"other_files": [{"path": "p\\odd.dat", "name": "odd.dat"}]}
    assert report.registration_problems(gpo(), built(machine=other)) == []


def test_an_emptied_samba_manifest_does_not_hold_a_registration_open():
    """The residue samba-tool leaves behind is not content."""
    manifest = {"vgp": [{"path": "p", "name": "Symlink Policy", "description": "", "entries": []}]}
    problems = report.registration_problems(gpo(machine="[{35378EAC-...}]"), built(machine=manifest))
    assert problems == ["machine_extension_without_content"]


def test_an_extension_windows_keeps_is_not_reported_as_stale():
    """GPMC leaves the security pair registered when the last setting goes,
    together with an empty [Registry Values] section. Verified on a throwaway
    GPO: password policy set, then removed, and the pair stayed. Flagging that
    would report a state GPMC produces on purpose."""
    problems = report.registration_problems(
        gpo(machine="[{827D319E-6EAC-11D2-A4EA-00C04F79F83A}"
                    "{803E14A0-B4FB-11D0-A0D0-00A0C90F574B}]"),
        built(),
    )
    assert problems == []


def test_folder_redirection_is_treated_as_kept_until_established():
    """Nothing has shown Windows clears it. Treating an unverified extension as
    kept costs a finding we might have raised; the other way round would flag a
    healthy policy."""
    problems = report.registration_problems(
        gpo(user="[{25537BA6-77A8-11D2-9B6C-0000F8080861}"
                 "{88E729D6-BDC1-11D1-BD2A-00C04FB9603F}]"),
        built(),
    )
    assert problems == []


def test_a_kept_extension_does_not_mask_a_stale_one_beside_it():
    machine = (
        "[{35378EAC-683F-11D2-A89A-00C04FBBCFA2}{D02B1F72-3407-48AE-BA88-E8213C6761F1}]"
        "[{827D319E-6EAC-11D2-A4EA-00C04F79F83A}{803E14A0-B4FB-11D0-A0D0-00A0C90F574B}]"
    )
    problems = report.registration_problems(gpo(machine=machine), built())
    assert problems == ["machine_extension_without_content"]


def test_scripts_are_reported_because_windows_clears_them():
    """Verified the same way: startup script set, then removed, and
    gPCMachineExtensionNames came back as a single space."""
    problems = report.registration_problems(
        gpo(machine="[{42B5FAAE-6536-11D2-AE5A-0000F87571E3}"
                    "{40B6664F-4972-11D1-A7CA-0000F87571E3}]"),
        built(),
    )
    assert problems == ["machine_extension_without_content"]

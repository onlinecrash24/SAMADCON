"""Administrative templates against a live domain controller.

The unit tests cover the parsing and the value mapping. What only a real
domain can show is whether a setting written here comes back out of SYSVOL
the same way — and whether the extension that makes a client read it is
registered, which is the part that fails silently.

The tests install their own template rather than relying on the domain having
one: a Samba domain usually has no central store at all.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.integration

# A template of our own, small enough to read in one screen and shaped like a
# real one: a category under a namespace, a policy with a value of its own and
# three elements of different kinds.
TEMPLATE_ADMX = """<?xml version="1.0" encoding="utf-8"?>
<policyDefinitions revision="1.0" schemaVersion="1.0"
    xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
  <policyNamespaces>
    <target prefix="samcon" namespace="SAMCON.Test.Policies" />
  </policyNamespaces>
  <resources minRequiredRevision="1.0" />
  <supportedOn>
    <definitions>
      <definition name="SUPPORTED_Any" displayName="$(string.SUPPORTED_Any)" />
    </definitions>
  </supportedOn>
  <categories>
    <category name="SamconTest" displayName="$(string.SamconTest)" />
  </categories>
  <policies>
    <policy name="TestSetting" class="Machine" displayName="$(string.TestSetting)"
            explainText="$(string.TestSetting_Help)" presentation="$(presentation.TestSetting)"
            key="Software\\Policies\\SAMCON\\Test" valueName="Enabled">
      <parentCategory ref="SamconTest" />
      <supportedOn ref="samcon:SUPPORTED_Any" />
      <elements>
        <decimal id="Interval" valueName="Interval" minValue="1" maxValue="24" />
        <text id="Server" valueName="Server" maxLength="64" />
        <boolean id="Verbose" valueName="Verbose">
          <trueValue><decimal value="1" /></trueValue>
          <falseValue><delete /></falseValue>
        </boolean>
      </elements>
    </policy>
  </policies>
</policyDefinitions>
"""

# The order of the three children below is fixed by the schema, and Windows
# enforces it: <displayName>, <description>, then <resources>. Leave one out
# and Windows abandons every administrative template in the store, not just
# this one — the same failure mode as a missing <resources> in an .admx.
TEMPLATE_ADML = """<?xml version="1.0" encoding="utf-8"?>
<policyDefinitionResources revision="1.0" schemaVersion="1.0"
    xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
  <displayName>SAMCON test settings</displayName>
  <description>Administrative template used by the SAMCON integration tests.</description>
  <resources>
    <stringTable>
      <string id="SamconTest">SAMCON test settings</string>
      <string id="TestSetting">A setting for the integration tests</string>
      <string id="TestSetting_Help">Exists only so the tests have something to write.</string>
      <string id="SUPPORTED_Any">Any version</string>
    </stringTable>
    <presentationTable>
      <presentation id="TestSetting">
        <decimalTextBox refId="Interval" defaultValue="4">Interval</decimalTextBox>
        <textBox refId="Server"><label>Server</label></textBox>
        <checkBox refId="Verbose">Verbose</checkBox>
      </presentation>
    </presentationTable>
  </resources>
</policyDefinitionResources>
"""

# The same text file in German. The policy tree is written in whatever
# language directory the store holds; the definitions carry no text of their
# own, only references into these.
TEMPLATE_ADML_DE = (
    TEMPLATE_ADML.replace(
        "<displayName>SAMCON test settings</displayName>",
        "<displayName>SAMCON-Testeinstellungen</displayName>",
    )
    .replace(
        '<string id="SamconTest">SAMCON test settings</string>',
        '<string id="SamconTest">SAMCON-Testeinstellungen</string>',
    )
    .replace(
        '<string id="TestSetting">A setting for the integration tests</string>',
        '<string id="TestSetting">Eine Einstellung für die Integrationstests</string>',
    )
)

POLICY_ID = "SAMCON.Test.Policies:TestSetting"
POLICY_KEY = "Software\\Policies\\SAMCON\\Test"
CATEGORY_ID = "SAMCON.Test.Policies:SamconTest"


def quoted(value: str) -> str:
    return quote(value, safe="")


def package() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("samcon-test.admx", TEMPLATE_ADMX)
        archive.writestr("en-US/samcon-test.adml", TEMPLATE_ADML)
        archive.writestr("de-DE/samcon-test.adml", TEMPLATE_ADML_DE)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def templates(api):
    """Our test template, installed in the domain's central store.

    Left there afterwards: removing templates is not something SAMCON offers,
    and one extra definition in a store is harmless — it describes a setting
    under a key nothing reads.
    """
    response = api.post(
        "/api/v1/admx/store?overwrite=true",
        files={"files": ("samcon-test.zip", package(), "application/zip")},
    )
    if response.status_code != 200:
        pytest.skip(f"cannot install a template: {response.text}")
    return response.json()


@pytest.fixture
def test_gpo(api, templates):
    response = api.post(
        "/api/v1/gpos", json={"display_name": f"SAMCON admx {uuid.uuid4().hex[:8]}"}
    )
    if response.status_code != 200:
        pytest.skip(f"cannot create a group policy: {response.text}")

    gpo = response.json()
    yield gpo
    api.delete(f"/api/v1/gpos?dn={quoted(gpo['dn'])}&force=true")


# ---------------------------------------------------------------------------
# The central store
# ---------------------------------------------------------------------------


def test_the_store_reports_what_is_installed(api, templates):
    described = api.get("/api/v1/admx/store").json()

    assert described["present"] is True
    assert "samcon-test.admx" in [item["name"] for item in described["templates"]]
    assert "en-US" in described["languages"]


def test_a_template_windows_cannot_read_never_reaches_the_store(api, templates):
    """The failure this prevents is domain-wide.

    Windows parses the central store as one. A single unreadable file makes it
    abandon *every* administrative template: the Group Policy report then
    shows one parser error where all the settings should be. Found the hard
    way — with a test template missing its <resources> element.
    """
    broken = TEMPLATE_ADMX.replace('<resources minRequiredRevision="1.0" />', "")

    response = api.post(
        "/api/v1/admx/store?overwrite=true",
        files={"files": ("samcon-broken.admx", broken.encode(), "text/xml")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_template"

    described = api.get("/api/v1/admx/store").json()
    assert "samcon-broken.admx" not in [item["name"] for item in described["templates"]]


def test_a_package_with_one_bad_file_leaves_nothing_behind(api, templates):
    """Half a package is its own domain-wide breakage.

    A definition written without the text file that belongs to it leaves
    Windows with unresolvable string references — the same abandoned store as
    a malformed file, arrived at from the other side. So the whole package is
    checked before any of it is written.
    """
    broken_adml = TEMPLATE_ADML.replace("<displayName>SAMCON test settings</displayName>", "")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("samcon-partial.admx", TEMPLATE_ADMX)
        archive.writestr("en-US/samcon-partial.adml", broken_adml)

    response = api.post(
        "/api/v1/admx/store?overwrite=true",
        files={"files": ("samcon-partial.zip", buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_template"

    described = api.get("/api/v1/admx/store").json()
    assert "samcon-partial.admx" not in [item["name"] for item in described["templates"]]


def test_the_installed_template_is_one_windows_can_read(api, templates):
    """Our own template, through the same check the upload applies."""
    described = api.get("/api/v1/admx/store").json()
    assert "samcon-test.admx" in [item["name"] for item in described["templates"]]


def test_a_template_lands_where_the_domain_expects_it(api, templates, domain):
    """Windows reads the same directory; a store somewhere else is invisible."""
    described = api.get("/api/v1/admx/store").json()
    assert described["path"] == f"{domain['dns_domain']}\\Policies\\PolicyDefinitions"


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


def test_the_installed_category_shows_up_in_the_tree(api, templates):
    tree = api.get("/api/v1/admx/tree?half=Machine").json()

    names = [item["display_name"] for item in tree["categories"]]
    assert "SAMCON test settings" in names, names


def test_the_setting_is_listed_under_its_category(api, templates):
    tree = api.get(f"/api/v1/admx/tree?half=Machine&category={quoted(CATEGORY_ID)}").json()

    assert [item["id"] for item in tree["policies"]] == [POLICY_ID]


def test_the_tree_is_written_in_the_language_that_was_asked_for(api, templates):
    """The definitions carry no text at all — every name in the tree comes from
    a language directory, so this is the whole of what "the editor in German"
    means.

    The reported language is the directory's own name, compared here without
    regard to case: a store that grew over time holds whatever spelling each
    upload used, and `de-de` is the same language as `de-DE`.
    """
    german = api.get(
        f"/api/v1/admx/tree?half=Machine&language=de-DE&category={quoted(CATEGORY_ID)}"
    ).json()
    assert german["language"].lower() == "de-de"
    assert [item["display_name"] for item in german["policies"]] == [
        "Eine Einstellung für die Integrationstests"
    ]

    english = api.get(
        f"/api/v1/admx/tree?half=Machine&language=en-US&category={quoted(CATEGORY_ID)}"
    ).json()
    assert english["language"].lower() == "en-us"
    assert [item["display_name"] for item in english["policies"]] == [
        "A setting for the integration tests"
    ]


def test_a_language_the_store_does_not_have_falls_back_and_says_so(api, templates):
    """A tree in a language nobody asked for beats one with no labels — but the
    answer names the language it actually used, so the editor can say why the
    console is German and the policies are not.

    The tag has to be one no vendor ships. A real store carries whatever
    Microsoft's package brought along, which is a few dozen languages — asking
    for French proves nothing.
    """
    listed = api.get("/api/v1/admx/tree?half=Machine&language=zz-ZZ").json()

    assert listed["language"].lower() == "en-us"


def test_the_setting_dialog_follows_the_same_language(api, templates):
    definition = api.get(f"/api/v1/admx/policy?id={quoted(POLICY_ID)}&language=de-DE").json()

    assert definition["display_name"] == "Eine Einstellung für die Integrationstests"


def test_a_setting_is_found_by_its_explanation(api, templates):
    """Nobody remembers what a setting is called."""
    found = api.get("/api/v1/admx/search?q=something to write&half=Machine").json()
    assert POLICY_ID in [item["id"] for item in found["policies"]]


def test_the_definition_carries_its_form(api, templates):
    definition = api.get(f"/api/v1/admx/policy?id={quoted(POLICY_ID)}").json()

    assert definition["key"] == POLICY_KEY
    assert [element["id"] for element in definition["elements"]] == [
        "Interval",
        "Server",
        "Verbose",
    ]
    assert [control["ref"] for control in definition["presentation"]] == [
        "Interval",
        "Server",
        "Verbose",
    ]
    # Resolved to its text, not left as the reference GPMC never shows.
    assert definition["supported_on"] == "Any version"

    # The editor fills an empty input with this when the setting is switched
    # on, the way GPMC does. Without it here the form stays blank and enabling
    # the policy writes no options at all.
    interval = next(item for item in definition["presentation"] if item["ref"] == "Interval")
    assert interval["default"] == "4"


# ---------------------------------------------------------------------------
# Writing a setting
# ---------------------------------------------------------------------------


def state_url(gpo: dict, half: str = "Machine") -> str:
    return f"/api/v1/admx/state?dn={quoted(gpo['dn'])}&id={quoted(POLICY_ID)}&half={half}"


def test_a_fresh_policy_has_the_setting_unconfigured(api, test_gpo):
    read = api.get(state_url(test_gpo)).json()

    assert read["state"] == "not_configured"
    assert read["values"] == {}
    assert read["version"] == 0


def test_a_setting_survives_the_round_trip(api, test_gpo):
    """Written into Registry.pol over SMB, and read back out of it."""
    applied = api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={
            "policy": POLICY_ID,
            "half": "Machine",
            "state": "enabled",
            "values": {"Interval": 8, "Server": "updates.example.lan", "Verbose": True},
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["changed"] is True

    read = api.get(state_url(test_gpo)).json()
    assert read["state"] == "enabled"
    assert read["values"] == {
        "Interval": 8,
        "Server": "updates.example.lan",
        "Verbose": True,
    }


def category_url(gpo: dict | None = None, half: str = "Machine") -> str:
    url = f"/api/v1/admx/tree?half={half}&category={quoted(CATEGORY_ID)}"
    return url + (f"&dn={quoted(gpo['dn'])}" if gpo else "")


def test_a_listing_without_a_gpo_says_nothing_about_state(api, templates):
    """Browsing the store is not asking about a policy; there is no state to
    report, and reporting "not configured" would be an answer we do not have."""
    listed = api.get(category_url()).json()["policies"]

    assert [item["id"] for item in listed] == [POLICY_ID]
    assert "state" not in listed[0]


def test_the_listing_carries_the_state_in_this_gpo(api, test_gpo):
    """The status column, and the reason it costs one request rather than one
    per row: the whole level is answered by a single read of Registry.pol."""
    before = api.get(category_url(test_gpo)).json()["policies"]
    assert [item["state"] for item in before] == ["not_configured"]

    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "Machine", "state": "enabled"},
    )

    after = api.get(category_url(test_gpo)).json()["policies"]
    assert [item["state"] for item in after] == ["enabled"]

    # And the same for the other half of the same GPO, which has nothing in it.
    assert api.get(category_url(test_gpo, half="User")).json()["policies"] == []


def test_a_search_result_carries_its_state_too(api, test_gpo):
    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "Machine", "state": "disabled"},
    )

    found = api.get(
        "/api/v1/admx/search?q=something to write&half=Machine"
        f"&dn={quoted(test_gpo['dn'])}"
    ).json()["policies"]

    assert [item["state"] for item in found if item["id"] == POLICY_ID] == ["disabled"]


def test_writing_a_setting_advances_the_version(api, test_gpo):
    """Windows re-reads a policy only when this number changes."""
    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "Machine", "state": "enabled"},
    )

    gpo = api.get(f"/api/v1/gpos/gpo?dn={quoted(test_gpo['dn'])}").json()
    assert gpo["version"] > 0
    assert gpo["machine_version"] > 0

    # And both halves still agree, which is what clients compare.
    status = api.get(f"/api/v1/gpos/status?dn={quoted(test_gpo['dn'])}").json()
    assert status["consistent"] is True, status["problems"]


def test_writing_registers_the_extension_that_applies_it(api, test_gpo):
    """The part that fails silently: values written, extension unregistered,
    policy visible everywhere and applied nowhere."""
    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "Machine", "state": "enabled"},
    )

    gpo = api.get(f"/api/v1/gpos/gpo?dn={quoted(test_gpo['dn'])}").json()
    extensions = (gpo["machine_extensions"] or "").upper()

    assert "35378EAC-683F-11D2-A89A-00C04FBBCFA2" in extensions
    # The tool GUID Windows writes beside it, so a policy made here looks like
    # one made by GPMC.
    assert "D02B1F72-3407-48AE-BA88-E8213C6761F1" in extensions


def test_writing_the_same_thing_twice_changes_nothing(api, test_gpo):
    """A write for nothing would make every client re-read the policy."""
    payload = {"policy": POLICY_ID, "half": "Machine", "state": "enabled", "values": {"Interval": 4}}
    api.post(f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}", json=payload)

    again = api.post(f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}", json=payload)

    assert again.status_code == 200, again.text
    assert again.json()["changed"] is False


def test_the_setting_shows_up_in_the_report(api, test_gpo):
    """The report reads the file back with a different parser than the editor."""
    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "Machine", "state": "enabled", "values": {"Interval": 8}},
    )

    report = api.get(f"/api/v1/gpos/report?dn={quoted(test_gpo['dn'])}").json()

    assert report["empty"] is False
    groups = {group["key"]: group for group in report["machine"]["registry"]}
    assert POLICY_KEY in groups, list(groups)
    values = {value["value"]: value["data"] for value in groups[POLICY_KEY]["values"]}
    assert values["Enabled"] == 1
    assert values["Interval"] == 8


# ---------------------------------------------------------------------------
# Switching off and back
# ---------------------------------------------------------------------------


def test_disabling_writes_the_off_value(api, test_gpo):
    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "Machine", "state": "enabled"},
    )
    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "Machine", "state": "disabled"},
    )

    assert api.get(state_url(test_gpo)).json()["state"] == "disabled"


def test_a_checkbox_switched_off_leaves_a_removal_marker(api, test_gpo):
    """Which is how a value already on a machine gets taken away again."""
    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={
            "policy": POLICY_ID,
            "half": "Machine",
            "state": "enabled",
            "values": {"Verbose": False},
        },
    )

    report = api.get(f"/api/v1/gpos/report?dn={quoted(test_gpo['dn'])}").json()
    group = next(item for item in report["machine"]["registry"] if item["key"] == POLICY_KEY)
    names = [value["value"] for value in group["values"]]

    assert "**del.Verbose" in names, names


def test_setting_it_back_to_not_configured_removes_everything_it_wrote(api, test_gpo):
    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={
            "policy": POLICY_ID,
            "half": "Machine",
            "state": "enabled",
            "values": {"Interval": 8, "Verbose": False},
        },
    )
    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "Machine", "state": "not_configured"},
    )

    assert api.get(state_url(test_gpo)).json()["state"] == "not_configured"

    report = api.get(f"/api/v1/gpos/report?dn={quoted(test_gpo['dn'])}").json()
    keys = [group["key"] for group in report["machine"]["registry"]]
    assert POLICY_KEY not in keys, keys


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_value_outside_its_range_is_refused_before_anything_is_written(api, test_gpo):
    response = api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={
            "policy": POLICY_ID,
            "half": "Machine",
            "state": "enabled",
            "values": {"Interval": 99},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "element_out_of_range"

    assert api.get(state_url(test_gpo)).json()["state"] == "not_configured"


def test_a_setting_cannot_be_written_into_the_wrong_half(api, test_gpo):
    response = api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "User", "state": "enabled"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "wrong_policy_half"


def test_a_setting_that_no_template_defines_is_refused(api, test_gpo):
    response = api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": "Nothing.At.All:Missing", "half": "Machine", "state": "enabled"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "policy_not_found"


def test_a_concurrent_change_is_refused(api, test_gpo):
    """Two administrators on the same policy must not overwrite each other."""
    read = api.get(state_url(test_gpo)).json()

    api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={"policy": POLICY_ID, "half": "Machine", "state": "enabled"},
    )

    response = api.post(
        f"/api/v1/admx/state?dn={quoted(test_gpo['dn'])}",
        json={
            "policy": POLICY_ID,
            "half": "Machine",
            "state": "disabled",
            "expected_version": read["version"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "gpo_version_conflict"


# ---------------------------------------------------------------------------
# The "only configured" filter
# ---------------------------------------------------------------------------


def enable_test_setting(api, gpo):
    return api.post(
        f"/api/v1/admx/state?dn={quoted(gpo['dn'])}",
        json={
            "policy": POLICY_ID,
            "half": "Machine",
            "state": "enabled",
            "values": {"Interval": 8, "Server": "updates.example.lan", "Verbose": True},
        },
    )


def tree(api, gpo, category=None, configured=False):
    url = f"/api/v1/admx/tree?half=Machine&dn={quoted(gpo['dn'])}"
    if category:
        url += f"&category={quoted(category)}"
    if configured:
        url += "&configured=true"
    return api.get(url).json()


def test_the_filter_leaves_only_the_branches_that_lead_somewhere(api, test_gpo):
    """The point of the filter is that a branch can be trusted to be empty.

    That cannot be decided in the browser: it holds one level, and a category
    worth showing may have its settings several levels further down.
    """
    unfiltered = tree(api, test_gpo)
    assert len(unfiltered["categories"]) > 0

    # Nothing configured yet, so nothing survives.
    assert tree(api, test_gpo, configured=True)["categories"] == []

    assert enable_test_setting(api, test_gpo).status_code == 200

    filtered = tree(api, test_gpo, configured=True)
    names = [item["display_name"] for item in filtered["categories"]]
    assert names == ["SAMCON test settings"], names
    # The count is what is configured below, not what the category holds.
    assert filtered["categories"][0]["policy_count"] == 1
    assert len(unfiltered["categories"]) > len(filtered["categories"])


def test_the_filter_also_trims_the_settings_beside_the_tree(api, test_gpo):
    enable_test_setting(api, test_gpo)

    listed = tree(api, test_gpo, category=CATEGORY_ID, configured=True)
    assert [item["id"] for item in listed["policies"]] == [POLICY_ID]
    assert all(item["state"] != "not_configured" for item in listed["policies"])


def test_without_a_policy_the_filter_changes_nothing(api, templates):
    """No GPO named, nothing to be configured *in* — the store is the store."""
    plain = api.get("/api/v1/admx/tree?half=Machine").json()
    asked = api.get("/api/v1/admx/tree?half=Machine&configured=true").json()

    assert [item["id"] for item in asked["categories"]] == [
        item["id"] for item in plain["categories"]
    ]

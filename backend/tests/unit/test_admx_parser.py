"""Parsing administrative templates.

The fixtures below are shaped like Microsoft's own files rather than minimised
to the attribute under test: the parts that go wrong in practice — namespace
prefixes, string references, elements that override their policy's key — only
appear together.
"""

from __future__ import annotations

import re

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo.admx import parser
from samadcon.gpo.admx.model import Catalogue

WINDOWS_ADMX = b"""<?xml version="1.0" encoding="utf-8"?>
<policyDefinitions revision="1.0" schemaVersion="1.0"
    xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
  <policyNamespaces>
    <target prefix="windows" namespace="Microsoft.Policies.Windows" />
  </policyNamespaces>
  <resources minRequiredRevision="1.0" />
  <supportedOn>
    <definitions>
      <definition name="SUPPORTED_Windows7" displayName="$(string.Windows7)" />
    </definitions>
  </supportedOn>
  <categories>
    <category name="System" displayName="$(string.System)" />
    <category name="Logon" displayName="$(string.Logon)">
      <parentCategory ref="System" />
    </category>
  </categories>
</policyDefinitions>
"""

WINDOWS_ADML = b"""<?xml version="1.0" encoding="utf-8"?>
<policyDefinitionResources revision="1.0" schemaVersion="1.0"
    xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
  <resources>
    <stringTable>
      <string id="System">System</string>
      <string id="Logon">Logon</string>
      <string id="Windows7">At least Windows 7</string>
    </stringTable>
  </resources>
</policyDefinitionResources>
"""

SAMPLE_ADMX = b"""<?xml version="1.0" encoding="utf-8"?>
<policyDefinitions revision="1.0" schemaVersion="1.0"
    xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
  <policyNamespaces>
    <target prefix="sample" namespace="Example.Policies.Sample" />
    <using prefix="windows" namespace="Microsoft.Policies.Windows" />
  </policyNamespaces>
  <resources minRequiredRevision="1.0" />
  <categories>
    <category name="Updates" displayName="$(string.Updates)">
      <parentCategory ref="windows:System" />
    </category>
  </categories>
  <policies>
    <policy name="AutoUpdate" class="Machine" displayName="$(string.AutoUpdate)"
            explainText="$(string.AutoUpdate_Help)" presentation="$(presentation.AutoUpdate)"
            key="Software\\Policies\\Example\\Update" valueName="NoAutoUpdate">
      <parentCategory ref="Updates" />
      <supportedOn ref="windows:SUPPORTED_Windows7" />
      <enabledValue><decimal value="1" /></enabledValue>
      <disabledValue><decimal value="0" /></disabledValue>
      <elements>
        <decimal id="Interval" valueName="Interval" minValue="1" maxValue="24" required="true" />
        <text id="Server" valueName="Server" maxLength="255" />
        <boolean id="Reboot" valueName="NoReboot">
          <trueValue><decimal value="1" /></trueValue>
          <falseValue><delete /></falseValue>
        </boolean>
        <enum id="Behaviour" valueName="AUOptions">
          <item displayName="$(string.Notify)"><value><decimal value="2" /></value></item>
          <item displayName="$(string.Install)"><value><decimal value="4" /></value></item>
        </enum>
        <list id="Exclusions" key="Software\\Policies\\Example\\Update\\Exclude"
              valuePrefix="Ex" explicitValue="false" additive="true" />
        <multiText id="Notes" valueName="Notes" />
      </elements>
    </policy>
    <policy name="UserSetting" displayName="$(string.UserSetting)"
            key="Software\\Policies\\Example" valueName="Something">
      <parentCategory ref="Updates" />
    </policy>
  </policies>
</policyDefinitions>
"""

SAMPLE_ADML = b"""<?xml version="1.0" encoding="utf-8"?>
<policyDefinitionResources revision="1.0" schemaVersion="1.0"
    xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
  <displayName>Sample</displayName>
  <description>A sample administrative template.</description>
  <resources>
    <stringTable>
      <string id="Updates">Updates</string>
      <string id="AutoUpdate">Configure automatic updates</string>
      <string id="AutoUpdate_Help">Decides whether updates install on their own.</string>
      <string id="Notify">Notify before download</string>
      <string id="Install">Install automatically</string>
      <string id="UserSetting">A setting for both halves</string>
    </stringTable>
    <presentationTable>
      <presentation id="AutoUpdate">
        <text>Pick how updates are installed.</text>
        <decimalTextBox refId="Interval" defaultValue="4">Interval (hours)</decimalTextBox>
        <textBox refId="Server">
        <label>Update server</label>
        <defaultValue>updates.example.lan</defaultValue>
      </textBox>
        <checkBox refId="Reboot" defaultChecked="true">Reboot when needed</checkBox>
        <dropdownList refId="Behaviour" defaultItem="0">Behaviour</dropdownList>
        <listBox refId="Exclusions">Excluded packages</listBox>
        <multiTextBox refId="Notes">Notes</multiTextBox>
      </presentation>
    </presentationTable>
  </resources>
</policyDefinitionResources>
"""


@pytest.fixture
def catalogue() -> Catalogue:
    loaded = Catalogue(language="en-US")
    parser.parse_admx(
        WINDOWS_ADMX, parser.parse_adml(WINDOWS_ADML), loaded, source="windows.admx"
    )
    parser.parse_admx(SAMPLE_ADMX, parser.parse_adml(SAMPLE_ADML), loaded, source="sample.admx")
    return loaded


def policy(catalogue: Catalogue, name: str):
    return next(item for item in catalogue.policies.values() if item.name == name)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def test_a_string_reference_resolves_to_its_text():
    strings = parser.parse_adml(SAMPLE_ADML)
    assert strings.resolve("$(string.Updates)") == "Updates"


def test_a_reference_with_no_string_behind_it_keeps_its_id():
    """An empty label would leave a policy that cannot be found or discussed."""
    strings = parser.parse_adml(SAMPLE_ADML)
    assert strings.resolve("$(string.Missing)") == "Missing"


def test_plain_text_is_passed_through():
    strings = parser.parse_adml(SAMPLE_ADML)
    assert strings.resolve("Just text") == "Just text"
    assert strings.resolve(None) == ""


def test_a_presentation_reference_yields_its_id():
    strings = parser.parse_adml(SAMPLE_ADML)
    assert strings.presentation_id("$(presentation.AutoUpdate)") == "AutoUpdate"
    assert strings.presentation_id("$(string.AutoUpdate)") is None


# ---------------------------------------------------------------------------
# Categories and namespaces
# ---------------------------------------------------------------------------


def test_categories_carry_their_namespace(catalogue: Catalogue):
    """Two templates may each define a category called System."""
    assert "Microsoft.Policies.Windows:System" in catalogue.categories
    assert "Example.Policies.Sample:Updates" in catalogue.categories


def test_a_reference_without_a_prefix_means_the_files_own_namespace(catalogue: Catalogue):
    logon = catalogue.categories["Microsoft.Policies.Windows:Logon"]
    assert logon.parent == "Microsoft.Policies.Windows:System"


def test_a_prefixed_reference_resolves_across_files(catalogue: Catalogue):
    """The case that decides whether the tree has a shape or is a pile of roots."""
    updates = catalogue.categories["Example.Policies.Sample:Updates"]
    assert updates.parent == "Microsoft.Policies.Windows:System"


def test_the_tree_hangs_together(catalogue: Catalogue):
    roots = catalogue.roots()
    assert [item.name for item in roots] == ["System"]

    children = catalogue.children_of("Microsoft.Policies.Windows:System")
    assert sorted(item.name for item in children) == ["Logon", "Updates"]


def test_a_category_whose_parent_is_not_installed_becomes_a_root():
    """Otherwise its settings exist and are unreachable."""
    loaded = Catalogue()
    parser.parse_admx(SAMPLE_ADMX, parser.parse_adml(SAMPLE_ADML), loaded, source="sample.admx")

    assert [item.name for item in loaded.roots()] == ["Updates"]


def test_the_path_to_a_category_reads_from_the_root_down(catalogue: Catalogue):
    path = catalogue.path_of("Example.Policies.Sample:Updates")
    assert [item.name for item in path] == ["System", "Updates"]


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def test_a_policy_carries_its_registry_location(catalogue: Catalogue):
    auto = policy(catalogue, "AutoUpdate")

    assert auto.key == "Software\\Policies\\Example\\Update"
    assert auto.value_name == "NoAutoUpdate"
    assert auto.display_name == "Configure automatic updates"
    assert auto.explain.startswith("Decides whether")


def test_the_class_decides_which_half_a_policy_writes_into(catalogue: Catalogue):
    assert policy(catalogue, "AutoUpdate").halves == ("Machine",)


def test_a_policy_without_a_class_belongs_to_both(catalogue: Catalogue):
    """Which is the schema's default, and easy to read as "neither"."""
    assert policy(catalogue, "UserSetting").policy_class == "Both"
    assert policy(catalogue, "UserSetting").halves == ("Machine", "User")


def test_the_enabled_and_disabled_values_are_read(catalogue: Catalogue):
    auto = policy(catalogue, "AutoUpdate")

    assert auto.enabled_value.kind == "decimal"
    assert auto.enabled_value.data == 1
    assert auto.disabled_value.data == 0


def test_a_policy_knows_its_presentation(catalogue: Catalogue):
    assert policy(catalogue, "AutoUpdate").presentation == "AutoUpdate"


def test_what_a_policy_needs_is_resolved_across_files(catalogue: Catalogue):
    """GPMC shows "At least Windows 7", not "windows:SUPPORTED_Windows7".

    The definitions live in one template and are referenced from every other,
    so the resolution belongs to the catalogue rather than to either file.
    """
    assert catalogue.supported_text(policy(catalogue, "AutoUpdate")) == "At least Windows 7"


def test_a_reference_we_cannot_resolve_is_not_passed_off_as_an_answer():
    """This used to return the raw reference, on the reasoning that it names a
    template someone may install later and half an answer beats none.

    It does not. Samba's templates reference a namespace generated by the tool
    that built them and installable nowhere, so a Linux-only smb.conf setting
    announced itself as ``…:SUPPORTED_WIN7`` — which reads as a requirement,
    and is the opposite of true. The reference stays available separately, for
    a reader who wants to know why there is no answer.
    """
    admx = b"""<?xml version="1.0"?>
    <policyDefinitions xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
      <policyNamespaces><target prefix="x" namespace="X" /></policyNamespaces>
      <resources minRequiredRevision="1.0" />
      <policies>
        <policy name="P" class="Machine" key="K">
          <supportedOn ref="elsewhere:SUPPORTED_Something" />
        </policy>
      </policies>
    </policyDefinitions>"""

    loaded = Catalogue()
    parser.parse_admx(admx, parser.Strings(), loaded, source="x.admx")

    assert catalogue_text(loaded, "X:P") is None
    assert loaded.supported_ref(loaded.policies["X:P"]) == "elsewhere:SUPPORTED_Something"


def test_a_resolved_reference_is_not_reported_as_unresolved(catalogue: Catalogue):
    """The two must never both have something to say."""
    assert catalogue.supported_text(policy(catalogue, "AutoUpdate")) is not None
    assert catalogue.supported_ref(policy(catalogue, "AutoUpdate")) is None


def test_a_policy_that_names_no_requirement_has_neither():
    admx = b"""<?xml version="1.0"?>
    <policyDefinitions xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
      <policyNamespaces><target prefix="y" namespace="Y" /></policyNamespaces>
      <resources minRequiredRevision="1.0" />
      <policies>
        <policy name="Q" class="Machine" key="K" />
      </policies>
    </policyDefinitions>"""

    loaded = Catalogue()
    parser.parse_admx(admx, parser.Strings(), loaded, source="y.admx")

    assert catalogue_text(loaded, "Y:Q") is None
    assert loaded.supported_ref(loaded.policies["Y:Q"]) is None


def catalogue_text(catalogue: Catalogue, policy_id: str) -> str | None:
    return catalogue.supported_text(catalogue.policies[policy_id])


# ---------------------------------------------------------------------------
# Refusing a template Windows cannot read
# ---------------------------------------------------------------------------


def test_a_well_formed_template_passes():
    parser.validate(SAMPLE_ADMX, "sample.admx")
    parser.validate(SAMPLE_ADML, "en-US/sample.adml")


def test_a_template_without_resources_is_refused():
    """The element the schema requires and everyone forgets.

    Windows parses the central store as one: a single file it cannot read
    makes it abandon every administrative template in the domain, and the
    Group Policy report shows a parser error where the settings should be.
    Refusing the upload is what keeps that from happening.
    """
    broken = SAMPLE_ADMX.replace(b'<resources minRequiredRevision="1.0" />', b"")

    with pytest.raises(InvalidRequest) as raised:
        parser.validate(broken, "sample.admx")

    assert raised.value.code == "invalid_template"
    assert "resources" in raised.value.message


@pytest.mark.parametrize("missing", ["displayName", "description"])
def test_a_text_file_without_its_heading_is_refused(missing):
    """The same domain-wide failure as a missing <resources>, one file over.

    An .adml opens with <displayName> and <description> before its resources,
    in that order. Windows reports the omission as *expected <displayName>,
    found <resources>* — which reads like a complaint about the element that
    is actually there, and is easy to answer in the wrong place.
    """
    broken = re.sub(rf"<{missing}>.*?</{missing}>\s*".encode(), b"", SAMPLE_ADML)
    assert broken != SAMPLE_ADML

    with pytest.raises(InvalidRequest) as raised:
        parser.validate(broken, "en-US/sample.adml")

    assert raised.value.code == "invalid_template"
    assert missing in raised.value.message


def test_a_definition_file_needs_no_heading():
    """Only the .adml carries one; requiring it of an .admx would reject
    templates Windows reads without complaint."""
    parser.validate(SAMPLE_ADMX, "sample.admx")
    assert b"<displayName>" not in SAMPLE_ADMX


def test_a_template_that_is_not_xml_is_refused():
    with pytest.raises(InvalidRequest) as raised:
        parser.validate(b"this is not xml", "sample.admx")
    assert raised.value.code == "invalid_template"


def test_a_document_of_another_kind_is_refused():
    with pytest.raises(InvalidRequest) as raised:
        parser.validate(b"<html><body>hello</body></html>", "sample.admx")
    assert raised.value.code == "invalid_template"


def test_a_template_without_its_own_namespace_is_refused():
    """Every category and policy in it would be unaddressable."""
    broken = b"""<?xml version="1.0"?>
    <policyDefinitions xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
      <policyNamespaces />
      <resources minRequiredRevision="1.0" />
    </policyDefinitions>"""

    with pytest.raises(InvalidRequest) as raised:
        parser.validate(broken, "sample.admx")
    assert raised.value.code == "invalid_template"


def test_a_text_file_is_judged_by_its_own_root():
    """An .adml is a different document, and an .admx in its place is a
    mistake worth catching before it reaches the share."""
    with pytest.raises(InvalidRequest):
        parser.validate(SAMPLE_ADMX, "en-US/sample.adml")


def test_a_policy_without_a_key_is_skipped_and_noted():
    """It could not be written anywhere, and silence would hide that."""
    broken = b"""<?xml version="1.0"?>
    <policyDefinitions xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions">
      <policyNamespaces><target prefix="x" namespace="X" /></policyNamespaces>
      <policies><policy name="Broken" class="Machine" /></policies>
    </policyDefinitions>"""

    loaded = Catalogue()
    parser.parse_admx(broken, parser.Strings(), loaded, source="broken.admx")

    assert loaded.policies == {}
    assert loaded.problems and "Broken" in loaded.problems[0]["reason"]


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


def test_every_element_kind_is_read(catalogue: Catalogue):
    auto = policy(catalogue, "AutoUpdate")
    assert [(item.id, item.kind) for item in auto.elements] == [
        ("Interval", "decimal"),
        ("Server", "text"),
        ("Reboot", "boolean"),
        ("Behaviour", "enum"),
        ("Exclusions", "list"),
        ("Notes", "multiText"),
    ]


def test_a_decimal_carries_its_range(catalogue: Catalogue):
    interval = policy(catalogue, "AutoUpdate").element("Interval")
    assert (interval.min_value, interval.max_value) == (1, 24)
    assert interval.required is True


def test_a_boolean_carries_the_values_for_both_states(catalogue: Catalogue):
    reboot = policy(catalogue, "AutoUpdate").element("Reboot")

    assert reboot.true_value.data == 1
    # "Off" is expressed as removing the value, which is the common case.
    assert reboot.false_value.is_delete is True


def test_an_enum_carries_its_items_with_their_labels(catalogue: Catalogue):
    behaviour = policy(catalogue, "AutoUpdate").element("Behaviour")

    assert [item.display_name for item in behaviour.items] == [
        "Notify before download",
        "Install automatically",
    ]
    assert [item.value.data for item in behaviour.items] == [2, 4]


def test_a_list_carries_its_own_key_and_prefix(catalogue: Catalogue):
    """A list writes any number of values, and usually not where its policy does."""
    exclusions = policy(catalogue, "AutoUpdate").element("Exclusions")

    assert exclusions.key == "Software\\Policies\\Example\\Update\\Exclude"
    assert exclusions.value_prefix == "Ex"
    assert exclusions.additive is True
    assert exclusions.explicit_value is False


def test_a_text_element_carries_its_limit(catalogue: Catalogue):
    assert policy(catalogue, "AutoUpdate").element("Server").max_length == 255


def test_an_element_that_is_not_there_is_not_found(catalogue: Catalogue):
    assert policy(catalogue, "AutoUpdate").element("Nothing") is None


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


def test_the_presentation_lists_its_controls_in_order():
    strings = parser.parse_adml(SAMPLE_ADML)
    controls = strings.presentations["AutoUpdate"]

    assert [control["kind"] for control in controls] == [
        "text",
        "decimalTextBox",
        "textBox",
        "checkBox",
        "dropdownList",
        "listBox",
        "multiTextBox",
    ]


def test_a_caption_has_no_element_behind_it():
    """Kept anyway — often the only explanation of the inputs below it."""
    controls = parser.parse_adml(SAMPLE_ADML).presentations["AutoUpdate"]
    assert controls[0]["ref"] is None
    assert controls[0]["text"] == "Pick how updates are installed."


def test_a_default_given_as_an_attribute_is_read():
    """Which is how decimalTextBox spells it."""
    controls = parser.parse_adml(SAMPLE_ADML).presentations["AutoUpdate"]
    interval = next(control for control in controls if control["ref"] == "Interval")

    assert interval["label"] == "Interval (hours)"
    assert interval["default"] == "4"


def test_a_default_given_as_a_child_element_is_read():
    """And that is how textBox spells the same thing — the schema is not
    consistent about it, so both forms have to be read."""
    controls = parser.parse_adml(SAMPLE_ADML).presentations["AutoUpdate"]
    server = next(control for control in controls if control["ref"] == "Server")

    assert server["label"] == "Update server"
    assert server["default"] == "updates.example.lan"


def test_a_checkbox_default_is_a_boolean():
    controls = parser.parse_adml(SAMPLE_ADML).presentations["AutoUpdate"]
    reboot = next(control for control in controls if control["ref"] == "Reboot")
    assert reboot["default"] is True


# ---------------------------------------------------------------------------
# Searching
# ---------------------------------------------------------------------------


def test_a_policy_is_found_by_its_name(catalogue: Catalogue):
    found = catalogue.search("automatic")
    assert [item.name for item in found] == ["AutoUpdate"]


def test_a_policy_is_found_by_what_it_does(catalogue: Catalogue):
    """Nobody remembers what a setting is called."""
    found = catalogue.search("install on their own")
    assert [item.name for item in found] == ["AutoUpdate"]


def test_a_name_match_comes_before_an_explanation_match(catalogue: Catalogue):
    found = catalogue.search("setting")
    assert found[0].name == "UserSetting"


def test_searching_for_nothing_finds_nothing(catalogue: Catalogue):
    assert catalogue.search("") == []
    assert catalogue.search("   ") == []


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_policies_are_listed_under_their_category(catalogue: Catalogue):
    found = catalogue.policies_in("Example.Policies.Sample:Updates")
    assert sorted(item.name for item in found) == ["AutoUpdate", "UserSetting"]


def test_policies_can_be_narrowed_to_one_half(catalogue: Catalogue):
    """The editor shows the computer and user halves separately."""
    found = catalogue.policies_in("Example.Policies.Sample:Updates", policy_class="User")
    assert [item.name for item in found] == ["UserSetting"]


def test_the_summary_counts_what_was_loaded(catalogue: Catalogue):
    summary = catalogue.summary()
    assert summary["categories"] == 3
    assert summary["policies"] == 2
    assert summary["problems"] == []

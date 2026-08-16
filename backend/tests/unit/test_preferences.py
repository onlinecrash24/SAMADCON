"""The preference files, against the ones GPMC wrote.

Nine references, all from the domain this is verified against:

* ``Drives.xml`` from *GPP-Laufwerke*, created for this — two drives, one with
  item-level targeting.
* ``Drives.xml`` from *Connect Network Drives*, in the domain since March 2025
  and written by a different GPMC. It disagrees with the first about attribute
  order, which is how we know nothing depends on it.
* ``Registry.xml`` from *GPP-Registry*, read twice — first with two value
  types, then with all five.
* ``Files.xml`` and ``Folders.xml``.
* ``Shortcuts.xml``, ``EnvironmentVariables.xml`` and ``Printers.xml`` in both
  halves, from wave two. Between them they broke three rules the first four
  had kept: ``status`` is not always ``name``, ``action`` is not always the
  first attribute of ``<Properties>``, and one file can hold several kinds of
  element.

The fixtures were transcribed byte for byte from the files themselves and
checked against the sizes the DC reported. That check survives for the one
fixture that carries no identifier of the domain it came from; the rest had
their names, SIDs, hosts and addresses replaced with example ones before
publication, which breaks the link to the original length. A recomputed number
would only assert that a fixture equals itself, so it is not written down —
what the fixtures still prove is checked by the round trips below, and those
are the ones that have caught every wrong assumption so far.
"""

from __future__ import annotations

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import cse
from samadcon.gpo.preferences import catalogue, store, xmlfile

# The literal "SAMCON" appears throughout the fixtures below and is left alone
# on purpose. It is not the product's name in them — it is test *data*: a
# registry key, a printer's local name, a shortcut path, a group, all typed
# into GPMC when these files were produced. The fixtures are byte-for-byte
# transcriptions, so rewriting them would falsify what they claim to be and
# break the one size assertion that survived anonymisation.

# Which half each type is exercised in. Only printers need more than one, and
# those tests name the half themselves.
HALF_OF = {
    "drives": "User",
    "registry": "Machine",
    "files": "Machine",
    "folders": "Machine",
    "shortcuts": "Machine",
    "environment": "Machine",
}


def _file(*lines: str) -> bytes:
    """The layout all nine references share: CRLF after every line, including
    the last."""
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


DECLARATION = '<?xml version="1.0" encoding="utf-8"?>'

DRIVES_XML = _file(
    DECLARATION,
    '<Drives clsid="{8FDDCC1A-0C3C-43cd-A6B4-71A6DF20DA8C}">'
    '<Drive clsid="{935D1B74-9CB8-4e3c-9914-7DD559B7A417}" name="K:" status="K:" image="0"'
    ' bypassErrors="1" changed="2026-08-16 07:29:38" uid="{B69A90EB-4958-4A93-8095-FA07AB8DDA10}">'
    '<Properties action="C" thisDrive="NOCHANGE" allDrives="NOCHANGE" userName=""'
    ' path="\\\\dc1\\netlogon" label="Test" persistent="1" useLetter="1" letter="K"/>'
    '<Filters><FilterGroup bool="AND" not="0" name="EXAMPLE\\Domain Admins"'
    ' sid="S-1-5-21-1004336348-1177238915-682003330-512" userContext="1" primaryGroup="0"'
    ' localGroup="0"/></Filters></Drive>',
    '\t<Drive clsid="{935D1B74-9CB8-4e3c-9914-7DD559B7A417}" name="L:" status="L:" image="3"'
    ' changed="2026-08-16 07:29:57" uid="{67E7DE09-9C76-404F-9667-9C6F681EA5D8}">'
    '<Properties action="D" thisDrive="NOCHANGE" allDrives="NOCHANGE" userName="" path=""'
    ' label="" persistent="0" useLetter="1" letter="L"/></Drive>',
    "</Drives>",
)

# The 2025 file. Note `userContext` and `bypassErrors` after `uid` rather than
# before `changed` — the same console, a different order.
DRIVES_2025_XML = _file(
    DECLARATION,
    '<Drives clsid="{8FDDCC1A-0C3C-43cd-A6B4-71A6DF20DA8C}">'
    '<Drive clsid="{935D1B74-9CB8-4e3c-9914-7DD559B7A417}" name="Z:" status="Z:" image="2"'
    ' changed="2025-03-16 19:06:36" uid="{398B9F4B-E179-4C0C-990F-8A2C54EBA216}"'
    ' userContext="1" bypassErrors="1">'
    '<Properties action="U" thisDrive="NOCHANGE" allDrives="NOCHANGE" userName=""'
    ' path="\\\\member1\\share" label="Share" persistent="1" useLetter="1" letter="Z"/>'
    '<Filters><FilterGroup bool="AND" not="0" name="EXAMPLE\\IT"'
    ' sid="S-1-5-21-1004336348-1177238915-682003330-1107" userContext="1" primaryGroup="0"'
    ' localGroup="0"/></Filters></Drive>',
    "</Drives>",
)

REGISTRY_XML = _file(
    DECLARATION,
    '<RegistrySettings clsid="{A3CCFC41-DFDB-43a5-8D26-0FE8B954DA51}">'
    '<Registry clsid="{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}" name="Probe" status="Probe"'
    ' image="7" changed="2026-08-16 07:31:27" uid="{33D397F0-DBC4-4E0B-AE48-ECF48DA1ABA8}">'
    '<Properties action="U" displayDecimal="0" default="0" hive="HKEY_LOCAL_MACHINE"'
    ' key="SOFTWARE\\SAMCON" name="Probe" type="REG_SZ" value="hallo"/></Registry>',
    '\t<Registry clsid="{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}" name="Zahl" status="Zahl"'
    ' image="12" changed="2026-08-16 07:32:01" uid="{9C0121BA-C386-4B64-99C6-481C563C3895}">'
    '<Properties action="U" displayDecimal="0" default="0" hive="HKEY_LOCAL_MACHINE"'
    ' key="SOFTWARE\\SAMCON" name="Zahl" type="REG_DWORD" value="00000007"/></Registry>',
    "</RegistrySettings>",
)

FILES_XML = _file(
    DECLARATION,
    '<Files clsid="{215B2E53-57CE-475c-80FE-9EEC14635851}">'
    '<File clsid="{50BE44C8-567A-4ed1-B1D0-9234FE1F38AF}" name="probe.txt" status="probe.txt"'
    ' image="0" changed="2026-08-16 07:33:29" uid="{86998CC5-421C-4A49-BD79-20F0418DEF4B}">'
    '<Properties action="C" fromPath="\\\\dc1\\netlogon\\probe.txt"'
    ' targetPath="C:\\Temp\\probe.txt" readOnly="1" archive="0" hidden="0"/></File>',
    "</Files>",
)

# The second reading of Registry.xml, after four more value types were added
# in GPMC. REG_MULTI_SZ is the one that matters: it is the only element in any
# preference file whose <Properties> is not empty.
REGISTRY_ALL_TYPES_XML = _file(
    DECLARATION,
    '<RegistrySettings clsid="{A3CCFC41-DFDB-43a5-8D26-0FE8B954DA51}">'
    '<Registry clsid="{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}" name="Pfad" status="Pfad"'
    ' image="7" changed="2026-08-16 07:52:22" uid="{4E82F523-EB89-489D-83F9-0D9C934722D1}">'
    '<Properties action="U" displayDecimal="0" default="0" hive="HKEY_LOCAL_MACHINE"'
    ' key="SOFTWARE\\SAMCON" name="Pfad" type="REG_EXPAND_SZ"'
    ' value="%SystemRoot%\\Temp"/></Registry>',
    '\t<Registry clsid="{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}" name="Liste" status="Liste"'
    ' image="7" changed="2026-08-16 07:53:04" uid="{A9E95662-DB4F-4399-A5A1-238F1A64967A}">'
    '<Properties action="U" displayDecimal="0" default="0" hive="HKEY_LOCAL_MACHINE"'
    ' key="SOFTWARE\\SAMCON" name="Liste" type="REG_MULTI_SZ" value="eins zwei drei">'
    "<Values><Value>eins</Value><Value>zwei</Value><Value>drei</Value></Values>"
    "</Properties></Registry>",
    '\t<Registry clsid="{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}" name="Bytes" status="Bytes"'
    ' image="17" changed="2026-08-16 07:53:29" uid="{0143BD62-6AC8-46B9-9F1B-0BBA37353998}">'
    '<Properties action="U" displayDecimal="0" default="0" hive="HKEY_LOCAL_MACHINE"'
    ' key="SOFTWARE\\SAMCON" name="Bytes" type="REG_BINARY" value="00 0f ff"/></Registry>',
    '\t<Registry clsid="{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}" name="Gross" status="Gross"'
    ' image="12" changed="2026-08-16 07:53:56" uid="{92A746F7-80E1-4C75-B6DC-167D897A4F5F}">'
    '<Properties action="U" displayDecimal="1" default="0" hive="HKEY_LOCAL_MACHINE"'
    ' key="SOFTWARE\\SAMCON" name="Gross" type="REG_DWORD" value="000000FF"/></Registry>',
    "</RegistrySettings>",
)

FOLDERS_XML = _file(
    DECLARATION,
    '<Folders clsid="{77CC39E7-3D16-4f8f-AF86-EC0BBEE2C861}">'
    '<Folder clsid="{07DA02F5-F9CD-4397-A550-4AE21B6B4BD3}" name="SAMCON" status="SAMCON"'
    ' image="0" changed="2026-08-16 07:51:06" uid="{EB3085CA-D7FA-425F-B45A-F164F756BA14}">'
    '<Properties action="C" path="C:\\Temp\\SAMCON" readOnly="0" archive="1" hidden="0"/>'
    "</Folder>",
    "</Folders>",
)

# Two shortcuts differing only in their target type. Note `userContext` right
# after `clsid` — a third attribute order from the same console.
SHORTCUTS_XML = _file(
    DECLARATION,
    '<Shortcuts clsid="{872ECB34-B2EC-401b-A585-D32574AA90EE}">'
    '<Shortcut clsid="{4F2F7C55-2790-433e-8127-0739D1CFA327}" userContext="1" name="SAMCON"'
    ' status="SAMCON" image="0" changed="2026-08-16 09:52:17"'
    ' uid="{E29CDB49-58E2-4D3E-AB56-28357ECFEFE5}">'
    '<Properties pidl="" targetType="URL" action="C" comment="Probe" shortcutKey="0"'
    ' startIn="C:\\Users\\admin\\Downloads" arguments="C:\\Temp\\probe.txt"'
    ' iconIndex="3" targetPath="https://example.invalid/"'
    ' iconPath="C:\\Windows\\System32\\shell32.dll" window="MIN"'
    ' shortcutPath="%DesktopDir%\\SAMCON"/></Shortcut>',
    '\t<Shortcut clsid="{4F2F7C55-2790-433e-8127-0739D1CFA327}" userContext="1" name="SAMCON"'
    ' status="SAMCON" image="0" changed="2026-08-16 09:52:46"'
    ' uid="{C3978912-DD1A-48B1-9DF5-39A47BF7BABA}">'
    '<Properties pidl="" targetType="FILESYSTEM" action="C" comment="Probe" shortcutKey="0"'
    ' startIn="C:\\Users\\admin\\Downloads" arguments="C:\\Temp\\probe.txt"'
    ' iconIndex="3" targetPath="C:\\Windows\\System32\\notepad.exe"'
    ' iconPath="C:\\Windows\\System32\\shell32.dll" window="MIN"'
    ' shortcutPath="%DesktopDir%\\SAMCON"/></Shortcut>',
    "</Shortcuts>",
)

# The file that proved `status` is not `name`.
ENVIRONMENT_XML = _file(
    DECLARATION,
    '<EnvironmentVariables clsid="{BF141A63-327B-438a-B9BF-2C188F13B7AD}">'
    '<EnvironmentVariable clsid="{78570023-8373-4a19-BA80-2F150738EA19}" name="SAMCON_PROBE"'
    ' status="SAMCON_PROBE = eins" image="2" changed="2026-08-16 09:57:49"'
    ' uid="{8B5D6490-ED20-40C0-843A-348B8555CF3C}">'
    '<Properties action="U" name="SAMCON_PROBE" value="eins" user="0" partial="0"/>'
    "</EnvironmentVariable>",
    '\t<EnvironmentVariable clsid="{78570023-8373-4a19-BA80-2F150738EA19}" name="PATH"'
    ' status="PATH = C:\\Temp" image="2" changed="2026-08-16 09:58:50"'
    ' uid="{CEEB9F8E-A59A-4222-AF76-2FE0D60D0B74}">'
    '<Properties action="U" name="PATH" value="C:\\Temp" user="0" partial="1"/>'
    "</EnvironmentVariable>",
    "</EnvironmentVariables>",
)

# One file, two kinds of element — and a `<Properties>` whose action is not
# first.
PRINTERS_MACHINE_XML = _file(
    DECLARATION,
    '<Printers clsid="{1F577D12-3D1B-471e-A1B7-060317597B9C}">'
    '<PortPrinter clsid="{C3A739D2-4A44-401e-9F9D-88E5E77DFB3E}" name="192.168.1.50"'
    ' status="192.168.1.50" image="0" changed="2026-08-16 10:01:58"'
    ' uid="{8F6A1FB1-0861-40F3-9A6A-6161C80FB3F0}">'
    '<Properties ipAddress="192.168.1.50" action="C" location="Serverraum"'
    ' localName="SAMCON-IP" comment="Probe" default="0" skipLocal="0" useDNS="0" useIPv6="0"'
    ' path="\\\\dc1\\Probe" deleteAll="0"/></PortPrinter>',
    '\t<LocalPrinter clsid="{F08996D5-568B-45f5-BB7A-D3FB1E370B0A}" name="SAMCON-Lokal"'
    ' status="Buero" image="0" changed="2026-08-16 10:01:50"'
    ' uid="{9BD1FCF3-1CBD-4A88-81D2-7C96FC3C38A2}">'
    '<Properties action="C" name="SAMCON-Lokal" port="LPT1:" path="\\\\dc1\\Probe"'
    ' default="0" deleteAll="0" location="Buero" comment="Probe"/></LocalPrinter>',
    "</Printers>",
)

PRINTERS_USER_XML = _file(
    DECLARATION,
    '<Printers clsid="{1F577D12-3D1B-471e-A1B7-060317597B9C}">'
    '<SharedPrinter clsid="{9A5E9697-9095-436d-A0EE-4D128FDFBCE5}" name="Probe" status="Probe"'
    ' image="0" changed="2026-08-16 10:02:34" uid="{B424DFF5-B63B-444C-AFE3-FCD03779500D}">'
    '<Properties action="C" comment="" path="\\\\dc1\\Probe" location="" default="1"'
    ' skipLocal="0" deleteAll="0" persistent="0" deleteMaps="0" port=""/></SharedPrinter>',
    "</Printers>",
)

# Wave three. Between them these three broke four rules the first seven files
# had kept: no `status` anywhere, a service with no `action` at all, an
# immediate task with neither an `image` nor an action and its `<Filters>`
# *before* its `<Properties>`, and a group whose members are a nested block.
GROUPS_XML = _file(
    DECLARATION,
    '<Groups clsid="{3125E937-EB16-4b4c-9934-544FC6D24D26}">'
    '<Group clsid="{6D4A79E4-529C-4481-ABD0-F5BD7EA93BA7}" name="SAMCON-Probe" image="0"'
    ' userContext="0" removePolicy="0" changed="2026-08-16 16:10:45"'
    ' uid="{6A2EE045-A96E-400B-A4EC-24FE8FBAEB28}">'
    '<Properties action="C" description="Probe" deleteAllUsers="0" deleteAllGroups="0"'
    ' removeAccounts="0" groupName="SAMCON-Probe">'
    '<Members><Member name="EXAMPLE\\Domain Admins" action="ADD"'
    ' sid="S-1-5-21-1004336348-1177238915-682003330-512"/>'
    '<Member name="EXAMPLE\\Domain Users" action="REMOVE"'
    ' sid="S-1-5-21-1004336348-1177238915-682003330-513"/></Members>'
    "</Properties></Group>",
    '\t<User clsid="{DF5F1855-51E5-4d24-8B1A-D9BDE98BA1D1}" name="samcon-probe" image="2"'
    ' changed="2026-08-16 16:20:58" uid="{CD39B848-F574-4C9D-8A0C-73A91FB5E97B}">'
    '<Properties action="U" newName="" fullName="SAMCON Probe" description="Probe"'
    ' cpassword="" changeLogon="1" noChange="0" neverExpires="0" acctDisabled="1"'
    ' userName="samcon-probe"/></User>',
    "</Groups>",
)

SERVICES_XML = _file(
    DECLARATION,
    '<NTServices clsid="{2CFB484A-4E96-4b5d-A0B6-093D2F91E6AE}">'
    '<NTService clsid="{AB6F0B67-341F-4e51-92F9-005FBFBA1A43}" name="Spooler" image="2"'
    ' changed="2026-08-16 16:13:28" uid="{CAEDBDD2-6415-43E2-B9F9-AD6132166A9A}">'
    '<Properties startupType="AUTOMATIC" serviceName="Spooler" serviceAction="START"'
    ' timeout="30"/></NTService>',
    "</NTServices>",
)

# Abridged: the two V2 tasks carry a <Task> tree of eighteen settings each,
# which the round-trip covers in full through the real file. What is kept here
# is the shape — the envelope, the nested tree, the whitespace inside it — and
# the two older kinds in full.
TASKS_XML = _file(
    DECLARATION,
    '<ScheduledTasks clsid="{CC63F200-7309-4ba0-B154-A71CD118DBCC}">'
    '<TaskV2 clsid="{D8896631-B747-47a7-84A6-C155337F3BC8}" name="SAMCON-Task" image="0"'
    ' changed="2026-08-16 16:15:35" uid="{E80AD78F-1137-4A92-A435-ECB09900E9E3}">'
    '<Properties action="C" name="SAMCON-Task" runAs="EXAMPLE\\Administrator"'
    ' logonType="InteractiveToken"><Task version="1.2"><RegistrationInfo>'
    "<Author>EXAMPLE\\admin</Author><Description></Description>"
    "</RegistrationInfo><Triggers><CalendarTrigger>"
    "<StartBoundary>2026-08-16T18:15:25</StartBoundary><Enabled>true</Enabled>"
    "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>",
    "\t\t\t\t</Triggers><Actions Context=\"Author\"><Exec>"
    "<Command>C:\\Windows\\System32\\notepad.exe</Command></Exec>",
    "\t\t\t\t</Actions></Task></Properties></TaskV2>",
    '\t<Task clsid="{2DEECB1C-261F-4e13-9B21-16FB83BC03BD}" name="SAMCON-Alt" image="0"'
    ' changed="2026-08-16 16:17:38" uid="{7FAD7564-33CC-4577-8398-CB38A5F0D631}">'
    '<Properties action="C" name="SAMCON-Alt" appName="C:\\Windows\\System32\\notepad.exe"'
    ' args="" startIn="" comment="" enabled="1"><Triggers>'
    '<Trigger type="DAILY" startHour="07" startMinutes="00" beginYear="2026" beginMonth="8"'
    ' beginDay="16" hasEndDate="0" repeatTask="0" interval="1"/></Triggers>'
    "</Properties></Task>",
    '\t<ImmediateTask clsid="{9F030D12-DDA3-4C26-8548-B7CE9151166A}" name="SAMCON-SofortAlt"'
    ' changed="2026-08-16 16:19:52" uid="{5B360D0A-E07B-4D67-9692-C894825198C3}">'
    '<Filters><FilterCollection hidden="1" bool="AND" not="0">'
    '<FilterOs hidden="1" not="0" bool="AND" class="NT" version="XP" type="NE" edition="NE"'
    ' sp="NE"/><FilterOs hidden="1" not="0" bool="OR" class="NT" version="2K3" type="NE"'
    ' edition="NE" sp="NE"/><FilterOs hidden="1" not="0" bool="OR" class="NT"'
    ' version="2K3R2" type="NE" edition="NE" sp="NE"/></FilterCollection></Filters>'
    '<Properties name="SAMCON-SofortAlt" appName="C:\\Windows\\System32\\notepad.exe"'
    ' args="" startIn="" comment=""/></ImmediateTask>',
    "</ScheduledTasks>",
)

# XML 1.0 §2.11 obliges every parser to turn a CRLF in content into a bare LF
# before anything downstream sees it. The whitespace GPMC leaves inside a
# task's <Task> tree *is* content, so a file read and written back carries LF
# there where the original had CRLF: the same document to any reader, two
# different bytes on disk. It is the one place a round trip is not byte for
# byte, and it is written down here rather than smoothed over. Everything
# outside the preserved tree — the item separators, which this module writes
# itself — stays CRLF.
TASKS_REWRITTEN = TASKS_XML.replace(b"\r\n\t\t\t\t", b"\n\t\t\t\t")

# (type, the file as the DC holds it, its byte count where one was taken,
#  what writing it back produces)
REFERENCES = [
    # Only the registry reference still carries the size the DC reported: it
    # holds no name, SID or address of the domain it came from, so nothing in
    # it had to be replaced for publication. 0 turns the check off for the
    # rest — either because they were anonymised, or because they were read
    # with `cat -A`, which reports no length.
    ("drives", DRIVES_XML, 0, DRIVES_XML),
    ("drives", DRIVES_2025_XML, 0, DRIVES_2025_XML),
    ("registry", REGISTRY_XML, 785, REGISTRY_XML),
    ("files", FILES_XML, 0, FILES_XML),
    ("registry", REGISTRY_ALL_TYPES_XML, 0, REGISTRY_ALL_TYPES_XML),
    ("folders", FOLDERS_XML, 0, FOLDERS_XML),
    ("shortcuts", SHORTCUTS_XML, 0, SHORTCUTS_XML),
    ("environment", ENVIRONMENT_XML, 0, ENVIRONMENT_XML),
    ("printers", PRINTERS_MACHINE_XML, 0, PRINTERS_MACHINE_XML),
    ("printers", PRINTERS_USER_XML, 0, PRINTERS_USER_XML),
    ("groups", GROUPS_XML, 0, GROUPS_XML),
    ("services", SERVICES_XML, 0, SERVICES_XML),
    ("tasks", TASKS_XML, 0, TASKS_REWRITTEN),
]


@pytest.mark.parametrize(("type_id", "raw", "size", "written"), REFERENCES)
def test_fixtures_have_the_size_the_dc_reported(
    type_id: str, raw: bytes, size: int, written: bytes
) -> None:
    if not size:
        pytest.skip("no byte count was taken for this reading")
    assert len(raw) == size


@pytest.mark.parametrize(("type_id", "raw", "size", "written"), REFERENCES)
def test_round_trip_changes_no_byte(
    type_id: str, raw: bytes, size: int, written: bytes
) -> None:
    """Read a GPMC file and write it back: it must come out identical.

    This is the check that has caught a wrong assumption in every format so
    far. Whitespace, attribute order, the empty-element spelling and the
    preserved `<Filters>` subtree all have to survive for it to pass.
    """
    kind = catalogue.type_for(type_id)
    assert xmlfile.render(kind, xmlfile.parse(kind, raw.decode("utf-8"))) == written


def test_drive_reads_its_settings() -> None:
    kind = catalogue.type_for("drives")
    first, second = xmlfile.parse(kind, DRIVES_XML.decode("utf-8"))

    assert first["name"] == "K:"
    assert first["action"] == "C"
    assert first["image"] == 0
    assert first["bypass_errors"] is True
    assert first["user_context"] is False
    assert first["properties"]["path"] == "\\\\dc1\\netlogon"
    assert first["properties"]["label"] == "Test"
    assert first["filter_names"] == ["FilterGroup: EXAMPLE\\Domain Admins"]

    assert second["action"] == "D"
    assert second["image"] == 3
    assert second["filters"] is None


def test_registry_reads_both_value_types() -> None:
    kind = catalogue.type_for("registry")
    text, number = xmlfile.parse(kind, REGISTRY_XML.decode("utf-8"))

    assert (text["properties"]["type"], text["properties"]["value"]) == ("REG_SZ", "hallo")
    assert (number["properties"]["type"], number["properties"]["value"]) == (
        "REG_DWORD",
        "00000007",
    )
    # The registry's image tracks the value type, not the action: both items
    # carry action="U" and they differ.
    assert text["action"] == number["action"] == "U"
    assert (text["image"], number["image"]) == (7, 12)


def test_an_item_built_here_is_the_one_gpmc_wrote(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other direction: build the file from scratch and compare bytes."""
    monkeypatch.setattr(store, "_now", lambda: "2026-08-16 07:33:29")
    kind = catalogue.type_for("files")

    item = store._prepare(
        kind,
        HALF_OF[kind.id],
        {
            "uid": "{86998CC5-421C-4A49-BD79-20F0418DEF4B}",
            "action": "C",
            "properties": {
                "fromPath": "\\\\dc1\\netlogon\\probe.txt",
                "targetPath": "C:\\Temp\\probe.txt",
                "readOnly": "1",
            },
        },
        {},
    )
    assert xmlfile.render(kind, [item]) == FILES_XML


def test_a_printers_file_holds_more_than_one_kind() -> None:
    """The case that shaped the model: three kinds share one file, and two of
    them do not share a half."""
    printers = catalogue.type_for("printers")
    port, local = xmlfile.parse(printers, PRINTERS_MACHINE_XML.decode("utf-8"))

    assert (port["kind"], local["kind"]) == ("port", "local")
    assert port["name"] == "192.168.1.50"
    assert port["properties"]["localName"] == "SAMCON-IP"
    assert local["properties"]["port"] == "LPT1:"

    shared = xmlfile.parse(printers, PRINTERS_USER_XML.decode("utf-8"))[0]
    assert shared["kind"] == "shared"
    assert shared["properties"]["path"] == "\\\\dc1\\Probe"

    assert printers.kind("shared").halves == ("User",)
    assert printers.kind("port").halves == ("Machine",)
    assert printers.halves == ("Machine", "User")


def test_the_action_is_not_always_the_first_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    """A TCP/IP printer writes `ipAddress` before it. Building the item from
    scratch has to put it back where the console puts it."""
    monkeypatch.setattr(store, "_now", lambda: "2026-08-16 10:01:58")
    printers = catalogue.type_for("printers")

    item = store._prepare(
        printers,
        "Machine",
        {
            "kind": "port",
            "uid": "{8F6A1FB1-0861-40F3-9A6A-6161C80FB3F0}",
            "action": "C",
            "properties": {
                "ipAddress": "192.168.1.50",
                "location": "Serverraum",
                "localName": "SAMCON-IP",
                "comment": "Probe",
                "path": "\\\\dc1\\Probe",
            },
        },
        {},
    )
    rendered = xmlfile.render(printers, [item]).decode("utf-8")
    assert '<Properties ipAddress="192.168.1.50" action="C"' in rendered


def test_a_status_line_is_not_always_the_name() -> None:
    """Wave one had them equal in all four types. Wave two has two that are
    not, and each is derived its own way."""
    environment = catalogue.type_for("environment")
    probe, path = xmlfile.parse(environment, ENVIRONMENT_XML.decode("utf-8"))

    assert (probe["name"], probe["status"]) == ("SAMCON_PROBE", "SAMCON_PROBE = eins")
    assert (path["name"], path["status"]) == ("PATH", "PATH = C:\\Temp")
    # "Append to PATH" rather than replace it.
    assert (probe["properties"]["partial"], path["properties"]["partial"]) == ("0", "1")

    assert catalogue.status_text("environment", {"value": "eins"}, "SAMCON_PROBE") == (
        "SAMCON_PROBE = eins"
    )
    # A local printer puts its location there instead.
    assert catalogue.status_text("local", {"location": "Buero"}, "SAMCON-Lokal") == "Buero"
    assert catalogue.status_text("registry", {}, "Probe") == "Probe"


def test_a_shortcut_takes_its_name_from_the_shortcut_path() -> None:
    shortcuts = catalogue.type_for("shortcuts")
    url, filesystem = xmlfile.parse(shortcuts, SHORTCUTS_XML.decode("utf-8"))

    assert url["name"] == "SAMCON"
    assert url["properties"]["targetType"] == "URL"
    assert filesystem["properties"]["targetType"] == "FILESYSTEM"
    assert url["user_context"] is True
    assert catalogue.display_name("shortcut", {"shortcutPath": "%DesktopDir%\\SAMCON"}) == (
        "SAMCON"
    )


def test_a_kind_from_the_wrong_half_is_refused() -> None:
    printers = catalogue.type_for("printers")
    with pytest.raises(InvalidRequest):
        store._kind(printers, "Machine", "shared")
    with pytest.raises(InvalidRequest):
        store._kind(printers, "User", "port")
    assert store._kind(printers, "User", "shared").tag == "SharedPrinter"


def test_a_file_with_an_unknown_element_is_not_rewritten() -> None:
    """Reading skips what this build does not know; writing would drop it.

    A newer console's file is left to that console rather than quietly cut
    down to what we understand.
    """
    printers = catalogue.type_for("printers")
    foreign = PRINTERS_USER_XML.replace(b"<SharedPrinter", b"<FaxPrinter", 1).replace(
        b"</SharedPrinter>", b"</FaxPrinter>", 1
    )

    assert xmlfile.parse(printers, foreign.decode("utf-8")) == []
    with pytest.raises(InvalidRequest):
        store._refuse_unknown_elements(printers, foreign)


def test_a_group_carries_its_members_as_a_nested_block() -> None:
    groups = catalogue.type_for("groups")
    group, user = xmlfile.parse(groups, GROUPS_XML.decode("utf-8"))

    assert group["kind"] == "group"
    assert group["name"] == "SAMCON-Probe"
    assert [(member["name"], member["action"]) for member in group["members"]] == [
        ("EXAMPLE\\Domain Admins", "ADD"),
        ("EXAMPLE\\Domain Users", "REMOVE"),
    ]
    # No `status` anywhere in wave three, and the group states userContext="0"
    # outright where a drive would simply leave it off.
    assert group["status"] == ""
    assert group["extra"]["userContext"] == "0"

    assert user["kind"] == "user"
    assert user["name"] == "samcon-probe"
    # An empty cpassword is not a stored password.
    assert user["properties"]["cpassword"] == ""
    assert user["has_password"] is False


def test_a_member_needs_a_direction() -> None:
    """Add or remove — a default either way would be a wrong answer, and one
    of them grants access."""
    groups = catalogue.type_for("groups")
    with pytest.raises(InvalidRequest):
        store._prepare(
            groups,
            "Machine",
            {
                "kind": "group",
                "action": "C",
                "properties": {"groupName": "X"},
                "members": [{"name": "EXAMPLE\\Domain Admins", "action": "JOIN"}],
            },
            {},
        )


def test_a_service_has_no_action_at_all() -> None:
    """Not "an action we do not model" — the element has none. It carries a
    startup type and a service action instead."""
    services = catalogue.type_for("services")
    service = xmlfile.parse(services, SERVICES_XML.decode("utf-8"))[0]

    assert service["action"] == ""
    assert service["properties"]["startupType"] == "AUTOMATIC"
    assert service["properties"]["serviceAction"] == "START"
    assert services.kind("service").has_action is False
    # No action to derive an icon from, so the kind names one.
    assert services.kind("service").fixed_image == 2


def test_a_service_round_trips_without_inventing_an_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "_now", lambda: "2026-08-16 16:13:28")
    services = catalogue.type_for("services")

    item = store._prepare(
        services,
        "Machine",
        {
            "kind": "service",
            "uid": "{CAEDBDD2-6415-43E2-B9F9-AD6132166A9A}",
            "properties": {"serviceName": "Spooler"},
        },
        {},
    )
    assert xmlfile.render(services, [item]) == SERVICES_XML


def test_an_immediate_task_writes_its_filters_first() -> None:
    """Every other kind writes <Properties> then <Filters>. This one is the
    other way round, and a round trip has to keep it that way."""
    tasks = catalogue.type_for("tasks")
    items = xmlfile.parse(tasks, TASKS_XML.decode("utf-8"))
    immediate = next(item for item in items if item["kind"] == "immediate")

    assert immediate["filters_first"] is True
    assert immediate["action"] == ""
    assert immediate["filter_names"][0].startswith("FilterCollection")

    rendered = xmlfile.render(tasks, [immediate]).decode("utf-8")
    assert "<ImmediateTask" in rendered
    assert rendered.index("<Filters>") < rendered.index("<Properties")


def test_a_task_keeps_the_tree_it_came_with() -> None:
    tasks = catalogue.type_for("tasks")
    task = xmlfile.parse(tasks, TASKS_XML.decode("utf-8"))[0]

    assert task["kind"] == "task_v2"
    assert task["properties"]["runAs"] == "EXAMPLE\\Administrator"
    assert "<CalendarTrigger>" in task["properties_children"]
    assert "<Command>C:\\Windows\\System32\\notepad.exe</Command>" in task["properties_children"]


def test_a_task_cannot_be_created_from_here() -> None:
    """A <Task> tree written from scratch without a reference for each of its
    parts is exactly the guess this project does not make."""
    tasks = catalogue.type_for("tasks")
    with pytest.raises(InvalidRequest) as caught:
        store._prepare(
            tasks, "Machine", {"kind": "task_v2", "action": "C", "properties": {}}, {}
        )
    assert caught.value.code == "preference_not_creatable"

    # An existing one is still editable.
    existing = {
        item["uid"]: item for item in xmlfile.parse(tasks, TASKS_XML.decode("utf-8"))
    }
    edited = store._prepare(
        tasks,
        "Machine",
        {"uid": "{E80AD78F-1137-4A92-A435-ECB09900E9E3}", "kind": "task_v2", "action": "U"},
        existing,
    )
    assert edited["action"] == "U"
    assert "<CalendarTrigger>" in edited["properties_children"]


def test_the_name_is_derived_the_way_gpmc_derives_it() -> None:
    assert catalogue.display_name("drive", {"letter": "K"}) == "K:"
    assert catalogue.display_name("registry", {"name": "Probe"}) == "Probe"
    assert catalogue.display_name("file", {"targetPath": "C:\\Temp\\probe.txt"}) == "probe.txt"
    assert catalogue.display_name("folder", {"path": "C:\\Temp\\SAMCON"}) == "SAMCON"


def test_a_folder_keeps_its_own_defaults() -> None:
    """A folder is archived by default where a file is not — both read off
    their own reference rather than one borrowed from the other."""
    folders = {field.name: field.default for field in catalogue.TYPES["folders"].kinds[0].fields}
    files = {field.name: field.default for field in catalogue.TYPES["files"].kinds[0].fields}
    assert (folders["archive"], files["archive"]) == ("1", "0")


def test_a_multi_sz_keeps_its_lines_in_a_values_block() -> None:
    kind = catalogue.type_for("registry")
    items = xmlfile.parse(kind, REGISTRY_ALL_TYPES_XML.decode("utf-8"))
    lines = next(item for item in items if item["name"] == "Liste")

    assert lines["values"] == ["eins", "zwei", "drei"]
    # The attribute beside the block is a summary, not the data.
    assert lines["properties"]["value"] == "eins zwei drei"
    assert lines["image"] == 7


def test_writing_a_multi_sz_produces_gpmcs_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "_now", lambda: "2026-08-16 07:53:04")
    kind = catalogue.type_for("registry")

    item = store._prepare(
        kind,
        HALF_OF[kind.id],
        {
            "uid": "{A9E95662-DB4F-4399-A5A1-238F1A64967A}",
            "action": "U",
            "properties": {"key": "SOFTWARE\\SAMCON", "name": "Liste", "type": "REG_MULTI_SZ"},
            "values": ["eins", "zwei", "drei"],
        },
        {},
    )

    assert item["properties_children"] == (
        "<Values><Value>eins</Value><Value>zwei</Value><Value>drei</Value></Values>"
    )
    assert item["properties"]["value"] == "eins zwei drei"
    assert xmlfile.render(kind, [item]).decode("utf-8").splitlines()[1].endswith(
        "</Values></Properties></Registry>"
    )


def test_changing_a_multi_sz_to_a_string_takes_the_block_with_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "_now", lambda: "2026-08-16 09:00:00")
    kind = catalogue.type_for("registry")
    existing = {
        item["uid"]: item
        for item in xmlfile.parse(kind, REGISTRY_ALL_TYPES_XML.decode("utf-8"))
    }

    item = store._prepare(
        kind,
        HALF_OF[kind.id],
        {
            "uid": "{A9E95662-DB4F-4399-A5A1-238F1A64967A}",
            "action": "U",
            "properties": {"type": "REG_SZ", "value": "nur eins"},
        },
        existing,
    )
    assert item["properties_children"] == ""
    assert item["properties"]["value"] == "nur eins"


def test_binary_values_are_written_as_lower_case_pairs() -> None:
    normalised = catalogue.normalise("registry", {"type": "REG_BINARY", "value": "00 0F FF"})
    assert normalised["value"] == "00 0f ff"
    # Grouping and spacing on the way in are the caller's business.
    assert catalogue.normalise("registry", {"type": "REG_BINARY", "value": "000fff"})[
        "value"
    ] == ("00 0f ff")
    with pytest.raises(InvalidRequest):
        catalogue.normalise("registry", {"type": "REG_BINARY", "value": "00 0f f"})
    with pytest.raises(InvalidRequest):
        catalogue.normalise("registry", {"type": "REG_BINARY", "value": "zz"})


def test_every_offered_registry_type_has_an_icon_read_off_a_file() -> None:
    offered = next(
        field for field in catalogue.TYPES["registry"].kinds[0].fields if field.name == "type"
    )
    assert set(offered.choices) == set(catalogue.REGISTRY_TYPE_IMAGE)


def test_a_dword_is_written_as_eight_hex_digits() -> None:
    assert catalogue.normalise("registry", {"type": "REG_DWORD", "value": "7"})["value"] == (
        "00000007"
    )
    assert catalogue.normalise("registry", {"type": "REG_DWORD", "value": "255"})["value"] == (
        "000000FF"
    )
    # Already eight digits: taken as the hex it is, not re-read as decimal.
    assert catalogue.normalise("registry", {"type": "REG_DWORD", "value": "0000000A"})[
        "value"
    ] == ("0000000A")
    # A string keeps whatever it holds.
    assert catalogue.normalise("registry", {"type": "REG_SZ", "value": "7"})["value"] == "7"


def test_a_dword_out_of_range_is_refused() -> None:
    with pytest.raises(InvalidRequest):
        catalogue.normalise("registry", {"type": "REG_DWORD", "value": "4294967296"})
    with pytest.raises(InvalidRequest):
        catalogue.normalise("registry", {"type": "REG_DWORD", "value": "keine Zahl"})


def test_editing_an_item_keeps_its_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Renaming a drive must not drop who it applies to."""
    monkeypatch.setattr(store, "_now", lambda: "2026-08-16 08:00:00")
    kind = catalogue.type_for("drives")
    existing = {
        item["uid"]: item for item in xmlfile.parse(kind, DRIVES_XML.decode("utf-8"))
    }

    updated = store._prepare(
        kind,
        HALF_OF[kind.id],
        {
            "uid": "{B69A90EB-4958-4A93-8095-FA07AB8DDA10}",
            "action": "C",
            "properties": {"label": "Anders"},
        },
        existing,
    )

    assert updated["properties"]["label"] == "Anders"
    # Untouched fields come from the file, not from a default.
    assert updated["properties"]["path"] == "\\\\dc1\\netlogon"
    # bypassErrors travels as the attribute it is rather than as a boolean: a
    # drive omits it when off, a group writes it out as "0", and regenerating
    # it from a flag would lose one of the two spellings.
    assert updated["extra"]["bypassErrors"] == "1"
    assert "EXAMPLE\\Domain Admins" in (updated["filters"] or "")


def test_saving_an_unchanged_item_leaves_its_stamp_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise every save rewrites the file and raises the GPO version, and
    every client in scope re-applies a policy that did not change."""
    monkeypatch.setattr(store, "_now", lambda: "2099-01-01 00:00:00")
    kind = catalogue.type_for("files")
    existing = {item["uid"]: item for item in xmlfile.parse(kind, FILES_XML.decode("utf-8"))}
    stored = next(iter(existing.values()))

    same = store._prepare(
        kind,
        HALF_OF[kind.id],
        {"uid": stored["uid"], "action": "C", "properties": dict(stored["properties"])},
        existing,
    )
    assert same["changed"] == "2026-08-16 07:33:29"
    assert xmlfile.render(kind, [same]) == FILES_XML

    moved = store._prepare(
        kind,
        HALF_OF[kind.id],
        {"uid": stored["uid"], "action": "C", "properties": {"hidden": "1"}},
        existing,
    )
    assert moved["changed"] == "2099-01-01 00:00:00"


def test_a_password_can_be_carried_but_never_introduced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cpassword is encrypted with a key Microsoft published in 2014.

    An item that already has one keeps working; nothing sent from outside can
    put one in.
    """
    monkeypatch.setattr(store, "_now", lambda: "2026-08-16 08:00:00")
    kind = catalogue.type_for("drives")

    injected = store._prepare(
        kind,
        HALF_OF[kind.id],
        {"action": "C", "properties": {"letter": "K", "cpassword": "AAAAAAAA"}},
        {},
    )
    assert "cpassword" not in injected["properties"]

    existing = {
        "{1}": {"properties": {"cpassword": "AAAAAAAA", "letter": "K"}, "order": [], "extra": {}}
    }
    carried = store._prepare(
        kind,
        HALF_OF[kind.id], {"uid": "{1}", "action": "C", "properties": {"label": "x"}}, existing
    )
    assert carried["properties"]["cpassword"] == "AAAAAAAA"


def test_an_unknown_action_is_refused() -> None:
    kind = catalogue.type_for("drives")
    with pytest.raises(InvalidRequest):
        store._prepare(kind, "User", {"action": "X", "properties": {}}, {})


def test_a_control_character_is_refused() -> None:
    kind = catalogue.type_for("files")
    with pytest.raises(InvalidRequest):
        xmlfile.render(
            kind,
            [{"uid": "{1}", "name": "a", "action": "C", "properties": {"targetPath": "a\x00b"}}],
        )


def test_drive_maps_exist_in_the_user_half_only() -> None:
    assert catalogue.TYPES["drives"].halves == ("User",)
    with pytest.raises(InvalidRequest):
        store._preference("drives", "Machine")
    assert store._preference("registry", "Machine").id == "registry"


# ---------------------------------------------------------------------------
# The extension names
# ---------------------------------------------------------------------------


def test_a_preference_registers_two_groups() -> None:
    """One pair for the type, one in the shared null group — as read off all
    three reference GPOs."""
    value = ""
    for pair_cse, tool in catalogue.TYPES["drives"].pairs:
        value = cse.add(value, pair_cse, [tool])

    assert value == (
        "[{00000000-0000-0000-0000-000000000000}{2EA1A81B-48E5-45E9-8BB7-A6E3AC170006}]"
        "[{5794DAFD-BE60-433F-88A2-1A31939AC01F}{2EA1A81B-48E5-45E9-8BB7-A6E3AC170006}]"
    )


# `gPCMachineExtensionNames` of GPP-Dateien after a registry item was added
# beside its file item — two preference types in one half, read off the DC.
TWO_TYPES = (
    "[{00000000-0000-0000-0000-000000000000}"
    "{3BAE7E51-E3F4-41D0-853D-9BB9FD47605F}{BEE07A6A-EC9F-4659-B8C9-0B1937907C83}]"
    "[{7150F9BF-48AD-4DA4-A49C-29EF4A8369BA}{3BAE7E51-E3F4-41D0-853D-9BB9FD47605F}]"
    "[{B087BE9D-ED37-454F-AF9C-04291E351182}{BEE07A6A-EC9F-4659-B8C9-0B1937907C83}]"
)


@pytest.mark.parametrize("order", [("files", "registry"), ("registry", "files")])
def test_two_types_in_one_half_match_what_gpmc_wrote(order: tuple[str, str]) -> None:
    """GPMC merges the null entries into one group rather than repeating it.

    Registering in either order has to give the same attribute, or the same
    two settings would produce different GPOs depending on which was made
    first.
    """
    value = ""
    for type_id in order:
        for pair_cse, tool in catalogue.TYPES[type_id].pairs:
            value = cse.add(value, pair_cse, [tool])

    assert value == TWO_TYPES


def test_a_type_registers_the_same_pair_in_both_halves() -> None:
    """Printers settled it: one GPO with a shared printer under User and a
    port printer under Machine carries the identical pair on both attributes.
    The tool GUID belongs to the type, not to the half."""
    printers = catalogue.TYPES["printers"]
    expected = (
        f"[{cse.braced(cse.PREFERENCES_NULL_CSE)}{cse.braced(cse.PRINTERS_TOOL)}]"
        f"[{cse.braced(cse.PRINTERS_CSE)}{cse.braced(cse.PRINTERS_TOOL)}]"
    )

    for _half in ("Machine", "User"):
        value = ""
        for pair_cse, tool in printers.pairs:
            value = cse.add(value, pair_cse, [tool])
        assert value == expected


def test_dropping_one_type_leaves_the_others_registration() -> None:
    value = TWO_TYPES
    for pair_cse, tool in catalogue.TYPES["files"].pairs:
        value = cse.remove_tool(value, pair_cse, tool)

    assert value == (
        "[{00000000-0000-0000-0000-000000000000}{BEE07A6A-EC9F-4659-B8C9-0B1937907C83}]"
        "[{B087BE9D-ED37-454F-AF9C-04291E351182}{BEE07A6A-EC9F-4659-B8C9-0B1937907C83}]"
    )


def test_dropping_the_last_type_leaves_nothing_behind() -> None:
    value = ""
    for pair_cse, tool in catalogue.TYPES["files"].pairs:
        value = cse.add(value, pair_cse, [tool])
    for pair_cse, tool in catalogue.TYPES["files"].pairs:
        value = cse.remove_tool(value, pair_cse, tool)

    assert value == ""


def test_an_existing_registration_is_left_alone() -> None:
    """Administrative templates and preferences in the same GPO."""
    value = cse.add("", cse.REGISTRY_CSE, [cse.REGISTRY_TOOL])
    for pair_cse, tool in catalogue.TYPES["registry"].pairs:
        value = cse.add(value, pair_cse, [tool])

    assert cse.braced(cse.REGISTRY_CSE) in value
    for pair_cse, tool in catalogue.TYPES["registry"].pairs:
        value = cse.remove_tool(value, pair_cse, tool)
    assert value == f"[{cse.braced(cse.REGISTRY_CSE)}{cse.braced(cse.REGISTRY_TOOL)}]"

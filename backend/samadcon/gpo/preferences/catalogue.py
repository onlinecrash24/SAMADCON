"""Which preference types exist, and what each one's XML says.

Every value here was read off a file GPMC wrote — seven throwaway GPOs created
for exactly this, plus one drive-map policy that had been in the domain since
2025 and served as an independent second reading. Where something could not be
read off one of those files it is listed at `UNVERIFIED` rather than filled in.
A wrong ``clsid`` or a wrong action letter produces a file every console
displays correctly and no client acts on.

Three things wave two contradicted, each of which had been true for all four
types of wave one:

* **``status`` is not always ``name``.** An environment variable writes
  ``status="SAMADCON_PROBE = eins"``, a local printer writes its *location*
  there. So it is derived per kind, not copied.
* **``action`` is not always the first attribute of ``<Properties>``.** A
  TCP/IP printer puts ``ipAddress`` before it, a shortcut ``pidl`` and
  ``targetType``. So the wire order names where the action sits rather than
  assuming the front.
* **One file can hold several kinds of element.** ``Printers.xml`` mixes
  ``SharedPrinter``, ``PortPrinter`` and ``LocalPrinter``, each with its own
  ``clsid``, its own fields and its own half.

What the two independent drive-map files settled between them still holds:
attribute order does not matter (the 2025 and 2026 files disagree about it),
and optional attributes are absent rather than empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import cse

# Details still waiting on a reference file. Kept here rather than scattered
# through comments so that anything relying on one can point at a single place.
UNVERIFIED = {
    # C, U and D have each been read off a file, and Samba's own
    # `gp_drive_maps_ext.py` tests `action in ['C', 'R', 'U']` against 'D',
    # which settles the letters. The icon index of Replace is filled in.
    "action_replace_image": "the icon index of the Replace action",
    # REG_BINARY reads `value="00 0f ff"` — lower case, byte pairs, single
    # spaces. Both readings were typed in lower case, so whether the console
    # normalises or keeps what it was given is open.
    "registry_binary_case": "whether REG_BINARY is normalised to lower case",
    # Not offered, so not guessed: no reference file carries one.
    "registry_qword": "REG_QWORD encoding and icon index",
    # Folders were only read with action="C". Delete carries further
    # attributes — recursion, and what happens to the contents.
    "folder_delete_attributes": "the attributes a Folder carries under Delete",
    # Only `window="MIN"` has been read. NORMAL and MAX are the remaining two
    # settings GPMC offers and are spelled here the way MIN suggests.
    "shortcut_window": "how the Normal and Maximized window states are spelled",
    # FILESYSTEM and URL were read. GPMC offers a third, shell objects.
    "shortcut_shell_target": "the targetType of a shell object shortcut",
    # Every environment variable read so far sits in the computer half, where
    # only system variables exist, and all carry user="0".
    "environment_user_flag": "whether a user variable writes user=\"1\"",
    # SharedPrinter is missing from the computer half in GPMC, which is why it
    # is user-only here. Whether the other two appear in the user half was not
    # tested, so they are computer-only — the restrictive direction.
    "printer_halves": "whether port and local printers exist in the user half",
    # A gpresult report shows a port printer applying with protocol TCP/IP
    # (Raw), port 9100 and SNMP off — none of which is in the file. GPMC omits
    # the Port Settings tab when it was not touched and the client fills in
    # its own defaults. An item that does carry them keeps them; a new one
    # written here does not invent them.
    "printer_port_settings": "the attributes of a port printer's Port Settings tab",
}

# The four actions, as the `action` attribute spells them. Samba's own
# `gp_drive_maps_ext.py` branches on `['C', 'R', 'U']` against `'D'`, which is
# a second, independent source for the same four letters.
ACTIONS = ("C", "R", "U", "D")

# `image` is the icon index in the console's list. Everywhere but the registry
# it tracks the action — C=0, U=2 and D=3 were read off files, R=1 fills the
# gap. The registry tracks the value type instead, which is how we know the
# two are unrelated: all six registry items carry action="U" and their images
# differ.
ACTION_IMAGE = {"C": 0, "R": 1, "U": 2, "D": 3}

# All five read off one file: the three string kinds share an icon, numbers
# and raw bytes have their own.
REGISTRY_TYPE_IMAGE = {
    "REG_SZ": 7,
    "REG_EXPAND_SZ": 7,
    "REG_MULTI_SZ": 7,
    "REG_DWORD": 12,
    "REG_BINARY": 17,
}

REGISTRY_TYPES = tuple(REGISTRY_TYPE_IMAGE)

# The value that is not in the `value` attribute. GPMC writes the lines into a
# `<Values>` block under `<Properties>` and leaves a space-joined summary in
# the attribute beside it — the only place a preference element has a child
# other than `<Filters>`.
MULTI_SZ = "REG_MULTI_SZ"
BINARY = "REG_BINARY"

# The marker for the action's place in the wire order. It is an attribute of
# <Properties> like the others and does not always come first.
ACTION = "action"


@dataclass(frozen=True)
class Field:
    """One attribute of a ``<Properties>`` element.

    ``secret`` is a field written but never offered: a local user carries
    ``cpassword=""``, and an empty one has to stay empty. It is filtered out of
    the catalogue the API serves and refused on the way in.
    """

    name: str
    kind: str = "text"  # text | bool | choice | action | secret
    default: str = ""
    choices: tuple[str, ...] = ()


ACTION_FIELD = Field(ACTION, kind="action")


@dataclass(frozen=True)
class ItemKind:
    """One kind of element inside a preference file.

    Most types have exactly one. Printers have three and scheduled tasks four,
    which is why this exists as its own thing rather than as fields on the
    type. The flags below are all read off reference files rather than assumed;
    wave three broke every one of the defaults that waves one and two had kept.
    """

    id: str
    tag: str
    clsid: str
    # In the order GPMC writes them onto <Properties>, action included at its
    # own place. Keeping the wire order lets a file we write be compared byte
    # for byte with one GPMC wrote; the editor arranges its own form.
    fields: tuple[Field, ...]
    halves: tuple[str, ...] = ("Machine", "User")

    # Whether the element repeats its name in a `status` attribute. Waves one
    # and two do; nothing in wave three does.
    writes_status: bool = True
    # An immediate task from the Windows XP era carries no icon index at all.
    writes_image: bool = True
    # A fixed icon for a kind whose action does not imply one — a service has
    # no action to derive it from.
    fixed_image: int | None = None
    # A service has no Create/Replace/Update/Delete. It has a startup type and
    # a service action instead, and its <Properties> carries no `action`.
    has_action: bool = True
    # The XP-era immediate task writes <Filters> *before* <Properties>. Every
    # other kind writes it after.
    filters_first: bool = False
    # Whether a new item of this kind can be written from here. The two V2
    # task kinds carry a whole <Task> tree — registration info, principals,
    # eighteen settings, triggers, actions — and writing one from scratch
    # without a reference for each part is exactly the guess this project does
    # not make. Existing ones are read, edited and removed; new ones are not
    # invented.
    creatable: bool = True


@dataclass(frozen=True)
class PreferenceType:
    """One preference type: where its file lives and what goes in it."""

    id: str
    directory: str
    filename: str
    root_tag: str
    root_clsid: str
    cse: str
    tool: str
    kinds: tuple[ItemKind, ...] = field(default_factory=tuple)

    def path(self, half: str) -> str:
        return f"{half}\\Preferences\\{self.directory}\\{self.filename}"

    @property
    def halves(self) -> tuple[str, ...]:
        """The halves any of its kinds can appear in."""
        return tuple(
            half for half in ("Machine", "User") if any(half in kind.halves for kind in self.kinds)
        )

    @property
    def pairs(self) -> list[tuple[str, str]]:
        """The two extension/tool pairs GPMC registers for this type."""
        return [(cse.PREFERENCES_NULL_CSE, self.tool), (self.cse, self.tool)]

    def kinds_in(self, half: str) -> tuple[ItemKind, ...]:
        return tuple(kind for kind in self.kinds if half in kind.halves)

    def kind(self, kind_id: str | None) -> ItemKind:
        if kind_id is None and len(self.kinds) == 1:
            return self.kinds[0]
        for kind in self.kinds:
            if kind.id == kind_id:
                return kind
        raise InvalidRequest(
            "Unknown kind of preference item.",
            code="unknown_preference_kind",
            hint=f"Expected one of: {', '.join(kind.id for kind in self.kinds)}.",
            context={"type": self.id, "given": kind_id},
        )

    def kind_for_tag(self, tag: str) -> ItemKind | None:
        return next((kind for kind in self.kinds if kind.tag == tag), None)


# The clsid values are copied **verbatim**, mixed case and all: GPMC writes
# `{8FDDCC1A-0C3C-43cd-A6B4-71A6DF20DA8C}` with a lower-case `43cd`. Nothing
# suggests a reader cares, and nothing suggests taking the chance either.
TYPES: dict[str, PreferenceType] = {
    "drives": PreferenceType(
        id="drives",
        directory="Drives",
        filename="Drives.xml",
        root_tag="Drives",
        root_clsid="{8FDDCC1A-0C3C-43cd-A6B4-71A6DF20DA8C}",
        cse=cse.DRIVES_CSE,
        tool=cse.DRIVES_TOOL,
        kinds=(
            ItemKind(
                id="drive",
                tag="Drive",
                clsid="{935D1B74-9CB8-4e3c-9914-7DD559B7A417}",
                # Drive maps exist in the user half only — GPMC offers the
                # branch nowhere else, and both reference files sit under User.
                halves=("User",),
                fields=(
                    ACTION_FIELD,
                    # NOCHANGE is what both reference files carry for a drive
                    # whose visibility the editor left alone.
                    Field("thisDrive", "choice", "NOCHANGE", ("NOCHANGE", "SHOW", "HIDE")),
                    Field("allDrives", "choice", "NOCHANGE", ("NOCHANGE", "SHOW", "HIDE")),
                    Field("userName"),
                    Field("path"),
                    Field("label"),
                    Field("persistent", "bool", "1"),
                    Field("useLetter", "bool", "1"),
                    Field("letter"),
                ),
            ),
        ),
    ),
    "registry": PreferenceType(
        id="registry",
        directory="Registry",
        filename="Registry.xml",
        root_tag="RegistrySettings",
        root_clsid="{A3CCFC41-DFDB-43a5-8D26-0FE8B954DA51}",
        cse=cse.PREF_REGISTRY_CSE,
        tool=cse.PREF_REGISTRY_TOOL,
        kinds=(
            ItemKind(
                id="registry",
                tag="Registry",
                clsid="{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}",
                fields=(
                    ACTION_FIELD,
                    Field("displayDecimal", "bool", "0"),
                    Field("default", "bool", "0"),
                    Field(
                        "hive",
                        "choice",
                        "HKEY_LOCAL_MACHINE",
                        (
                            "HKEY_LOCAL_MACHINE",
                            "HKEY_CURRENT_USER",
                            "HKEY_CLASSES_ROOT",
                            "HKEY_USERS",
                            "HKEY_CURRENT_CONFIG",
                        ),
                    ),
                    Field("key"),
                    Field("name"),
                    # Every type offered has been read off a reference file
                    # with its encoding and its icon. REG_QWORD has not.
                    Field("type", "choice", "REG_SZ", REGISTRY_TYPES),
                    Field("value"),
                ),
            ),
        ),
    ),
    "files": PreferenceType(
        id="files",
        directory="Files",
        filename="Files.xml",
        root_tag="Files",
        root_clsid="{215B2E53-57CE-475c-80FE-9EEC14635851}",
        cse=cse.FILES_CSE,
        tool=cse.FILES_TOOL,
        kinds=(
            ItemKind(
                id="file",
                tag="File",
                clsid="{50BE44C8-567A-4ed1-B1D0-9234FE1F38AF}",
                fields=(
                    ACTION_FIELD,
                    Field("fromPath"),
                    Field("targetPath"),
                    Field("readOnly", "bool", "0"),
                    Field("archive", "bool", "0"),
                    Field("hidden", "bool", "0"),
                ),
            ),
        ),
    ),
    "folders": PreferenceType(
        id="folders",
        directory="Folders",
        filename="Folders.xml",
        root_tag="Folders",
        root_clsid="{77CC39E7-3D16-4f8f-AF86-EC0BBEE2C861}",
        cse=cse.FOLDERS_CSE,
        tool=cse.FOLDERS_TOOL,
        kinds=(
            ItemKind(
                id="folder",
                tag="Folder",
                clsid="{07DA02F5-F9CD-4397-A550-4AE21B6B4BD3}",
                fields=(
                    ACTION_FIELD,
                    Field("path"),
                    Field("readOnly", "bool", "0"),
                    # A folder defaults to archive="1" where a file defaults to
                    # "0". Both were read off their own reference; neither is
                    # carried over from the other.
                    Field("archive", "bool", "1"),
                    Field("hidden", "bool", "0"),
                ),
            ),
        ),
    ),
    "shortcuts": PreferenceType(
        id="shortcuts",
        directory="Shortcuts",
        filename="Shortcuts.xml",
        root_tag="Shortcuts",
        root_clsid="{872ECB34-B2EC-401b-A585-D32574AA90EE}",
        cse=cse.SHORTCUTS_CSE,
        tool=cse.SHORTCUTS_TOOL,
        kinds=(
            ItemKind(
                id="shortcut",
                tag="Shortcut",
                clsid="{4F2F7C55-2790-433e-8127-0739D1CFA327}",
                fields=(
                    # `pidl` and `targetType` come before the action here.
                    Field("pidl"),
                    Field("targetType", "choice", "FILESYSTEM", ("FILESYSTEM", "URL")),
                    ACTION_FIELD,
                    Field("comment"),
                    Field("shortcutKey", "text", "0"),
                    Field("startIn"),
                    Field("arguments"),
                    Field("iconIndex", "text", "0"),
                    Field("targetPath"),
                    Field("iconPath"),
                    Field("window", "choice", "NORMAL", ("NORMAL", "MIN", "MAX")),
                    Field("shortcutPath"),
                ),
            ),
        ),
    ),
    "environment": PreferenceType(
        id="environment",
        directory="EnvironmentVariables",
        filename="EnvironmentVariables.xml",
        root_tag="EnvironmentVariables",
        root_clsid="{BF141A63-327B-438a-B9BF-2C188F13B7AD}",
        cse=cse.ENVIRONMENT_CSE,
        tool=cse.ENVIRONMENT_TOOL,
        kinds=(
            ItemKind(
                id="environment",
                tag="EnvironmentVariable",
                clsid="{78570023-8373-4a19-BA80-2F150738EA19}",
                fields=(
                    ACTION_FIELD,
                    Field("name"),
                    Field("value"),
                    Field("user", "bool", "0"),
                    # "Append to the PATH variable" rather than replace it.
                    Field("partial", "bool", "0"),
                ),
            ),
        ),
    ),
    "printers": PreferenceType(
        id="printers",
        directory="Printers",
        filename="Printers.xml",
        root_tag="Printers",
        root_clsid="{1F577D12-3D1B-471e-A1B7-060317597B9C}",
        cse=cse.PRINTERS_CSE,
        tool=cse.PRINTERS_TOOL,
        kinds=(
            ItemKind(
                id="shared",
                tag="SharedPrinter",
                clsid="{9A5E9697-9095-436d-A0EE-4D128FDFBCE5}",
                # GPMC does not offer this one in the computer half at all.
                halves=("User",),
                fields=(
                    ACTION_FIELD,
                    Field("comment"),
                    Field("path"),
                    Field("location"),
                    Field("default", "bool", "0"),
                    Field("skipLocal", "bool", "0"),
                    Field("deleteAll", "bool", "0"),
                    Field("persistent", "bool", "0"),
                    Field("deleteMaps", "bool", "0"),
                    Field("port"),
                ),
            ),
            ItemKind(
                id="port",
                tag="PortPrinter",
                clsid="{C3A739D2-4A44-401e-9F9D-88E5E77DFB3E}",
                halves=("Machine",),
                fields=(
                    # The one element whose action is not the first attribute.
                    Field("ipAddress"),
                    ACTION_FIELD,
                    Field("location"),
                    Field("localName"),
                    Field("comment"),
                    Field("default", "bool", "0"),
                    Field("skipLocal", "bool", "0"),
                    Field("useDNS", "bool", "0"),
                    Field("useIPv6", "bool", "0"),
                    Field("path"),
                    Field("deleteAll", "bool", "0"),
                ),
            ),
            ItemKind(
                id="local",
                tag="LocalPrinter",
                clsid="{F08996D5-568B-45f5-BB7A-D3FB1E370B0A}",
                halves=("Machine",),
                fields=(
                    ACTION_FIELD,
                    Field("name"),
                    Field("port"),
                    Field("path"),
                    Field("default", "bool", "0"),
                    Field("deleteAll", "bool", "0"),
                    Field("location"),
                    Field("comment"),
                ),
            ),
        ),
    ),
    "groups": PreferenceType(
        id="groups",
        directory="Groups",
        filename="Groups.xml",
        root_tag="Groups",
        root_clsid="{3125E937-EB16-4b4c-9934-544FC6D24D26}",
        cse=cse.GROUPS_CSE,
        tool=cse.GROUPS_TOOL,
        kinds=(
            ItemKind(
                id="group",
                tag="Group",
                clsid="{6D4A79E4-529C-4481-ABD0-F5BD7EA93BA7}",
                writes_status=False,
                fields=(
                    ACTION_FIELD,
                    Field("description"),
                    Field("deleteAllUsers", "bool", "0"),
                    Field("deleteAllGroups", "bool", "0"),
                    Field("removeAccounts", "bool", "0"),
                    Field("groupName"),
                ),
            ),
            ItemKind(
                id="user",
                tag="User",
                clsid="{DF5F1855-51E5-4d24-8B1A-D9BDE98BA1D1}",
                writes_status=False,
                fields=(
                    ACTION_FIELD,
                    Field("newName"),
                    Field("fullName"),
                    Field("description"),
                    # Written empty and never offered. GPMC itself warns that
                    # this attribute is a known security risk; the key that
                    # decrypts it was published in 2014.
                    Field("cpassword", "secret", ""),
                    Field("changeLogon", "bool", "0"),
                    Field("noChange", "bool", "0"),
                    Field("neverExpires", "bool", "0"),
                    Field("acctDisabled", "bool", "0"),
                    Field("userName"),
                ),
            ),
        ),
    ),
    "services": PreferenceType(
        id="services",
        directory="Services",
        filename="Services.xml",
        root_tag="NTServices",
        root_clsid="{2CFB484A-4E96-4b5d-A0B6-093D2F91E6AE}",
        cse=cse.SERVICES_CSE,
        tool=cse.SERVICES_TOOL,
        kinds=(
            ItemKind(
                id="service",
                tag="NTService",
                clsid="{AB6F0B67-341F-4e51-92F9-005FBFBA1A43}",
                # GPMC offers services in the computer half only.
                halves=("Machine",),
                writes_status=False,
                # No action to derive an icon from; 2 is what the reference
                # carries and the only value seen.
                fixed_image=2,
                has_action=False,
                fields=(
                    Field(
                        "startupType",
                        "choice",
                        "AUTOMATIC",
                        ("AUTOMATIC", "MANUAL", "DISABLED", "NOCHANGE"),
                    ),
                    Field("serviceName"),
                    Field(
                        "serviceAction",
                        "choice",
                        "START",
                        ("START", "STOP", "RESTART", "NOCHANGE"),
                    ),
                    Field("timeout", "text", "30"),
                ),
            ),
        ),
    ),
    "tasks": PreferenceType(
        id="tasks",
        directory="ScheduledTasks",
        filename="ScheduledTasks.xml",
        root_tag="ScheduledTasks",
        root_clsid="{CC63F200-7309-4ba0-B154-A71CD118DBCC}",
        cse=cse.TASKS_CSE,
        tool=cse.TASKS_TOOL,
        # None of the four can be created from here — see `creatable`. They are
        # read so a policy holding them stays editable, and so that saving some
        # other type in the same GPO does not have to refuse.
        kinds=(
            ItemKind(
                id="task_v2",
                tag="TaskV2",
                clsid="{D8896631-B747-47a7-84A6-C155337F3BC8}",
                writes_status=False,
                creatable=False,
                fields=(
                    ACTION_FIELD,
                    Field("name"),
                    Field("runAs"),
                    Field("logonType"),
                ),
            ),
            ItemKind(
                id="immediate_v2",
                tag="ImmediateTaskV2",
                clsid="{9756B581-76EC-4169-9AFC-0CA8D43ADB5F}",
                writes_status=False,
                creatable=False,
                fields=(
                    ACTION_FIELD,
                    Field("name"),
                    Field("runAs"),
                    Field("logonType"),
                ),
            ),
            ItemKind(
                id="task",
                tag="Task",
                clsid="{2DEECB1C-261F-4e13-9B21-16FB83BC03BD}",
                writes_status=False,
                creatable=False,
                fields=(
                    ACTION_FIELD,
                    Field("name"),
                    Field("appName"),
                    Field("args"),
                    Field("startIn"),
                    Field("comment"),
                    Field("enabled", "bool", "1"),
                ),
            ),
            ItemKind(
                id="immediate",
                tag="ImmediateTask",
                clsid="{9F030D12-DDA3-4C26-8548-B7CE9151166A}",
                writes_status=False,
                writes_image=False,
                has_action=False,
                # GPMC generates a <Filters> block for this one that keeps it
                # off anything newer than Server 2003 — and writes it before
                # <Properties> rather than after.
                filters_first=True,
                creatable=False,
                fields=(
                    Field("name"),
                    Field("appName"),
                    Field("args"),
                    Field("startIn"),
                    Field("comment"),
                ),
            ),
        ),
    ),
}


def type_for(type_id: str) -> PreferenceType:
    try:
        return TYPES[type_id]
    except KeyError:
        raise InvalidRequest(
            "Unknown preference type.",
            code="unknown_preference_type",
            hint=f"Expected one of: {', '.join(sorted(TYPES))}.",
            context={"given": type_id},
        ) from None


# ---------------------------------------------------------------------------
# What the console puts in `name` and `status`
# ---------------------------------------------------------------------------
#
# Neither is entered: both are derived from the settings, and each kind
# derives them its own way. Reading them off the files is the only way to
# know, and wave two is where they stopped agreeing with each other.


# Kinds whose display name is simply one of their own attributes.
NAME_FROM_PROPERTY = {
    "registry": "name",
    "environment": "name",
    "local": "name",
    "port": "ipAddress",
    "group": "groupName",
    "user": "userName",
    "service": "serviceName",
    "task_v2": "name",
    "immediate_v2": "name",
    "task": "name",
    "immediate": "name",
}


def display_name(kind_id: str, properties: dict[str, str]) -> str:
    if kind_id == "drive":
        letter = (properties.get("letter") or "").strip()
        return f"{letter}:" if letter else ""
    if kind_id in NAME_FROM_PROPERTY:
        return (properties.get(NAME_FROM_PROPERTY[kind_id]) or "").strip()

    source = {"file": "targetPath", "shortcut": "shortcutPath"}.get(kind_id, "path")
    target = (properties.get(source) or "").strip().rstrip("\\")
    return target.rsplit("\\", 1)[-1] if target else ""


def status_text(kind_id: str, properties: dict[str, str], name: str) -> str:
    """Usually the name — but not always, and the exceptions are read, not
    reasoned about."""
    if kind_id == "environment":
        return f"{name} = {properties.get('value') or ''}"
    if kind_id == "local":
        return (properties.get("location") or "").strip()
    return name


def image_for(kind: ItemKind, properties: dict[str, str], action: str) -> int:
    """The icon index for a new item."""
    if kind.fixed_image is not None:
        return kind.fixed_image
    if kind.id == "registry":
        return REGISTRY_TYPE_IMAGE.get(properties.get("type", ""), 0)
    return ACTION_IMAGE.get(action, 0)


# ---------------------------------------------------------------------------
# Values the file spells differently from the way anyone types them
# ---------------------------------------------------------------------------


def normalise(kind_id: str, properties: dict[str, str]) -> dict[str, str]:
    """Two registry types, both spellings read off the same reference file:

    * **REG_DWORD** is eight hex digits, zero padded, upper case. 255 entered
      as a decimal came back as ``000000FF``, which settles the case.
    * **REG_BINARY** is byte pairs in lower case, single spaces between them:
      ``00 0f ff``.
    """
    if kind_id != "registry":
        return properties

    kind = properties.get("type")
    if kind == "REG_DWORD":
        return {**properties, "value": _dword(properties.get("value"))}
    if kind == BINARY:
        return {**properties, "value": _binary(properties.get("value"))}
    return properties


def _dword(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return f"{0:08X}"

    try:
        number = int(raw, 16) if len(raw) == 8 and _is_hex(raw) else int(raw, 10)
    except ValueError:
        raise InvalidRequest(
            "A REG_DWORD needs a number.",
            code="preference_dword_value",
            hint="Enter a decimal number, or eight hexadecimal digits.",
            context={"given": raw},
        ) from None

    if not 0 <= number <= 0xFFFFFFFF:
        raise InvalidRequest(
            "A REG_DWORD holds a number from 0 to 4294967295.",
            code="preference_dword_range",
            context={"given": raw},
        )
    return f"{number:08X}"


def _binary(value: str | None) -> str:
    """Byte pairs, lower case, one space between them.

    Both spacing and grouping are accepted on the way in — ``000FFF`` and
    ``00 0F FF`` mean the same thing — because a value pasted from elsewhere
    should not have to be reformatted by hand first.
    """
    digits = "".join((value or "").split())
    if not digits:
        return ""
    if not _is_hex(digits) or len(digits) % 2:
        raise InvalidRequest(
            "A REG_BINARY holds pairs of hexadecimal digits.",
            code="preference_binary_value",
            hint="For example: 00 0f ff",
            context={"given": value},
        )
    return " ".join(digits[index : index + 2].lower() for index in range(0, len(digits), 2))


def _is_hex(value: str) -> bool:
    return all(character in "0123456789abcdefABCDEF" for character in value)

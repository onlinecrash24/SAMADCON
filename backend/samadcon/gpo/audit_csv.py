"""The advanced audit policy — ``Machine/Microsoft/Windows NT/Audit/audit.csv``.

Computer configuration only. Measured on a file the German GPMC wrote for a
reference GPO, and every detail below comes from that file rather than from
documentation:

* **UTF-8 without a byte-order mark, CRLF line endings, seven columns.**
* **The header and the texts are in the language of the GPMC that wrote the
  file.** A German console wrote ``Computername,Richtlinienziel,…`` and
  ``Anmelden überwachen`` / ``Erfolg und Fehler``. What a client acts on is
  the subcategory's GUID in column four and the number in column seven —
  0 no auditing, 1 success, 2 failure, 3 both — so the file is read by column
  position and never by header name.
* **The GUID is written in lower case, in braces**, the policy target is
  ``System``, the machine name and the exclusion column are empty.

Rows SAMADCON does not edit — options such as ``Option:CrashOnAuditFail``,
the global object access lists — are kept as they are. A file this code does
not fully understand is written back whole, not thinned out to what it knows.

A subcategory that is *not configured* has no row. "No auditing" is a row with
the value 0, and is not the same thing: it switches the subcategory off on the
client, where an absent row leaves whatever else configured it in charge.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest
from samadcon.gpo import container, cse, sysvol

logger = logging.getLogger(__name__)

AUDIT_PATH = "Machine\\Microsoft\\Windows NT\\Audit\\audit.csv"
NEWLINE = "\r\n"

# The header a new file gets, as an English GPMC writes it. An existing file
# keeps its own: rewriting a German header in English would be a change nobody
# asked for.
HEADER_EN = [
    "Machine Name",
    "Policy Target",
    "Subcategory",
    "Subcategory GUID",
    "Inclusion Setting",
    "Exclusion Setting",
    "Setting Value",
]
# Measured: the header the German GPMC wrote.
HEADER_DE = [
    "Computername",
    "Richtlinienziel",
    "Unterkategorie",
    "Unterkategorie-GUID",
    "Aufnahmeeinstellung",
    "Ausschlusseinstellung",
    "Einstellungswert",
]

# The text in the inclusion column, per value. Measured in German: 1
# "Erfolgreich", 3 "Erfolg und Fehler". The others are what the console shows
# for those choices; a client reads column seven, not this.
INCLUSION = {
    "en": {0: "No Auditing", 1: "Success", 2: "Failure", 3: "Success and Failure"},
    "de": {0: "Keine Überwachung", 1: "Erfolgreich", 2: "Fehler", 3: "Erfolg und Fehler"},
}
VALUES = (0, 1, 2, 3)

_GUID = re.compile(r"^\{[0-9a-fA-F-]{36}\}$")

# ---------------------------------------------------------------------------
# The subcategories
# ---------------------------------------------------------------------------

# Read off `auditpol /list /subcategory:* /v` on a German Windows 11 in
# September 2026: categories, subcategories, GUIDs and German names as Windows
# itself reports them. The English names are the ones the same command prints
# on an English Windows. ("Plug & Play" is printed "Plug &amp; Play" by the
# German auditpol; the entity is Windows' mistake, not the name.)
def _category(code: str) -> str:
    return "{" + code + "-797A-11D9-BED3-505054503030}"


def _subcategory(code: str) -> str:
    """Every subcategory GUID is {0CCExxxx-69AE-11D9-BED3-505054503030}; the
    table below carries the four digits that differ."""
    return "{0CCE" + code + "-69AE-11D9-BED3-505054503030}"


CATEGORIES: list[dict[str, Any]] = [
    {"guid": _category("69979848"), "de": "System", "en": "System",
     "subcategories": [
         ("9210", "Sicherheitsstatusänderung", "Security State Change"),
         ("9211", "Sicherheitssystemerweiterung", "Security System Extension"),
         ("9212", "Systemintegrität", "System Integrity"),
         ("9213", "IPSEC-Treiber", "IPsec Driver"),
         ("9214", "Andere Systemereignisse", "Other System Events"),
     ]},
    {"guid": _category("69979849"), "de": "An-/Abmeldung", "en": "Logon/Logoff",
     "subcategories": [
         ("9215", "Anmelden", "Logon"),
         ("9216", "Abmelden", "Logoff"),
         ("9217", "Kontosperrung", "Account Lockout"),
         ("9218", "IPsec-Hauptmodus", "IPsec Main Mode"),
         ("9219", "IPsec-Schnellmodus", "IPsec Quick Mode"),
         ("921A", "IPsec-Erweiterungsmodus", "IPsec Extended Mode"),
         ("921B", "Spezielle Anmeldung", "Special Logon"),
         ("921C", "Andere Anmelde-/Abmeldeereignisse", "Other Logon/Logoff Events"),
         ("9243", "Netzwerkrichtlinienserver", "Network Policy Server"),
         ("9247", "Benutzer-/Geräteansprüche", "User / Device Claims"),
         ("9249", "Gruppenmitgliedschaft", "Group Membership"),
         ("924B", "Zugriffsrechte", "Access Rights"),
     ]},
    {"guid": _category("6997984A"), "de": "Objektzugriff", "en": "Object Access",
     "subcategories": [
         ("921D", "Dateisystem", "File System"),
         ("921E", "Registrierung", "Registry"),
         ("921F", "Kernelobjekt", "Kernel Object"),
         ("9220", "SAM", "SAM"),
         ("9221", "Zertifizierungsdienste", "Certification Services"),
         ("9222", "Anwendung wurde generiert.", "Application Generated"),
         ("9223", "Handleänderung", "Handle Manipulation"),
         ("9224", "Dateifreigabe", "File Share"),
         ("9225", "Filterplattform: Verworfene Pakete", "Filtering Platform Packet Drop"),
         ("9226", "Filterplattformverbindung", "Filtering Platform Connection"),
         ("9227", "Andere Objektzugriffsereignisse", "Other Object Access Events"),
         ("9244", "Detaillierte Dateifreigabe", "Detailed File Share"),
         ("9245", "Wechselmedien", "Removable Storage"),
         ("9246", "Staging zentraler Richtlinien", "Central Policy Staging"),
     ]},
    {"guid": _category("6997984B"), "de": "Berechtigungen", "en": "Privilege Use",
     "subcategories": [
         ("9228", "Sensible Verwendung von Rechten", "Sensitive Privilege Use"),
         ("9229", "Nicht sensible Verwendung von Rechten", "Non Sensitive Privilege Use"),
         ("922A", "Andere Rechteverwendungsereignisse", "Other Privilege Use Events"),
     ]},
    {"guid": _category("6997984C"), "de": "Detaillierte Nachverfolgung", "en": "Detailed Tracking",
     "subcategories": [
         ("922B", "Prozesserstellung", "Process Creation"),
         ("922C", "Prozessbeendigung", "Process Termination"),
         ("922D", "DPAPI-Aktivität", "DPAPI Activity"),
         ("922E", "RPC-Ereignisse", "RPC Events"),
         ("9248", "Plug & Play-Ereignisse", "Plug and Play Events"),
         ("924A", "Ereignisse zu angepassten Tokenrechten", "Token Right Adjusted Events"),
     ]},
    {"guid": _category("6997984D"), "de": "Richtlinienänderung", "en": "Policy Change",
     "subcategories": [
         ("922F", "Richtlinienänderungen überwachen", "Audit Policy Change"),
         ("9230", "Authentifizierungsrichtlinienänderung", "Authentication Policy Change"),
         ("9231", "Autorisierungsrichtlinienänderung", "Authorization Policy Change"),
         ("9232", "MPSSVC-Richtlinienänderung auf Regelebene", "MPSSVC Rule-Level Policy Change"),
         ("9233", "Filterplattform-Richtlinienänderung", "Filtering Platform Policy Change"),
         ("9234", "Andere Richtlinienänderungsereignisse", "Other Policy Change Events"),
     ]},
    {"guid": _category("6997984E"), "de": "Kontenverwaltung", "en": "Account Management",
     "subcategories": [
         ("9235", "Benutzerkontenverwaltung", "User Account Management"),
         ("9236", "Computerkontoverwaltung", "Computer Account Management"),
         ("9237", "Sicherheitsgruppenverwaltung", "Security Group Management"),
         ("9238", "Verteilergruppenverwaltung", "Distribution Group Management"),
         ("9239", "Anwendungsgruppenverwaltung", "Application Group Management"),
         ("923A", "Andere Kontoverwaltungsereignisse", "Other Account Management Events"),
     ]},
    {"guid": _category("6997984F"), "de": "DS-Zugriff", "en": "DS Access",
     "subcategories": [
         ("923B", "Verzeichnisdienstzugriff", "Directory Service Access"),
         ("923C", "Verzeichnisdienständerungen", "Directory Service Changes"),
         ("923D", "Verzeichnisdienstreplikation", "Directory Service Replication"),
         ("923E", "Detaillierte Verzeichnisdienstreplikation",
          "Detailed Directory Service Replication"),
     ]},
    {"guid": _category("69979850"), "de": "Kontoanmeldung", "en": "Account Logon",
     "subcategories": [
         ("923F", "Überprüfung der Anmeldeinformationen", "Credential Validation"),
         ("9240", "Ticketvorgänge des Kerberos-Diensts", "Kerberos Service Ticket Operations"),
         ("9241", "Andere Kontoanmeldungsereignisse", "Other Account Logon Events"),
         ("9242", "Kerberos-Authentifizierungsdienst", "Kerberos Authentication Service"),
     ]},
]

#: Subcategory GUID (lower case) -> (German name, English name).
SUBCATEGORIES: dict[str, tuple[str, str]] = {
    _subcategory(code).lower(): (german, english)
    for category in CATEGORIES
    for code, german, english in category["subcategories"]
}


def describe_catalogue() -> dict[str, Any]:
    """The catalogue for the editor, with the GUIDs in the form the file uses."""
    return {
        "categories": [
            {
                "guid": category["guid"].lower(),
                "de": category["de"],
                "en": category["en"],
                "subcategories": [
                    {"guid": _subcategory(code).lower(), "de": german, "en": english}
                    for code, german, english in category["subcategories"]
                ],
            }
            for category in CATEGORIES
        ],
        "values": list(VALUES),
    }


def _row_label(guid: str, language: str) -> str:
    """The subcategory text GPMC writes: "Anmelden überwachen", "Audit Logon"."""
    german, english = SUBCATEGORIES[guid]
    return f"{german} überwachen" if language == "de" else f"Audit {english}"


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


class AuditFile:
    """The header and the rows, as they stand in the file."""

    def __init__(self, header: list[str], rows: list[list[str]]) -> None:
        self.header = header
        self.rows = rows

    @property
    def language(self) -> str:
        """The language the file's texts were written in, from its header."""
        return "de" if self.header and self.header[0] == HEADER_DE[0] else "en"

    def settings(self) -> dict[str, int]:
        """Configured subcategories: GUID (lower case) -> value."""
        found: dict[str, int] = {}
        for row in self.rows:
            guid = _row_guid(row)
            if guid is None:
                continue
            try:
                found[guid] = int(row[6])
            except (IndexError, ValueError):
                continue
        return found


def _row_guid(row: list[str]) -> str | None:
    """The subcategory a row configures, or None for an option or a SACL row."""
    if len(row) < 7:
        return None
    guid = row[3].strip()
    return guid.lower() if _GUID.match(guid) else None


def parse(raw: bytes | None) -> AuditFile:
    """Read the file. A byte-order mark is tolerated, though GPMC writes none."""
    if not raw:
        return AuditFile(list(HEADER_EN), [])
    text = raw.decode("utf-8-sig")
    rows = [row for row in csv.reader(io.StringIO(text)) if row]
    if not rows:
        return AuditFile(list(HEADER_EN), [])
    return AuditFile(rows[0], rows[1:])


def render(audit: AuditFile) -> bytes:
    """Write the file as GPMC does: UTF-8, no byte-order mark, CRLF."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=NEWLINE)
    writer.writerow(audit.header)
    writer.writerows(audit.rows)
    return buffer.getvalue().encode("utf-8")


def apply(audit: AuditFile, changes: dict[str, int | None]) -> AuditFile:
    """*audit* with each subcategory in *changes* set to its value, or removed
    for None. Rows are changed in place, new ones appended in catalogue order,
    and every other row is left exactly as it was."""
    wanted = {_check_guid(guid): _check_value(value) for guid, value in changes.items()}
    language = audit.language
    rows: list[list[str]] = []
    seen: set[str] = set()

    for row in audit.rows:
        guid = _row_guid(row)
        if guid is None or guid not in wanted:
            rows.append(row)
            continue
        seen.add(guid)
        value = wanted[guid]
        if value is not None:
            rows.append(_row(guid, value, language, like=row))

    order = list(SUBCATEGORIES)
    for guid in sorted(wanted, key=order.index):
        value = wanted[guid]
        if guid not in seen and value is not None:
            rows.append(_row(guid, value, language))

    return AuditFile(audit.header, rows)


def _row(guid: str, value: int, language: str, like: list[str] | None = None) -> list[str]:
    """A subcategory row. An existing row keeps its machine name, target and
    exclusion column; only its label, inclusion text and value change."""
    machine, target, exclusion = ("", "System", "") if like is None else (like[0], like[1], like[5])
    return [
        machine,
        target,
        _row_label(guid, language),
        guid,
        INCLUSION[language][value],
        exclusion,
        str(value),
    ]


def _check_guid(guid: str) -> str:
    key = guid.strip().lower()
    if key not in SUBCATEGORIES:
        raise InvalidRequest(
            "Unknown audit subcategory.",
            code="unknown_audit_subcategory",
            context={"guid": guid},
        )
    return key


def _check_value(value: int | None) -> int | None:
    if value is not None and value not in VALUES:
        raise InvalidRequest(
            "An audit setting is 0 (no auditing), 1 (success), 2 (failure) or 3 (both).",
            code="invalid_audit_value",
            context={"value": value},
        )
    return value


# ---------------------------------------------------------------------------
# One GPO
# ---------------------------------------------------------------------------


def read(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """The advanced audit settings of one GPO."""
    gpo = container.get_gpo(conn, dn)
    raw = _read_file(conn, gpo)
    return {
        "dn": dn,
        "present": raw is not None,
        "version_number": gpo["version"],
        "registered": cse.is_registered(conn, dn, "Machine", cse.AUDIT_CSE),
        "settings": parse(raw).settings() if raw is not None else {},
    }


def write(
    conn: DirectoryConnection,
    dn: str,
    changes: dict[str, int | None],
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Set or clear subcategories, and register the extension that applies them.

    Registered and not unregistered, as with the security settings — and for
    the same reason: a client reverts what it applied earlier by running the
    extension and finding the row gone.
    """
    gpo = container.get_gpo(conn, dn)
    if expected_version is not None and gpo["version"] != expected_version:
        raise Conflict(
            "This policy was changed by someone else in the meantime.",
            code="gpo_version_conflict",
            hint="Reload the settings and make the change again.",
            context={"expected": expected_version, "current": gpo["version"]},
        )
    if not gpo["path"]:
        raise InvalidRequest(
            "This policy has no SYSVOL path.", code="gpo_without_path", context={"dn": dn}
        )

    current = _read_file(conn, gpo)
    updated = render(apply(parse(current), changes))
    if current is not None and updated == current:
        return {"dn": dn, "changed": False, "version": gpo["version"]}

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    target = share.resolve(base, AUDIT_PATH) or sysvol.join(base, AUDIT_PATH)
    share.makedirs(target.rsplit("\\", 1)[0])
    share.write(target, updated)

    cse.register(conn, dn, "Machine", cse.AUDIT_CSE, cse.AUDIT_TOOL)
    after = container.bump_version(conn, dn, machine_changed=True, user_changed=False)
    logger.info("set %d audit subcategories in %s", len(changes), gpo["display_name"])
    return {"dn": dn, "changed": True, "version": after["version"]}


def _read_file(conn: DirectoryConnection, gpo: dict[str, Any]) -> bytes | None:
    if not gpo["path"]:
        return None
    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    resolved = share.resolve(base, AUDIT_PATH)
    return None if resolved is None else share.read(resolved)

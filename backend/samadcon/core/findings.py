"""What is worth telling an administrator about this domain, and why.

The binding half of both reports — the domain's security and its group
policies. Every finding here is decided by a
rule over values the tool already reads, carries the values it was decided
from, and says the same thing on every run. Nothing here asks a language
model anything; the model's part is to explain and prioritise what this
produces, in a place the interface keeps visibly separate.

Two kinds of statement are mixed in on purpose, and the severity says which:

* **Facts about consequences.** Reversible password storage means the domain
  can hand out the plaintext. No lockout threshold means an attacker may guess
  for as long as they like. These do not depend on anyone's opinion.
* **Conventions.** That a password should be at least eight characters is a
  widely held convention, not a law of nature. Findings that rest on one carry
  the threshold in their evidence, so a reader can disagree with the number
  rather than with the finding.

**Rules deliberately not written** matter as much as the ones that are:

* *Passwords that never expire* are not reported. Forced rotation was standard
  advice for decades and is no longer — NIST dropped it, on the grounds that
  it pushes people towards predictable variations. Flagging it would spread
  advice its own authors withdrew.
* *Locked or disabled accounts* are not reported. They are operational facts
  the diagnostics view already lists, and repeating them here as findings
  would bury the ones that need a decision.

The module is a pure function over data someone else fetched. That keeps a
network round trip out of the rules and makes each one testable on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# High to low. Used for sorting, so the order of the tuple is the order the
# report shows.
SEVERITIES = ("high", "medium", "low", "info")

# The convention this module measures a password policy against. Named rather
# than inlined, because a reader who disagrees should be able to see the number
# and find every finding that rests on it.
MIN_PASSWORD_LENGTH = 8

# How old the krbtgt password may be. A convention as well: its key signs
# every ticket in the domain, a copy of it forges them for as long as it is
# unchanged, and nothing ever changes it by itself.
MAX_KRBTGT_PASSWORD_DAYS = 365

# The month in which the Samba team stopped maintaining a 4.x series, from
# wiki.samba.org "Samba Release Planning" as edited on 16 October 2026. The
# last three are that page's forecast. A series newer than this table says
# nothing, and one older than it ended before the table begins.
#
# THIS TABLE AGES. A new series appears every six months; add it then.
SAMBA_SERIES_AS_OF = "2026-10-16"
SAMBA_SERIES_END: dict[int, tuple[int, int]] = {
    15: (2023, 3),
    16: (2023, 9),
    17: (2024, 3),
    18: (2024, 9),
    19: (2025, 3),
    20: (2025, 9),
    21: (2026, 3),
    22: (2026, 9),
    23: (2027, 3),
    24: (2027, 9),
    25: (2028, 3),
}
_SAMBA_VERSION = re.compile(r"^\s*4\.(\d{1,3})\.\d")


@dataclass(frozen=True)
class Finding:
    """One thing worth saying, with what it was decided from.

    ``id`` is stable and is what the interface translates; the text lives with
    the other messages rather than here, so a finding reads in the language the
    console is set to.
    """

    id: str
    severity: str
    area: str
    #: What this is about — a policy's name, say. Empty for findings about
    #: the domain itself, which are one of a kind; policy findings are not,
    #: and several can share an id.
    subject: str = ""
    #: The values the rule looked at. Present so a finding can be checked
    #: rather than believed.
    evidence: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "area": self.area,
            "subject": self.subject,
            "evidence": self.evidence,
        }


def evaluate(
    *,
    policy: dict[str, Any] | None = None,
    replication: dict[str, Any] | None = None,
    connection: dict[str, Any] | None = None,
    members: dict[str, Any] | None = None,
    accounts: dict[str, Any] | None = None,
    domain: dict[str, Any] | None = None,
    today: date | None = None,
) -> list[Finding]:
    """Every finding these inputs support, worst first.

    Each argument may be absent: a caller that could not read one part still
    gets the findings for the parts it could. Reporting nothing about a section
    is honest; guessing at it is not.

    `today` is for the two rules that measure against the calendar, and is
    an argument so that they say the same thing in a test as in a year.
    """
    today = today or date.today()
    found: list[Finding] = []
    if accounts is not None:
        found.extend(_accounts(accounts, today))
    if domain is not None:
        found.extend(_samba_series(domain, today))
    if policy is not None:
        found.extend(_password_policy(policy))
    if replication is not None:
        found.extend(_replication(replication))
    if connection is not None:
        found.extend(_connection(connection))
    if members is not None:
        found.extend(_members(members))

    order = {name: index for index, name in enumerate(SEVERITIES)}
    found.sort(key=lambda finding: (order.get(finding.severity, len(order)), finding.id))
    return found


def evaluate_policies(
    gpos: list[dict[str, Any]],
    *,
    links: dict[str, list[dict[str, Any]]],
    deep: dict[str, list[str]] | None = None,
) -> list[Finding]:
    """Every finding about the domain's group policies, worst first.

    The shallow rules need nothing but the directory: a policy that reaches
    nobody looks exactly like one that works, and no console says which is
    which. The `deep` argument carries what only SYSVOL can answer —
    content that no registered extension will apply, and a version the two
    halves disagree about — and is absent when the report was not asked to
    go that far.
    """
    found: list[Finding] = []
    for gpo in gpos:
        name = gpo.get("display_name") or gpo.get("name") or ""
        guid = (gpo.get("guid") or "").upper()
        here = links.get(guid, [])

        if not here:
            # Not a fault — a policy may be staged deliberately — but it
            # applies to nobody, and that is invisible from its own page.
            found.append(
                Finding(
                    id="gpo_not_linked",
                    severity="low",
                    area="policies",
                    subject=name,
                    evidence={"guid": guid},
                )
            )
        elif not any(link.get("enabled") for link in here):
            found.append(
                Finding(
                    id="gpo_all_links_disabled",
                    severity="low",
                    area="policies",
                    subject=name,
                    evidence={"links": len(here)},
                )
            )

        if not gpo.get("machine_enabled") and not gpo.get("user_enabled"):
            found.append(
                Finding(
                    id="gpo_both_halves_disabled",
                    severity="low",
                    area="policies",
                    subject=name,
                    evidence={},
                )
            )
        elif here and not gpo.get("machine_extensions") and not gpo.get(
            "user_extensions"
        ):
            # Linked, switched on, and registering nothing: the link does
            # nothing at all, which reads as a working policy everywhere.
            found.append(
                Finding(
                    id="gpo_linked_but_empty",
                    severity="medium",
                    area="policies",
                    subject=name,
                    evidence={"links": len(here)},
                )
            )

        for problem in (deep or {}).get(guid, []):
            found.append(
                Finding(
                    id=f"gpo_{problem}",
                    # A path to another policy's folder means this GPO applies
                    # that policy's settings wherever it is linked.
                    severity=(
                        "high"
                        if "content_without_extension" in problem or problem == "path_mismatch"
                        else "medium"
                    ),
                    area="policies",
                    subject=name,
                    evidence={},
                )
            )

    order = {name: index for index, name in enumerate(SEVERITIES)}
    found.sort(
        key=lambda finding: (
            order.get(finding.severity, len(order)),
            finding.subject.lower(),
            finding.id,
        )
    )
    return found


def _password_policy(policy: dict[str, Any]) -> list[Finding]:
    found: list[Finding] = []

    if policy.get("reversible_encryption"):
        # Not a convention: the domain stores passwords it can hand back.
        found.append(
            Finding(
                id="password_reversible_encryption",
                severity="high",
                area="password_policy",
                evidence={"reversible_encryption": True},
            )
        )

    threshold = policy.get("lockout_threshold")
    if threshold == 0:
        found.append(
            Finding(
                id="password_no_lockout",
                severity="medium",
                area="password_policy",
                evidence={"lockout_threshold": 0},
            )
        )

    length = policy.get("min_length")
    if isinstance(length, int) and length < MIN_PASSWORD_LENGTH:
        found.append(
            Finding(
                id="password_short_minimum",
                severity="medium",
                area="password_policy",
                evidence={"min_length": length, "convention": MIN_PASSWORD_LENGTH},
            )
        )

    if policy.get("complexity") is False:
        found.append(
            Finding(
                id="password_no_complexity",
                severity="low",
                area="password_policy",
                evidence={"complexity": False},
            )
        )

    objects = policy.get("password_settings_objects") or []
    if objects:
        # Not a fault. It is the reason the findings above may not describe
        # everyone: a PSO overrides the domain policy for whoever it applies
        # to, and a reader who takes the domain policy for the whole answer
        # draws a wrong conclusion.
        found.append(
            Finding(
                id="password_settings_objects_present",
                severity="info",
                area="password_policy",
                evidence={"count": len(objects)},
            )
        )

    return found


def _replication(replication: dict[str, Any]) -> list[Finding]:
    failing = replication.get("failing") or 0
    if not failing:
        return []
    return [
        Finding(
            id="replication_failing",
            severity="high",
            area="replication",
            evidence={
                "failing": failing,
                "partners": len(replication.get("neighbours") or []),
                "dc": replication.get("dc"),
            },
        )
    ]



def _members(members: dict[str, Any]) -> list[Finding]:
    """What a computer account's trust with the domain is worth.

    Two rules, one per machine, and both about something the machine can do
    rather than something it happens to be doing.

    Everything else this listing carries — operating system, last logon, an
    unset encryption list — is context and not a finding. In particular an
    absent msDS-SupportedEncryptionTypes is not a weakness: it leaves the
    choice to the KDC, which on a current Samba or Windows includes AES. A
    rule on it would mark most healthy domains.
    """
    found: list[Finding] = []

    for member in members.get("members") or []:
        name = member.get("name") or member.get("dn") or ""

        # Expected on a domain controller and alarming on anything else, so
        # the DCs are skipped rather than explained away in the text.
        if member.get("delegation") == "unconstrained" and not member.get(
            "is_domain_controller"
        ):
            found.append(
                Finding(
                    id="member_unconstrained_delegation",
                    severity="high",
                    area="members",
                    subject=name,
                    evidence={
                        "operating_system": member.get("operating_system"),
                        "enabled": member.get("enabled"),
                    },
                )
            )

        weak = (member.get("encryption") or {}).get("weak") or []
        if weak:
            found.append(
                Finding(
                    id="member_weak_encryption",
                    severity="high",
                    area="members",
                    subject=name,
                    evidence={"ciphers": ", ".join(weak)},
                )
            )

    return found

def _accounts(read: dict[str, Any], today: date) -> list[Finding]:
    """What accounts and three settings of the domain give away.

    Prompted by a tester's own audit tool and measured on a Samba domain
    before a line was written. Every exception below is something that
    measurement found in a domain nobody had touched:

    * a disabled account raises nothing — the guest account carries
      PASSWD_NOTREQD in every domain, disabled;
    * krbtgt's own service name and the guest are not accounts here at all;
      the reader keeps them apart;
    * Authenticated Users in the pre-Windows 2000 group is what a provision
      puts there, so only Everyone and Anonymous are reported.

    Deliberately absent: a machine password that was never changed. A Samba
    DC never changes its own, so the rule would mark every one of them.
    """
    found: list[Finding] = []

    guest = read.get("guest")
    if guest and guest.get("enabled"):
        found.append(
            Finding(
                id="guest_enabled",
                severity="high",
                area="accounts",
                subject=guest.get("name") or "",
                evidence={"enabled": True},
            )
        )

    for account in read.get("accounts") or []:
        if not account.get("enabled"):
            continue
        name = account.get("name") or account.get("dn") or ""
        privileged = bool(account.get("privileged"))

        if account.get("no_preauth"):
            # Not a convention: the KDC hands out material encrypted with
            # this password to anyone who asks, signed in or not.
            found.append(
                Finding(
                    id="account_no_preauth",
                    severity="high",
                    area="accounts",
                    subject=name,
                    evidence={"privileged": privileged},
                )
            )

        spns = account.get("spns") or []
        if spns:
            # Any signed-in user may ask for a ticket to it and guess at the
            # password offline. A person's password gives; a machine's
            # does not, which is why computers are not looked at.
            found.append(
                Finding(
                    id="account_with_spn",
                    severity="high" if privileged else "medium",
                    area="accounts",
                    subject=name,
                    evidence={"spn": spns[0], "count": len(spns), "privileged": privileged},
                )
            )

        if account.get("password_not_required"):
            found.append(
                Finding(
                    id="account_password_not_required",
                    severity="medium",
                    area="accounts",
                    subject=name,
                    evidence={"privileged": privileged},
                )
            )

    last_set = read.get("krbtgt_password_last_set")
    if last_set is not None:
        age = (today - last_set.date()).days
        if age > MAX_KRBTGT_PASSWORD_DAYS:
            found.append(
                Finding(
                    id="krbtgt_password_old",
                    severity="medium",
                    area="accounts",
                    evidence={
                        "age_days": age,
                        "convention": MAX_KRBTGT_PASSWORD_DAYS,
                        "last_set": last_set.date().isoformat(),
                    },
                )
            )

    opened = read.get("pre_windows_2000_open") or []
    if opened:
        found.append(
            Finding(
                id="pre_windows_2000_open",
                severity="medium",
                area="domain",
                evidence={"members": ", ".join(opened)},
            )
        )

    quota = read.get("machine_account_quota")
    if isinstance(quota, int) and quota > 0:
        # The default of ten, in every domain nobody changed. Low for that
        # reason: true and worth a decision, and not an alarm.
        found.append(
            Finding(
                id="machine_account_quota",
                severity="low",
                area="domain",
                evidence={"quota": quota},
            )
        )

    return found


def _samba_series(domain: dict[str, Any], today: date) -> list[Finding]:
    """Whether the Samba team still maintains the series this DC runs.

    A note, not an alarm. A distribution may well patch a series the Samba
    team has dropped — Debian does — and only its maintainer can say. What
    this tells the reader is whom to ask.

    The version is the rootDSE's and nothing else. The DC's computer object
    carries one too, written when the domain was provisioned and not when it
    was upgraded: measured as 4.17.12 on a DC running 4.22.11.
    """
    if not (domain.get("vendor") or "").strip().lower().startswith("samba"):
        return []
    version = domain.get("vendor_version") or ""
    match = _SAMBA_VERSION.match(version)
    if match is None:
        return []

    series = int(match.group(1))
    if series > max(SAMBA_SERIES_END):
        return []

    end = SAMBA_SERIES_END.get(series)
    # Maintained through the month the table names.
    if end is not None and (today.year, today.month) <= end:
        return []

    return [
        Finding(
            id="samba_series_unmaintained",
            severity="info",
            area="domain",
            evidence={
                "version": version,
                "series": f"4.{series}",
                "maintained_until": f"{end[0]}-{end[1]:02d}" if end else "before 2023",
                "table_as_of": SAMBA_SERIES_AS_OF,
            },
        )
    ]


def _connection(connection: dict[str, Any]) -> list[Finding]:
    # Only LDAPS involves a certificate. Under Kerberos the DC proves itself by
    # decrypting the ticket, so there is nothing here to have skipped — and a
    # finding saying otherwise would report a weakness that does not exist.
    if connection.get("certificate_verified") is not False:
        return []
    return [
        Finding(
            id="connection_certificate_unverified",
            severity="medium",
            area="connection",
            evidence={
                "transport": connection.get("transport"),
                "url": connection.get("url"),
            },
        )
    ]

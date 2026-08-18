"""What is worth telling an administrator about this domain, and why.

The binding half of the security report. Every finding here is decided by a
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

from dataclasses import dataclass, field
from typing import Any

# High to low. Used for sorting, so the order of the tuple is the order the
# report shows.
SEVERITIES = ("high", "medium", "low", "info")

# The convention this module measures a password policy against. Named rather
# than inlined, because a reader who disagrees should be able to see the number
# and find every finding that rests on it.
MIN_PASSWORD_LENGTH = 8


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
    #: The values the rule looked at. Present so a finding can be checked
    #: rather than believed.
    evidence: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "area": self.area,
            "evidence": self.evidence,
        }


def evaluate(
    *,
    policy: dict[str, Any] | None = None,
    replication: dict[str, Any] | None = None,
    connection: dict[str, Any] | None = None,
) -> list[Finding]:
    """Every finding these inputs support, worst first.

    Each argument may be absent: a caller that could not read one part still
    gets the findings for the parts it could. Reporting nothing about a section
    is honest; guessing at it is not.
    """
    found: list[Finding] = []
    if policy is not None:
        found.extend(_password_policy(policy))
    if replication is not None:
        found.extend(_replication(replication))
    if connection is not None:
        found.extend(_connection(connection))

    order = {name: index for index, name in enumerate(SEVERITIES)}
    found.sort(key=lambda finding: (order.get(finding.severity, len(order)), finding.id))
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

"""Writing an administrative-template setting into a GPO.

``Registry.pol`` is read, merged and written through SAMADCON's own SYSVOL
connection, and the version through :func:`samadcon.gpo.container.bump_version`
— the same two paths every other editor here uses.

This used to go through ``samba.policies.RegistryGroupPolicies``, on the
argument that it owned the file and both versions and kept them in step. It
did not keep them in step. It writes with a plain ``savefile``, and SMB
refuses that with ACCESS_DENIED on a file marked hidden or read-only — which
SAMADCON's own writer has handled since GPMC's hidden scripts.ini first broke
it. A tester met it in October 2026: ``merge_s`` wrote ``Registry.pol``, then
failed on ``GPT.INI``, so the version never moved. Saving again "worked",
because the value was already in the file and there was nothing left to
write — and every client that had the policy kept the old setting, with no
console showing why. ``registry_pol.parse`` and ``build`` already did the
packing through ``samba.dcerpc.preg``; the merge is a few lines.

Two things belong to this module either way:

* **Registering the client-side extension.** A policy whose values are written
  but whose CSE is not listed in ``gPCMachineExtensionNames`` is read by no
  client. Nothing reports this: the setting is visible in every console and
  simply never applies. It is the single most common way a policy edit ends
  up doing nothing.
* **Keeping that list sorted.** MS-GPOL requires the entries in ascending,
  case-insensitive order. Samba's own helper appends, which is right until
  something was registered before.

The version advances once per save that changed something, in the half that
changed — not again for the registration, which would make every client
re-read the policy for no reason and the version useless as a record of how
often a policy changed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest
from samadcon.gpo import container, cse, registry_pol, sysvol
from samadcon.gpo.admx import resolver
from samadcon.gpo.admx.model import Policy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reading the current state
# ---------------------------------------------------------------------------


def registry_entries(conn: DirectoryConnection, gpo: dict[str, Any], half: str) -> list[dict]:
    """The parsed ``Registry.pol`` of one half, empty when there is none."""
    if not gpo["path"]:
        return []

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    path = share.resolve(base, f"{half}\\Registry.pol")
    if path is None:
        return []
    return registry_pol.parse(share.read(path))


def states_for(
    conn: DirectoryConnection, dn: str, policies: Sequence[Policy], half: str
) -> dict[str, str]:
    """What a GPO says about each of *policies* — the listing's status column.

    One read of the ``Registry.pol`` answers for all of them, which is the
    whole point: asking per setting would be one SMB round trip per row.
    """
    if half not in ("Machine", "User") or not policies:
        return {}

    gpo = container.get_gpo(conn, dn)
    entries = registry_entries(conn, gpo, half)

    return {
        policy.id: str(resolver.state_of(policy, entries)["state"])
        for policy in policies
        if half in policy.halves
    }


def read_state(
    conn: DirectoryConnection, dn: str, policy: Policy, half: str
) -> dict[str, Any]:
    """A policy's current state in one GPO, for filling in the form.

    The version number comes back with it: it is what a later write is
    checked against, so that two administrators editing the same policy do
    not silently overwrite each other.
    """
    _check_half(policy, half)
    gpo = container.get_gpo(conn, dn)
    entries = registry_entries(conn, gpo, half)

    return {
        "gpo": gpo["dn"],
        "policy": policy.id,
        "half": half,
        "version": gpo["version"],
        **resolver.state_of(policy, entries),
    }


def _check_half(policy: Policy, half: str) -> None:
    if half not in ("Machine", "User"):
        raise InvalidRequest(
            "A policy is set in the computer half or the user half.",
            code="unknown_policy_half",
            context={"given": half},
        )
    if half not in policy.halves:
        raise InvalidRequest(
            "This setting does not exist in that half of the policy.",
            code="wrong_policy_half",
            context={"policy": policy.name, "half": half, "supported": list(policy.halves)},
        )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def apply_state(
    conn: DirectoryConnection,
    dn: str,
    policy: Policy,
    half: str,
    state: str,
    element_values: dict[str, Any] | None = None,
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Set a policy in a GPO, and register the extension that applies it."""
    _check_half(policy, half)

    gpo = container.get_gpo(conn, dn)
    if expected_version is not None and gpo["version"] != expected_version:
        raise Conflict(
            "This policy was changed by someone else in the meantime.",
            code="gpo_version_conflict",
            hint="Reload the setting and make the change again.",
            context={"expected": expected_version, "current": gpo["version"]},
        )

    current = registry_entries(conn, gpo, half)
    desired = resolver.entries_for(policy, state, element_values)  # type: ignore[arg-type]
    plan = resolver.plan(policy, current, desired)

    if plan.empty:
        # Nothing to write into Registry.pol. Saying so beats advancing the
        # version and making every client in the domain re-read a policy that
        # did not change.
        #
        # The registration is still reconciled, and that is not belt and
        # braces: a half emptied before this code existed — or by a tool that
        # does not unregister — keeps an extension registered with nothing to
        # apply, and returning here first left no way back. `current` is
        # already in hand, so this costs no extra read, and the attribute is
        # written only when it actually disagrees.
        register_extension(conn, dn, half, present=bool(current))
        return {"dn": dn, "changed": False, "version": gpo["version"]}

    remaining = write_entries(conn, dn, gpo, half, current, plan)
    register_extension(conn, dn, half, present=bool(remaining))

    updated = container.get_gpo(conn, dn)
    logger.info(
        "set %s to %s in %s (%s half)", policy.name, state, gpo["display_name"], half.lower()
    )
    return {
        "dn": dn,
        "changed": True,
        "version": updated["version"],
        "written": len(plan.set),
        "removed": len(plan.remove),
    }


def write_entries(
    conn: DirectoryConnection,
    dn: str,
    gpo: dict[str, Any],
    half: str,
    current: list[dict[str, Any]],
    plan: resolver.Plan,
) -> list[dict[str, Any]]:
    """Write *plan* into this half's ``Registry.pol`` and advance its version.

    *current* is the file as it was read for the plan. Both writes go through
    the hidden-aware SYSVOL writer. Returns what the file holds afterwards,
    which decides whether the extension stays registered.
    """
    if not gpo["path"]:
        raise InvalidRequest(
            "This policy has no SYSVOL path.", code="gpo_without_path", context={"dn": dn}
        )

    merged = registry_pol.merge(
        current,
        [
            {"key": entry.key, "value": entry.value_name, "type": entry.type, "data": entry.data}
            for entry in plan.set
        ],
        [(entry.key, entry.value_name) for entry in plan.remove],
    )

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    target = share.resolve(base, f"{half}\\Registry.pol") or sysvol.join(
        base, half, "Registry.pol"
    )
    share.makedirs(target.rsplit("\\", 1)[0])
    share.write(target, registry_pol.build(merged))

    container.bump_version(
        conn, dn, machine_changed=half == "Machine", user_changed=half == "User"
    )
    return merged


# ---------------------------------------------------------------------------
# The extension registration
# ---------------------------------------------------------------------------


def register_extension(
    conn: DirectoryConnection, dn: str, half: str, *, present: bool = True
) -> str | None:
    """List or unlist this GPO's registry extension for *half*.

    The list itself lives in ``samadcon.gpo.cse``: scripts and folder
    redirection register in the same attribute, and the sorting it requires
    has to take their entries into account too.

    An emptied half is unlisted, which was read off GPMC rather than reasoned
    about — and the reasoning would have got it wrong. It looked as though the
    registration had to stay, since a client clears a value it applied earlier
    by running the extension and finding the value gone. GPMC does not agree:
    setting a GPO's only administrative template back to "not configured"
    leaves ``gPCMachineExtensionNames`` holding a single space.
    """
    return cse.register(conn, dn, half, cse.REGISTRY_CSE, cse.REGISTRY_TOOL, present=present)

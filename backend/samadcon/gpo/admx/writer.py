"""Writing an administrative-template setting into a GPO.

The values themselves go through ``samba.policies.RegistryGroupPolicies``,
which owns the ``Registry.pol`` file, the ``GPT.INI`` version and the
``versionNumber`` attribute and keeps the three in step. Reimplementing that
would be reimplementing the part of group policy that is hardest to get right
and easiest to get subtly wrong.

Two things it does not do, and this module does:

* **Registering the client-side extension.** A policy whose values are written
  but whose CSE is not listed in ``gPCMachineExtensionNames`` is read by no
  client. Nothing reports this: the setting is visible in every console and
  simply never applies. It is the single most common way a policy edit ends
  up doing nothing.
* **Keeping that list sorted.** MS-GPOL requires the entries in ascending,
  case-insensitive order. Samba's own helper appends, which is right until
  something was registered before.

Note that ``merge_s`` advances the version itself. Calling
``increment_gpt_ini`` afterwards would advance it twice — harmless for
correctness, but it makes every client re-read the policy for no reason and
makes the version useless as a record of how often a policy changed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest, SamadconError
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
        # Nothing to write. Saying so beats advancing the version and making
        # every client in the domain re-read a policy that did not change.
        return {"dn": dn, "changed": False, "version": gpo["version"]}

    policies = _registry_group_policies(conn, gpo)

    if plan.set:
        policies.merge_s(
            [
                {
                    "keyname": entry.key,
                    "valuename": entry.value_name,
                    "class": half.upper(),
                    "type": registry_pol.type_name(entry.type),
                    "data": entry.data,
                }
                for entry in plan.set
            ]
        )
    if plan.remove:
        policies.remove_s(
            [
                {"keyname": entry.key, "valuename": entry.value_name, "class": half.upper()}
                for entry in plan.remove
            ]
        )

    # Re-read rather than subtract the plan from what was there: the file has
    # just been rewritten by Samba's own writer, and it is the authority on
    # what is left. One extra read on save, for an answer that cannot drift.
    register_extension(conn, dn, half, present=bool(registry_entries(conn, gpo, half)))

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


def _registry_group_policies(conn: DirectoryConnection, gpo: dict[str, Any]) -> Any:
    """Samba's own writer for ``Registry.pol``.

    It opens its own SMB connection, so it gets credentials built from the
    session's ticket rather than the ones the LDAP bind has already used.
    """
    try:
        from samba.policies import RegistryGroupPolicies
    except ImportError as exc:  # pragma: no cover - the image always has it
        raise SamadconError(
            "The Samba group policy bindings are not available.",
            code="samba_missing",
            hint="The container image must provide a recent python3-samba.",
        ) from exc

    creds = sysvol.smb_credentials(conn, conn.lp)
    return RegistryGroupPolicies(
        gpo["name"], conn.lp, creds, conn.samdb, conn.info.dc_hostname or conn.host
    )


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

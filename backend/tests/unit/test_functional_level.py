"""The domain and forest functional level: where it stands, what a raise
needs, and the samba-tool command that does it.

SAMADCON shows the raise and does not perform it. msDS-Behavior-Version is
systemOnly; samba-tool writes it on the DC as system. Over LDAP Samba refuses
it, and relax does not help: rootdse_filter_controls drops a control no
module registered from an untrusted (LDAP) request, and relax is not
registered. Measured on a throwaway Samba 4.22 DC, 2026-10-17:
    relax:0 -> LDAP_CONSTRAINT_VIOLATION, "can only be modified as system"
    relax:1 -> LDAP_UNAVAILABLE_CRITICAL_EXTENSION, "critical non-registered control"

The readiness checks are what samba-tool leaves to the administrator: every
DC at the level, functionalprep's revision on CN=ActiveDirectoryUpdate
(forest_update.py and domain_update.py, functional_level_to_version), and the
schema the 4.19 release notes ask for before 2016.

Measured on zmb-ad (Samba 4.22.11, 2026-10-17): domain, crossRef, Partitions
and the one NTDS Settings at 4, nTMixedDomain 0, both revisions 5, schema 69.
A fresh 4.22 domain, measured on the throwaway DC, comes with schema 88 and
both revisions at 16.
"""

from __future__ import annotations

from samadcon.ad import functional_level as fl

MEASURED = fl.State(
    is_samba=True,
    domain_level=4,
    forest_level=4,
    mixed=False,
    other_domain_levels=(),
    controllers=(fl.Controller("ZMB-AD", 4),),
    forest_revision=5,
    domain_revision=5,
    schema_version=69,
)

# The same domain after the 4.19 release notes' steps for 2016: the DC's
# smb.conf raised and Samba restarted, schemaupgrade --schema=2019, and
# functionalprep --function-level=2016.
READY = fl.State(
    **{
        **MEASURED.__dict__,
        "controllers": (fl.Controller("ZMB-AD", 7),),
        "forest_revision": 16,
        "domain_revision": 16,
        "schema_version": 88,
    }
)


def changed(state: fl.State, **fields) -> fl.State:
    return fl.State(**{**state.__dict__, **fields})


# ---------------------------------------------------------------------------
# What is missing for each level
# ---------------------------------------------------------------------------


def test_the_measured_domain_lacks_the_dc_level_the_schema_and_the_prep_for_2016():
    steps = fl.missing(MEASURED, 7)
    assert [step["step"] for step in steps] == ["dc_level", "schema", "prep"]
    assert steps[0]["controllers"] == ["ZMB-AD"]
    assert steps[0]["setting"] == "ad dc functional level = 2016"
    assert steps[1]["command"] == "samba-tool domain schemaupgrade --schema=2019"
    assert steps[2]["command"] == "samba-tool domain functionalprep --function-level=2016"


def test_2012_r2_needs_no_newer_schema_than_the_measured_one():
    steps = fl.missing(MEASURED, 6)
    assert [step["step"] for step in steps] == ["dc_level", "prep"]
    assert steps[0]["setting"] == "ad dc functional level = 2012_R2"
    assert steps[1]["command"] == "samba-tool domain functionalprep --function-level=2012_R2"


def test_the_prep_is_measured_by_both_revisions():
    # functionalprep runs the forest and the domain part; either one short
    # means it has not run for that level.
    assert [s["step"] for s in fl.missing(changed(READY, forest_revision=15), 7)] == ["prep"]
    assert [s["step"] for s in fl.missing(changed(READY, domain_revision=10), 7)] == ["prep"]
    assert fl.missing(READY, 7) == []


def test_samba_s_revisions_for_each_level():
    # forest_update.py / domain_update.py, functional_level_to_version.
    assert fl.FOREST_PREP == {3: 2, 4: 5, 5: 11, 6: 15, 7: 16}
    assert fl.DOMAIN_PREP == {3: 3, 4: 5, 5: 9, 6: 10, 7: 16}


def test_every_dc_below_the_level_is_named():
    state = changed(
        READY,
        controllers=(fl.Controller("DC1", 7), fl.Controller("DC2", 4), fl.Controller("DC3", 6)),
    )
    assert fl.missing(state, 7)[0]["controllers"] == ["DC2", "DC3"]


def test_a_windows_dc_needs_only_its_own_level():
    # The prep and the schema come with the Windows Server that is installed;
    # a DC of that version cannot join without them.
    state = changed(
        MEASURED,
        is_samba=False,
        controllers=(fl.Controller("WS2016", 7), fl.Controller("WS2012", 6)),
    )
    assert fl.missing(state, 7) == [{"step": "dc_level", "controllers": ["WS2012"]}]


def test_the_targets_offered_start_above_the_forest_and_stop_at_samba_s_last():
    levels = [target["level"] for target in fl.targets(MEASURED)]
    assert levels == [5, 6, 7]


def test_windows_targets_reach_2025_and_skip_the_unused_numbers():
    state = changed(MEASURED, is_samba=False, domain_level=7, forest_level=7)
    assert [target["level"] for target in fl.targets(state)] == [10]


def test_a_target_says_whether_the_domain_moves_too():
    state = changed(READY, domain_level=6, forest_level=5)
    by_level = {target["level"]: target for target in fl.targets(state)}
    assert by_level[6]["domain"] is False
    assert by_level[7]["domain"] is True


# ---------------------------------------------------------------------------
# Reading it from the directory
# ---------------------------------------------------------------------------

BASE = "DC=myantispam,DC=local"
CONFIG = f"CN=Configuration,{BASE}"
SCHEMA = f"CN=Schema,{CONFIG}"
NTDS = f"CN=NTDS Settings,CN=ZMB-AD,CN=Servers,CN=Default-First-Site-Name,CN=Sites,{CONFIG}"


class Info:
    base_dn = BASE
    config_dn = CONFIG
    schema_dn = SCHEMA
    dns_domain = "myantispam.local"
    is_samba = True


class Result:
    def __init__(self, entries):
        self.entries = entries


class Directory:
    """zmb-ad as measured, answering the reads read_state makes."""

    info = Info()

    def __init__(self, objects):
        self.objects = objects

    def get(self, dn, attrs=None):
        return self.objects.get(dn)

    def search(self, base=None, *, scope=None, expression="", attrs=None, **_):
        if "crossRef" in expression:
            return Result([self.objects[f"CN=MYANTISPAM,CN=Partitions,{CONFIG}"]])
        if "nTDSDSA" in expression:
            return Result([self.objects[NTDS]])
        raise AssertionError(expression)


MEASURED_OBJECTS = {
    BASE: {"dn": [BASE], "msDS-Behavior-Version": ["4"], "nTMixedDomain": ["0"]},
    f"CN=Partitions,{CONFIG}": {"msDS-Behavior-Version": ["4"]},
    f"CN=MYANTISPAM,CN=Partitions,{CONFIG}": {
        "distinguishedName": [f"CN=MYANTISPAM,CN=Partitions,{CONFIG}"],
        "nCName": [BASE.upper()],
        "msDS-Behavior-Version": ["4"],
        "nTMixedDomain": ["0"],
    },
    NTDS: {"distinguishedName": [NTDS], "msDS-Behavior-Version": ["4"]},
    f"CN=ActiveDirectoryUpdate,CN=ForestUpdates,{CONFIG}": {"revision": ["5"]},
    f"CN=ActiveDirectoryUpdate,CN=DomainUpdates,CN=System,{BASE}": {"revision": ["5"]},
    SCHEMA: {"objectVersion": ["69"]},
}


def test_the_measured_directory_reads_as_measured():
    assert fl.read_state(Directory(MEASURED_OBJECTS)) == MEASURED


def test_a_dc_without_a_level_counts_as_windows_2000():
    # samba-tool: msDS-Behavior-Version does not exist on Windows 2000 AD.
    objects = {**MEASURED_OBJECTS, NTDS: {"distinguishedName": [NTDS]}}
    assert fl.read_state(Directory(objects)).controllers == (fl.Controller("ZMB-AD", 0),)


def test_a_domain_never_prepared_reads_as_revision_zero():
    objects = dict(MEASURED_OBJECTS)
    del objects[f"CN=ActiveDirectoryUpdate,CN=DomainUpdates,CN=System,{BASE}"]
    assert fl.read_state(Directory(objects)).domain_revision == 0


# ---------------------------------------------------------------------------
# The command for the DC
# ---------------------------------------------------------------------------


def commands(state: fl.State, level: int) -> dict[str, str]:
    return {entry["scope"]: entry["command"] for entry in fl.raise_commands(state, level)}


def test_while_the_domain_is_below_both_or_the_domain_alone_are_offered():
    assert commands(READY, 7) == {
        "both": "samba-tool domain level raise --domain-level=2016 --forest-level=2016",
        "domain": "samba-tool domain level raise --domain-level=2016",
    }
    assert [entry["scope"] for entry in fl.raise_commands(READY, 7)] == ["both", "domain"]


def test_once_the_domain_is_there_only_the_forest_is_offered():
    # samba-tool refuses a forest above the domain.
    assert commands(changed(READY, domain_level=7), 7) == {
        "forest": "samba-tool domain level raise --forest-level=2016",
    }


def test_the_samba_tool_spelling_of_the_level_is_used():
    assert commands(changed(READY, controllers=(fl.Controller("ZMB-AD", 6),)), 6)["domain"] == (
        "samba-tool domain level raise --domain-level=2012_R2"
    )


def test_the_forest_is_not_offered_above_another_domain_of_the_forest():
    assert commands(changed(READY, other_domain_levels=(4,)), 7) == {
        "domain": "samba-tool domain level raise --domain-level=2016",
    }


def test_there_is_no_samba_tool_command_for_a_windows_dc():
    assert fl.raise_commands(changed(READY, is_samba=False), 7) == []


def test_each_target_carries_its_commands():
    by_level = {target["level"]: target for target in fl.targets(READY)}
    assert by_level[7]["raise"] == fl.raise_commands(READY, 7)


def test_samadcon_has_no_way_to_write_the_level():
    """Samba refuses it over LDAP; a route that always fails is not offered."""
    assert not hasattr(fl, "raise_levels")

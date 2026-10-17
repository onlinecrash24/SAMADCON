"""Raising the domain and forest functional level, as samba-tool does it.

The rules are those of ``samba-tool domain level raise`` (Samba 4.22.11,
python/samba/netcmd/domain/level.py): only upwards, the domain never above
the weakest DC, the forest never above the domain. What it writes is what it
writes, in its order. On top of that SAMADCON checks what samba-tool leaves
to the administrator: that ``functionalprep`` ran, read from the revision it
leaves on CN=ActiveDirectoryUpdate (forest_update.py and domain_update.py,
functional_level_to_version), and the schema the 4.19 release notes ask for
before 2016.

Measured on zmb-ad (Samba 4.22.11, 2026-10-17): domain, crossRef, Partitions
and the one NTDS Settings at 4, nTMixedDomain 0, both revisions 5, schema 69.
"""

from __future__ import annotations

import pytest

from samadcon.ad import functional_level as fl
from samadcon.core.errors import Conflict, InvalidRequest

MEASURED = fl.State(
    is_samba=True,
    dns_domain="myantispam.local",
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


def raise_(state: fl.State, *, domain=None, forest=None, confirm="myantispam.local"):
    fl.check_raise(state, domain=domain, forest=forest, confirm=confirm)


def refusal(error_type, state: fl.State, **kwargs):
    with pytest.raises(error_type) as caught:
        raise_(state, **kwargs)
    return caught.value


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
# What is refused
# ---------------------------------------------------------------------------


def test_a_ready_domain_may_be_raised_to_2016():
    raise_(READY, domain=7, forest=7)


def test_on_a_windows_dc_nothing_is_written():
    error = refusal(Conflict, changed(READY, is_samba=False), domain=7)
    assert error.code == "windows_dc_functional_level"


def test_nothing_asked_for_is_refused():
    assert refusal(InvalidRequest, READY).code == "no_changes"


def test_the_domain_name_must_be_typed_to_confirm():
    assert refusal(InvalidRequest, READY, domain=7, confirm="").code == "functional_level_confirm"
    assert refusal(InvalidRequest, READY, domain=7, confirm="other.local").code == (
        "functional_level_confirm"
    )
    raise_(READY, domain=7, confirm=" MyAntiSpam.Local ")


@pytest.mark.parametrize("level", [0, 1, 8, 10, 99])
def test_levels_samba_does_not_know_are_refused(level):
    error = refusal(InvalidRequest, READY, domain=level)
    assert error.code == "functional_level_unknown"
    assert error.context["level"] == level


def test_only_upwards():
    error = refusal(InvalidRequest, READY, domain=4)
    assert (error.code, error.context["reason"]) == ("functional_level_not_higher", "domain")
    error = refusal(InvalidRequest, changed(READY, domain_level=7), forest=3)
    assert (error.code, error.context["reason"]) == ("functional_level_not_higher", "forest")


def test_a_mixed_domain_may_be_raised_to_its_own_level():
    # samba-tool: "<= level_domain and level_domain_mixed == 0" refuses; a
    # mixed domain is raised to clear nTMixedDomain.
    raise_(changed(READY, domain_level=2, forest_level=2, mixed=True), domain=2)


def test_the_domain_never_above_the_weakest_dc():
    state = changed(READY, controllers=(fl.Controller("ZMB-AD", 7), fl.Controller("OLD", 4)))
    error = refusal(Conflict, state, domain=7)
    assert error.code == "functional_level_above_dc"
    assert error.context["controllers"] == "OLD"
    assert error.context["setting"] == "ad dc functional level = 2016"


def test_the_forest_never_above_the_domain():
    error = refusal(Conflict, READY, forest=7)
    assert error.code == "functional_level_forest_above_domain"
    # Raised together, the domain goes first, as in samba-tool.
    raise_(READY, domain=7, forest=7)
    # And never above another domain of the forest.
    error = refusal(Conflict, changed(READY, other_domain_levels=(4,)), domain=7, forest=7)
    assert error.code == "functional_level_forest_above_domain"


def test_without_the_schema_2016_is_refused():
    error = refusal(Conflict, changed(READY, schema_version=69), domain=7)
    assert (error.code, error.context["reason"]) == ("functional_level_not_prepared", "schema")
    assert error.context["command"] == "samba-tool domain schemaupgrade --schema=2019"


def test_without_the_prep_the_raise_is_refused():
    error = refusal(Conflict, changed(READY, domain_revision=5), domain=7)
    assert (error.code, error.context["reason"]) == ("functional_level_not_prepared", "prep")
    assert error.context["command"] == "samba-tool domain functionalprep --function-level=2016"


def test_the_measured_domain_is_refused_for_2016_because_of_its_dc_first():
    assert refusal(Conflict, MEASURED, domain=7).code == "functional_level_above_dc"


# ---------------------------------------------------------------------------
# What is written
# ---------------------------------------------------------------------------


def test_the_domain_is_written_on_its_object_and_its_cross_ref():
    assert fl.writes(READY, domain=7, forest=None) == [
        ("domain", "msDS-Behavior-Version", "7"),
        ("crossref", "msDS-Behavior-Version", "7"),
    ]


def test_the_forest_is_written_on_partitions_after_the_domain():
    assert fl.writes(READY, domain=7, forest=7) == [
        ("domain", "msDS-Behavior-Version", "7"),
        ("crossref", "msDS-Behavior-Version", "7"),
        ("partitions", "msDS-Behavior-Version", "7"),
    ]
    assert fl.writes(changed(READY, domain_level=7), domain=None, forest=7) == [
        ("partitions", "msDS-Behavior-Version", "7"),
    ]


def test_a_mixed_domain_is_made_native_first():
    state = changed(READY, domain_level=0, forest_level=0, mixed=True)
    assert fl.writes(state, domain=2, forest=None) == [
        ("domain", "nTMixedDomain", "0"),
        ("crossref", "nTMixedDomain", "0"),
        ("domain", "msDS-Behavior-Version", "2"),
        ("crossref", "msDS-Behavior-Version", "2"),
    ]


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
# Writing it
# ---------------------------------------------------------------------------

READY_OBJECTS = {
    **MEASURED_OBJECTS,
    NTDS: {"distinguishedName": [NTDS], "msDS-Behavior-Version": ["7"]},
    f"CN=ActiveDirectoryUpdate,CN=ForestUpdates,{CONFIG}": {"revision": ["16"]},
    f"CN=ActiveDirectoryUpdate,CN=DomainUpdates,CN=System,{BASE}": {"revision": ["16"]},
    SCHEMA: {"objectVersion": ["88"]},
}


class Writable(Directory):
    def __init__(self, objects, *, cross_ref_unwilling=False):
        super().__init__(objects)
        self.modified = []
        self.controls = []
        self.cross_ref_unwilling = cross_ref_unwilling

    @property
    def samdb(self):
        import ldb

        return ldb.Ldb()

    def modify(self, message, controls=None):
        from samadcon.ad import values

        dn = str(message.dn)
        # keys(), not iteration: what a pyldb Message iterates over has varied.
        names = [name for name in message.keys() if name != "dn"]  # noqa: SIM118
        changes = {name: values.to_text(message[name][0]) for name in names}
        if self.cross_ref_unwilling and dn.startswith("CN=MYANTISPAM,"):
            # What connection.translate makes of LDB_ERR_UNWILLING_TO_PERFORM.
            raise InvalidRequest("The directory server refused it.", code="unwilling_to_perform")
        self.modified.append((dn, changes))
        self.controls.append(controls)


def test_raising_writes_what_samba_tool_writes_where_it_writes_it():
    pytest.importorskip("ldb")
    conn = Writable(READY_OBJECTS)
    fl.raise_levels(conn, domain_level=7, forest_level=7, confirm="myantispam.local")
    assert [(dn.lower(), changes) for dn, changes in conn.modified] == [
        (BASE.lower(), {"msDS-Behavior-Version": "7"}),
        (f"CN=MYANTISPAM,CN=Partitions,{CONFIG}".lower(), {"msDS-Behavior-Version": "7"}),
        (f"CN=Partitions,{CONFIG}".lower(), {"msDS-Behavior-Version": "7"}),
    ]


def test_a_cross_ref_the_server_will_not_take_is_passed_over_as_samba_tool_does():
    pytest.importorskip("ldb")
    conn = Writable(READY_OBJECTS, cross_ref_unwilling=True)
    fl.raise_levels(conn, domain_level=7, forest_level=None, confirm="myantispam.local")
    assert [dn.lower() for dn, _ in conn.modified] == [BASE.lower()]


def test_a_refused_raise_writes_nothing():
    conn = Writable(MEASURED_OBJECTS)
    with pytest.raises(Conflict):
        fl.raise_levels(conn, domain_level=7, forest_level=None, confirm="myantispam.local")
    assert conn.modified == []


def test_every_write_carries_the_relax_control():
    """msDS-Behavior-Version is systemOnly. samba-tool writes it on the DC,
    as system; over LDAP Samba refuses it without relax (objectclass_attrs.c),
    measured on the throwaway DC: LDAP_CONSTRAINT_VIOLATION, "can only be
    modified as system"."""
    pytest.importorskip("ldb")
    conn = Writable(READY_OBJECTS)
    fl.raise_levels(conn, domain_level=7, forest_level=7, confirm="myantispam.local")
    assert conn.controls == [["relax:0"]] * 3

"""Common options and item-level targeting of group policy preferences.

The reference is a GPO made in a German GPMC on Windows 11 for exactly this,
"SAMADCON-Referenz-ILT"; tests/data/PROVENANCE.md says what each item in it
settles. Until now SAMADCON kept both as they were read and offered neither:
the options were attributes it carried, the targeting a block it displayed.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo.preferences import catalogue, store, targeting, xmlfile

DATA = Path(__file__).resolve().parent.parent / "data"
DRIVES = (DATA / "Drives-ilt.xml").read_bytes()
REGISTRY = (DATA / "Registry-ilt.xml").read_bytes()

DOMAIN = "S-1-5-21-2540059117-2646349506-3686739550"
P, T, Q, R, S = (
    "{718EAC78-EB36-4A14-9951-E4C535D2C0B9}",
    "{5F251808-52AA-4490-9371-FDE554E24814}",
    "{1BB43386-C802-4AF0-8852-97880BA57F83}",
    "{1021BED0-FEB4-40BA-9706-1C9C5B7CF5B9}",
    "{DB261335-00BD-4EFB-A90C-C7996530FE2E}",
)


def drives() -> dict[str, dict[str, Any]]:
    kind = catalogue.type_for("drives")
    return {item["uid"]: item for item in xmlfile.parse(kind, DRIVES.decode("utf-8"))}


# ---------------------------------------------------------------------------
# Reading what GPMC wrote
# ---------------------------------------------------------------------------


def test_the_options_read_as_gpmc_shows_them():
    items = drives()
    assert items[P]["options"] == {
        "stop_on_error": True,  # bypassErrors="0"
        "user_context": True,
        "remove_policy": True,
        "run_once": False,
    }
    assert items[T]["options"]["run_once"] is True
    assert items[Q]["options"] == {
        "stop_on_error": False,  # bypassErrors="1"
        "user_context": False,
        "remove_policy": False,
        "run_once": False,
    }


def test_each_measured_filter_reads_as_a_condition():
    items = drives()
    assert items[P]["targeting"] == {
        "editable": True,
        "conditions": [
            {
                "type": "group",
                "bool": "AND",
                "not": False,
                "name": "MYANTISPAM\\Domain Users",
                "sid": f"{DOMAIN}-513",
                "user_context": True,
                "primary_group": False,
                "local_group": False,
            }
        ],
    }
    assert items[Q]["targeting"]["conditions"] == [
        {
            "type": "ou",
            "bool": "AND",
            "not": True,
            "name": "OU=Test,DC=myantispam,DC=local",
            "user_context": True,
            "direct_member": False,
        }
    ]
    first, second = items[R]["targeting"]["conditions"]
    assert first == {
        "type": "computer",
        "bool": "AND",
        "not": False,
        "name": "WIN11-PVE",
        "computer_type": "NETBIOS",
    }
    assert (second["type"], second["bool"], second["user_context"]) == ("group", "OR", False)
    assert [c["type"] for c in items[S]["targeting"]["conditions"]] == ["user", "group", "computer"]
    assert items[S]["targeting"]["conditions"][0]["sid"] == f"{DOMAIN}-500"


def test_run_once_is_an_option_not_a_condition():
    """GPMC writes it as a filter; it ticks a box in the common options."""
    conditions = drives()[T]["targeting"]["conditions"]
    assert [c["type"] for c in conditions] == ["group"]


@pytest.mark.parametrize(
    ("raw", "kind"),
    [(DRIVES, "drives"), (REGISTRY, "registry")],
)
def test_the_reference_files_round_trip_byte_for_byte(raw, kind):
    """Including the CRLF and two tabs GPMC writes before </Filters> after a
    run-once filter, which a parser hands over as a bare LF."""
    preference = catalogue.type_for(kind)
    assert xmlfile.render(preference, xmlfile.parse(preference, raw.decode("utf-8"))) == raw


# ---------------------------------------------------------------------------
# What stays read-only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filters",
    [
        # A collection: nested, and not measured from a visible one yet.
        '<Filters><FilterCollection bool="AND" not="0">'
        '<FilterGroup bool="AND" not="0" name="X\\A" sid="S-1-5-21-1-2-3-512"'
        ' userContext="1" primaryGroup="0" localGroup="0"/></FilterCollection></Filters>',
        # A filter type SAMADCON does not model.
        '<Filters><FilterIpRange bool="AND" not="0" min="10.0.0.1" max="10.0.0.9"/></Filters>',
        # Run once not at the end: moving it could change what an OR binds.
        '<Filters><FilterRunOnce hidden="1" not="0" bool="AND" id="{0D35E111-6304-4C7C-9C35-'
        '7E0570042660}"/><FilterComputer bool="OR" not="0" type="NETBIOS" name="A"/></Filters>',
    ],
)
def test_targeting_it_does_not_fully_understand_stays_as_it_is(filters):
    parsed = targeting.parse(filters)
    assert parsed["editable"] is False
    assert parsed["conditions"] == []


# ---------------------------------------------------------------------------
# Writing options
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixed_time(monkeypatch):
    monkeypatch.setattr(store, "_now", lambda: "2026-10-17 20:00:00")


def prepare(uid: str, **changes: Any) -> dict[str, Any]:
    items = drives()
    item = items[uid]
    request = {
        "uid": uid,
        "action": item["action"],
        "properties": dict(item["properties"]),
        **changes,
    }
    return store._prepare(catalogue.type_for("drives"), "User", request, items)


def options(**set_: bool) -> dict[str, bool]:
    return {
        "stop_on_error": False,
        "user_context": False,
        "remove_policy": False,
        "run_once": False,
        **set_,
    }


def test_an_item_sent_without_options_keeps_them(fixed_time):
    """What the editor did before: the attributes travel untouched."""
    built = prepare(P)
    assert built["extra"]["removePolicy"] == "1"
    assert built["extra"]["bypassErrors"] == "0"
    assert built["changed"] == "2026-10-17 18:14:18"


def test_removal_turns_the_action_into_replace(fixed_time):
    """GPMC did so for P: when the box was ticked."""
    built = prepare(Q, options=options(remove_policy=True))
    assert built["extra"]["removePolicy"] == "1"
    assert built["action"] == "R"


def test_removal_and_run_once_exclude_each_other():
    with pytest.raises(InvalidRequest) as caught:
        prepare(Q, options=options(remove_policy=True, run_once=True))
    assert caught.value.code == "preference_options_conflict"


def test_stop_on_error_is_bypass_errors_turned_round(fixed_time):
    assert prepare(Q, options=options(stop_on_error=True))["extra"]["bypassErrors"] == "0"
    assert prepare(P, options=options(user_context=True, remove_policy=True))["extra"][
        "bypassErrors"
    ] == "1"


def test_an_option_turned_off_is_written_as_zero_where_it_stood_and_left_out_where_not(
    fixed_time,
):
    """A group states userContext="0" outright, a drive leaves it out."""
    off = prepare(P, options=options(stop_on_error=True))
    assert off["extra"]["userContext"] == "0"
    assert off["extra"]["removePolicy"] == "0"
    assert "userContext" not in prepare(Q, options=options())["extra"]
    assert "removePolicy" not in prepare(Q, options=options())["extra"]


def test_run_once_adds_its_filter_and_keeps_its_id(fixed_time):
    added = prepare(Q, options=options(run_once=True))
    parsed = targeting.parse(added["filters"])
    assert parsed["run_once"]
    assert parsed["conditions"][0]["type"] == "ou"
    kept = prepare(T, options=options(stop_on_error=True, user_context=True, run_once=True))
    assert targeting.parse(kept["filters"])["run_once"] == "{0D35E111-6304-4C7C-9C35-7E0570042660}"
    removed = prepare(T, options=options(stop_on_error=True, user_context=True))
    assert "FilterRunOnce" not in (removed["filters"] or "")


def test_a_computer_half_item_cannot_run_as_the_user():
    """GPMC greys the box out there; the registry reference has no userContext."""
    kind = catalogue.type_for("registry")
    items = {i["uid"]: i for i in xmlfile.parse(kind, REGISTRY.decode("utf-8"))}
    item = next(iter(items.values()))
    with pytest.raises(InvalidRequest) as caught:
        store._prepare(
            kind,
            "Machine",
            {
                "uid": item["uid"],
                "action": item["action"],
                "properties": item["properties"],
                "options": options(user_context=True),
            },
            items,
        )
    assert caught.value.code == "preference_user_context_machine"


def test_a_new_item_gets_the_options_where_gpmc_puts_them(fixed_time):
    kind = catalogue.type_for("drives")
    built = store._prepare(
        kind,
        "User",
        {
            "action": "U",
            "properties": {"letter": "X", "path": "\\\\zmb-ad\\netlogon", "useLetter": "1"},
            "options": options(stop_on_error=True, user_context=True, remove_policy=True),
        },
        {},
    )
    line = xmlfile.render(kind, [built]).decode("utf-8")
    start = line.index("<Drive ")
    head = line[start : line.index(">", start)]
    names = [part.split("=")[0] for part in head.split()[1:]]
    # P:'s order: name status image removePolicy userContext bypassErrors changed uid
    assert names[names.index("image") + 1 : names.index("changed")] == [
        "removePolicy",
        "userContext",
        "bypassErrors",
    ]


# ---------------------------------------------------------------------------
# Writing targeting
# ---------------------------------------------------------------------------


def test_conditions_are_written_as_gpmc_writes_them(fixed_time):
    """Rebuilt from S:'s own conditions, the block is S:'s block."""
    s = drives()[S]
    built = prepare(S, targeting={"conditions": s["targeting"]["conditions"]})
    assert built["filters"] == s["filters"]
    assert built["changed"] == "2026-10-17 18:22:33"


def test_the_first_condition_is_always_and():
    rendered = targeting.render(
        [{"type": "computer", "bool": "OR", "not": False, "name": "A"}], None
    )
    assert rendered == (
        '<Filters><FilterComputer bool="AND" not="0" type="NETBIOS" name="A"/></Filters>'
    )


def test_no_conditions_and_no_run_once_is_no_filters_block():
    assert targeting.render([], None) is None


def test_targeting_that_stays_read_only_cannot_be_overwritten():
    kind = catalogue.type_for("drives")
    collection = (
        '<Filters><FilterCollection bool="AND" not="0"><FilterComputer bool="AND" not="0"'
        ' type="NETBIOS" name="A"/></FilterCollection></Filters>'
    )
    existing = {"{1}": {"kind": "drive", "uid": "{1}", "filters": collection, "extra": {},
                        "order": [], "properties": {"letter": "K"}, "action": "U"}}
    with pytest.raises(InvalidRequest) as caught:
        store._prepare(
            kind,
            "User",
            {"uid": "{1}", "action": "U", "properties": {"letter": "K"},
             "targeting": {"conditions": []}},
            existing,
        )
    assert caught.value.code == "preference_targeting_not_editable"


@pytest.mark.parametrize(
    ("condition", "reason"),
    [
        ({"type": "wmi", "name": "x"}, "type"),
        ({"type": "group", "name": "X\\A", "sid": "nope", "user_context": True}, "sid"),
        ({"type": "group", "name": "", "sid": f"{DOMAIN}-512", "user_context": True}, "name"),
        ({"type": "computer", "name": "A", "bool": "XOR"}, "bool"),
        ({"type": "computer", "name": "A", "computer_type": "MAC"}, "computer_type"),
    ],
)
def test_a_condition_that_is_not_one_is_refused(condition, reason):
    with pytest.raises(InvalidRequest) as caught:
        targeting.validate([condition])
    assert caught.value.code == "preference_condition_invalid"
    assert caught.value.context["reason"] == reason


# ---------------------------------------------------------------------------
# Picking from the directory
# ---------------------------------------------------------------------------


class _Directory:
    """A group, a user and an OU, as conn.get returns them."""

    def __init__(self) -> None:
        self.info = types.SimpleNamespace(netbios_name="MYANTISPAM")
        self.entries = {
            "cn=domain users,cn=users,dc=myantispam,dc=local": {
                "objectClass": [b"top", b"group"],
                "sAMAccountName": [b"Domain Users"],
                "objectSid": [_sid(513)],
            },
            "cn=administrator,cn=users,dc=myantispam,dc=local": {
                "objectClass": [b"top", b"person", b"user"],
                "sAMAccountName": [b"Administrator"],
                "objectSid": [_sid(500)],
            },
            "ou=test,dc=myantispam,dc=local": {
                "objectClass": [b"top", b"organizationalUnit"],
                "distinguishedName": [b"OU=Test,DC=myantispam,DC=local"],
            },
        }

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        entry = self.entries.get(dn.lower())
        if entry is None:
            return None

        class Entry(dict):
            def get(self, name: str, default: Any = None) -> Any:
                for key, value in self.items():
                    if key.lower() == name.lower():
                        return value
                return default

        return Entry(entry)


def _sid(rid: int) -> bytes:
    """The binary objectSid of DOMAIN-<rid>."""
    authorities = [21, 2540059117, 2646349506, 3686739550, rid]
    head = bytes([1, len(authorities)]) + (5).to_bytes(6, "big")
    return head + b"".join(value.to_bytes(4, "little") for value in authorities)


def test_a_picked_group_user_or_ou_is_written_with_the_directorys_name_and_sid():
    resolved = targeting.resolve(
        _Directory(),
        [
            {"type": "group", "dn": "CN=Domain Users,CN=Users,DC=myantispam,DC=local",
             "user_context": True},
            {"type": "user", "dn": "CN=Administrator,CN=Users,DC=myantispam,DC=local",
             "bool": "OR"},
            {"type": "ou", "dn": "OU=Test,DC=myantispam,DC=local", "user_context": False},
        ],
    )
    assert [(c["name"], c.get("sid")) for c in resolved] == [
        ("MYANTISPAM\\Domain Users", f"{DOMAIN}-513"),
        ("MYANTISPAM\\Administrator", f"{DOMAIN}-500"),
        ("OU=Test,DC=myantispam,DC=local", None),
    ]
    assert "dn" not in resolved[0]


def test_a_picked_object_of_the_wrong_kind_is_refused():
    with pytest.raises(InvalidRequest) as caught:
        targeting.resolve(
            _Directory(),
            [{"type": "group", "dn": "CN=Administrator,CN=Users,DC=myantispam,DC=local"}],
        )
    assert caught.value.code == "preference_condition_invalid"
    assert caught.value.context["reason"] == "dn"

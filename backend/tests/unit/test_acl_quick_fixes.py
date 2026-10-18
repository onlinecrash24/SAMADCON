"""Three faults found while planning the full ACL editor.

1. A duplicate entry was never recognised. SAMADCON builds an ACE with a hex
   mask and the trustee's full SID — ``(A;;0x00000010;;;S-1-5-21-…-512)`` —
   while Samba hands the ACL back in its own spelling, ``(A;;RP;;;DA)``. The
   two were compared as text, so the same permission added twice passed.
2. Every resolved SID took a slot in the schema cache, which holds 32: an
   ACL of forty entries pushed the schema itself out, and the next ACL
   resolved all its SIDs again.
3. The descriptor was read without an sd_flags control, so which parts came
   back depended on the server and the account.
"""

from __future__ import annotations

import pytest

from samadcon.ad import rights, sacl
from samadcon.core import cache
from samadcon.core.errors import Conflict

DOMAIN = "S-1-5-21-1-2-3"


# ---------------------------------------------------------------------------
# 1. The same permission, however it is spelled
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ours", "samba"),
    [
        # Rights: hex mask against Samba's letters.
        ("(A;;0x00000010;;;S-1-5-21-1-2-3-1105)", "(A;;RP;;;S-1-5-21-1-2-3-1105)"),
        ("(A;CI;0x00020014;;;S-1-5-21-1-2-3-1105)", "(A;CI;RCLCRP;;;S-1-5-21-1-2-3-1105)"),
        (
            "(A;;0x000f01ff;;;S-1-5-21-1-2-3-1105)",
            "(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;S-1-5-21-1-2-3-1105)",
        ),
        # Trustees: a full SID against Samba's alias, domain-relative and well-known.
        ("(A;;0x00000010;;;S-1-5-21-1-2-3-512)", "(A;;RP;;;DA)"),
        ("(D;;0x00010040;;;S-1-1-0)", "(D;;SDDT;;;WD)"),
        ("(A;;0x00000010;;;S-1-5-11)", "(A;;RP;;;AU)"),
        ("(A;;0x00000010;;;S-1-5-32-544)", "(A;;RP;;;BA)"),
        # Object GUIDs: case and braces.
        (
            "(OA;CI;0x00000100;{00299570-246D-11D0-A768-00AA006E0529};BF967ABA-0DE6-11D0-A285-00AA003049E2;S-1-5-21-1-2-3-1105)",
            "(OA;CI;CR;00299570-246d-11d0-a768-00aa006e0529;bf967aba-0de6-11d0-a285-00aa003049e2;S-1-5-21-1-2-3-1105)",
        ),
        # Flags in another order.
        ("(A;CIIO;0x00000010;;;S-1-5-21-1-2-3-1105)", "(A;IOCI;RP;;;S-1-5-21-1-2-3-1105)"),
    ],
)
def test_the_same_permission_is_the_same_however_it_is_spelled(ours, samba):
    assert sacl.same_ace(ours, samba, DOMAIN)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("(A;;RP;;;DA)", "(A;;WP;;;DA)"),  # another right
        ("(A;;RP;;;DA)", "(D;;RP;;;DA)"),  # deny, not allow
        ("(A;;RP;;;DA)", "(A;CI;RP;;;DA)"),  # inherited by children
        ("(A;;RP;;;DA)", "(A;;RP;;;DU)"),  # another trustee
        ("(A;;RP;;;S-1-5-21-1-2-3-512)", "(A;;RP;;;S-1-5-21-9-9-9-512)"),  # another domain
    ],
)
def test_a_different_permission_stays_different(a, b):
    assert not sacl.same_ace(a, b, DOMAIN)


def test_without_the_domain_a_domain_alias_only_matches_itself():
    """Better to miss a duplicate than to call two trustees one."""
    assert sacl.same_ace("(A;;RP;;;DA)", "(A;;0x10;;;DA)", None)
    assert not sacl.same_ace("(A;;RP;;;DA)", "(A;;RP;;;S-1-5-21-1-2-3-512)", None)


class _Info:
    domain_sid = DOMAIN


class _Conn:
    info = _Info()


@pytest.fixture
def samba_spelled_acl(monkeypatch: pytest.MonkeyPatch):
    """An ACL as Samba hands it back: letters and aliases."""
    state = {"sddl": "O:DAG:DAD:AI(A;;RP;;;DA)(A;;RPWP;;;S-1-5-21-1-2-3-1105)", "writes": 0}
    monkeypatch.setattr(sacl, "read_sddl", lambda conn, dn: state["sddl"])

    def write(conn, dn, sddl):
        state["sddl"] = sddl
        state["writes"] += 1

    monkeypatch.setattr(sacl, "write_sddl", write)
    return state


def test_adding_what_samba_already_shows_is_refused(samba_spelled_acl):
    with pytest.raises(Conflict) as caught:
        sacl.add_ace(_Conn(), "CN=x", ace="(A;;0x00000010;;;S-1-5-21-1-2-3-512)")
    assert caught.value.code == "ace_exists"
    assert samba_spelled_acl["writes"] == 0


def test_a_queued_batch_with_such_a_duplicate_writes_nothing(samba_spelled_acl):
    with pytest.raises(Conflict) as caught:
        sacl.change_acl(
            _Conn(),
            "CN=x",
            remove=[],
            add=["(A;;0x00000030;;;S-1-5-21-1-2-3-1105)"],
            expected_sddl=samba_spelled_acl["sddl"],
        )
    assert caught.value.code == "ace_exists"
    assert samba_spelled_acl["writes"] == 0


def test_two_spellings_of_one_entry_in_a_batch_are_refused(samba_spelled_acl):
    with pytest.raises(Conflict):
        sacl.change_acl(
            _Conn(),
            "CN=x",
            remove=[],
            add=["(A;;0x00000004;;;S-1-5-11)", "(A;;LC;;;AU)"],
            expected_sddl=samba_spelled_acl["sddl"],
        )


# ---------------------------------------------------------------------------
# 2. SIDs in a cache of their own
# ---------------------------------------------------------------------------


class _DirInfo:
    base_dn = "DC=example,DC=lan"


class _Empty:
    entries = ()

    def __len__(self):
        return 0


class _Directory:
    info = _DirInfo()

    def __init__(self):
        self.searches = 0

    def search(self, *args, **kwargs):
        self.searches += 1

        return _Empty()


@pytest.fixture
def clean_caches():
    cache.clear_caches()
    yield
    cache.clear_caches()


def test_resolved_sids_do_not_take_the_schema_cache(clean_caches):
    conn = _Directory()
    for rid in range(40):
        rights.resolve_sid(conn, f"S-1-5-21-1-2-3-{1100 + rid}")
    assert len(cache.schema_cache) == 0
    assert len(cache.sid_cache) == 40


def test_an_acl_of_many_entries_is_resolved_once(clean_caches):
    conn = _Directory()
    sids = [f"S-1-5-21-1-2-3-{1100 + rid}" for rid in range(200)]
    for sid in sids:
        rights.resolve_sid(conn, sid)
    for sid in sids:
        rights.resolve_sid(conn, sid)
    assert conn.searches == 200


def test_the_sid_cache_can_be_cleared_by_name(clean_caches):
    rights.resolve_sid(_Directory(), "S-1-5-21-1-2-3-1105")
    assert cache.clear_caches("sid") == ["sid"]
    assert len(cache.sid_cache) == 0


# ---------------------------------------------------------------------------
# 3. Which parts of the descriptor are asked for
# ---------------------------------------------------------------------------


def test_the_descriptor_is_read_with_owner_group_and_dacl():
    # SECINFO_OWNER | SECINFO_GROUP | SECINFO_DACL; not the SACL, which needs
    # a privilege most delegated admins do not have.
    assert sacl.READ_SD_CONTROLS == ["sd_flags:1:7"]


def test_the_read_sends_that_control():
    seen = {}

    class Conn:
        def search(self, base, *, scope, attrs, controls, max_results, **_):
            seen.update(base=base, attrs=attrs, controls=controls)

            class Result:
                entries = ({"nTSecurityDescriptor": [b"raw"]},)

            return Result()

    raw = sacl._raw_descriptor(Conn(), "CN=x")
    assert raw == b"raw"
    assert seen == {"base": "CN=x", "attrs": ["nTSecurityDescriptor"], "controls": ["sd_flags:1:7"]}


def test_an_entry_that_cannot_be_taken_apart_is_compared_as_text():
    odd = "(XA;;0x10;;;WD;(@User.x == 1))"
    assert sacl.same_ace(odd, odd, DOMAIN)
    assert not sacl.same_ace("(A;;RP;;;WD)", "(broken)", DOMAIN)

"""Diagnosis against a live domain controller.

Everything here is read-only, so these tests are safe against any domain. What
they check is that the values we derive line up with each other — a role owner
that is not in the DC list, or a policy that reads back as None everywhere,
means the derivation is wrong even though nothing raised.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# FSMO roles
# ---------------------------------------------------------------------------


def test_the_five_domain_roles_have_an_owner(api):
    """A domain missing one of these cannot function; the DNS ones are optional."""
    roles = {role["role"]: role for role in api.get("/api/v1/diagnostics/roles").json()["roles"]}

    for name in ("schema", "domain_naming", "pdc", "rid", "infrastructure"):
        assert roles[name]["present"] is True, f"{name} has no owner"
        assert roles[name]["owner"], f"{name} owner did not resolve to a server name"


def test_a_role_owner_is_named_after_a_real_dc(api):
    """fSMORoleOwner points at NTDS Settings; we report the server above it."""
    roles = api.get("/api/v1/diagnostics/roles").json()["roles"]
    controllers = {dc["name"] for dc in api.get("/api/v1/diagnostics/controllers").json()["controllers"]}

    owners = {role["owner"] for role in roles if role["owner"]}
    assert owners, "no role owner resolved at all"
    assert owners <= controllers, f"role owners that are not DCs: {owners - controllers}"


def test_a_role_owner_reports_the_site_it_sits_in(api):
    roles = api.get("/api/v1/diagnostics/roles").json()["roles"]
    pdc = next(role for role in roles if role["role"] == "pdc")
    assert pdc["site"]


def test_the_dns_roles_are_reported_either_way(api):
    """Provisioned without the DNS partitions is a state, not a failure."""
    roles = {role["role"]: role for role in api.get("/api/v1/diagnostics/roles").json()["roles"]}

    for name in ("domain_dns", "forest_dns"):
        assert name in roles
        assert isinstance(roles[name]["present"], bool)


# ---------------------------------------------------------------------------
# Domain controllers
# ---------------------------------------------------------------------------


def test_the_connected_dc_is_in_the_controller_list(api):
    overview = api.get("/api/v1/diagnostics").json()
    connected = overview["domain"]["connected_dc"]
    names = [dc["name"].lower() for dc in overview["controllers"]]
    dns_names = [(dc["dns_name"] or "").lower() for dc in overview["controllers"]]

    assert connected
    assert connected.split(".")[0].lower() in names or connected.lower() in dns_names


def test_every_controller_reports_its_site_and_ntds(api):
    controllers = api.get("/api/v1/diagnostics/controllers").json()["controllers"]
    assert controllers

    for dc in controllers:
        assert dc["is_dc"] is True
        assert dc["site"], f"{dc['name']} has no site"
        assert dc["ntds_dn"], f"{dc['name']} has no NTDS Settings"
        assert isinstance(dc["is_global_catalog"], bool)


def test_at_least_one_controller_is_a_global_catalog(api):
    """A forest without one cannot resolve universal group membership."""
    controllers = api.get("/api/v1/diagnostics/controllers").json()["controllers"]
    assert any(dc["is_global_catalog"] for dc in controllers)


# ---------------------------------------------------------------------------
# Functional levels
# ---------------------------------------------------------------------------


def test_the_functional_levels_are_named(api):
    domain = api.get("/api/v1/diagnostics").json()["domain"]

    assert domain["domain_level"] is not None
    assert domain["domain_level_name"]
    assert not domain["domain_level_name"].startswith("Unknown"), (
        "an unnamed level means the table needs a new entry"
    )
    assert domain["forest_level_name"]


# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------


def test_replication_reads_without_failing(api):
    """A single-DC domain has no partners — an empty list, not an error."""
    replication = api.get("/api/v1/diagnostics/replication").json()

    assert replication["dc"]
    assert isinstance(replication["neighbours"], list)
    assert replication["unreadable_partitions"] == [], (
        "a repsFrom value could not be decoded — the blob layout does not match"
    )


def test_every_replication_partner_is_decoded_completely(api):
    """If there are partners, none of their fields may come back empty."""
    neighbours = api.get("/api/v1/diagnostics/replication").json()["neighbours"]
    if not neighbours:
        pytest.skip("single-DC domain — no replication partners to check")

    for item in neighbours:
        assert item["partition"]
        assert item["source_guid"]
        # None would mean the WERROR could not be read, which must not pass as
        # success.
        assert item["result"] is not None


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------


def test_the_password_policy_reads_back_with_real_values(api):
    policy = api.get("/api/v1/diagnostics/policy").json()

    assert policy["min_length"] is not None
    assert policy["history_length"] is not None
    assert isinstance(policy["complexity"], bool)
    assert policy["lockout_threshold"] is not None
    # Samba's default is 42 days; any domain has some maximum age or none at all.
    assert policy["max_age_days"] is None or policy["max_age_days"] > 0


def test_password_settings_objects_are_listed_in_precedence_order(api):
    policies = api.get("/api/v1/diagnostics/policy").json()["password_settings_objects"]
    if not policies:
        pytest.skip("no fine-grained password policies in this domain")

    precedences = [pso["precedence"] for pso in policies if pso["precedence"] is not None]
    assert precedences == sorted(precedences), "the lowest precedence wins, so it goes first"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def test_account_problems_are_classified(api):
    accounts = api.get("/api/v1/diagnostics/accounts").json()

    for bucket in ("locked", "disabled", "expired"):
        assert isinstance(accounts[bucket], list)
        for account in accounts[bucket]:
            assert account["name"], "an account without a logon name should not be listed"


def test_the_guest_account_shows_up_as_disabled(api):
    """Every domain has it, and it is disabled unless someone changed that."""
    disabled = api.get("/api/v1/diagnostics/accounts").json()["disabled"]
    names = {account["name"].lower() for account in disabled}
    assert "guest" in names or "krbtgt" in names


def test_an_expired_lockout_is_not_reported_as_locked(api):
    """lockoutTime is not cleared when a lockout runs out.

    Listing every account that was ever locked would make the view useless, so
    the duration decides — and that means no account may appear as locked with
    a lockout time older than the policy allows.
    """
    accounts = api.get("/api/v1/diagnostics/accounts").json()
    duration = accounts["lockout_duration_minutes"]
    if duration is None:
        pytest.skip("lockouts in this domain never expire on their own")

    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(minutes=duration)
    for account in accounts["locked"]:
        moment = datetime.fromisoformat(account["lockout_time"])
        assert moment >= cutoff, f"{account['name']} was locked longer ago than the policy lasts"


def test_the_overview_answers_in_one_call(api):
    """The diagnosis page must not need six round trips to draw itself."""
    overview = api.get("/api/v1/diagnostics").json()

    assert set(overview) == {"domain", "roles", "controllers", "replication", "policy"}
    assert overview["domain"]["dns_domain"]
    assert overview["domain"]["netbios_name"]
    assert overview["roles"]
    assert overview["controllers"]

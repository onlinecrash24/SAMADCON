"""What the accounts and the domain's own settings give away.

Eight rules, prompted by a tester's own audit tool and written here from
scratch. Each was measured against a real Samba domain first (zmb-ad, Samba
4.22.11, 21 November 2026), and what that showed is why every rule has an
exception — a rule that marks what a fresh domain looks like teaches people
to skip the report:

* krbtgt carries the SPN ``kadmin/changepw`` in every domain;
* the guest account carries PASSWD_NOTREQD and is disabled;
* "Pre-Windows 2000 Compatible Access" holds Authenticated Users as
  provisioned;
* the DC's computer object said ``4.17.12-Debian`` while 4.22.11 ran — the
  attribute is written at provision and not at upgrade, so the version is
  taken from the rootDSE.
"""

from __future__ import annotations

import struct
from datetime import UTC, date, datetime
from typing import Any

from samadcon.ad import diagnostics, uac
from samadcon.ad.connection import SearchResult
from samadcon.core import findings

TODAY = date(2026, 11, 21)
SAMBA = "Samba Team (https://www.samba.org)"


def exposure(**overrides: Any) -> dict[str, Any]:
    """What zmb-ad would look like with nothing to report."""
    base: dict[str, Any] = {
        "accounts": [],
        "guest": {"name": "Guest", "enabled": False},
        "krbtgt_password_last_set": datetime(2026, 6, 1, tzinfo=UTC),
        "machine_account_quota": 0,
        "pre_windows_2000_open": [],
        "truncated": False,
    }
    base.update(overrides)
    return base


def account(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "dn": "CN=svc,CN=Users,DC=example,DC=test",
        "name": "svc",
        "enabled": True,
        "privileged": False,
        "spns": [],
        "no_preauth": False,
        "password_not_required": False,
    }
    base.update(overrides)
    return base


def evaluate(**overrides: Any) -> list[findings.Finding]:
    return findings.evaluate(accounts=exposure(**overrides), today=TODAY)


def ids(found: list[findings.Finding]) -> list[str]:
    return [item.id for item in found]


def test_a_domain_with_nothing_exposed_raises_nothing() -> None:
    assert evaluate() == []


# --- the guest account ------------------------------------------------------


def test_an_enabled_guest_account_is_a_finding() -> None:
    found = evaluate(guest={"name": "Gast", "enabled": True})

    assert ids(found) == ["guest_enabled"]
    assert found[0].severity == "high"
    assert found[0].subject == "Gast"


def test_a_domain_whose_guest_could_not_be_found_is_not_guessed_at() -> None:
    assert evaluate(guest=None) == []


# --- accounts ---------------------------------------------------------------


def test_an_account_without_pre_authentication_is_a_finding() -> None:
    """Anyone may ask the KDC for material encrypted with its password and
    guess at it offline, without ever having signed in."""
    found = evaluate(accounts=[account(no_preauth=True)])

    assert ids(found) == ["account_no_preauth"]
    assert found[0].severity == "high"
    assert found[0].subject == "svc"


def test_a_user_with_a_service_name_is_a_finding() -> None:
    found = evaluate(accounts=[account(spns=["http/app.example.test", "http/app"])])

    assert ids(found) == ["account_with_spn"]
    assert found[0].severity == "medium"
    assert found[0].evidence["spn"] == "http/app.example.test"
    assert found[0].evidence["count"] == 2


def test_on_an_administrator_it_weighs_more() -> None:
    found = evaluate(accounts=[account(spns=["http/app"], privileged=True)])

    assert found[0].severity == "high"
    assert found[0].evidence["privileged"] is True


def test_an_account_that_needs_no_password_is_a_finding() -> None:
    found = evaluate(accounts=[account(password_not_required=True)])

    assert ids(found) == ["account_password_not_required"]
    assert found[0].severity == "medium"


def test_a_disabled_account_raises_none_of_them() -> None:
    """Nobody can sign in as it or get a ticket for it. This is the guest
    account in every domain, which is why the exception exists."""
    found = evaluate(
        accounts=[
            account(
                enabled=False, no_preauth=True, spns=["http/app"], password_not_required=True
            )
        ]
    )

    assert found == []


def test_one_account_can_raise_several() -> None:
    found = evaluate(accounts=[account(no_preauth=True, spns=["http/app"])])

    assert sorted(ids(found)) == ["account_no_preauth", "account_with_spn"]


# --- krbtgt -----------------------------------------------------------------


def test_a_krbtgt_password_older_than_a_year_is_a_finding() -> None:
    """Measured: unchanged since provision on 28 March 2025."""
    found = evaluate(krbtgt_password_last_set=datetime(2025, 3, 28, 20, 34, tzinfo=UTC))

    assert ids(found) == ["krbtgt_password_old"]
    assert found[0].severity == "medium"
    assert found[0].evidence["age_days"] == 603
    assert found[0].evidence["convention"] == findings.MAX_KRBTGT_PASSWORD_DAYS == 365
    assert found[0].evidence["last_set"] == "2025-03-28"


def test_a_year_exactly_is_not() -> None:
    assert evaluate(krbtgt_password_last_set=datetime(2025, 11, 21, tzinfo=UTC)) == []
    assert ids(evaluate(krbtgt_password_last_set=datetime(2025, 11, 20, tzinfo=UTC))) == [
        "krbtgt_password_old"
    ]


def test_an_unreadable_krbtgt_date_is_not_guessed_at() -> None:
    assert evaluate(krbtgt_password_last_set=None) == []


# --- the domain's own settings ---------------------------------------------


def test_everyone_in_the_pre_windows_2000_group_is_a_finding() -> None:
    found = evaluate(pre_windows_2000_open=["S-1-1-0", "S-1-5-7"])

    assert ids(found) == ["pre_windows_2000_open"]
    assert found[0].severity == "medium"
    assert found[0].evidence["members"] == "S-1-1-0, S-1-5-7"


def test_a_quota_that_lets_any_user_join_machines_is_a_low_finding() -> None:
    """The default of ten, in every domain nobody changed. True and worth
    knowing, and not an alarm."""
    found = evaluate(machine_account_quota=10)

    assert ids(found) == ["machine_account_quota"]
    assert found[0].severity == "low"
    assert found[0].evidence == {"quota": 10}


def test_an_unreadable_quota_is_not_a_finding() -> None:
    assert evaluate(machine_account_quota=None) == []


# --- the Samba series -------------------------------------------------------


def series(version: str | None, vendor: str | None = SAMBA, today: date = TODAY) -> list[str]:
    found = findings.evaluate(domain={"vendor": vendor, "vendor_version": version}, today=today)
    return ids(found)


def test_a_series_the_samba_team_has_dropped_is_a_note() -> None:
    """For a Samba built from the team's own release: nobody else stands
    behind it."""
    found = findings.evaluate(domain={"vendor": SAMBA, "vendor_version": "4.22.11"}, today=TODAY)

    assert ids(found) == ["samba_series_unmaintained"]
    assert found[0].severity == "info"
    assert found[0].evidence["series"] == "4.22"
    assert found[0].evidence["maintained_until"] == "2026-09"
    assert found[0].evidence["version"] == "4.22.11"


def test_a_distribution_s_package_says_nothing() -> None:
    """Its maintenance is the distribution's and cannot be read from a series
    number. Measured on zmb-ad: Debian 13 ships 4.22 with its own security
    updates, fully current, months after the Samba team dropped the series.
    The maintainer's reaction to the note there was "but it is up to date" —
    and it was."""
    assert series("4.22.11-Debian-4.22.11+dfsg-0+deb13u1") == []
    assert series("4.15.13-Ubuntu") == []
    assert series("4.9.5-Synology") == []
    assert series("4.21.3-SerNet-RedHat-12.el9") == []


def test_a_maintained_series_is_not() -> None:
    assert series("4.24.3") == []
    assert series("4.23.5-Debian") == []


def test_the_month_it_ends_in_still_counts_as_maintained() -> None:
    assert series("4.22.11", today=date(2026, 9, 30)) == []
    assert series("4.22.11", today=date(2026, 10, 1)) == ["samba_series_unmaintained"]


def test_a_series_older_than_the_table_is_long_gone() -> None:
    assert series("4.9.5") == ["samba_series_unmaintained"]


def test_a_series_newer_than_the_table_says_nothing() -> None:
    """The table ages. An old SAMADCON must not call a new Samba unmaintained."""
    assert series("4.31.0") == []
    assert series("5.0.1") == []


def test_a_windows_dc_has_no_samba_series() -> None:
    assert series(None, vendor=None) == []
    assert series("10.0 (20348)", vendor=None) == []


def test_a_version_nobody_can_read_says_nothing() -> None:
    assert series("unknown") == []
    assert series(None) == []


# --- the reading ------------------------------------------------------------

DOMAIN_SID = "S-1-5-21-1111-2222-3333"
BASE = "DC=myantispam,DC=local"


def sid_bytes(text: str) -> bytes:
    parts = text.split("-")[1:]
    subs = [int(part) for part in parts[2:]]
    return (
        bytes([int(parts[0]), len(subs)])
        + int(parts[1]).to_bytes(6, "big")
        + struct.pack(f"<{len(subs)}I", *subs)
    )


class Entry(dict):
    """An LDAP message: every attribute a list of bytes."""

    def __init__(self, dn: str, **attrs: Any) -> None:
        super().__init__()
        self.dn = dn
        for name, value in attrs.items():
            items = value if isinstance(value, list) else [value]
            self[name] = [
                item if isinstance(item, bytes) else str(item).encode() for item in items
            ]


def user(name: str, flags: int, rid: int, **attrs: Any) -> Entry:
    return Entry(
        f"CN={name},CN=Users,{BASE}",
        sAMAccountName=name,
        userAccountControl=flags,
        objectSid=sid_bytes(f"{DOMAIN_SID}-{rid}"),
        **attrs,
    )


class Info:
    base_dn = BASE
    domain_sid = DOMAIN_SID


class Conn:
    """Answers the three questions the reader asks, and records them."""

    info = Info()

    def __init__(self, users: list[Entry], group_members: list[str], quota: int | None) -> None:
        self.users = users
        self.group_members = group_members
        self.quota = quota
        self.searches: list[str] = []

    def search(self, base: Any = None, *, expression: str = "", **_: Any) -> SearchResult:
        self.searches.append(expression)
        if "S-1-5-32-554" in expression:
            return SearchResult([Entry("CN=Pre", member=self.group_members)])
        return SearchResult(list(self.users))

    def get(self, dn: str, attrs: Any = None) -> Any:
        if self.quota is None:
            return Entry(dn)
        return Entry(dn, **{"ms-DS-MachineAccountQuota": self.quota})


# userAccountControl as measured: 66082 on Guest, 514 on krbtgt.
MEASURED = [
    user("Guest", 66082, 501),
    user(
        "krbtgt",
        514,
        502,
        adminCount=1,
        servicePrincipalName="kadmin/changepw",
        pwdLastSet=133876676623717950,
    ),
]


def test_the_measured_domain_reads_as_it_was() -> None:
    conn = Conn(MEASURED, [f"CN=S-1-5-11,CN=ForeignSecurityPrincipals,{BASE}"], 10)

    read = diagnostics.account_exposure(conn)

    assert read["guest"] == {"name": "Guest", "enabled": False}
    assert read["krbtgt_password_last_set"].date() == date(2025, 3, 28)
    assert read["machine_account_quota"] == 10
    assert read["pre_windows_2000_open"] == []
    assert read["truncated"] is False
    # krbtgt's service name is every domain's, and the guest is not a finding
    # about an account: neither is listed.
    assert read["accounts"] == []

    found = findings.evaluate(accounts=read, today=TODAY)
    assert ids(found) == ["krbtgt_password_old", "machine_account_quota"]


def test_the_accounts_come_back_with_what_was_found_on_them() -> None:
    conn = Conn(
        [
            *MEASURED,
            user(
                "svc-web",
                uac.NORMAL_ACCOUNT | uac.DONT_REQ_PREAUTH,
                1105,
                adminCount=1,
                servicePrincipalName=["http/b", "http/a"],
            ),
            user("old", uac.NORMAL_ACCOUNT | uac.ACCOUNTDISABLE | uac.PASSWD_NOTREQD, 1106),
            user("kiosk", uac.NORMAL_ACCOUNT | uac.PASSWD_NOTREQD, 1107),
        ],
        [f"CN=S-1-1-0,CN=ForeignSecurityPrincipals,{BASE}", f"CN=helpdesk,CN=Users,{BASE}"],
        None,
    )

    read = diagnostics.account_exposure(conn)

    assert [item["name"] for item in read["accounts"]] == ["kiosk", "old", "svc-web"]
    web = read["accounts"][2]
    assert web["privileged"] is True
    assert web["no_preauth"] is True
    assert web["spns"] == ["http/a", "http/b"]
    assert web["enabled"] is True
    assert read["accounts"][1]["enabled"] is False
    assert read["accounts"][0]["password_not_required"] is True
    assert read["pre_windows_2000_open"] == ["S-1-1-0"]
    assert read["machine_account_quota"] is None


def test_the_guest_is_found_by_its_number_not_its_name() -> None:
    """On a German Windows domain it is called Gast."""
    conn = Conn([user("Gast", uac.NORMAL_ACCOUNT, 501)], [], 0)

    read = diagnostics.account_exposure(conn)

    assert read["guest"] == {"name": "Gast", "enabled": True}
    assert f"(objectSid={DOMAIN_SID}-501)" in conn.searches[0]

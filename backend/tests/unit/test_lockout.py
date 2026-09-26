"""Locked means locked now, not locked once.

A DC leaves lockoutTime in place after the lockout window has passed and simply
stops enforcing it. is_locked_out said so and was called by nothing: the list
of locked accounts filtered on lockoutTime>=1, and the detail pane on
lockoutTime being present, so an account whose lockout ended yesterday was
listed as locked today and offered "Unlock". Found by an outside review.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from samadcon.ad import users, values

BASE = "DC=example,DC=test"


def interval(minutes: float) -> int:
    """An AD interval: negative, in 100-nanosecond ticks."""
    return -int(minutes * 60 * 10_000_000)


def account(name: str, locked_minutes_ago: float | None) -> dict[str, list[bytes]]:
    entry = {
        "distinguishedName": [f"CN={name},CN=Users,{BASE}".encode()],
        "name": [name.encode()],
        "sAMAccountName": [name.encode()],
        "objectClass": [b"top", b"person", b"user"],
    }
    if locked_minutes_ago is not None:
        moment = datetime.now(UTC) - timedelta(minutes=locked_minutes_ago)
        entry["lockoutTime"] = [str(values.datetime_to_filetime(moment)).encode()]
    return entry


class Domain:
    """The domain head with its lockout policy, and the accounts a search finds."""

    class Info:
        base_dn = BASE

    def __init__(self, duration: int, accounts: list[dict[str, Any]]) -> None:
        self.info = Domain.Info()
        self.duration = duration
        self.accounts = accounts

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        if dn == BASE:
            return {"lockoutDuration": [str(self.duration).encode()]}
        return None

    def search(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self.accounts


def listed(domain: Domain) -> list[str]:
    return sorted(item["name"] for item in users.list_locked_accounts(domain))


def test_a_lockout_that_has_run_out_is_not_listed():
    domain = Domain(interval(30), [account("current", 10), account("expired", 90)])
    assert listed(domain) == ["current"]


def test_a_duration_of_zero_means_until_an_administrator_unlocks():
    domain = Domain(0, [account("days-ago", 5 * 24 * 60)])
    assert listed(domain) == ["days-ago"]


def test_the_detail_pane_agrees_with_the_list():
    domain = Domain(interval(30), [])
    assert users._render_user(domain, account("expired", 90))["status"]["locked_out"] is False
    assert users._render_user(domain, account("current", 10))["status"]["locked_out"] is True


def test_an_account_never_locked_is_not_locked():
    domain = Domain(interval(30), [])
    assert users._render_user(domain, account("never", None))["status"]["locked_out"] is False

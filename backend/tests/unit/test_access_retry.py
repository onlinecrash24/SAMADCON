"""When a read is worth trying a second time.

ad_read reconnects once when the connection fails, because a DC restart or an
idle connection dropped by a firewall should not reach the administrator. It
also retried when the *server* had given up on the search at its own time
limit — which ran the same expensive search twice for an answer that was
already final. Found by an outside review.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from samadcon.ad import access
from samadcon.core.errors import OperationTimeout, UpstreamUnavailable


class Worker:
    async def run(self, fn: Any, *, label: str | None = None, timeout: float | None = None) -> Any:
        return fn()


@pytest.fixture(autouse=True)
def connections(monkeypatch):
    monkeypatch.setattr(access, "_connection", lambda worker, session, settings: "first")
    monkeypatch.setattr(access, "_reconnect", lambda worker, session, settings: "second")


def attempts_for(error: Exception) -> list[str]:
    seen: list[str] = []

    def read(conn: str) -> str:
        seen.append(conn)
        if conn == "first":
            raise error
        return "answer"

    try:
        asyncio.run(access.ad_read(Worker(), object(), read, settings=object()))
    except type(error):
        pass
    return seen


def test_a_dropped_connection_is_tried_again_on_a_new_one():
    assert attempts_for(UpstreamUnavailable("gone", code="dc_unreachable")) == ["first", "second"]


def test_a_connection_that_timed_out_is_tried_again():
    assert attempts_for(OperationTimeout("slow", code="dc_timeout")) == ["first", "second"]


def test_the_servers_own_time_limit_is_not_run_twice():
    """The DC abandoned the search itself; the same search would meet the same limit."""
    assert attempts_for(OperationTimeout("limit", code="ldap_time_limit")) == ["first"]

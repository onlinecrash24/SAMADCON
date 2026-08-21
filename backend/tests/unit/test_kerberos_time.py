"""When the ticket expires, and why the answer must not depend on the host.

``klist`` prints local time. :func:`ticket_expiry` reads it as UTC, which was
right only while nobody set a timezone on the container — and a ``TZ`` line in
a compose file is an easy thing to add. The failure it caused is nasty
precisely because it looks like nothing: with the offset running forward the
session outlives the ticket, so operations fail partway through the work
instead of sending the user back to the sign-in screen.

Nothing here reaches Kerberos. What is worth testing is the environment the
command is handed, because that is where the guarantee now lives.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from samadcon.auth import kerberos

# A real klist -c listing, trimmed to the parts the regex looks at.
KLIST_OUTPUT = b"""Ticket cache: FILE:/dev/shm/samadcon-ccache/abc
Default principal: administrator@EXAMPLE.TEST

Valid starting     Expires            Service principal
08/21/2026 09:14:02  08/21/2026 19:14:02  krbtgt/EXAMPLE.TEST@EXAMPLE.TEST
"""


@pytest.fixture
def krb5(monkeypatch: pytest.MonkeyPatch) -> None:
    class Configuration:
        def environment(self) -> dict[str, str]:
            return {"KRB5_CONFIG": "/etc/samadcon/krb5.conf"}

    import samadcon.auth.krb5conf as krb5conf

    monkeypatch.setattr(krb5conf, "get_krb5_configuration", lambda: Configuration())


@pytest.fixture
def captured(krb5: None, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Runs klist without klist: keeps the env, returns a fixed listing.

    The real _krb5_env runs — stubbing it would leave the test asserting its
    own stub, and the assertion below is the whole reason this file exists.
    Only the generated krb5 configuration is stood in for.
    """
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        seen["argv"] = argv
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, KLIST_OUTPUT, b"")

    monkeypatch.setattr(kerberos.subprocess, "run", fake_run)
    return seen


def test_the_expiry_is_read_as_utc(captured: dict[str, Any]) -> None:
    found = kerberos.ticket_expiry(Path("/dev/shm/ccache"))

    assert found == datetime(2026, 8, 21, 19, 14, 2, tzinfo=UTC)


def test_klist_is_run_with_the_timezone_pinned(captured: dict[str, Any]) -> None:
    """The whole point: the reading above is only true because of this."""
    kerberos.ticket_expiry(Path("/dev/shm/ccache"))

    assert captured["env"]["TZ"] == "UTC"


# ---------------------------------------------------------------------------
# The environment itself
# ---------------------------------------------------------------------------


def test_every_kerberos_command_gets_utc(
    krb5: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pinned in one place rather than at the call that was noticed. A second
    command parsing a timestamp later would otherwise inherit the old bug."""
    monkeypatch.setenv("TZ", "Europe/Berlin")

    assert kerberos._krb5_env()["TZ"] == "UTC"


def test_the_host_environment_still_comes_through(
    krb5: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAMADCON_MARKER", "kept")

    assert kerberos._krb5_env()["SAMADCON_MARKER"] == "kept"


def test_the_cache_is_named_only_when_one_is_given(krb5: None) -> None:
    """kinit is told where to write; the read-only commands are not."""
    assert "KRB5CCNAME" not in kerberos._krb5_env()
    assert kerberos._krb5_env(Path("/dev/shm/c")).get("KRB5CCNAME", "").startswith("FILE:")

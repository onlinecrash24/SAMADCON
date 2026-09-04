"""kinit is invoked with the principal as an operand, never as a flag."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from samadcon.auth import kerberos
from samadcon.auth.kerberos import Principal


@pytest.fixture
def settings(tmp_path: Path):
    from samadcon.config import Settings

    return Settings(
        realm="EXAMPLE.TEST",
        workgroup="EXAMPLE",
        ccache_dir=tmp_path / "ccache",
        krb5_config=tmp_path / "krb5.conf",
    )


def test_the_principal_is_separated_from_the_options(monkeypatch, settings):
    """A principal beginning with a dash must reach kinit as a name, not a
    switch. "--" ends option parsing, so the token straight after it is always
    an operand — the guarantee that does not depend on the regex two files
    away staying strict."""
    seen: dict[str, list[str]] = {}

    def fake_run(argv, **rest):
        seen["argv"] = argv
        return SimpleNamespace(returncode=0, stderr=b"", stdout=b"")

    monkeypatch.setattr(kerberos, "_krb5_env", lambda ccache=None: {})
    monkeypatch.setattr(kerberos.subprocess, "run", fake_run)

    kerberos._acquire_via_kinit(
        Principal(username="-k", realm="EXAMPLE.TEST"),
        "secret",
        Path("/tmp/cc"),
        settings,
    )

    argv = seen["argv"]
    assert "--" in argv
    assert argv[argv.index("--") + 1] == "-k@EXAMPLE.TEST"
    # And nothing the shell or getopt could read as an option precedes the name
    # without the terminator in between.
    assert argv.index("--") == len(argv) - 2

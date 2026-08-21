"""Shared test fixtures.

Unit tests run anywhere, including on machines without python3-samba: the
modules they exercise import the samba bindings lazily, inside the functions
that need them. Integration tests require the compose test environment and are
skipped otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Must be set before samadcon.config is imported anywhere.
os.environ.setdefault("SAMADCON_REALM", "SAMADCON.TEST")
os.environ.setdefault("SAMADCON_WORKGROUP", "SAMADCON")
os.environ.setdefault("SAMADCON_AUDIT_FILE", "")

DATA = Path(__file__).parent / "data"


def reference(name: str) -> bytes:
    """A file GPMC wrote, read from disk rather than retyped in a test.

    These used to be byte literals in the test modules. A literal is a
    transcription, and a transcription is a place for a slip that no test
    can catch — every assertion would agree with the mistake. Read as files,
    they can also be opened, hashed and compared by someone who did not
    write them.

    What they are, and what was changed for publication, is in
    tests/data/PROVENANCE.md.
    """
    return (DATA / name).read_bytes()


@pytest.fixture
def settings(tmp_path: Path):
    from samadcon.config import Settings

    return Settings(
        realm="SAMADCON.TEST",
        workgroup="SAMADCON",
        dc_hosts=["dc1.samadcon.test"],
        ccache_dir=tmp_path / "ccache",
        audit_file=tmp_path / "audit.jsonl",
        smb_conf=tmp_path / "smb.conf",
        krb5_config=tmp_path / "krb5.conf",
    )


@pytest.fixture
def audit_log(tmp_path: Path):
    from samadcon.core.audit import AuditLog

    return AuditLog(tmp_path / "audit.jsonl")


def has_samba() -> bool:
    try:
        import samba  # noqa: F401

        return True
    except ImportError:
        return False


requires_samba = pytest.mark.skipif(
    not has_samba(), reason="needs python3-samba (run inside the container)"
)

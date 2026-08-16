"""Credential cache naming.

A bare filesystem path is not a valid credential cache name. Kerberos wants a
type prefix, and without it the failure surfaces nowhere near its cause: the
ticket is obtained successfully, and the *bind* then fails with
NT_STATUS_INVALID_PARAMETER. samba-tool's --use-krb5-ccache does the same
prefixing for the same reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from samcon.auth.kerberos import CRED_SPECIFIED, ccache_url


def test_a_bare_path_gets_the_file_prefix():
    # Built from parts so the assertion holds on any platform's separator.
    path = Path("/dev/shm/samcon-ccache/tkt-abc")
    assert ccache_url(path) == f"FILE:{path}"
    assert ccache_url(path).startswith("FILE:")


def test_a_string_path_works_too():
    assert ccache_url("/tmp/ticket") == "FILE:/tmp/ticket"


@pytest.mark.parametrize(
    "name",
    [
        "FILE:/dev/shm/tkt",
        "DIR:/run/user/1000/krb5cc",
        "KEYRING:persistent:1000",
        "KCM:1000",
        "MEMORY:samcon",
    ],
)
def test_an_existing_type_prefix_is_left_alone(name: str):
    assert ccache_url(name) == name


def test_a_windows_style_path_is_not_mistaken_for_a_type():
    """C: is a drive letter, not a cache type — relevant for local test runs."""
    assert ccache_url("C:\\temp\\ticket") == "FILE:C:\\temp\\ticket"


def test_cred_specified_is_not_the_guess_value():
    """CRED_GUESS_ENV is 3; using it leaves the cache at guess priority.

    The bind then fails with a parameter error instead of saying what is wrong,
    which is exactly the trap this constant exists to avoid.
    """
    assert CRED_SPECIFIED != 3
    assert CRED_SPECIFIED == 6

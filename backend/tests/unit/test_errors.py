"""Error translation.

These cases are the ones that decide whether an administrator sees "the
password does not meet the policy" or "LDAP error 19".
"""

from __future__ import annotations

import pytest

from samcon.core import errors


class FakeLdbError(Exception):
    """Stands in for ldb.LdbError, which is only importable with samba present.

    Translation keys off the class *name*, so this is a faithful substitute.
    """

    __name__ = "LdbError"


# The translator matches on type(exc).__name__, so the class must be named
# LdbError exactly.
LdbError = type("LdbError", (Exception,), {})


def test_no_such_object_becomes_not_found():
    error = errors.translate(LdbError(32, "No such object: CN=nobody,DC=test"))
    assert isinstance(error, errors.NotFound)
    assert error.status_code == 404
    assert error.code == "not_found"


def test_insufficient_rights_becomes_permission_denied():
    error = errors.translate(LdbError(50, "Insufficient access rights"))
    assert isinstance(error, errors.PermissionDenied)
    assert error.status_code == 403
    assert error.hint  # points at delegation


def test_entry_already_exists_becomes_conflict():
    error = errors.translate(LdbError(68, "Entry already exists"))
    assert isinstance(error, errors.Conflict)
    assert error.code == "already_exists"


def test_non_leaf_delete_names_the_actual_problem():
    error = errors.translate(LdbError(66, "Not allowed on non-leaf"))
    assert error.code == "not_empty"
    assert error.status_code == 409


def test_password_policy_violation_is_recognised():
    """A constraint violation on a password must not read as a generic error."""
    message = (
        "0000052D: Constraint violation - check_password_restrictions: "
        "the password does not meet the complexity criteria!"
    )
    error = errors.translate(LdbError(19, message))
    assert error.code == "password_policy_violation"
    assert isinstance(error, errors.ConstraintViolation)
    assert "complexity" in (error.hint or "").lower() or "length" in (error.hint or "").lower()


def test_generic_constraint_violation_stays_generic():
    error = errors.translate(LdbError(19, "0000209A: Constraint violation on attribute foo"))
    assert error.code == "constraint_violation"


@pytest.mark.parametrize(
    ("data_code", "expected"),
    [
        ("52e", "invalid_credentials"),
        ("533", "account_disabled"),
        ("775", "account_locked_out"),
        ("532", "password_expired"),
        ("773", "password_must_change"),
        ("701", "account_expired"),
    ],
)
def test_bind_failure_subcodes_are_decoded(data_code: str, expected: str):
    """AD hides the real reason behind "invalid credentials" plus a data code."""
    message = f"80090308: LdapErr: DSID-0C0903A9, comment: AcceptSecurityContext error, data {data_code}, v4563"
    error = errors.translate(LdbError(49, message))
    assert error.code == expected


def test_unknown_bind_subcode_falls_back():
    error = errors.translate(LdbError(49, "data ffff"))
    assert error.code == "invalid_credentials"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("NT_STATUS_ACCESS_DENIED", "insufficient_access"),
        ("NT_STATUS_LOGON_FAILURE", "invalid_credentials"),
        ("NT_STATUS_OBJECT_NAME_COLLISION", "already_exists"),
        ("NT_STATUS_SHARING_VIOLATION", "file_in_use"),
        ("NT_STATUS_PASSWORD_RESTRICTION", "password_policy_violation"),
        ("NT_STATUS_TIME_DIFFERENCE_AT_DC", "clock_skew"),
    ],
)
def test_nt_status_is_mapped(text: str, expected: str):
    error = errors.translate(RuntimeError(f"failed: {text}"))
    assert error.code == expected


def test_unknown_nt_status_is_still_recognised_as_one():
    error = errors.translate(RuntimeError("NT_STATUS_SOMETHING_NEW"))
    assert error.code == "nt_status_error"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Clock skew too great", "clock_skew"),
        ("Preauthentication failed", "invalid_credentials"),
        ("Cannot contact any KDC for realm", "kdc_unreachable"),
        ("Client 'x@Y' not found in Kerberos database", "user_not_found"),
        ("certificate verify failed", "tls_verification_failed"),
    ],
)
def test_kerberos_text_is_mapped(text: str, expected: str):
    error = errors.translate(RuntimeError(text))
    assert error.code == expected


def test_clock_skew_hint_mentions_time_sync():
    error = errors.translate(RuntimeError("Clock skew too great"))
    assert "ntp" in (error.hint or "").lower()


def test_samcon_errors_pass_through_unchanged():
    original = errors.NotFound("gone")
    assert errors.translate(original) is original


def test_connection_errors_become_upstream_unavailable():
    error = errors.translate(ConnectionRefusedError("refused"))
    assert isinstance(error, errors.UpstreamUnavailable)


def test_to_dict_omits_empty_fields():
    payload = errors.NotFound("gone").to_dict()
    assert payload == {"code": "not_found", "message": "gone"}


def test_to_dict_includes_hint_and_context():
    payload = errors.PermissionDenied(
        "no", hint="check delegation", context={"dn": "CN=x"}
    ).to_dict()
    assert payload["hint"] == "check delegation"
    assert payload["context"] == {"dn": "CN=x"}


# ---------------------------------------------------------------------------
# NT_STATUS arriving as a number
# ---------------------------------------------------------------------------


class FakeNtStatusError(Exception):
    """Shaped like samba.NTSTATUSError: a number and a sentence, no symbol."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(code, message)


def test_a_status_named_in_the_text_is_translated():
    error = errors.translate(RuntimeError("NT_STATUS_SHARING_VIOLATION"))
    assert error.code == "file_in_use"


def test_a_status_that_arrives_only_as_a_number_is_translated(monkeypatch):
    """The SMB bindings never spell the symbol out.

    An NTSTATUSError reads (3221225539, 'A file cannot be opened because the
    share access flags are incompatible.') — until the number is looked up,
    every SMB failure surfaces as "an unexpected error occurred".
    """
    monkeypatch.setattr(
        errors, "_NUMERIC_NT_STATUS", {0xC0000043: "NT_STATUS_SHARING_VIOLATION"}
    )

    error = errors.translate(
        FakeNtStatusError(0xC0000043, "A file cannot be opened because the share access...")
    )

    assert error.code == "file_in_use"
    assert isinstance(error, errors.Conflict)


def test_an_unknown_number_still_falls_through_to_the_generic_message(monkeypatch):
    monkeypatch.setattr(errors, "_NUMERIC_NT_STATUS", {})
    error = errors.translate(FakeNtStatusError(0xC0000999, "something else"))
    assert error.code == "internal_error"


def test_the_numeric_table_is_built_from_the_symbols_we_translate():
    """So a symbol added to the table is recognised in both forms without
    anyone having to look up its number."""
    numeric = errors._numeric_nt_status()
    if not numeric:
        import pytest

        pytest.skip("the samba bindings are not installed here")

    assert set(numeric.values()) <= set(errors._NT_STATUS)
    assert numeric[0xC0000043] == "NT_STATUS_SHARING_VIOLATION"

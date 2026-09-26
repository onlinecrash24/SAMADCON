"""Generated passwords: long enough, complex, readable, and not the account's name.

A new account's first password is read off a screen or a printout and typed by
someone who has never seen it. So it must satisfy the domain on the first try,
and it must not contain characters that are the same shape as others.
"""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.ad import passwords

AMBIGUOUS = set("0O1lI")


@pytest.mark.parametrize("minimum", [0, 7, 16, 24])
def test_a_thousand_passwords_each_have_every_class_and_the_length(minimum: int):
    expected = max(passwords.MIN_LENGTH, minimum)
    for _ in range(1000):
        password = passwords.generate(minimum)
        assert len(password) == expected
        for kind in passwords.CLASSES:
            assert any(char in kind for char in password), (password, kind)
        assert not AMBIGUOUS & set(password)


def test_nothing_a_shell_or_a_csv_file_would_trip_over():
    alphabet = set("".join(passwords.CLASSES))
    assert not alphabet & set(" \t\"'`\\,;:<>|^~()[]{}/")


def test_the_account_name_is_split_the_way_complexity_splits_it():
    tokens = passwords.forbidden_tokens(["mmuster", "Max Muster-Schmidt", None, "Al"])
    assert "mmuster" in tokens
    assert {"max", "muster", "schmidt"} <= set(tokens)
    assert "al" not in tokens  # shorter than three characters is not checked


def test_a_password_containing_a_name_is_drawn_again(monkeypatch):
    """Rare with a random password, but not impossible — and the failure would
    look like a policy SAMADCON did not understand."""
    draws = iter(["Xy7!MUSTERabcdefgh", "Xy7!cleanabcdefghj"])
    monkeypatch.setattr(passwords, "_draw", lambda length, complex_: next(draws))
    assert passwords.generate(16, avoid=["Max Muster"]) == "Xy7!cleanabcdefghj"


class Domain:
    class Info:
        base_dn = "DC=example,DC=test"

    def __init__(self, head: dict[str, list[bytes]] | None) -> None:
        self.info = Domain.Info()
        self.head = head

    def get(self, dn: str, attrs: Any = None) -> Any:
        return self.head


def test_the_domain_minimum_is_honoured():
    domain = Domain({"minPwdLength": [b"21"], "pwdProperties": [b"1"]})
    assert len(passwords.for_domain(domain)) == 21


def test_an_unreadable_domain_head_still_gives_a_complex_password():
    password = passwords.for_domain(Domain(None))
    assert len(password) == passwords.MIN_LENGTH
    assert all(any(char in kind for char in password) for kind in passwords.CLASSES)

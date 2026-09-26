"""The interface language can be set for the deployment, and unset means the browser's.

Asked for by the maintainer: an English default without every administrator
clicking EN first. Set in the compose file; a choice made with the DE/EN
switch still wins, which is the interface's business and tested there.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from samadcon.config import Settings


def settings(monkeypatch, value: str | None) -> Settings:
    if value is None:
        monkeypatch.delenv("SAMADCON_DEFAULT_LANGUAGE", raising=False)
    else:
        monkeypatch.setenv("SAMADCON_DEFAULT_LANGUAGE", value)
    return Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize(("given", "expected"), [("en", "en"), ("DE", "de"), (" en ", "en")])
def test_a_language_the_interface_has_is_taken(monkeypatch, given, expected):
    assert settings(monkeypatch, given).default_language == expected


@pytest.mark.parametrize("given", [None, ""])
def test_unset_or_empty_leaves_it_to_the_browser(monkeypatch, given):
    """compose turns an unset variable into an empty string."""
    assert settings(monkeypatch, given).default_language is None


def test_a_language_the_interface_lacks_stops_the_start(monkeypatch):
    with pytest.raises(ValidationError):
        settings(monkeypatch, "fr")


def test_the_sign_in_page_is_told(monkeypatch):
    from samadcon.api.v1 import health
    from samadcon.config import get_settings

    monkeypatch.setenv("SAMADCON_DEFAULT_LANGUAGE", "en")
    get_settings.cache_clear()
    try:
        assert health.info()["default_language"] == "en"
    finally:
        get_settings.cache_clear()

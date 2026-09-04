"""Liveness and readiness."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samadcon import __version__
from samadcon.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, Any]:
    """Cheap liveness probe — never touches a domain controller."""
    return {"status": "ok", "version": __version__}


@router.get("/info")
def info() -> dict[str, Any]:
    """What the front end needs before anyone signs in.

    Deliberately small: this is reachable without a session, so it carries
    only what the sign-in form actually reads. The internal DC addresses and a
    live count of signed-in administrators used to be here too, answering a
    question nobody on the sign-in page had asked — the front end never read
    either. What is left is the realm to name on the form, whether LDAPS
    validation is off, and the transports this deployment permits.
    """
    settings = get_settings()
    return {
        "version": __version__,
        # Empty when no default domain is configured — the sign-in form then
        # asks for a server address.
        "realm": settings.realm or None,
        "ldap_insecure": settings.ldap_insecure,
        # What this deployment permits, in the order it tries them. Shown
        # beside what the session actually got, because the two answer
        # different questions: one is policy, the other is what happened.
        "ldap_transports": list(settings.ldap_transports),
    }

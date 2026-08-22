"""Liveness and readiness."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samadcon import __version__
from samadcon.auth.session import get_store
from samadcon.config import get_settings
from samadcon.core.executor import get_registry

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, Any]:
    """Cheap liveness probe — never touches a domain controller."""
    return {"status": "ok", "version": __version__}


@router.get("/info")
def info() -> dict[str, Any]:
    """What the front end needs before anyone signs in."""
    settings = get_settings()
    return {
        "version": __version__,
        # Empty when no default domain is configured — the sign-in form then
        # asks for a server address.
        "realm": settings.realm or None,
        "workgroup": settings.netbios_name or None,
        "dc_hosts": settings.dc_hosts or None,
        "dc_discovery": "static" if settings.dc_hosts else "dns",
        "allow_custom_servers": settings.allow_custom_servers,
        "has_server_profiles": bool(settings.servers_file),
        "ldap_insecure": settings.ldap_insecure,
        # What this deployment permits, in the order it tries them. Shown
        # beside what the session actually got, because the two answer
        # different questions: one is policy, the other is what happened.
        "ldap_transports": list(settings.ldap_transports),
        "sessions": {
            "active": get_store().count(),
            "workers": get_registry().active_sessions(),
            "idle_timeout_minutes": settings.session_idle_minutes,
        },
    }

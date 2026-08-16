"""Version 1 of the API."""

from fastapi import APIRouter

from samadcon.api.v1 import (
    admx,
    auth,
    computers,
    diagnostics,
    directory,
    dns,
    folders,
    gpos,
    groups,
    health,
    ous,
    preferences,
    scripts,
    security,
    security_settings,
    servers,
    sites,
    users,
    vgp,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(servers.router)
router.include_router(auth.router)
router.include_router(directory.router)
router.include_router(users.router)
router.include_router(groups.router)
router.include_router(computers.router)
router.include_router(ous.router)
router.include_router(security.router)
router.include_router(dns.router)
router.include_router(sites.router)
router.include_router(diagnostics.router)
router.include_router(gpos.router)
router.include_router(admx.router)
router.include_router(scripts.router)
router.include_router(folders.router)
router.include_router(security_settings.router)
router.include_router(vgp.router)
router.include_router(preferences.router)

__all__ = ["router"]

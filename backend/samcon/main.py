"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from samcon import __version__
from samcon.api.v1 import router as api_router
from samcon.auth.session import get_store
from samcon.config import get_settings
from samcon.core.errors import SamconError
from samcon.core.executor import get_registry

logger = logging.getLogger("samcon")

# How often expired sessions are reaped. Sessions also expire lazily on use;
# this exists so an abandoned session's Kerberos ticket does not sit in tmpfs
# until the container restarts.
SWEEP_INTERVAL_SECONDS = 60

STATIC_DIR = Path("/srv/samcon/www")


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level, logging.INFO))

    # uvicorn's access log duplicates what nginx already records.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


async def _sweep_sessions() -> None:
    store = get_store()
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            removed = store.sweep()
            if removed:
                logger.info("swept %d expired session(s)", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    if settings.realm:
        logger.info(
            "SAMCON %s starting (default realm=%s, dc=%s)",
            __version__,
            settings.realm,
            ", ".join(settings.dc_hosts) if settings.dc_hosts else "via DNS",
        )
    else:
        profiles = settings.load_profiles()
        logger.info(
            "SAMCON %s starting (no default realm; %d configured domain(s), "
            "custom addresses %s)",
            __version__,
            len(profiles),
            "allowed" if settings.allow_custom_servers else "disabled",
        )
    if settings.ldap_insecure:
        logger.warning(
            "SAMCON_LDAP_INSECURE=1 — LDAPS certificates are not validated. "
            "Do not run this way in production."
        )
    if settings.dev_mode:
        logger.warning("SAMCON_DEV_MODE=1 — development conveniences are enabled.")

    sweeper = asyncio.create_task(_sweep_sessions())
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        # Destroys every ticket and releases the Samba handles.
        get_store().close_all()
        get_registry().shutdown()
        logger.info("SAMCON stopped")


app = FastAPI(
    title="SAMCON — Samba AD Console",
    description=(
        "Administration API for Samba Active Directory domains. Every request "
        "runs with the Kerberos credentials of the signed-in administrator."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.include_router(api_router)


@app.exception_handler(SamconError)
async def handle_samcon_error(request: Request, exc: SamconError) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error("%s: %s", exc.code, exc.detail or exc.message)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Report validation problems in the same envelope as everything else."""
    fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", [])[1:]),
            "message": error.get("msg", "invalid value"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_failed",
                "message": "The request contains invalid values.",
                "context": {"fields": fields},
            }
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort.

    The detail stays in the container log; the client gets a stable code. An
    LDAP error message can quote DNs and attribute values, which is not
    something to hand out on an unauthenticated path.
    """
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred. See the server log for details.",
            }
        },
    )


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Any:
    """Headers for API responses.

    nginx sets these for the HTML it serves; API responses do not pass through
    that server block's add_header directives, so they are set again here.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


# Only used when running without nginx (`entrypoint.sh api`); in the normal
# container nginx serves the bundle directly.
if STATIC_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

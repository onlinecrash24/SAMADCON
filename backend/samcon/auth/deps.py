"""FastAPI dependencies for authenticated requests."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from samcon.auth.session import Session, get_store
from samcon.config import Settings, get_settings
from samcon.core.errors import SamconError
from samcon.core.executor import SessionWorker, get_registry

CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def client_ip(request: Request) -> str | None:
    """Caller address.

    uvicorn runs with --proxy-headers and trusts only 127.0.0.1, so by the time
    we see it the value already reflects nginx's X-Forwarded-For.
    """
    return request.client.host if request.client else None


def current_session(request: Request) -> Session:
    settings = get_settings()
    session = get_store().get(request.cookies.get(settings.cookie_name))
    # Makes the session available to exception handlers and the audit log.
    request.state.session = session
    return session


def verified_session(request: Request, session: Session = Depends(current_session)) -> Session:
    """Session plus CSRF check for state-changing requests.

    The cookie is SameSite=Strict, which already blocks cross-site form posts;
    the double-submit token covers the remaining cases (a same-site subdomain
    that got compromised, or a browser that ignores SameSite).
    """
    if request.method in UNSAFE_METHODS:
        token = request.headers.get(CSRF_HEADER)
        if not token or not _constant_time_equals(token, session.csrf_token):
            raise SamconError(
                "The request is missing a valid CSRF token.",
                code="csrf_failed",
                status_code=403,
                hint="Reload the page and try again.",
            )
    return session


def session_worker(session: Session = Depends(current_session)) -> SessionWorker:
    return get_registry().get(session.id)


def verified_worker(session: Session = Depends(verified_session)) -> SessionWorker:
    return get_registry().get(session.id)


def _constant_time_equals(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


CurrentSession = Annotated[Session, Depends(current_session)]
VerifiedSession = Annotated[Session, Depends(verified_session)]
Worker = Annotated[SessionWorker, Depends(session_worker)]
VerifiedWorker = Annotated[SessionWorker, Depends(verified_worker)]
AppSettings = Annotated[Settings, Depends(get_settings)]

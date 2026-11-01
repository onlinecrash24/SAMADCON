"""FastAPI dependencies for authenticated requests."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from samadcon.auth.session import Session, get_store
from samadcon.config import Settings, get_settings
from samadcon.core.errors import SamadconError
from samadcon.core.executor import SessionWorker, get_registry

CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def client_ip(request: Request) -> str | None:
    """Caller address.

    uvicorn runs with --proxy-headers and trusts only 127.0.0.1, so by the time
    we see it the value already reflects nginx's X-Forwarded-For.
    """
    return request.client.host if request.client else None


#: What nginx passes the identity provider's user on as. Set by nginx on every
#: API request — empty, which drops it, unless the request came from a trusted
#: proxy and SAMADCON_PROXY_USER_HEADER names the header that proxy uses.
IDP_USER_HEADER = "X-Samadcon-Idp-User"


def idp_user(request: Request) -> str | None:
    """The user the identity provider in front signed in, if there is one.

    Only what nginx let through reaches here, so this is about shape, not
    trust: a value that would not read as a name in the audit log is taken
    as no value at all.
    """
    value = (request.headers.get(IDP_USER_HEADER) or "").strip()
    if not value or len(value) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


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
            raise SamadconError(
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

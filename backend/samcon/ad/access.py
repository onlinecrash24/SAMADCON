"""Bridge between the async API layer and the per-session LDAP connection.

Routers never touch :class:`~samcon.ad.connection.DirectoryConnection`
directly. They hand a plain function to :func:`ad_read` or :func:`ad_write`,
which runs it on the session's worker thread with a live connection as its
first argument.

The read/write split exists for one reason: a lost connection may be retried
transparently for a search, but never for a modification — a write that failed
halfway must surface, not be replayed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from samcon.ad.connection import DirectoryConnection, connect
from samcon.auth.session import Session
from samcon.config import Settings, get_settings
from samcon.core.errors import OperationTimeout, UpstreamUnavailable
from samcon.core.executor import SessionWorker

logger = logging.getLogger(__name__)

T = TypeVar("T")

STATE_KEY = "directory"


def _connection(worker: SessionWorker, session: Session, settings: Settings) -> DirectoryConnection:
    """Return the session's connection, opening one if needed.

    Only ever called from inside the worker thread. The target comes from the
    session, so each signed-in administrator talks to the domain they chose.
    """
    conn = worker.state.get(STATE_KEY)
    if conn is None:
        conn = connect(session.target, settings, session.ccache)
        worker.state[STATE_KEY] = conn
    return conn


def _reconnect(worker: SessionWorker, session: Session, settings: Settings) -> DirectoryConnection:
    worker.state.pop(STATE_KEY, None)
    conn = connect(session.target, settings, session.ccache)
    worker.state[STATE_KEY] = conn
    return conn


async def ad_read(
    worker: SessionWorker,
    session: Session,
    func: Callable[..., T],
    *args: Any,
    label: str | None = None,
    timeout: float | None = None,
    settings: Settings | None = None,
    **kwargs: Any,
) -> T:
    """Run a read-only directory operation, reconnecting once if the DC drops."""
    resolved = settings or get_settings()

    def _run() -> T:
        conn = _connection(worker, session, resolved)
        try:
            return func(conn, *args, **kwargs)
        except (UpstreamUnavailable, OperationTimeout):
            logger.info("connection lost, reconnecting for %s", label or func.__name__)
            conn = _reconnect(worker, session, resolved)
            return func(conn, *args, **kwargs)

    return await worker.run(
        _run, label=label or getattr(func, "__name__", "ad.read"), timeout=timeout
    )


async def ad_write(
    worker: SessionWorker,
    session: Session,
    func: Callable[..., T],
    *args: Any,
    label: str | None = None,
    timeout: float | None = None,
    settings: Settings | None = None,
    **kwargs: Any,
) -> T:
    """Run a modifying directory operation. Never retried."""
    resolved = settings or get_settings()

    def _run() -> T:
        conn = _connection(worker, session, resolved)
        return func(conn, *args, **kwargs)

    return await worker.run(
        _run, label=label or getattr(func, "__name__", "ad.write"), timeout=timeout
    )

"""Off-loading blocking Samba calls from the event loop.

The Samba python bindings are blocking C extensions and are not thread-safe;
an ldb handle in particular must not be used from two threads at once. Instead
of guarding a shared pool with locks, every session gets **its own worker
thread**:

* operations of one session are serialised by construction, even when a call
  times out — the next one simply waits in that worker's queue,
* long-lived handles (SamDB, SMB connections) stay pinned to the single thread
  that created them and can be cached in :attr:`SessionWorker.state`,
* one runaway session cannot starve the others.

Nothing outside this module may call into samba directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from samadcon.core.errors import OperationTimeout, SamadconError, translate

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Operations slower than this are logged; they usually mean an unindexed
# search or a DC that is struggling.
SLOW_OPERATION_SECONDS = 2.0


def _discard_result(future: Any) -> None:
    """Consume the result of an abandoned call.

    Without this, a future whose caller already gave up on a timeout would
    raise "exception was never retrieved" once it finally completes.
    """
    # Cancellation or a translated error — both were already reported to the
    # caller that gave up.
    with contextlib.suppress(Exception):
        future.exception()


class SessionWorker:
    """A single thread that owns all Samba state of one session."""

    def __init__(self, session_id: str, default_timeout: float) -> None:
        self.session_id = session_id
        self.default_timeout = default_timeout
        self.state: dict[str, Any] = {}
        self.created_at = time.monotonic()
        self._pool = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"samba-{session_id[:8]}",
        )
        self._closed = False

    async def run(
        self,
        func: Callable[..., T],
        *args: Any,
        timeout: float | None = None,
        label: str | None = None,
        **kwargs: Any,
    ) -> T:
        if self._closed:
            raise SamadconError(
                "The session has been closed.", code="session_closed", status_code=401
            )

        name = label or getattr(func, "__name__", "samba-op")
        loop = asyncio.get_running_loop()
        started = time.monotonic()

        def _invoke() -> T:
            return func(*args, **kwargs)

        future = loop.run_in_executor(self._pool, _invoke)
        try:
            result = await asyncio.wait_for(
                asyncio.shield(future), timeout or self.default_timeout
            )
        except TimeoutError as exc:
            # The worker keeps running the call; the shield above makes sure it
            # is not cancelled mid-write, which could leave a half-applied
            # change behind. Queued work simply waits.
            future.add_done_callback(_discard_result)
            logger.warning(
                "operation timed out", extra={"op": name, "session": self.session_id[:8]}
            )
            raise OperationTimeout(
                "The operation did not finish in time.",
                code="timeout",
                hint="The domain controller may be slow or unreachable.",
                context={"operation": name},
            ) from exc
        except Exception as exc:
            error = translate(exc)
            # A refusal we raised ourselves is self-explanatory; anything that
            # came out of Samba is not, and the one question it always raises
            # is *which call* produced it. Without the traceback the log says
            # only that something went wrong somewhere in the operation, which
            # is how an afternoon goes into guessing at ACLs.
            #
            # The test is the cause, not the type: the layers below translate
            # Samba's exceptions where they happen, so by the time one arrives
            # here it is a SamadconError either way. What separates them is that
            # a translated one still carries what it wrapped.
            ours = isinstance(exc, SamadconError) and exc.__cause__ is None
            logger.log(
                logging.INFO if ours else logging.WARNING,
                "operation failed: %s (%s)",
                error.message,
                error.code,
                extra={"op": name, "session": self.session_id[:8], "code": error.code},
                exc_info=not ours,
            )
            raise error from exc

        elapsed = time.monotonic() - started
        if elapsed > SLOW_OPERATION_SECONDS:
            logger.warning(
                "slow operation: %s took %.1fs", name, elapsed,
                extra={"op": name, "session": self.session_id[:8]},
            )
        return result

    def close(self) -> None:
        """Drop the worker.

        Cached handles are released first so an ldb/SMB connection is torn down
        on the very thread that opened it.
        """
        if self._closed:
            return
        self._closed = True

        def _cleanup() -> None:
            for key, value in list(self.state.items()):
                closer = getattr(value, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:
                        logger.debug("failed to close %s", key, exc_info=True)
            self.state.clear()

        # RuntimeError means the pool is already shutting down — nothing left
        # to clean up.
        with contextlib.suppress(RuntimeError):
            self._pool.submit(_cleanup)
        # Do not block the event loop: pending work finishes in the background.
        self._pool.shutdown(wait=False)


class ExecutorRegistry:
    """Keeps one :class:`SessionWorker` per active session."""

    def __init__(self, default_timeout: float = 120.0, max_sessions: int = 64) -> None:
        self.default_timeout = default_timeout
        self.max_sessions = max_sessions
        self._workers: dict[str, SessionWorker] = {}

    def get(self, session_id: str) -> SessionWorker:
        worker = self._workers.get(session_id)
        if worker is None:
            if len(self._workers) >= self.max_sessions:
                raise SamadconError(
                    "Too many concurrent sessions.",
                    code="too_many_sessions",
                    status_code=503,
                    hint="Wait for other sessions to expire or raise SAMADCON_MAX_SESSIONS.",
                )
            worker = SessionWorker(session_id, self.default_timeout)
            self._workers[session_id] = worker
            logger.debug("worker created", extra={"session": session_id[:8]})
        return worker

    def drop(self, session_id: str) -> None:
        worker = self._workers.pop(session_id, None)
        if worker is not None:
            worker.close()
            logger.debug("worker dropped", extra={"session": session_id[:8]})

    def active_sessions(self) -> int:
        return len(self._workers)

    def shutdown(self) -> None:
        for session_id in list(self._workers):
            self.drop(session_id)


_registry: ExecutorRegistry | None = None


def get_registry() -> ExecutorRegistry:
    global _registry
    if _registry is None:
        from samadcon.config import get_settings

        settings = get_settings()
        _registry = ExecutorRegistry(default_timeout=float(settings.operation_timeout_seconds))
    return _registry


def reset_registry() -> None:
    """Test hook — drops all workers and forgets the singleton."""
    global _registry
    if _registry is not None:
        _registry.shutdown()
    _registry = None

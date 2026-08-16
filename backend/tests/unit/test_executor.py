"""The per-session worker.

The guarantee under test: two calls of the same session never run at the same
time. Samba's ldb handles are not thread-safe, and this is the only thing
standing between that fact and a corrupted connection.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from samcon.core.errors import NotFound, OperationTimeout, SamconError
from samcon.core.executor import ExecutorRegistry, SessionWorker


@pytest.fixture
def worker():
    instance = SessionWorker("test-session-id", default_timeout=5.0)
    yield instance
    instance.close()


async def test_runs_a_function_and_returns_its_value(worker: SessionWorker):
    assert await worker.run(lambda: 21 * 2) == 42


async def test_passes_arguments(worker: SessionWorker):
    assert await worker.run(lambda a, b=0: a + b, 40, b=2) == 42


async def test_runs_off_the_event_loop_thread(worker: SessionWorker):
    main_thread = threading.get_ident()
    worker_thread = await worker.run(threading.get_ident)
    assert worker_thread != main_thread


async def test_all_calls_share_one_thread(worker: SessionWorker):
    """State cached on the worker must stay pinned to a single thread."""
    threads = {await worker.run(threading.get_ident) for _ in range(5)}
    assert len(threads) == 1


async def test_calls_of_one_session_never_overlap(worker: SessionWorker):
    concurrent = 0
    peak = 0
    lock = threading.Lock()

    def slow() -> None:
        nonlocal concurrent, peak
        with lock:
            concurrent += 1
            peak = max(peak, concurrent)
        time.sleep(0.05)
        with lock:
            concurrent -= 1

    await asyncio.gather(*(worker.run(slow) for _ in range(5)))
    assert peak == 1


async def test_different_sessions_run_in_parallel():
    registry = ExecutorRegistry(default_timeout=5.0)
    barrier = threading.Barrier(3, timeout=5)

    def wait_for_others() -> str:
        # Deadlocks unless all three sessions really run concurrently.
        barrier.wait()
        return "ok"

    try:
        results = await asyncio.gather(
            *(registry.get(f"session-{index}").run(wait_for_others) for index in range(3))
        )
        assert results == ["ok", "ok", "ok"]
    finally:
        registry.shutdown()


async def test_exceptions_are_translated(worker: SessionWorker):
    def fail() -> None:
        raise RuntimeError("NT_STATUS_ACCESS_DENIED")

    with pytest.raises(SamconError) as excinfo:
        await worker.run(fail)
    assert excinfo.value.code == "insufficient_access"
    assert excinfo.value.status_code == 403


async def test_samcon_errors_pass_through_unchanged(worker: SessionWorker):
    def fail() -> None:
        raise NotFound("gone", context={"dn": "CN=x"})

    with pytest.raises(NotFound) as excinfo:
        await worker.run(fail)
    assert excinfo.value.context == {"dn": "CN=x"}


async def test_timeout_raises_and_names_the_operation(worker: SessionWorker):
    with pytest.raises(OperationTimeout) as excinfo:
        await worker.run(lambda: time.sleep(2), timeout=0.05, label="slow.op")
    assert excinfo.value.status_code == 504
    assert excinfo.value.context["operation"] == "slow.op"


async def test_a_timed_out_call_still_blocks_the_next_one(worker: SessionWorker):
    """The abandoned call keeps the worker; it is not cancelled mid-write.

    Cancelling a half-finished LDAP modify would be worse than making the
    next request wait.
    """
    started = time.monotonic()
    duration = 0.4

    with pytest.raises(OperationTimeout):
        await worker.run(lambda: time.sleep(duration), timeout=0.05)

    await worker.run(lambda: None)
    # The second call had to wait for the first to finish on its own. The
    # margin covers coarse sleep resolution on Windows, which can return a few
    # milliseconds early.
    assert time.monotonic() - started >= duration * 0.9


async def test_state_is_per_session():
    registry = ExecutorRegistry(default_timeout=5.0)
    try:
        registry.get("a").state["directory"] = "conn-a"
        registry.get("b").state["directory"] = "conn-b"
        assert registry.get("a").state["directory"] == "conn-a"
        assert registry.get("b").state["directory"] == "conn-b"
    finally:
        registry.shutdown()


async def test_drop_closes_cached_handles():
    registry = ExecutorRegistry(default_timeout=5.0)
    closed = threading.Event()

    class Handle:
        def close(self) -> None:
            closed.set()

    registry.get("a").state["directory"] = Handle()
    registry.drop("a")
    assert closed.wait(timeout=5)


async def test_closed_worker_refuses_further_work(worker: SessionWorker):
    worker.close()
    with pytest.raises(SamconError) as excinfo:
        await worker.run(lambda: 1)
    assert excinfo.value.code == "session_closed"


async def test_registry_enforces_a_session_ceiling():
    registry = ExecutorRegistry(default_timeout=5.0, max_sessions=2)
    try:
        registry.get("a")
        registry.get("b")
        with pytest.raises(SamconError) as excinfo:
            registry.get("c")
        assert excinfo.value.code == "too_many_sessions"
        assert excinfo.value.status_code == 503
    finally:
        registry.shutdown()


async def test_dropping_frees_a_slot():
    registry = ExecutorRegistry(default_timeout=5.0, max_sessions=1)
    try:
        registry.get("a")
        registry.drop("a")
        registry.get("b")  # must not raise
        assert registry.active_sessions() == 1
    finally:
        registry.shutdown()

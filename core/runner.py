"""The one way to run something for the browser: the work runs as a task, the generator relays.

    work (an asyncio.Task)                      relay (the SSE generator)
    ----------------------                      -------------------------
    run_started                                 start the work task
    body(trace) -> emits events  -- live -->    yield each event, in seq order
    run_complete / run_failed / run_aborted     until None (finish() was called)
    finish(status)               -- None -->    await the task, so errors surface

A generator can only send at a `yield`, so a generator that awaited the work itself would be deaf
for the whole of a model call. Here the work never yields, and the generator never does work.

The gotcha: if the browser leaves, Starlette cancels the generator but NOT the task, which would
go on making paid model calls for nobody. So the generator cancels the task on its way out.
"""

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable

from core.trace import RunStatus, RunTrace

# A run body does the actual work, emitting events as it goes, and returns the payload for
# `run_complete`. It does not emit lifecycle events or call finish(); run_work does that.
RunBody = Callable[[RunTrace], Awaitable[dict[str, Any]]]


async def run_work(trace: RunTrace, body: RunBody, note: str) -> None:
    """Own one run's lifecycle, from run_started to finish(). Runs as a task."""
    status: RunStatus = "aborted"  # guilty until proven: only a known outcome overwrites this
    abort_reason = "unknown"
    try:
        trace.emit("run_started", "system", {"note": note})
        outcome = await body(trace)
        trace.emit("run_complete", "system", outcome)
        status = "complete"
    except asyncio.CancelledError as exc:
        # Not an Exception (it is a BaseException), so it never lands in the branch below.
        # The canceller says why in the message; we record it and let the cancellation proceed.
        abort_reason = str(exc.args[0]) if exc.args else "cancelled"
        raise
    except Exception as exc:
        status = "failed"
        trace.emit("run_failed", "system", {"error": repr(exc)})
        raise
    finally:
        # No `yield` or `await` in here: we may be mid-cancellation. Synchronous writes only.
        if status == "aborted":
            trace.emit("run_aborted", "system", {"reason": abort_reason})
        trace.finish(status)  # also puts None on trace.live: the relay's signal to stop


async def stream_run(body: RunBody, note: str) -> AsyncIterator[str]:
    """Start `body` as a run and relay its events as SSE text, live, until the run finishes."""
    trace = RunTrace()
    task = asyncio.create_task(run_work(trace, body, note))
    try:
        while (event := await trace.live.get()) is not None:
            yield event.to_sse()
        await task  # the run is over; re-raises here if the work failed, so the error is seen
    finally:
        # Synchronous only. If the client left mid-run we are being cancelled; stop the work too,
        # or it keeps calling the model. cancel() just asks: the task raises CancelledError at
        # its next await and its own `finally` records run_aborted. A no-op if it is done.
        task.cancel("client disconnected")
        if task.done() and not task.cancelled():
            # The work may have failed while we were parked at a `yield` and then the client left,
            # so nobody awaited it. Mark its exception retrieved (it is already in the trace as
            # run_failed) so asyncio does not log "Task exception was never retrieved".
            task.exception()

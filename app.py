import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse

from core.trace import RunStatus, RunTrace

app = FastAPI(title="Agent Choir Studio V2")

FRONTEND = Path(__file__).parent / "frontend"


async def fake_run():
    trace = RunTrace()
    status: RunStatus = "aborted"  # guilty until proven: only a known outcome overwrites this
    try:
        yield trace.emit("run_started", "system", {"note": "skeleton run"}).to_sse()
        for step in range(1, 4):
            await asyncio.sleep(1)
            yield trace.emit("test_event", "system", {"step": step}).to_sse()
        done = trace.emit("run_complete", "system", {"note": "done"})
        status = "complete"  # the run finished; delivering the last message is not part of that
        yield done.to_sse()
    except Exception as exc:
        # A real error in our code. Client hang-ups never land here (see walkthrough).
        status = "failed"
        trace.emit("run_failed", "system", {"error": repr(exc)})
        raise
    finally:
        # No `yield` or `await` in here: the client may be gone and the task may be cancelled.
        # Only synchronous file writes, which is all RunTrace does.
        if status == "aborted":
            trace.emit("run_aborted", "system", {"reason": "client disconnected"})
        trace.finish(status)


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stream")
def stream():
    return StreamingResponse(
        fake_run(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )

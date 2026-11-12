import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse

from core.runner import stream_run
from core.trace import RunTrace
from demo.live_demo import editor_demo

app = FastAPI(title="Agent Choir Studio V2")

FRONTEND = Path(__file__).parent / "frontend"


async def fake_body(trace: RunTrace) -> dict[str, Any]:
    """The free test run: three timed test events, no model calls."""
    for step in range(1, 4):
        await asyncio.sleep(1)
        trace.emit("test_event", "system", {"step": step})
    return {"note": "done"}


def sse(events: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(events, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stream")
def stream():
    return sse(stream_run(fake_body, "skeleton run"))


@app.get("/stream/live")
def stream_live():
    """Costs money: one real call_model() run (demo fixture, ~2 model calls)."""
    return sse(stream_run(editor_demo, "live demo: editor, fake corpus"))

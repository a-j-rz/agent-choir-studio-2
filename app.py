import asyncio
from functools import partial
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from core.llm import get_client
from core.runner import stream_run
from core.trace import RunTrace
from demo.live_demo import editor_demo
from host.run import host_run
from retrieval.vectors import get_model, on_model

log = logging.getLogger("uvicorn.error")  # uvicorn's own logger, so the line shows in its output


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at server start, before any request: do the client's one-off blocking setup
    here, so it never stalls the event loop inside a run. No network call is made."""
    t0 = time.monotonic()
    get_client()
    log.info("OpenAI client created at startup in %.0f ms", (time.monotonic() - t0) * 1000)
    # The embedding model once, at startup (Decisions K9): a run then only fetches it.
    t0 = time.monotonic()
    await on_model(get_model)
    log.info("embedding model loaded at startup in %.0f ms", (time.monotonic() - t0) * 1000)
    yield


app = FastAPI(title="Agent Choir Studio V2", lifespan=lifespan)

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


class HostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


@app.post("/run/host")
def run_host(body: HostRequest):
    """Costs money: up to three Host calls (triage; then scoring and cast on proceed). POST, so
    a prefetch or link preview cannot fire it."""
    return sse(stream_run(partial(host_run, question=body.question), "host run (4c)"))

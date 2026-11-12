import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse

app = FastAPI(title="Agent Choir Studio V2")

FRONTEND = Path(__file__).parent / "frontend"


def sse(event_type: str, role: str, payload: dict) -> str:
    data = {"type": event_type, "role": role, "payload": payload, "ts": time.time()}
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def fake_run():
    yield sse("run_started", "system", {"note": "skeleton run"})
    for step in range(1, 4):
        await asyncio.sleep(1)
        yield sse("test_event", "system", {"step": step})
    yield sse("run_complete", "system", {"note": "done"})


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

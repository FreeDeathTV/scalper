"""Backend entrypoint — loopback HTTP + SSE server (spec §5).

Run standalone:  uvicorn main:app --host 127.0.0.1 --port <random>
Tauri sidecar spawns this via src-tauri/src/lib.rs; the chosen port is printed
on stdout as `SCALPER_PORT=<n>` for the shell to relay to the UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from core import pipeline
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from ipc.events import bus
from ipc.schemas import (
    BatchJobRequest,
    HealthReport,
    JobCreated,
    JobStatus,
    StreamStartRequest,
)

logging.basicConfig(level=logging.INFO, stream=sys.stderr)

app = FastAPI(title="scalper-transcriber-backend", version="0.1.0")


@app.get("/health")
async def health() -> HealthReport:
    from core.aligner import aligner_available
    from core.devices import cpu_cores, has_cuda
    from core.engines.faster_whisper_engine import FasterWhisperEngine
    from ipc.schemas import Settings

    engines = {
        "faster-whisper": FasterWhisperEngine().available(),
        "aligner": aligner_available(),
    }
    report = HealthReport(
        status="ok" if engines["faster-whisper"] else "degraded",
        engines=engines,
        models_present=[],  # populated by scripts/download_models.py inventory
        devices={
            "cuda": has_cuda(),
            "cpu_cores": cpu_cores(),
            "compute_default": Settings().compute_type,
        },
    )
    return report


@app.post("/jobs/batch")
async def jobs_batch(req: BatchJobRequest) -> JobCreated:
    """Fire-and-track: the job runs as a background task; UI follows GET /events."""
    path_exists = __import__("pathlib").Path(req.file_path).exists()
    if not path_exists:
        raise HTTPException(status_code=400, detail="file not found")
    job_holder: dict[str, str] = {}

    async def runner() -> None:
        try:
            await pipeline.run_batch(req, bus)
        except Exception:
            pass  # status already published as stage="error"

    task = asyncio.create_task(runner())
    _TASKS[id(task)] = task
    job_id = f"batch-{id(task):x}"
    job_holder["id"] = job_id
    return JobCreated(job_id=job_id)


@app.post("/jobs/cancel")
async def jobs_cancel(payload: dict) -> dict[str, object]:
    job_id = str(payload.get("job_id", ""))
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id required")
    pipeline.cancel(job_id)
    return {"cancelled": True}


@app.post("/jobs/stream/start")
async def jobs_stream_start(req: StreamStartRequest) -> JobCreated:
    raise HTTPException(status_code=501, detail="live streaming lands in milestone M5")


@app.get("/events")
async def events(request: Request) -> StreamingResponse:
    async def gen():
        queue = bus.subscribe("*")
        try:
            while True:
                if await request.is_disconnected():
                    break
                status: JobStatus = await queue.get()
                yield f"data: {json.dumps(status.model_dump())}\n\n"
        finally:
            bus.unsubscribe("*", queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


_TASKS: dict[int, asyncio.Task] = {}

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
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
from core import pipeline
from core.live import UtteranceBuffer
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from ipc.events import bus
from ipc.schemas import (
    BatchJobRequest,
    HealthReport,
    JobCreated,
    JobStatus,
    LiveTranscriptEvent,
    Settings,
)
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("main")

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


_DOCS: dict[str, object] = {}  # completed batch docs keyed by our external job_id


def _spawn_batch(file_path: str, settings: Settings) -> str:
    """Shared fire-and-track runner for file-picker and uploaded captures."""
    ext_id = f"batch-{uuid.uuid4().hex[:8]}"
    req = BatchJobRequest(file_path=file_path, settings=settings)

    async def runner() -> None:
        try:
            doc = await pipeline.run_batch(req, bus)
            _DOCS[ext_id] = doc.model_dump(mode="json")
        except Exception:
            # surface in server logs so errors aren't silently invisible;
            # the bus already carries a stage="error" JobStatus for the UI.
            logger.exception("batch %s failed for %s", ext_id, file_path)

    task = asyncio.create_task(runner())
    _TASKS[id(task)] = task
    return ext_id
    # NOTE(m1): run_batch emits its own internal session id on the bus; progress
    # consumers listen on '*' today. Unify ids when cancellation is wired (M1).
    return ext_id


@app.get("/transcript/{job_id}")
async def get_transcript(job_id: str) -> object:
    doc = _DOCS.get(job_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="transcript not ready or unknown job")
    return doc


@app.post("/jobs/batch")
async def jobs_batch(req: BatchJobRequest) -> JobCreated:
    """Fire-and-track: the job runs as a background task; UI follows GET /events."""
    if not Path(req.file_path).exists():
        raise HTTPException(status_code=400, detail="file not found")
    return JobCreated(job_id=_spawn_batch(req.file_path, req.settings))


@app.post("/jobs/cancel")
async def jobs_cancel(payload: dict[str, object]) -> dict[str, object]:
    job_id = str(payload.get("job_id", ""))
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id required")
    pipeline.cancel(job_id)
    return {"cancelled": True}


@app.post("/capture/upload")
async def capture_upload(
    file: UploadFile = File(...), settings_json: str = Form("{}")
) -> JobCreated:
    """System-audio capture recorded in the webview → batch pipeline.

    The client WAV-encodes its capture locally (16 kHz mono PCM) and POSTs it;
    the server persists it under the OS temp dir and runs the same stages as
    /jobs/batch. Transcripts land next to the capture file as usual.
    """
    raw = await file.read()
    if len(raw) <= 44:  # a WAV header with no samples behind it
        raise HTTPException(status_code=400, detail="empty capture upload")
    cap_dir = Path(tempfile.gettempdir()) / "scalper_captures"
    cap_dir.mkdir(parents=True, exist_ok=True)
    dest = cap_dir / f"capture-{uuid.uuid4().hex[:12]}.wav"
    dest.write_bytes(raw)
    try:
        settings = Settings(**json.loads(settings_json or "{}"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"bad settings: {exc}") from exc
    return JobCreated(job_id=_spawn_batch(str(dest), settings))


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    """Live transcription: binary frames in (f32le PCM @16k), events via SSE.

    Protocol: first TEXT frame is JSON {\"settings\": {...}}; then binary PCM
    chunks; a final TEXT frame {\"action\": \"stop\"} flushes and closes.
    Completed utterances are published to the bus as LiveTranscriptEvent so the
    UI receives them over the same SSE stream used for batch progress.
    """
    await ws.accept()
    session_id = uuid.uuid4().hex[:12]
    settings = Settings()
    try:
        init_raw = await ws.receive_text()
        init = json.loads(init_raw)
        if isinstance(init.get("settings"), dict):
            settings = Settings(**init["settings"])
        await ws.send_json({"session_id": session_id})
    except WebSocketDisconnect:
        return
    except ValueError:
        await ws.close(code=1008)
        return

    from core.transcriber import get_engine

    try:
        engine = await asyncio.to_thread(get_engine, settings)
    except RuntimeError as exc:
        bus.publish(JobStatus(job_id=f"live-{session_id}", stage="error", message=str(exc)))
        await ws.close(code=1011)
        return

    buf = UtteranceBuffer()
    live_job = f"live-{session_id}"

    async def transcribe(start: float, end: float, chunk: np.ndarray) -> None:
        try:
            result = await asyncio.to_thread(
                engine.transcribe_chunk, chunk, start, end, settings
            )
        except Exception as exc:  # noqa: BLE001 — a bad utterance must not kill the session
            logger.warning("live utterance %s..%s failed: %s", start, end, exc)
            bus.publish(
                JobStatus(job_id=live_job, stage="error", message=f"transcription failed: {exc}")
            )
            return
        if not result.text.strip():
            return
        bus.publish(
            LiveTranscriptEvent(
                session_id=session_id, start_s=start, end_s=end, text=result.text.strip()
            )
        )
        bus.publish(JobStatus(job_id=live_job, stage="listening", message=result.text[:80]))

    try:
        bus.publish(JobStatus(job_id=live_job, stage="listening", message="live session started"))
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            text_frame = msg.get("text")
            if text_frame is not None:
                data = json.loads(text_frame)
                if data.get("action") == "stop":
                    break
                continue
            frame = msg.get("bytes")
            if not frame:
                continue
            pcm = np.frombuffer(frame, dtype="<f4").astype(np.float32)
            for start, end, chunk in buf.feed(pcm):
                await transcribe(start, end, chunk)
        # graceful stop: emit the tail utterance if any
        tail = buf.flush()
        if tail is not None:
            await transcribe(*tail)
        bus.publish(JobStatus(job_id=live_job, stage="done", message="live session ended"))
        try:
            await ws.send_json({"done": True, "session_id": session_id})
            await ws.close()
        except Exception:  # noqa: BLE001 — client may already be gone
            pass
    except WebSocketDisconnect:
        tail = buf.flush()
        if tail is not None:
            await transcribe(*tail)


@app.get("/events")
async def events(request: Request) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        queue = bus.subscribe("*")
        try:
            while True:
                if await request.is_disconnected():
                    break
                status: BaseModel = await queue.get()
                yield f"data: {json.dumps(status.model_dump())}\n\n"
        finally:
            bus.unsubscribe("*", queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


_TASKS: dict[int, asyncio.Task[None]] = {}

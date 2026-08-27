"""Backend entrypoint â€” loopback HTTP + SSE server (spec Â§5).

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
import time
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
from fastapi.middleware.cors import CORSMiddleware
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

# The webview is a different origin than the loopback sidecar (http://localhost:1420
# in dev, http://tauri.localhost in the packaged Tauri window), so cross-origin
# requests/SSE must be allowed explicitly. Local service only â€” safe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LIVE_OVERLAP_S = 0.5


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
    """System-audio capture recorded in the webview â†’ batch pipeline.

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

    # Keep live results responsive; long uninterrupted speech is split into
    # shorter ASR chunks instead of waiting up to the batch-oriented default.
    buf = UtteranceBuffer(max_utterance_s=settings.live_chunk_seconds)
    live_job = f"live-{session_id}"
    transcription_lock = asyncio.Lock()
    transcription_tasks: list[asyncio.Task[None]] = []
    overlap_tail = np.empty(0, dtype=np.float32)
    captured_chunks: list[np.ndarray] = []
    captured_samples = 0
    cancelled = False
    session_started = time.perf_counter()
    last_capture_at = session_started

    async def finish_transcriptions(timeout: float | None = 2.0) -> None:
        if not transcription_tasks:
            return
        try:
            pending = asyncio.gather(*transcription_tasks)
            if timeout is None:
                await pending
            else:
                await asyncio.wait_for(pending, timeout=timeout)
        except asyncio.TimeoutError:
            logger.info("live session %s stopping with transcription still in progress", session_id)
            for task in transcription_tasks:
                if not task.done():
                    task.cancel()

    def queue_utterance(start: float, end: float, chunk: np.ndarray) -> None:
        nonlocal overlap_tail
        overlap_samples = int(LIVE_OVERLAP_S * 16_000)
        if overlap_tail.size:
            chunk = np.concatenate((overlap_tail, chunk))
            start = max(0.0, start - LIVE_OVERLAP_S)
        logger.info(
            "live timing session=%s phase=utterance-queued capture_s=%.3f "
            "utterance_s=%.3f queue_depth=%d model=%s device=%s",
            session_id,
            end,
            end - start,
            len(transcription_tasks),
            settings.model_size,
            settings.effective_device,
        )
        transcription_tasks.append(asyncio.create_task(transcribe(start, end, chunk)))
        overlap_tail = chunk[-overlap_samples:].copy()

    async def transcribe(start: float, end: float, chunk: np.ndarray) -> None:
        queued_at = time.perf_counter()
        async with transcription_lock:
            try:
                result = await asyncio.to_thread(engine.transcribe_chunk, chunk, start, end, settings)
            except Exception as exc:  # noqa: BLE001 â€” a bad utterance must not kill the session
                logger.warning("live utterance %s..%s failed: %s", start, end, exc)
                bus.publish(
                    JobStatus(job_id=live_job, stage="error", message=f"transcription failed: {exc}")
                )
                return
        completed_at = time.perf_counter()
        transcription_s = completed_at - queued_at
        logger.info(
            "live timing session=%s phase=transcription-complete capture_s=%.3f "
            "utterance_s=%.3f transcription_s=%.3f queue_depth=%d model=%s device=%s rtf=%.3f",
            session_id,
            end,
            end - start,
            transcription_s,
            max(0, sum(not task.done() for task in transcription_tasks) - 1),
            settings.model_size,
            settings.effective_device,
            transcription_s / max(end - start, 0.001),
        )
        if not result.text.strip():
            return
        bus.publish(
            LiveTranscriptEvent(
                session_id=session_id, start_s=start, end_s=end, text=result.text.strip(), draft=True
            )
        )
        bus.publish(JobStatus(job_id=live_job, stage="listening", message=result.text[:80]))

    async def finalize_capture() -> tuple[str, float] | None:
        if not captured_chunks or captured_samples == 0:
            return None
        pcm = np.concatenate(captured_chunks) if len(captured_chunks) > 1 else captured_chunks[0]
        duration_s = captured_samples / 16_000
        logger.info(
            "live timing session=%s phase=final-pass-start capture_s=%.3f model=%s device=%s",
            session_id,
            duration_s,
            settings.model_size,
            settings.effective_device,
        )
        final_settings = settings
        final_engine = engine
        if settings.final_model_size and settings.final_model_size != settings.model_size:
            final_settings = settings.model_copy(update={"model_size": settings.final_model_size})
            final_engine = await asyncio.to_thread(get_engine, final_settings)
        result = await asyncio.to_thread(final_engine.transcribe_chunk, pcm, 0.0, duration_s, final_settings)
        final_text = result.text.strip()
        if final_text:
            bus.publish(
                LiveTranscriptEvent(
                    session_id=session_id,
                    start_s=0.0,
                    end_s=duration_s,
                    text=final_text,
                    draft=False,
                )
            )
        logger.info(
            "live timing session=%s phase=final-pass-complete capture_s=%.3f",
            session_id,
            duration_s,
        )
        return (final_text, duration_s) if final_text else None
    try:
        bus.publish(JobStatus(job_id=live_job, stage="listening", message="live session started"))
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            text_frame = msg.get("text")
            if text_frame is not None:
                data = json.loads(text_frame)
                if data.get("action") == "cancel":
                    cancelled = True
                    break
                if data.get("action") == "stop":
                    break
                continue
            frame = msg.get("bytes")
            if frame is None or len(frame) == 0:
                continue
            last_capture_at = time.perf_counter()
            pcm = np.frombuffer(frame, dtype="<f4").astype(np.float32)
            captured_chunks.append(pcm.copy())
            captured_samples += pcm.size
            for start, end, chunk in buf.feed(pcm):
                queue_utterance(start, end, chunk)
        if not cancelled:
            # graceful stop: emit the tail utterance if any
            tail = buf.flush()
            if tail is not None:
                queue_utterance(*tail)
        await finish_transcriptions(timeout=None)
        final_result: tuple[str, float] | None = None
        if not cancelled:
            final_result = await finalize_capture()
        logger.info(
            "live timing session=%s phase=session-complete capture_s=%.3f "
            "elapsed_s=%.3f model=%s device=%s",
            session_id,
            max(0.0, last_capture_at - session_started),
            time.perf_counter() - session_started,
            settings.model_size,
            settings.effective_device,
        )
        bus.publish(
            JobStatus(
                job_id=live_job,
                stage="cancelled" if cancelled else "done",
                message="live session cancelled" if cancelled else "live session ended",
            )
        )
        try:
            completion = {"done": True, "session_id": session_id}
            if final_result is not None:
                completion.update({"final_text": final_result[0], "final_end_s": final_result[1]})
            await ws.send_json(completion)
            await ws.close()
        except Exception:  # noqa: BLE001 â€” client may already be gone
            pass
    except WebSocketDisconnect:
        tail = buf.flush()
        if tail is not None:
            queue_utterance(*tail)
        await finish_transcriptions()


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


async def _warm_live_model() -> None:
    """Load the low-latency live model while the app is starting."""
    from core.engines.faster_whisper_engine import FasterWhisperEngine

    try:
        await asyncio.to_thread(
            FasterWhisperEngine().load,
            Settings(model_size="base", device="cpu"),
        )
        logger.info("live model warmed: base (cpu)")
    except Exception:
        logger.exception("live model warmup failed; it will retry on first use")


@app.on_event("startup")
async def warm_live_model_on_startup() -> None:
    task = asyncio.create_task(_warm_live_model())
    _TASKS[id(task)] = task

"""Pipeline orchestrator — batch mode end-to-end (spec §4).

Stage order: preprocess → vad → transcribe → align → diarize → postprocess → export.
Each stage publishes JobStatus via ipc.events; cancellation is checked between
stages AND between chunks (must respond <1 s per acceptance criteria §10).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from functools import partial
from pathlib import Path
from typing import cast

import numpy as np
from ipc.events import EventBus, compute_overall
from ipc.schemas import (
    BatchJobRequest,
    Stage,
    TranscriptDocument,
    TranscriptSegment,
)

from core import audio_preprocess, exporter, postprocess, vad_segmenter

logger = logging.getLogger(__name__)

CANCELLED: set[str] = set()


class CancelledError(Exception):
    pass


def _check_cancel(job_id: str) -> None:
    if job_id in CANCELLED:
        raise CancelledError(job_id)


async def run_batch(request: BatchJobRequest, bus: EventBus) -> TranscriptDocument:
    job_id = uuid.uuid4().hex[:12]
    loop = asyncio.get_running_loop()

    def emit(stage: Stage, progress: float, message: str | None = None) -> None:
        from ipc.schemas import JobStatus

        bus.publish(
            JobStatus(
                job_id=job_id,
                stage=stage,
                progress=progress,
                overall_progress=compute_overall(stage, progress),
                message=message,
            )
        )

    emit("queued", 0.0)
    started = time.monotonic()
    try:
        # ---- preprocess ----
        audio_pcm, sr = await loop.run_in_executor(
            None, audio_preprocess.load_audio, request.file_path
        )
        prep = audio_preprocess.preprocess(audio_pcm, sr, denoise_enabled=request.settings.denoise)
        pcm = cast(np.ndarray, prep["audio"])
        # TODO(m1): segment timestamps below are offsets into the TRIMMED timeline;
        # before release they must be rebased onto the source-file timeline using
        # prep["trim_start_s"] once word alignment (M2) lands. Known limitation.
        emit(
            "preprocess",
            1.0,
            f"{cast(float, prep['duration_s']):.1f}s audio ready",
        )

        # ---- vad ----
        _check_cancel(job_id)
        model = await loop.run_in_executor(None, vad_segmenter.load_vad_model)
        segments = vad_segmenter.segment(pcm, threshold=request.settings.vad_threshold, model=model)
        chunks = vad_segmenter.chunks_for_asr(pcm, segments)
        emit("vad", 1.0, f"{len(chunks)} speech segments")

        # ---- transcribe (fallback ladder resolved inside engine) ----
        _check_cancel(job_id)
        from core.transcriber import get_engine

        engine = await loop.run_in_executor(None, get_engine, request.settings)
        doc_segments: list[TranscriptSegment] = []
        language: str | None = None
        for i, (start_s, end_s, chunk) in enumerate(chunks):
            _check_cancel(job_id)
            result = await loop.run_in_executor(
                None,
                partial(
                    engine.transcribe_chunk,
                    chunk,
                    start_s,
                    end_s,
                    request.settings,
                ),
            )
            language = language or result.language
            doc_segments.append(TranscriptSegment(start=start_s, end=end_s, text=result.text))
            emit("transcribe", (i + 1) / max(len(chunks), 1))

        doc = TranscriptDocument(
            source_file=request.file_path,
            duration_s=len(pcm) / vad_segmenter.SILERO_SR,
            language=language or "en",
            segments=doc_segments,
        )

        # ---- align ----
        _check_cancel(job_id)
        from core.aligner import align_segment

        for seg in doc.segments:
            seg_idx = doc.segments.index(seg)
            a, b, chunk = chunks[seg_idx]
            local = seg.model_copy(update={"start": 0.0, "end": b - a})
            aligned = await loop.run_in_executor(None, align_segment, chunk, local, language)
            aligned.start, aligned.end = a, b
            doc.segments[seg_idx] = aligned
        emit("align", 1.0)

        # ---- diarize ----
        if request.settings.diarize:
            _check_cancel(job_id)
            from core.diarizer import apply_diarization

            doc = await loop.run_in_executor(None, apply_diarization, doc, pcm, request.settings)
        emit("diarize", 1.0)

        # ---- postprocess + export ----
        _check_cancel(job_id)
        doc = postprocess.postprocess(doc, request.settings.custom_vocabulary)
        emit("postprocess", 1.0)
        out_dir = Path(request.file_path).parent / "transcripts"
        written = exporter.export(doc, out_dir, request.settings.export_formats)
        emit("export", 1.0, f"wrote {[p.name for p in written]}")
        emit("done", 1.0)
        logger.info("job %s finished in %.1fs", job_id, time.monotonic() - started)
        return doc
    except CancelledError:
        emit("cancelled", 0.0, "cancelled by user")
        raise
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        emit("error", 0.0, str(exc))
        raise


def cancel(job_id: str) -> bool:
    CANCELLED.add(job_id)
    return True

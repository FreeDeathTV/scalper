"""IPC schemas — single source of truth for frontend/backend exchange.

Mirrored in TypeScript at src/lib/types/ipc.ts.
RULE (spec §5): change this file AND the TS mirror in the same commit.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal[
    "queued",
    "preprocess",
    "vad",
    "transcribe",
    "align",
    "diarize",
    "postprocess",
    "export",
    "done",
    "error",
    "cancelled",
    "listening",  # live session idle/waiting for speech
]

ComputeType = Literal["int8", "int8_float16", "float16"]
Device = Literal["auto", "cuda", "cpu"]


class TranscriptWord(BaseModel):
    start: float
    end: float
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    speaker: str | None = None  # e.g. "Speaker 1"
    low_confidence: bool = False  # set by postprocess quality guard (spec §7.4)


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    words: list[TranscriptWord] = []
    language: str | None = None
    draft: bool = False  # true until the streaming final pass completes


class TranscriptDocument(BaseModel):
    schema_version: Literal[1] = 1
    source_file: str | None = None
    duration_s: float = 0.0
    language: str = "en"  # ISO 639-1
    segments: list[TranscriptSegment] = []
    vocabulary_applied: list[str] = []


class Settings(BaseModel):
    model_size: str = "medium"
    final_model_size: str | None = None
    language: str | None = None
    live_chunk_seconds: float = Field(default=4.0, ge=3.0, le=5.0)
    device: Device = "auto"
    compute_type: ComputeType = "int8"
    denoise: bool = False
    diarize: bool = False
    min_speakers: int | None = Field(default=None, ge=2, le=5)
    max_speakers: int | None = Field(default=None, ge=2, le=5)
    translate_to_english: bool = False
    custom_vocabulary: list[str] = []
    vad_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    export_formats: list[Literal["txt", "srt", "vtt", "json"]] = ["txt"]

    @property
    def effective_device(self) -> str:
        """Resolve 'auto' via device probe (spec §6)."""
        if self.device != "auto":
            return self.device
        from core.devices import has_cuda  # local import avoids probe at import time

        return "cuda" if has_cuda() else "cpu"


class BatchJobRequest(BaseModel):
    file_path: str
    settings: Settings = Settings()


class StreamStartRequest(BaseModel):
    settings: Settings = Settings()


class JobStatus(BaseModel):
    event: Literal["job_status"] = "job_status"  # SSE discriminator
    job_id: str
    stage: Stage = "queued"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)  # within current stage
    overall_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str | None = None


class LiveTranscriptEvent(BaseModel):
    """A live draft or final transcript update, via GET /events."""

    event: Literal["live_segment"] = "live_segment"
    session_id: str
    start_s: float  # absolute offset in the live stream
    end_s: float
    text: str
    draft: bool = True


class JobCreated(BaseModel):
    job_id: str


class HealthReport(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    app_version: str = "0.1.0"
    engines: dict[str, bool] = {}
    models_present: list[str] = []
    devices: dict[str, object] = {}


# Weighted stage durations used by overall_progress (spec §5, tune after M1).
STAGE_WEIGHTS: dict[str, float] = {
    "queued": 0.01,
    "preprocess": 0.09,
    "vad": 0.10,
    "transcribe": 0.50,
    "align": 0.15,
    "diarize": 0.10,
    "postprocess": 0.03,
    "export": 0.02,
}

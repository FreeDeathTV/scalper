"""SSE event bus — emits JobStatus updates consumed via GET /events (spec §5)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

from .schemas import STAGE_WEIGHTS, JobStatus


def compute_overall(stage: str, stage_progress: float) -> float:
    """Weighted progress across pipeline stages so one bar reflects everything."""
    done_weight = sum(
        w
        for s, w in STAGE_WEIGHTS.items()
        if s not in ("done", "error", "cancelled") and _stage_index(s) < _stage_index(stage)
    )
    current = STAGE_WEIGHTS.get(stage, 0.0) * stage_progress
    total = sum(w for s, w in STAGE_WEIGHTS.items() if s not in ("done", "error", "cancelled"))
    value = (done_weight + current) / total if total else stage_progress
    return round(min(max(value, 0.0), 1.0), 4)


_ORDER = [
    "queued",
    "preprocess",
    "vad",
    "transcribe",
    "align",
    "diarize",
    "postprocess",
    "export",
    "done",
]


def _stage_index(stage: str) -> int:
    try:
        return _ORDER.index(stage)
    except ValueError:
        return -1


class EventBus:
    """Per-job pub/sub keyed by job_id ('*' broadcasts to all listeners)."""

    def __init__(self) -> None:
        self._queues: dict[str, set[asyncio.Queue[JobStatus]]] = defaultdict(set)

    def subscribe(self, job_id: str = "*") -> asyncio.Queue[JobStatus]:
        q: asyncio.Queue[JobStatus] = asyncio.Queue(maxsize=256)
        self._queues[job_id].add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue[JobStatus]) -> None:
        self._queues[job_id].discard(q)

    def publish(self, status: JobStatus) -> None:
        for key in (status.job_id, "*"):
            for q in list(self._queues.get(key, ())):
                try:
                    q.put_nowait(status)
                except asyncio.QueueFull:  # slow consumer: drop oldest semantics are fine
                    pass

    async def stream(self, job_id: str = "*") -> AsyncIterator[JobStatus]:
        q = self.subscribe(job_id)
        try:
            while True:
                yield await q.get()
        finally:
            self.unsubscribe(job_id, q)


bus = EventBus()

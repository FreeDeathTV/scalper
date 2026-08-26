"""Stage 3: transcriber — engine-agnostic ASR interface (spec §3/§6).

Engines register through TranscriberEngine. Selection + fallback ladder lives
in get_engine() per spec §6: large-v3 fp16 → large-v3 int8_float16 → medium int8.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from ipc.schemas import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AsrChunkResult:
    text: str
    language: str | None
    start_s: float
    end_s: float


class TranscriberEngine(Protocol):
    name: str

    def available(self) -> bool: ...
    def load(self, settings: Settings) -> None: ...
    def unload(self) -> None: ...
    def transcribe_chunk(
        self,
        pcm: np.ndarray,
        start_s: float,
        end_s: float,
        settings: Settings,
        **kwargs: object,
    ) -> AsrChunkResult: ...


_FALLBACK_LADDER: tuple[tuple[str, str], ...] = (
    ("large-v3", "float16"),
    ("large-v3", "int8_float16"),
    ("medium", "int8"),
)


def get_engine(settings: Settings) -> TranscriberEngine:
    """Resolve engine by capability; step down the ladder rather than fail (spec §6.3).

    Raises RuntimeError only when NO backend is installed — surfaced to the UI
    as a user-readable error ('install faster-whisper') per checklist error taxonomy.
    """
    from core.devices import has_cuda

    candidates: list[TranscriberEngine] = []

    if (
        settings.model_size.startswith(("parakeet", "canary"))
        or settings.device == "cuda"
        and has_cuda()
    ):
        try:
            from core.engines.parakeet_engine import ParakeetEngine

            candidates.append(ParakeetEngine())
        except ImportError:
            logger.info("parakeet engine requested but nemo not installed")

    from core.engines.faster_whisper_engine import FasterWhisperEngine

    candidates.append(FasterWhisperEngine())

    for engine in candidates:
        if engine.available():
            engine.load(settings)
            return engine
    raise RuntimeError(
        "No transcription backend available. Install 'faster-whisper' "
        "(pip install faster-whisper) and retry."
    )


def resolve_ladder(settings: Settings) -> list[tuple[str, str]]:
    """Ordered (model_size, compute_type) attempts honoring explicit user choice."""
    requested = (settings.model_size, settings.compute_type)
    ladder: list[tuple[str, str]] = [requested]
    ladder += [x for x in _FALLBACK_LADDER if x != requested]
    if settings.model_size in ("small", "base"):  # small models keep their size
        return [requested]
    return ladder

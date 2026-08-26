"""Parakeet/Canary engine stub — FEATURE-FLAGGED OFF until after M1 (spec §8).

Interface compiles and reports unavailable until NeMo is installed. Kept behind
the `parakeet.enabled` settings flag per docs/GITHUB_WORKFLOW.md §4.
"""

from __future__ import annotations

import numpy as np

from ..transcriber import AsrChunkResult
from ipc.schemas import Settings


class ParakeetEngine:
    name = "parakeet"

    def available(self) -> bool:
        try:
            import nemo.collections.asr  # noqa: F401

            return True
        except ImportError:
            return False

    def load(self, settings: Settings) -> None:
        if not settings.model_size.startswith(("parakeet", "canary")):
            raise ValueError("ParakeetEngine requires a parakeet/canary model_size")
        raise NotImplementedError(
            "Parakeet backend lands in M1+; see checklist decisions log"
        )

    def unload(self) -> None:
        pass

    def transcribe_chunk(
        self,
        pcm: np.ndarray,
        start_s: float,
        end_s: float,
        settings: Settings,
        **kw: object,
    ) -> AsrChunkResult:
        raise NotImplementedError("Parakeet backend lands in M1+")

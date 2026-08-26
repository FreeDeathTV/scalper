"""Stage 5: diarizer — pyannote.audio 3.1 wrapper (M3).

Licensing gate lives HERE per spec §11: user-supplied HF token accepted once,
cached locally under app data, never logged/transmitted. Absence of token or
package ⇒ graceful degradation to no-speaker transcripts.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from ipc.schemas import Settings, TranscriptDocument


def diarizer_available() -> bool:
    try:
        import pyannote.audio  # noqa: F401

        return True
    except ImportError:
        return False


def hf_token_present() -> bool:
    if "HF_TOKEN" in os.environ:
        return True
    cache = Path.home() / ".scalper" / "hf_token"
    return cache.exists()


def apply_diarization(doc: TranscriptDocument, pcm: np.ndarray, settings: Settings) -> TranscriptDocument:
    """Label speakers Speaker 1..N via max temporal overlap mapping (spec §4)."""
    if not (settings.diarize and diarizer_available() and hf_token_present()):
        return doc  # graceful skip mode with clear UI messaging handled client-side
    # M3 implementation plan (checklist): pyannote speaker-diarization-3.1 on wav;
    # merge turns; overlap policy below stays regardless of embedding source.
    raise NotImplementedError("wire pyannote in M3")


def map_turns_to_words(doc: TranscriptDocument, turns: list[tuple[str, float, float]]) -> TranscriptDocument:
    """Shared overlap-mapping logic — unit-testable without pyannote installed."""
    for seg in doc.segments:
        for w in seg.words:
            mid = (w.start + w.end) / 2
            best = max(
                turns,
                key=lambda t: min(w.end, t[2]) - max(w.start, t[1]),
                default=None,
            )
            if best and best[1] <= mid <= best[2]:
                w.speaker = best[0]
    return doc

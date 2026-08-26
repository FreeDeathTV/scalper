"""Stage 4: aligner — WhisperX wav2vec2 forced alignment (M2).

Word-level timings are REQUIRED for SRT/VTT exports + clickable transcript UI.
Pipeline tolerates its absence: segments carry segment-level times only, and
`low_confidence` flagging is skipped (guarded import mirrors engines).
"""

from __future__ import annotations

import numpy as np

from ipc.schemas import TranscriptSegment, TranscriptWord


def aligner_available() -> bool:
    try:
        import whisperx  # noqa: F401

        return True
    except ImportError:
        return False


def align_segment(
    pcm: np.ndarray, seg: TranscriptSegment, language: str | None
) -> TranscriptSegment:
    """Attach word-level timestamps to one segment.

    Falls back to uniform interpolation across the segment when whisperx is not
    installed so downstream code can rely on `words` existing — but confidence
    values are neutral (0.5), flagged low_confidence=False to avoid false alarms.
    """
    tokens = [t for t in seg.text.split() if t]
    if not tokens or aligner_available() is False:
        return _interpolate_words(seg, tokens)
    # Real implementation (M2): whisperx.load_align_model(language) → assign word spans.
    raise NotImplementedError("wire whisperx here in M2")


def _interpolate_words(seg: TranscriptSegment, tokens: list[str]) -> TranscriptSegment:
    dur = max(seg.end - seg.start, 1e-6)
    per = dur / len(tokens)
    seg.words = [
        TranscriptWord(
            start=seg.start + i * per,
            end=seg.start + (i + 1) * per,
            text=tok,
            confidence=0.5,
        )
        for i, tok in enumerate(tokens)
    ]
    return seg

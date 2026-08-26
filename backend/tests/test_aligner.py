"""Aligner tests — interpolation fallback + empty-segment regression."""
import numpy as np

from core.aligner import _interpolate_words, align_segment
from ipc.schemas import TranscriptSegment


def test_empty_segment_gets_no_words_and_does_not_crash():
    """Regression: Whisper may return '' for a noisy segment; M1 E2E hit
    ZeroDivisionError in _interpolate_words before this fix."""
    seg = TranscriptSegment(start=1.0, end=2.5, text="")
    out = _interpolate_words(seg, [])
    assert out.words == []


def test_interpolation_spans_words_across_segment():
    seg = TranscriptSegment(start=0.0, end=4.0, text="alpha beta gamma delta")
    out = _interpolate_words(seg, seg.text.split())
    assert [w.text for w in out.words] == ["alpha", "beta", "gamma", "delta"]
    assert out.words[0].start == 0.0
    assert abs(out.words[-1].end - 4.0) < 1e-6
    # contiguous word boundaries
    for prev, cur in zip(out.words, out.words[1:]):
        assert abs(prev.end - cur.start) < 1e-6


def test_align_segment_without_whisperx_falls_back_to_interpolation():
    seg = TranscriptSegment(start=10.0, end=12.0, text="hello world")
    out = align_segment(np.zeros(100, dtype=np.float32), seg, "en")
    if not __import__("core.aligner", fromlist=["aligner_available"]).aligner_available():
        assert [w.text for w in out.words] == ["hello", "world"]

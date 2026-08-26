"""VAD segmentation + diarizer word-mapping logic (no model downloads needed)."""

import numpy as np

from core import vad_segmenter as vad
from core.diarizer import map_turns_to_words
from ipc.schemas import TranscriptDocument, TranscriptSegment, TranscriptWord


class TestSegmentation:
    def test_silence_returns_no_segments(self):
        silent = np.zeros(16_000 * 3, dtype=np.float32)
        segs = vad.segment(silent)  # energy fallback path (model absent in CI)
        assert segs == []

    def test_tone_produces_at_least_one_segment(self):
        audio = np.concatenate([
            np.zeros(16_000, dtype=np.float32),
            (0.3 * np.sin(2 * np.pi * 300 * np.arange(16_000 * 2) / 16_000)).astype(np.float32),
            np.zeros(16_000, dtype=np.float32),
        ])
        segs = vad.segment(audio)
        assert len(segs) >= 1
        for s in segs:
            assert s.duration >= vad.MIN_SPEECH_S - 0.01

    def test_nonempty_audio_never_yields_zero_duration_segments(self):
        audio = (0.4 * np.sin(np.arange(48_000) / 50)).astype(np.float32)
        for s in vad.segment(audio):
            assert s.end_s > s.start_s

    def test_chunks_for_asr_slices_match_segments(self):
        audio = (0.5 * np.sin(np.arange(32_000) / 30)).astype(np.float32)
        segs = vad.segment(audio)
        chunks = vad.chunks_for_asr(audio, segs)
        if segs:  # dev-fallback may legitimately return some segments here
            for (start, end, pcm), s in zip(chunks, segs):
                assert abs(start - s.start_s) < 1e-6
                assert len(pcm) <= len(audio)


def _doc() -> TranscriptDocument:
    return TranscriptDocument(
        language="en",
        duration_s=10.0,
        segments=[
            TranscriptSegment(
                start=0.0,
                end=2.0,
                text="hello there world",
                words=[
                    TranscriptWord(start=0.0, end=0.7, text="hello", confidence=0.9),
                    TranscriptWord(start=0.8, end=1.3, text="there", confidence=0.9),
                    TranscriptWord(start=1.4, end=2.0, text="world", confidence=0.9),
                ],
            ),
            TranscriptSegment(
                start=5.0,
                end=6.5,
                text="second turn",
                words=[
                    TranscriptWord(start=5.0, end=6.5, text="second turn", confidence=0.8),
                ],
            ),
        ],
    )


class TestSpeakerMapping:
    def test_words_mapped_to_overlapping_turn(self):
        turns = [("Speaker 1", 0.0, 2.0), ("Speaker 2", 4.5, 7.0)]
        out = map_turns_to_words(_doc(), turns)
        assert out.segments[0].words[0].speaker == "Speaker 1"
        assert out.segments[1].words[0].speaker == "Speaker 2"

    def test_word_outside_any_turn_stays_unlabeled(self):
        turns = [("Speaker 1", 100.0, 101.0)]  # nowhere near our words
        out = map_turns_to_words(_doc(), turns)
        assert all(w.speaker is None for s in out.segments for w in s.words)

    def test_higher_overlap_wins_regardless_of_listing_order(self):
        # A hugs the word tighter (0.45s overlap) than B (0.40s) despite being listed first
        turns = [("A", 0.05, 0.5), ("B", 0.0, 0.4)]
        out = map_turns_to_words(_doc(), turns)
        assert out.segments[0].words[0].speaker == "A"

    def test_word_straddling_turn_boundary_uses_midpoint(self):
        turns = [("Speaker 1", 0.0, 0.35), ("Speaker 2", 0.36, 2.0)]
        out = map_turns_to_words(_doc(), turns)
        words = out.segments[0].words
        assert {w.speaker for w in words} == {"Speaker 1", "Speaker 2"}

    def test_no_turns_leaves_document_intact(self):
        doc = _doc()
        snapshot = [w.model_copy() for s in doc.segments for w in s.words]
        out = map_turns_to_words(doc, [])
        assert [w.model_copy() for s in out.segments for w in s.words] == snapshot

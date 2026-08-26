"""Spec §7 quality guards: repetition collapse, confidence floor, vocab replacement."""

import pytest

from core import postprocess
from ipc.schemas import TranscriptDocument, TranscriptSegment, TranscriptWord


def _doc(texts: list[str]) -> TranscriptDocument:
    return TranscriptDocument(
        language="en",
        duration_s=10.0,
        segments=[
            TranscriptSegment(start=float(i) * 5, end=(i + 1) * 5.0 - 0.1, text=t)
            for i, t in enumerate(texts)
        ],
    )


class TestRepetitionCollapse:
    def test_detects_looped_whisper_output(self):
        looped = "the meeting starts the meeting starts the meeting starts the meeting starts"
        assert postprocess.detect_repetition_collapse(looped)

    def test_normal_speech_not_flagged(self):
        normal = "good morning everyone and welcome to our quarterly review session"
        assert not postprocess.detect_repetition_collapse(normal)

    def test_retry_kwargs_match_spec(self):
        # spec §7.2 pins these exact values
        assert postprocess.RETRY_GENERATION_KWARGS == {
            "no_repeat_ngram_size": 6,
            "temperature": 0.4,
        }


class TestConfidenceFloor:
    def test_words_below_floor_flagged(self):
        doc = _doc(["hello there"])
        doc.segments[0].words = [
            TranscriptWord(start=0, end=0.3, text="hello", confidence=0.9),
            TranscriptWord(start=0.3, end=0.6, text="there", confidence=0.2),
        ]
        out = postprocess.apply_confidence_floor(doc)
        assert out.segments[0].words[0].low_confidence is False
        assert out.segments[0].words[1].low_confidence is True


class TestVocabulary:
    def test_longest_match_wins(self):
        doc = _doc(["contact joe at acme"])
        _, applied = postprocess.apply_vocabulary(doc, ["acme", "acme corp", "joe"])
        assert applied == sorted({"acme", "joe"})

    def test_case_preserving_and_initial_caps(self):
        doc = _doc(["the Ceo spoke"])
        postprocess.apply_vocabulary(doc, ["ceo"])
        assert "Ceo" in doc.segments[0].text  # preserved source case shape

    def test_allcaps_vocab_forced_upper(self):
        doc = _doc(["use api today"])
        postprocess.apply_vocabulary(doc, ["API"])
        assert "API" in doc.segments[0].text

    def test_applied_list_recorded_on_document(self):
        doc = _doc(["faster whisper rocks"])
        postprocess.apply_vocabulary(doc, ["Faster Whisper"])
        assert doc.vocabulary_applied == ["Faster Whisper"]


class TestPunctuationCasing:
    def test_adds_final_period_and_caps_first_word(self):
        doc = _doc(["welcome to the show"])
        out = postprocess.restore_punctuation_casing(doc)
        assert out.segments[0].text == "Welcome to the show."

    @pytest.mark.parametrize("existing", ["already done.", "what?", "wow!"])
    def test_does_not_double_punctuate(self, existing):
        doc = _doc([existing])
        out = postprocess.restore_punctuation_casing(doc)
        assert out.segments[0].text == existing


class TestRuntDropping:
    def test_segments_below_min_speech_dropped(self):
        doc = TranscriptDocument(
            segments=[
                TranscriptSegment(start=0, end=0.1, text="hm"),  # below spec §7.3 floor
                TranscriptSegment(start=0.2, end=2.0, text="real speech"),
            ]
        )
        out = postprocess.drop_runt_segments(doc)
        assert [s.text for s in out.segments] == ["real speech"]

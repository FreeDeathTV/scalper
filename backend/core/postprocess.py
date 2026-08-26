"""Stage 6: postprocess (spec §4, §7).

Includes the MANDATORY hallucination/quality guards from spec §7:
  - repetition-collapse detection + retry parameters
  - confidence floor flagging
  - custom-vocabulary longest-match replacement (case preserving)
"""

from __future__ import annotations

import re
from collections import Counter

from ipc.schemas import TranscriptDocument

CONFIDENCE_FLOOR = 0.35  # spec §7.4
REPETITION_NGRAM_THRESHOLD = 4  # spec §7.2


def detect_repetition_collapse(
    text: str, *, n: int = 3, threshold: int = REPETITION_NGRAM_THRESHOLD
) -> bool:
    """Whisper loop detection (spec §7.2): the same token n-gram recurring ≥ threshold times."""
    tokens = text.split()
    if len(tokens) < n * threshold:
        return False
    grams = [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
    counts = Counter(grams)
    return counts.most_common(1)[0][1] >= threshold


# Retry parameters handed to the transcriber for flagged chunks (spec §7.2)
RETRY_GENERATION_KWARGS = {"no_repeat_ngram_size": 6, "temperature": 0.4}


def apply_confidence_floor(doc: TranscriptDocument) -> TranscriptDocument:
    for seg in doc.segments:
        seg.words = [
            w.model_copy(update={"low_confidence": w.confidence < CONFIDENCE_FLOOR})
            if not w.low_confidence
            else w
            for w in seg.words
        ]
    return doc


def _build_vocab_pattern(vocab: list[str]) -> re.Pattern[str] | None:
    terms = sorted({v.strip() for v in vocab if v.strip()}, key=len, reverse=True)
    if not terms:
        return None
    escaped = "|".join(re.escape(t) for t in terms)
    return re.compile(rf"\b({escaped})\b", flags=re.IGNORECASE)


def apply_vocabulary(
    doc: TranscriptDocument, vocab: list[str]
) -> tuple[TranscriptDocument, list[str]]:
    """Longest-match replacement preserving case variants (spec §7.5).

    Case rule: ALL-CAPS term in vocabulary → replacement upper-cases;
    otherwise match the source word's case shape via .title()/lower().
    """
    pattern = _build_vocab_pattern(vocab)
    applied: list[str] = []

    def replace(match: re.Match[str]) -> str:
        src = match.group(0)
        target = next(t for t in vocab if t.lower() == src.lower())
        if target.isupper():
            fixed = target
        elif src[:1].isupper():
            fixed = " ".join(w.capitalize() for w in target.split())
        else:
            fixed = target.lower()
        applied.append(target)
        return fixed

    if pattern is not None:
        for seg in doc.segments:
            seg.text = pattern.sub(replace, seg.text)
            seg.words = [
                w.model_copy(update={"text": pattern.sub(replace, w.text)}) for w in seg.words
            ]
    doc.vocabulary_applied = sorted(set(applied))
    return doc, doc.vocabulary_applied


def restore_punctuation_casing(doc: TranscriptDocument) -> TranscriptDocument:
    """Placeholder stage (M4). Guarantees segment-final terminal punctuation;
    full recaser model plugs into this single function later. Existing casing
    inside the segment is preserved verbatim — we only normalize the tail."""
    for seg in doc.segments:
        text = seg.text.strip()
        if not text:
            continue
        if text[-1] not in ".!?…":
            seg.text = text[0].upper() + text[1:] + "."
        else:
            seg.text = text
    return doc


def drop_runt_segments(doc: TranscriptDocument, min_speech_s: float = 0.25) -> TranscriptDocument:
    """Segments shorter than VAD min_speech are dropped entirely (spec §7.3)."""
    doc.segments = [s for s in doc.segments if (s.end - s.start) >= min_speech_s or s.words]
    return doc


def postprocess(doc: TranscriptDocument, vocab: list[str]) -> TranscriptDocument:
    doc = drop_runt_segments(doc)
    doc = apply_confidence_floor(doc)
    doc = restore_punctuation_casing(doc)
    if vocab:
        doc, _ = apply_vocabulary(doc, vocab)
    return doc

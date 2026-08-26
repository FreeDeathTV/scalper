"""Stage 7: exporter — TXT / SRT / VTT / JSON writers (spec §4, deliverable M1/M2)."""

from __future__ import annotations

import json
from pathlib import Path

from ipc.schemas import TranscriptDocument

Format = str  # one of "txt" | "srt" | "vtt" | "json" (validated against ALLOWED)


ALLOWED = ("txt", "srt", "vtt", "json")


def _ts_srt(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ts_vtt(seconds: float) -> str:
    return _ts_srt(seconds).replace(",", ".")


def to_txt(doc: TranscriptDocument, *, with_timestamps: bool = False) -> str:
    lines: list[str] = []
    for seg in doc.segments:
        speakers = {w.speaker for w in seg.words if w.speaker}
        label = f"[{sorted(speakers)[0]}] " if speakers else ""
        stamp = f"[{_ts_vtt(seg.start)}] " if with_timestamps else ""
        lines.append(f"{stamp}{label}{seg.text}")
    return "\n".join(lines) + "\n"


def _cue_block(idx: int, start: float, end: float, body: str, sep_fmt) -> str:
    return f"{idx}\n{sep_fmt(start)} --> {sep_fmt(end)}\n{body}\n"


def to_srt(doc: TranscriptDocument) -> str:
    blocks = [
        _cue_block(i + 1, seg.start, seg.end, seg.text.strip(), _ts_srt)
        for i, seg in enumerate([s for s in doc.segments if s.text.strip()])
    ]
    return "\n".join(blocks)


def to_vtt(doc: TranscriptDocument) -> str:
    cues = [
        _cue_block(i + 1, seg.start, seg.end, seg.text.strip(), _ts_vtt)
        for i, seg in enumerate([s for s in doc.segments if s.text.strip()])
    ]
    header = "WEBVTT\n\n"
    # Word-level cues appended when alignment produced words (spec §4, milestone M2)
    word_cues: list[str] = []
    idx = len(cues)
    for seg in doc.segments:
        for w in seg.words:
            idx += 1
            body = f"<{w.speaker}> " if w.speaker else ""
            word_cues.append(_cue_block(idx, w.start, w.end, body + w.text.strip(), _ts_vtt))
    return header + "\n".join(cues + word_cues)


def to_json(doc: TranscriptDocument) -> str:
    return json.dumps(doc.model_dump(), ensure_ascii=False, indent=2)


FORMATTERS = {
    "txt": lambda d: to_txt(d),
    "srt": to_srt,
    "vtt": to_vtt,
    "json": to_json,
}


def export(doc: TranscriptDocument, out_dir: str | Path, formats: list[str]) -> list[Path]:
    """Write requested formats next to each other; returns written paths."""
    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    stem = Path(doc.source_file).stem if doc.source_file else "transcript"
    written: list[Path] = []
    for fmt in formats:
        fmt_l = fmt.lower().lstrip(".")
        if fmt_l not in ALLOWED:
            raise ValueError(f"unsupported export format: {fmt!r} (allowed: {ALLOWED})")
        path = base / f"{stem}.{fmt_l}"
        path.write_text(FORMATTERS[fmt_l](doc), encoding="utf-8")
        written.append(path)
    return written

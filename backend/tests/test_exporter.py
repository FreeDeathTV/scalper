import json

from core import exporter
from ipc.schemas import TranscriptDocument, TranscriptSegment, TranscriptWord


def _doc() -> TranscriptDocument:
    return TranscriptDocument(
        source_file="meeting.mp3",
        duration_s=6.0,
        language="en",
        segments=[
            TranscriptSegment(
                start=0.0,
                end=2.0,
                text="Welcome to the meeting",
                words=[
                    TranscriptWord(start=0.0, end=0.5, text="Welcome", confidence=0.95),
                    TranscriptWord(start=0.5, end=1.0, text="to", confidence=0.90),
                    TranscriptWord(start=1.0, end=2.0, text="the meeting", confidence=0.88),
                ],
            ),
            TranscriptSegment(start=3.0, end=5.5, text="Second speaker starts here"),
        ],
    )


def test_srt_format_timestamps():
    srt = exporter.to_srt(_doc())
    assert "00:00:00,000 --> 00:00:02,000" in srt
    assert "00:00:03,000 --> 00:00:05,500" in srt
    assert srt.splitlines()[0] == "1"
    # blank line between cues
    blocks = srt.strip().split("\n\n")
    assert len(blocks) == 2


def test_vtt_header_and_word_cues():
    vtt = exporter.to_vtt(_doc())
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.000" in vtt
    # word-level cues present because alignment produced words (M2 contract)
    assert "--> 00:00:00.500" in vtt
    assert "Welcome" in vtt


def test_txt_plain_and_timestamped():
    plain = exporter.to_txt(_doc())
    assert "Welcome to the meeting" in plain
    stamped = exporter.to_txt(_doc(), with_timestamps=True)
    assert "[00:00:00.000] Welcome to the meeting" in stamped


def test_json_roundtrip_through_pydantic():
    raw = json.loads(exporter.to_json(_doc()))
    assert raw["schema_version"] == 1
    assert raw["source_file"] == "meeting.mp3"
    restored = TranscriptDocument.model_validate(raw)
    assert len(restored.segments) == 2


def test_export_writes_requested_formats(tmp_path):
    written = exporter.export(_doc(), tmp_path, ["txt", "srt", "vtt", "json"])
    names = {p.name for p in written}
    assert names == {"meeting.txt", "meeting.srt", "meeting.vtt", "meeting.json"}
    for p in written:
        assert p.read_text(encoding="utf-8")


def test_export_rejects_unknown_format(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="unsupported export format"):
        exporter.export(_doc(), tmp_path, ["pdf"])

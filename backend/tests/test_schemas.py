"""IPC contracts as consumed by CI/tests."""

import pytest
from ipc.events import compute_overall
from ipc.schemas import (
    BatchJobRequest,
    JobStatus,
    Settings,
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)


def test_settings_defaults_match_spec():
    s = Settings()
    assert s.vad_threshold == 0.5
    assert s.compute_type == "int8"  # CPU default per spec §2
    assert s.export_formats == ["txt"]


def test_word_confidence_bounds():
    w = TranscriptWord(start=0, end=1, text="hi", confidence=0.9)
    assert not w.low_confidence
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TranscriptWord(start=0, end=1, text="x", confidence=1.5)


def test_transcript_document_schema_version_locked():
    doc = TranscriptDocument(segments=[TranscriptSegment(start=0, end=1, text="hello world")])
    assert doc.schema_version == 1  # Literal[1] per spec §5


def test_batch_request_rejects_missing_fields_ok():
    req = BatchJobRequest(file_path="C:/audio/meeting.mp3")
    assert req.settings.device == "auto"


def test_job_status_stage_progress_bounds():
    js = JobStatus(job_id="abc", stage="transcribe", progress=0.4)
    assert 0 <= js.overall_progress <= 1


def test_compute_overall_boundary_and_completion():
    # transcribe starting point == vad completed point (adjacent-stage boundary)
    p_vad = compute_overall("vad", 1.0)
    p_transcribe_start = compute_overall("transcribe", 0.0)
    assert abs(p_vad - p_transcribe_start) < 0.01
    assert p_vad < compute_overall("transcribe", 0.5)
    assert compute_overall("done", 1.0) == pytest.approx(1.0)

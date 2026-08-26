"""Stage 2: vad_segmenter — Silero VAD v5 via ONNX (spec §4).

CRITICAL RULE (spec §7.1): regions this module marks non-speech must NEVER
reach the ASR stage. `segment()` is the only sanctioned boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_THRESHOLD = 0.5
MIN_SPEECH_S = 0.25  # spec §7.3
PAD_S = 0.2
SILERO_SR = 16_000


@dataclass(frozen=True)
class SpeechSegment:
    start_s: float
    end_s: float

    @property
    def duration(self) -> float:
        return self.end_s - self.start_s


def load_vad_model(model_path: str | None = None):
    """Load Silero ONNX; returns None when unavailable so callers can degrade."""
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]

        path = model_path or _default_model_path()
        if not path.exists():
            return None
        return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    except Exception:
        return None


def _default_model_path():
    from pathlib import Path

    local = Path(__file__).resolve().parent.parent / "tests" / "models" / "silero_vad.onnx"
    return local if local.exists() else Path("silero_vad.onnx")


def segment(
    audio: np.ndarray,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    model=None,
) -> list[SpeechSegment]:
    """Split into speech segments using Silero probabilities.

    Falls back to an energy-based heuristic ONLY when the model file is absent
    (dev/bootstrap mode); this fallback must be disabled before release builds.
    """
    if audio.size == 0:
        return []
    pad = PAD_S
    min_len = MIN_SPEECH_S
    duration = len(audio) / SILERO_SR

    if model is not None:
        probs = _silero_probabilities(audio, model)
        voiced = probs >= threshold
    else:
        voiced = _energy_gate(audio)

    segs: list[SpeechSegment] = []
    step = SILERO_SR // 100  # 10 ms frames, matching silero windowing
    in_run = False
    run_start = 0
    for i, flag in enumerate(voiced):
        t = i * step / SILERO_SR
        if flag and not in_run:
            in_run, run_start = True, t
        elif not flag and in_run:
            end = min(duration, t)
            if end - run_start >= min_len:
                segs.append(SpeechSegment(max(0, run_start - pad), end))
            in_run = False
    if in_run:
        if duration - run_start >= min_len or not segs:
            segs.append(SpeechSegment(max(0, run_start - pad), duration))
    # merge adjacent segments split by sub-min gaps
    merged: list[SpeechSegment] = []
    for s in segs:
        if merged and s.start_s - merged[-1].end_s < 0.12:
            merged[-1] = SpeechSegment(merged[-1].start_s, s.end_s)
        else:
            merged.append(s)
    return merged


def _energy_gate(audio: np.ndarray) -> np.ndarray:
    """Dev-only fallback gate. TODO(m1): delete once model always present."""
    frame = SILERO_SR // 100
    n = len(audio) // frame
    frames = audio[: n * frame].reshape(n, frame)
    db = 20 * np.log10(np.maximum(np.sqrt(np.mean(frames**2, axis=1)), 1e-9))
    return db > -40.0


def _silero_probabilities(audio: np.ndarray, session) -> np.ndarray:
    x = audio.astype(np.float32)
    chunk = SILERO_SR  # 1 s chunks keep state management simple
    out = []
    h = np.zeros((2, 1, 64), dtype=np.float32)
    c = np.zeros((2, 1, 64), dtype=np.float32)
    for i in range(0, len(x), chunk):
        piece = x[i : i + chunk]
        if len(piece) < chunk:
            piece = np.pad(piece, (0, chunk - len(piece)))
        prob, hh, cc = session.run(None, {"input": piece[None, :], "h": h, "c": c})
        out.append(float(prob[0][0]))
        h, c = hh, cc
    # upsample per-second probability to 10 ms decision grid length used above
    frame_count = int(len(x) // (SILERO_SR // 100))
    return np.repeat(np.asarray(out), SILERO_SR // 100)[:frame_count]


def chunks_for_asr(audio: np.ndarray, segments: list[SpeechSegment]) -> list[tuple[float, float, np.ndarray]]:
    """Materialize PCM for each segment — the ONLY audio handed to transcriber."""
    out = []
    for s in segments:
        a = int(s.start_s * SILERO_SR)
        b = int(s.end_s * SILERO_SR)
        out.append((s.start_s, s.end_s, audio[a:b]))
    return out

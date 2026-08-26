"""Stage 1: audio_preprocess (spec §4).

Pure functions: PCM16 mono 16 kHz float32 in → normalized/trimmed float32 out.
Anti-hallucination rule: this module never decides what is "speech" — it only
normalizes and trims head/tail silence; per-segment decisions belong to VAD.
"""

from __future__ import annotations

import numpy as np

TARGET_SAMPLE_RATE = 16_000
TARGET_RMS_DBFS = -20.0
TRIM_THRESHOLD_DBFS = -45.0
MAX_GAIN_DB = 30.0  # never boost pure silence to full scale


def resample_to_16k(audio: np.ndarray, sr_in: int) -> np.ndarray:
    """Linear resample fallback. scipy/librosa polyphase preferred when present."""
    if sr_in == TARGET_SAMPLE_RATE:
        return audio.astype(np.float32)
    duration = len(audio) / sr_in
    out_len = max(1, round(duration * TARGET_SAMPLE_RATE))
    x = np.linspace(0.0, duration, num=len(audio), endpoint=False)
    xp = np.linspace(0.0, duration, num=out_len, endpoint=False)
    # Linear interpolation is quality-adequate for speech ASR input here;
    # swap to librosa.resample when available.
    try:
        import librosa  # type: ignore[import-untyped]

        return librosa.resample(
            audio.astype(np.float32), orig_sr=sr_in, target_sr=TARGET_SAMPLE_RATE
        )
    except ImportError:
        return np.interp(xp, x, audio).astype(np.float32)


def rms_dbfs(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
    return 20 * np.log10(rms) if rms > 0 else -120.0


def normalize_rms(audio: np.ndarray, target_dbfs: float = TARGET_RMS_DBFS) -> np.ndarray:
    """RMS-normalize to target level with a gain ceiling (spec §2)."""
    if audio.size == 0:
        return audio
    current = rms_dbfs(audio)
    if current <= -120.0:
        return audio.copy()
    gain = min(target_dbfs - current, MAX_GAIN_DB)
    out = audio * (10 ** (gain / 20))
    peak = float(np.max(np.abs(out)))
    if peak > 1.0:  # soft safety limit instead of hard clipping
        out *= 1.0 / peak
    return out.astype(np.float32)


def trim_silence(audio: np.ndarray, threshold_dbfs: float = TRIM_THRESHOLD_DBFS) -> tuple[np.ndarray, float, float]:
    """Trim leading/trailing silence below threshold.

    Returns (trimmed_audio, start_seconds, end_seconds) where seconds are offsets
    into the INPUT array — needed later to rebase VAD/word timestamps (spec §4).
    """
    if audio.size == 0:
        return audio, 0.0, 0.0
    frame = int(TARGET_SAMPLE_RATE * 0.02)
    n_frames = len(audio) // frame
    if n_frames == 0:
        return audio, 0.0, len(audio) / TARGET_SAMPLE_RATE
    frames = audio[: n_frames * frame].reshape(n_frames, frame)
    frame_db = 20 * np.log10(np.maximum(np.sqrt(np.mean(frames**2, axis=1)), 1e-9))
    voiced = np.where(frame_db >= threshold_dbfs)[0]
    if voiced.size == 0:  # effectively silent input — keep as-is, timestamps zeroed
        return audio[:frame], 0.0, frame / TARGET_SAMPLE_RATE
    first, last = int(voiced[0]), int(voiced[-1])
    pad = 2  # small pad in frames (40 ms each side)
    s = max(0, first - pad) * frame
    e = min(len(audio), (last + 1 + pad) * frame)
    return (
        audio[s:e].astype(np.float32),
        s / TARGET_SAMPLE_RATE,
        e / TARGET_SAMPLE_RATE,
    )


def denoise(audio: np.ndarray) -> np.ndarray:
    """RNNoise pass — optional (spec §2). Graceful no-op until the native lib ships (M1)."""
    try:
        from rnnoise_python import RNNNoise  # type: ignore[import-not-found]

        d = RNNNoise()
        chunks = [d.process_frame(chunk) for chunk in np.split(audio, np.arange(480, len(audio), 480)) if len(chunk) == 480]
        remainder_len = len(audio) % 480
        tail = audio[-remainder_len:] if remainder_len else np.empty(0, dtype=np.float32)
        return np.concatenate([np.concatenate(chunks), tail]).astype(np.float32) if chunks else audio
    except ImportError:
        return audio


def preprocess(audio: np.ndarray, sr_in: int, *, denoise_enabled: bool = False) -> dict[str, object]:
    """Full chain: resample → (denoise) → normalize → trim."""
    x = resample_to_16k(audio, sr_in)
    if denoise_enabled:
        x = denoise(x)
    x = normalize_rms(x)
    trimmed, start_s, end_s = trim_silence(x)
    return {
        "audio": trimmed,
        "sample_rate": TARGET_SAMPLE_RATE,
        "trim_start_s": start_s,
        "trim_end_s": end_s,
        "duration_s": len(trimmed) / TARGET_SAMPLE_RATE,
    }


def load_audio(path: str) -> tuple[np.ndarray, int]:
    """Load any ffmpeg/soundfile-supported file as mono float32 (batch entrypoint)."""
    import soundfile as sf

    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    return mono.astype(np.float32), sr

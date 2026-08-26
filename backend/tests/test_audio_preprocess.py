"""Stage-1 audio preprocessing unit tests (numpy-only, no model deps)."""

import numpy as np
import pytest
from core import audio_preprocess as ap


def tone(freq: float, seconds: float, sr: int = 16_000, amp: float = 0.25) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def with_silence(center: np.ndarray, silence_s: float = 0.7, sr: int = 16_000) -> np.ndarray:
    pad = np.zeros(int(sr * silence_s), dtype=np.float32)
    return np.concatenate([pad, center, pad])


class TestResample:
    def test_passthrough_at_16k(self):
        x = tone(440, 1.0)
        assert ap.resample_to_16k(x, 16_000) is x or np.array_equal(
            ap.resample_to_16k(x, 16_000), x.astype(np.float32)
        )

    def test_duration_preserved_from_44k(self):
        x = tone(440, 2.0, sr=44_100)
        out = ap.resample_to_16k(x, 44_100)
        expected_len = round(2.0 * ap.TARGET_SAMPLE_RATE)
        assert abs(len(out) - expected_len) <= 2  # interpolation edge tolerance


class TestNormalize:
    def test_quiet_audio_lifted_to_target_rms(self):
        quiet = tone(220, 1.0, amp=0.02)  # ~ -34 dBFS-ish
        out = ap.normalize_rms(quiet)
        assert abs(ap.rms_dbfs(out) - ap.TARGET_RMS_DBFS) < 1.0

    def test_silence_not_blown_up(self):
        silent = np.zeros(16_000, dtype=np.float32)
        out = ap.normalize_rms(silent)
        assert float(np.max(np.abs(out))) == 0.0

    def test_no_hard_clipping(self):
        loud = tone(220, 1.0, amp=0.95)
        out = ap.normalize_rms(loud)
        assert float(np.max(np.abs(out))) <= 1.0 + 1e-6


class TestTrimSilence:
    def test_trims_head_and_tail_with_correct_offsets(self):
        speech = tone(300, 1.5)
        padded = with_silence(speech, silence_s=0.8)
        trimmed, start_s, end_s = ap.trim_silence(padded)
        assert len(trimmed) < len(padded)
        assert 0.6 <= start_s <= 1.0
        assert 2.0 <= end_s <= 2.5

    def test_pure_silence_degrades_gracefully(self):
        silent = np.zeros(32_000, dtype=np.float32)
        trimmed, start_s, end_s = ap.trim_silence(silent)
        assert len(trimmed) > 0 and start_s == 0.0 and end_s >= 0.0


class TestFullChain:
    def test_preprocess_report_shape(self):
        x = with_silence(tone(350, 2.0), sr=44_100)
        report = ap.preprocess(x, sr_in=44_100)
        keys = {"audio", "sample_rate", "trim_start_s", "trim_end_s", "duration_s"}
        assert keys == set(report.keys())
        assert report["sample_rate"] == ap.TARGET_SAMPLE_RATE
        assert (
            abs(
                float(report["trim_end_s"])
                - float(report["trim_start_s"])
                - float(report["duration_s"])
            )
            < 0.05
        )

    def test_denoise_toggled_off_by_default_is_identity(self):
        x = with_silence(tone(350, 1.0))
        a = ap.preprocess(x, sr_in=16_000, denoise_enabled=False)
        b = ap.preprocess(x, sr_in=16_000, denoise_enabled=False)
        assert np.array_equal(a["audio"], b["audio"])


def test_unknown_sr_resamples_not_crashes():
    x = tone(500, 1.0, sr=22_050)
    out = ap.preprocess(x, sr_in=22_050)
    assert float(np.max(np.abs(out["audio"]))) > 0  # type: ignore[index]


@pytest.mark.parametrize("sr", [8_000, 24_000, 48_000])
def test_various_sample_rates_survive(sr):
    x = tone(440, 0.5, sr=sr)
    out = ap.resample_to_16k(x, sr)
    assert len(out) > 0 and out.dtype == np.float32

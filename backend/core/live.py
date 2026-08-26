"""Live session audio segmentation (system-audio loopback capture, M5 early).

The browser feeds 16 kHz float32 PCM over /ws/live in small chunks. This module
decides when an *utterance* is complete so it can be handed to the ASR engine:
energy-gated, closed by hangover silence or a hard max length.

Deliberate v1 simplification (TODO(m5)): batch mode uses Silero VAD; live uses
this energy gate because running the ONNX net over a sliding stream window adds
latency/complexity. Revisit once live is stable on real content.
"""

from __future__ import annotations

import numpy as np

Utterance = tuple[float, float, np.ndarray]  # (start_s, end_s, pcm @ sr)


class UtteranceBuffer:
    """Accumulates PCM and emits utterances at natural speech boundaries.

    Timestamps are absolute offsets into the live stream (seconds) so the UI can
    build one continuous timeline across many emitted utterances.
    """

    def __init__(
        self,
        sr: int = 16_000,
        rms_threshold: float = 0.008,
        min_utterance_s: float = 0.35,
        hangover_s: float = 0.6,
        max_utterance_s: float = 12.0,
    ) -> None:
        self.sr = sr
        self.rms_threshold = rms_threshold
        self.min_utterance_s = min_utterance_s
        self.hangover_s = hangover_s
        self.max_utterance_s = max_utterance_s
        self._chunks: list[np.ndarray] = []
        self._samples_in_buf = 0
        self._total_fed_s = 0.0
        self._speech_s = 0.0
        self._silence_s = 0.0
        self._heard_speech = False

    @property
    def buffered_s(self) -> float:
        return self._samples_in_buf / self.sr

    def feed(self, pcm: np.ndarray) -> list[Utterance]:
        """Consume one chunk; return any utterances completed by it."""
        arr = np.asarray(pcm, dtype=np.float32)
        n = arr.shape[0]
        self._total_fed_s += n / self.sr
        if n:
            self._chunks.append(arr)
            self._samples_in_buf += n

        rms = float(np.sqrt(np.mean(arr**2))) if n else 0.0
        if rms >= self.rms_threshold:
            self._heard_speech = True
            self._speech_s += n / self.sr
            self._silence_s = 0.0
        else:
            self._silence_s += n / self.sr

        if not (
            self._heard_speech
            and (self._silence_s >= self.hangover_s or self.buffered_s >= self.max_utterance_s)
        ):
            return []
        # min-length gates on SPEECH duration — a short blip wrapped in silence
        # must not pass just because the buffer is long.
        speech_ok = self._speech_s >= self.min_utterance_s
        out = self._take()
        return [out] if speech_ok else []

    def flush(self) -> Utterance | None:
        """Stream end: emit what's buffered only if it carries real speech."""
        out = (
            self._take() if self._heard_speech and self._speech_s >= self.min_utterance_s else None
        )
        self.reset()
        return out

    def reset(self) -> None:
        self._chunks.clear()
        self._samples_in_buf = 0
        self._speech_s = 0.0
        self._silence_s = 0.0
        self._heard_speech = False

    def _take(self) -> Utterance:
        pcm = np.concatenate(self._chunks) if len(self._chunks) > 1 else self._chunks[0].copy()
        start = round(self._total_fed_s - self.buffered_s, 4)
        end = round(start + pcm.shape[0] / self.sr, 4)
        self.reset()
        return start, end, pcm

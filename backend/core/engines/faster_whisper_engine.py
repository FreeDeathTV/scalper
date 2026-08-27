"""faster-whisper engine (CTranslate2) — default ASR backend (spec §2)."""

from __future__ import annotations

import logging
import threading

import numpy as np
from ipc.schemas import Settings

from ..transcriber import AsrChunkResult, resolve_ladder

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000


class FasterWhisperEngine:
    name = "faster-whisper"
    _model_cache: dict[tuple[str, str, str], object] = {}
    _cache_lock = threading.Lock()

    def __init__(self) -> None:
        self._model = None
        self._loaded_key: tuple[str, str] | None = None

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            return False

    def load(self, settings: Settings) -> None:
        from faster_whisper import WhisperModel

        last_error: Exception | None = None
        for model_size, compute_type in resolve_ladder(settings):
            device = settings.effective_device
            cache_key = (model_size, compute_type, device)
            cached = self._model_cache.get(cache_key)
            if cached is not None:
                self._model = cached
                self._loaded_key = (model_size, compute_type)
                logger.info("reused %s (%s, %s)", model_size, compute_type, device)
                return
            try:
                with self._cache_lock:
                    cached = self._model_cache.get(cache_key)
                    if cached is None:
                        cached = WhisperModel(model_size, device=device, compute_type=compute_type)
                        self._model_cache[cache_key] = cached
                self._model = cached
                self._loaded_key = (model_size, compute_type)
                logger.info("loaded %s (%s, %s)", model_size, compute_type, device)
                return
            except Exception as exc:  # step down the ladder (spec §6.3)
                logger.warning("failed to load %s/%s: %s", model_size, compute_type, exc)
                last_error = exc
        raise RuntimeError(f"could not load any model configuration: {last_error}")

    def unload(self) -> None:
        self._model = None
        self._loaded_key = None

    def transcribe_chunk(
        self,
        pcm: np.ndarray,
        start_s: float,
        end_s: float,
        settings: Settings,
        **gen_kwargs: object,
    ) -> AsrChunkResult:
        if self._model is None:
            raise RuntimeError("engine.load() must complete before transcribe_chunk()")
        initial_prompt = (
            " ".join(settings.custom_vocabulary[:20]) if settings.custom_vocabulary else None
        )
        try:
            segments, info = self._model.transcribe(
                pcm,
                task="translate" if settings.translate_to_english else "transcribe",
                language=settings.language,
                initial_prompt=initial_prompt,
                word_timestamps=False,  # words come from the aligner stage (spec §4)
                vad_filter=False,  # VAD already applied upstream — do NOT re-gate (§7.1)
                **gen_kwargs,
            )
        except Exception as exc:
            # CUDA can be reported as present while its cuBLAS runtime DLL is
            # missing. Retry once on CPU so a broken optional GPU install does
            # not make live transcription unusable.
            message = str(exc).lower()
            if self._loaded_key is None or "cublas" not in message and "cuda" not in message:
                raise
            logger.warning("CUDA transcription failed; retrying on CPU: %s", exc)
            from faster_whisper import WhisperModel

            self._model = WhisperModel("medium", device="cpu", compute_type="int8")
            self._loaded_key = ("medium", "int8")
            self._model_cache[("medium", "int8", "cpu")] = self._model
            segments, info = self._model.transcribe(
                pcm,
                task="translate" if settings.translate_to_english else "transcribe",
                language=settings.language,
                initial_prompt=initial_prompt,
                word_timestamps=False,
                vad_filter=False,
                **gen_kwargs,
            )
        text = " ".join(s.text.strip() for s in segments if s.text.strip())
        return AsrChunkResult(text=text, language=info.language, start_s=start_s, end_s=end_s)

    @property
    def loaded_config(self) -> tuple[str, str] | None:
        return self._loaded_key

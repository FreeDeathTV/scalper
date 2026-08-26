"""Device probing (spec §6). Cached; safe to call anywhere."""

from __future__ import annotations

import functools
import os


@functools.lru_cache(maxsize=1)
def has_cuda() -> bool:
    """Detect CUDA via ctranslate2 without importing heavy deps eagerly."""
    try:
        import ctranslate2

        return bool(ctranslate2.get_cuda_device_count())
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def cpu_cores() -> int:
    return os.cpu_count() or 1
